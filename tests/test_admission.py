"""Concurrent callers and ambiguous transport must not release ownership early."""

import asyncio
import json
import unittest

import httpx

from toolgap import PrefetchAdmission, PrefetchClient


def reply(operation_id, state="RUNNING", *, cleanup_pending=False, tokens=0):
    return dict(
        operation_id=operation_id,
        state=state,
        cleanup_pending=cleanup_pending,
        restored_tokens=tokens,
        restored_bytes=tokens * 8,
    )


class TestAdmission(unittest.IsolatedAsyncioTestCase):
    def client(self, handler):
        client = PrefetchClient("http://engine", transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        return client

    async def test_two_sessions_busy_fallback_without_second_backend_submit(self):
        entered, release = asyncio.Event(), asyncio.Event()
        requests = []

        async def handler(request):
            p = json.loads(request.content)
            requests.append(p)
            entered.set()
            await release.wait()
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"]))
            )

        policy = PrefetchAdmission(self.client(handler))
        task = asyncio.create_task(policy.submit("A", [1, 2], cache_salt="salt-A"))
        await entered.wait()
        b = await policy.submit("B", [1, 2], cache_salt="salt-B")
        self.assertEqual(b.state["state"], "LOCAL_BUSY")
        self.assertFalse(b.state["accepted"])
        await b.cancel()
        b.finish(used_tokens=0)
        self.assertEqual(len(requests), 1)
        release.set()
        a = await task
        self.assertEqual(requests[0]["cache_salt"], "salt-A")
        self.assertNotEqual(a.operation_id, b.operation_id)
        self.assertEqual(policy.metrics["active_slots"], 1)

    async def test_cancellation_holds_slot_until_ack_and_never_targets_next_session(
        self,
    ):
        requests = []
        drained = False

        async def handler(request):
            p = json.loads(request.content)
            requests.append(p)
            if p["action"] == "submit":
                state = reply(p["operation_id"])
            else:
                state = reply(
                    p["operation_id"], "CANCELLED", cleanup_pending=not drained
                )
            return httpx.Response(200, json=dict(success=True, result=state))

        policy = PrefetchAdmission(self.client(handler))
        a = await policy.submit("A", [1])
        self.assertTrue((await a.cancel())["cleanup_pending"])
        self.assertEqual((await policy.submit("B", [2])).state["state"], "LOCAL_BUSY")
        with self.assertRaises(ValueError):
            a.finish(used_tokens=0)
        drained = True
        await a.status()
        a.finish(used_tokens=0)
        b = await policy.submit("B", [2])
        before = len(requests)
        await a.cancel()
        self.assertEqual(len(requests), before)
        self.assertIs(policy.active, b)
        self.assertTrue(all(p["operation_id"] == a.operation_id for p in requests[1:3]))

    async def test_timeout_unknown_then_late_success_is_not_zero_waste(self):
        async def handler(request):
            p = json.loads(request.content)
            if p["action"] == "submit":
                raise httpx.ReadTimeout("lost ACK")
            return httpx.Response(
                200,
                json=dict(
                    success=True, result=reply(p["operation_id"], "SUCCESS", tokens=2)
                ),
            )

        policy = PrefetchAdmission(self.client(handler))
        a = await policy.submit("A", [1, 2])
        self.assertIsNone(a.state["accepted"])
        self.assertEqual((await policy.submit("B", [2])).state["state"], "LOCAL_BUSY")
        await a.status()
        a.finish()
        self.assertEqual(policy.metrics["usage_unknown_tokens"], 2)
        self.assertNotIn("unused_published_tokens", policy.metrics)
        self.assertEqual(policy.metrics["active_slots"], 0)

    async def test_unknown_cancel_does_not_release_late_submit(self):
        async def handler(request):
            p = json.loads(request.content)
            if p["action"] == "submit":
                raise httpx.ReadTimeout("late submit")
            return httpx.Response(
                400, json=dict(success=False, message="not found yet")
            )

        policy = PrefetchAdmission(self.client(handler))
        a = await policy.submit("A", [1])
        await a.cancel()
        self.assertEqual(a.state["state"], "UNKNOWN")
        self.assertEqual(policy.metrics["active_slots"], 1)

    async def test_rejected_submit_releases_slot(self):
        async def handler(request):
            return httpx.Response(400, json=dict(success=False, message="server busy"))

        policy = PrefetchAdmission(self.client(handler))
        for session in ("A", "B"):
            lease = await policy.submit(session, [1])
            self.assertEqual(lease.state["state"], "DECLINED")
            lease.finish(used_tokens=0)
        self.assertEqual(policy.metrics["server_rejected"], 2)
        self.assertEqual(policy.metrics["active_slots"], 0)

    async def test_limits_and_validation_before_http(self):
        async def handler(request):
            raise AssertionError("must not submit")

        policy = PrefetchAdmission(self.client(handler), max_prefix_tokens=2)
        self.assertEqual(
            (await policy.submit("A", [1, 2, 3])).state["state"], "LOCAL_LIMIT"
        )
        for tokens, salt, ttl in [([True], None, 1), ([1], 23, 1), ([1], None, 0)]:
            with self.assertRaises(ValueError):
                await policy.submit("A", tokens, cache_salt=salt, ttl_ms=ttl)
        self.assertEqual(policy.metrics["active_slots"], 0)

    async def test_usage_is_once_bounded_and_unknown_is_separate(self):
        async def handler(request):
            p = json.loads(request.content)
            return httpx.Response(
                200,
                json=dict(
                    success=True, result=reply(p["operation_id"], "SUCCESS", tokens=4)
                ),
            )

        policy = PrefetchAdmission(self.client(handler))
        a = await policy.submit("same-label", [1, 2, 3, 4])
        with self.assertRaises(ValueError):
            a.finish(used_tokens=5)
        with self.assertRaises(ValueError):
            a.finish(used_tokens=True)
        a.finish(used_tokens=3)
        with self.assertRaises(ValueError):
            a.finish(used_tokens=0)
        b = await policy.submit("same-label", [1, 2, 3, 4])
        b.finish(used_tokens=0)
        self.assertNotEqual(a.operation_id, b.operation_id)
        self.assertEqual(policy.metrics["published_tokens"], 8)
        self.assertEqual(policy.metrics["caller_reported_used_tokens"], 3)
        self.assertEqual(policy.metrics["unused_published_tokens"], 5)
        self.assertEqual(policy.metrics["unused_published_bytes"], 40)

    async def test_foreign_reply_cannot_complete_ownership(self):
        async def handler(request):
            return httpx.Response(
                200,
                json=dict(
                    success=True, result=reply("other-operation", "SUCCESS", tokens=1)
                ),
            )

        policy = PrefetchAdmission(self.client(handler))
        a = await policy.submit("A", [1])
        self.assertEqual(a.state["state"], "UNKNOWN")
        self.assertIs(policy.active, a)

    async def test_history_bound_does_not_forget_active_operation(self):
        async def handler(request):
            p = json.loads(request.content)
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"]))
            )

        policy = PrefetchAdmission(self.client(handler), history_size=1)
        a = await policy.submit("A", [1])
        for i in range(40):
            await policy.submit(str(i), [2])
        self.assertIs(policy.active, a)
        self.assertEqual(policy.metrics["retained_records"], 1)

    async def test_cancelled_transport_preserves_slot_for_reconciliation(self):
        entered = asyncio.Event()

        async def handler(request):
            entered.set()
            await asyncio.Event().wait()

        policy = PrefetchAdmission(self.client(handler))
        task = asyncio.create_task(policy.submit("A", [1]))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(policy.active.state["state"], "UNKNOWN")
        self.assertEqual((await policy.submit("B", [2])).state["state"], "LOCAL_BUSY")

    async def test_control_calls_serialize_late_running_status_and_cancel(self):
        entered, release = asyncio.Event(), asyncio.Event()
        requests = []

        async def handler(request):
            p = json.loads(request.content)
            requests.append(p["action"])
            if p["action"] == "status":
                entered.set()
                await release.wait()
            state = "CANCELLED" if p["action"] == "cancel" else "RUNNING"
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"], state))
            )

        policy = PrefetchAdmission(self.client(handler))
        a = await policy.submit("A", [1])
        status = asyncio.create_task(a.status())
        await entered.wait()
        cancel = asyncio.create_task(a.cancel())
        await asyncio.sleep(0)
        self.assertEqual(requests, ["submit", "status"])
        release.set()
        await status
        await cancel
        self.assertEqual(a.state["state"], "CANCELLED")
        self.assertEqual(policy.metrics["active_slots"], 0)

    async def test_prefix_limit_does_not_consume_unbounded_iterator(self):
        def tokens():
            yield from [1, 2, 3]
            raise AssertionError("Admission consumed beyond limit + 1")

        async def handler(request):
            raise AssertionError("Oversized prefix must not reach HTTP")

        policy = PrefetchAdmission(self.client(handler), max_prefix_tokens=2)
        self.assertEqual(
            (await policy.submit("A", tokens())).state["state"], "LOCAL_LIMIT"
        )

    async def test_expired_pending_cleanup_is_not_a_local_timeout_release(self):
        drained = False

        async def handler(request):
            p = json.loads(request.content)
            state = reply(p["operation_id"], "EXPIRED", cleanup_pending=not drained)
            return httpx.Response(200, json=dict(success=True, result=state))

        policy = PrefetchAdmission(self.client(handler))
        a = await policy.submit("A", [1], ttl_ms=1)
        self.assertIs(policy.active, a)
        drained = True
        await a.status()
        self.assertIsNone(policy.active)
        a.finish(used_tokens=0)

    async def test_missing_cleanup_confirmation_keeps_slot(self):
        async def handler(request):
            p = json.loads(request.content)
            state = reply(p["operation_id"], "SUCCESS", tokens=1)
            state.pop("cleanup_pending")
            return httpx.Response(200, json=dict(success=True, result=state))

        policy = PrefetchAdmission(self.client(handler))
        a = await policy.submit("A", [1])
        self.assertEqual(a.state["state"], "UNKNOWN")
        self.assertIs(policy.active, a)

    async def test_local_busy_does_not_serialize_independent_tool_work(self):
        first_started, second_done, resume = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )

        async def handler(request):
            p = json.loads(request.content)
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"]))
            )

        policy = PrefetchAdmission(self.client(handler))

        async def first_agent():
            await policy.submit("A", [1])
            first_started.set()
            await resume.wait()  # Controlled unfinished tool; not a timing benchmark.

        async def second_agent():
            await first_started.wait()
            b = await policy.submit("B", [2])
            self.assertFalse(b.state["accepted"])
            self.assertEqual(sum(x * x for x in range(10)), 285)
            second_done.set()

        first = asyncio.create_task(first_agent())
        try:
            await asyncio.wait_for(second_agent(), 1)
            self.assertTrue(second_done.is_set())
            self.assertFalse(first.done())
        finally:
            resume.set()
            await first

    async def test_unexpected_control_error_preserves_unknown_ownership(self):
        async def handler(request):
            raise RuntimeError("unexpected transport failure")

        policy = PrefetchAdmission(self.client(handler))
        a = await policy.submit("A", [1])
        self.assertEqual(a.state["state"], "UNKNOWN")
        self.assertIs(policy.active, a)

    async def test_operation_identity_cannot_be_reassigned(self):
        async def handler(request):
            p = json.loads(request.content)
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"]))
            )

        policy = PrefetchAdmission(self.client(handler))
        lease = await policy.submit("A", [1])
        with self.assertRaises(AttributeError):
            lease.operation_id = "another-owner"
        self.assertEqual(policy.active.operation_id, lease.operation_id)
