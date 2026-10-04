"""Bounded observation can release admission, never infer remote cleanup."""

import asyncio
import json
import unittest

import httpx

from toolgap import PrefetchAdmission, PrefetchClient
from test_admission import reply


class TestReconciliation(unittest.IsolatedAsyncioTestCase):
    def policy(self, handler, **kwargs):
        client = PrefetchClient("http://engine", transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        policy = PrefetchAdmission(
            client,
            reconcile_interval_ms=1,
            reconcile_max_checks=3,
            reconcile_timeout_ms=30,
            **kwargs,
        )
        self.addAsyncCleanup(policy.aclose)
        return policy

    async def done(self, policy):
        task = policy._reconcile_task
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), 1)

    async def test_later_caller_admitted_before_owner_continuation_finishes(self):
        requests = []
        status_entered, published, continuation_done = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )

        async def handler(request):
            p = json.loads(request.content)
            requests.append(p)
            state = reply(p["operation_id"])
            if p["action"] == "status":
                status_entered.set()
                await published.wait()
                state = reply(p["operation_id"], "SUCCESS", tokens=2)
            return httpx.Response(200, json=dict(success=True, result=state))

        policy = self.policy(handler)
        a = await policy.submit("A", [1, 2], cache_salt="A")
        owner = asyncio.create_task(continuation_done.wait())
        try:
            await asyncio.wait_for(status_entered.wait(), 1)
            busy = await policy.submit("early-B", [3], cache_salt="B")
            self.assertEqual(busy.state["state"], "LOCAL_BUSY")
            # Observation does not block useful work on the event loop.
            useful_work = await asyncio.wait_for(asyncio.sleep(0, result=42), 1)
            self.assertEqual(useful_work, 42)
            published.set()
            await self.done(policy)
            self.assertFalse(owner.done())
            self.assertIsNone(policy.active)
            b = await policy.submit("later-B", [3], cache_salt="B")
            self.assertTrue(b.state["accepted"])
            self.assertIs(policy.active, b)
            self.assertEqual(a.state["restored_tokens"], 2)
            self.assertNotIn("finalized_operations", policy.metrics)
            before = len(requests)
            await a.status()
            await a.cancel()
            a.finish()
            self.assertEqual(len(requests), before)
            self.assertIs(policy.active, b)
            self.assertEqual(policy.metrics["usage_unknown_tokens"], 2)
            self.assertNotIn("unused_published_tokens", policy.metrics)
        finally:
            continuation_done.set()
            await owner

    async def test_pending_terminal_needs_physical_cleanup_confirmation(self):
        drained = False

        async def handler(request):
            p = json.loads(request.content)
            state = reply(p["operation_id"])
            if p["action"] != "submit":
                state = reply(
                    p["operation_id"], "CANCELLED", cleanup_pending=not drained
                )
            return httpx.Response(200, json=dict(success=True, result=state))

        policy = self.policy(handler)
        a = await policy.submit("A", [1])
        await self.done(policy)
        self.assertEqual(a.state["state"], "CANCELLED")
        self.assertTrue(a.state["cleanup_pending"])
        self.assertIs(policy.active, a)
        self.assertEqual(policy.metrics["reconciliation_exhausted"], 1)
        self.assertEqual((await policy.submit("B", [2])).state["state"], "LOCAL_BUSY")
        drained = True
        await a.status()
        self.assertIsNone(policy.active)

    async def test_unknown_budget_is_not_reset_by_busy_callers(self):
        calls = []

        async def handler(request):
            p = json.loads(request.content)
            calls.append(p["action"])
            if p["action"] == "submit":
                raise httpx.ReadTimeout("lost submit acknowledgement")
            return httpx.Response(400, json=dict(success=False, message="unknown id"))

        policy = self.policy(handler)
        a = await policy.submit("A", [1])
        await self.done(policy)
        for _ in range(5):
            self.assertEqual(
                (await policy.submit("B", [2])).state["state"], "LOCAL_BUSY"
            )
        await asyncio.sleep(0)
        self.assertIsNone(policy._reconcile_task)
        self.assertEqual(calls, ["submit", "status", "status", "status"])
        self.assertEqual(a.state["state"], "UNKNOWN")
        self.assertIs(policy.active, a)

    async def test_foreign_and_malformed_replies_do_not_release_slot(self):
        states = [reply("another-id", "SUCCESS")]

        async def handler(request):
            p = json.loads(request.content)
            if p["action"] == "submit":
                state = reply(p["operation_id"])
            elif states:
                state = states.pop()
            else:
                state = reply(p["operation_id"], "SUCCESS")
                del state["cleanup_pending"]
            return httpx.Response(200, json=dict(success=True, result=state))

        policy = self.policy(handler)
        a = await policy.submit("A", [1])
        await self.done(policy)
        self.assertEqual(a.state["state"], "UNKNOWN")
        self.assertIs(policy.active, a)

    async def test_status_timeout_keeps_slot_and_reaps_transport(self):
        cancelled = asyncio.Event()

        async def handler(request):
            p = json.loads(request.content)
            if p["action"] == "status":
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"]))
            )

        policy = self.policy(handler)
        a = await policy.submit("A", [1])
        await self.done(policy)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(policy.metrics["reconciliation_timeouts"], 3)
        self.assertEqual(a.state["state"], "UNKNOWN")
        self.assertIs(policy.active, a)
        self.assertIsNone(policy._reconcile_task)

    async def test_close_during_status_retains_owner_and_allows_manual_cleanup(self):
        entered, resume, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = []

        async def handler(request):
            p = json.loads(request.content)
            calls.append(p["action"])
            if p["action"] == "status":
                entered.set()
                try:
                    await resume.wait()
                finally:
                    cancelled.set()
            state = reply(
                p["operation_id"], "SUCCESS" if resume.is_set() else "RUNNING"
            )
            return httpx.Response(200, json=dict(success=True, result=state))

        policy = self.policy(handler)
        a = await policy.submit("A", [1])
        await asyncio.wait_for(entered.wait(), 1)
        task = policy._reconcile_task
        await policy.aclose()
        await policy.aclose()
        self.assertTrue(task.done())
        self.assertTrue(cancelled.is_set())
        self.assertIsNone(policy._reconcile_task)
        self.assertEqual(a.state["state"], "UNKNOWN")
        self.assertIs(policy.active, a)
        with self.assertRaises(RuntimeError):
            await policy.submit("B", [2])
        self.assertNotIn("cancel", calls)
        resume.set()
        await a.status()
        self.assertIsNone(policy.active)
        self.assertIsNone(policy._reconcile_task)

    async def test_context_exit_before_submit_reply_does_not_spawn_or_reclaim(self):
        entered, resume = asyncio.Event(), asyncio.Event()

        async def handler(request):
            p = json.loads(request.content)
            entered.set()
            await resume.wait()
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"]))
            )

        policy = self.policy(handler)
        async with policy:
            submit = asyncio.create_task(policy.submit("A", [1]))
            await asyncio.wait_for(entered.wait(), 1)
        resume.set()
        a = await submit
        self.assertIsNone(policy._reconcile_task)
        self.assertIs(policy.active, a)
        with self.assertRaises(RuntimeError):
            async with policy:
                pass

    async def test_close_before_poller_first_tick_reaps_without_status(self):
        calls = []

        async def handler(request):
            p = json.loads(request.content)
            calls.append(p["action"])
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"]))
            )

        policy = self.policy(handler)
        a = await policy.submit("A", [1])
        task = policy._reconcile_task
        await policy.aclose()
        self.assertTrue(task.done())
        self.assertIsNone(policy._reconcile_task)
        self.assertIs(policy.active, a)
        self.assertEqual(calls, ["submit"])

    async def test_slow_replacement_submit_does_not_restart_exhausted_budget(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        calls = []

        async def handler(request):
            p = json.loads(request.content)
            calls.append(p)
            if p["action"] == "submit" and len(calls) > 1:
                entered.set()
                await resume.wait()
            state = reply(
                p["operation_id"], "SUCCESS" if p["action"] == "status" else "RUNNING"
            )
            return httpx.Response(200, json=dict(success=True, result=state))

        policy = self.policy(handler)
        a = await policy.submit("A", [1])
        old_task = policy._reconcile_task
        await a.status()
        submit = asyncio.create_task(policy.submit("B", [2]))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await asyncio.wait_for(asyncio.shield(old_task), 1)
            await self.done(policy)
            self.assertEqual(policy.metrics["reconciliation_checks"], 3)
            self.assertEqual(policy.metrics["reconciliation_timeouts"], 3)
            self.assertEqual(policy.metrics["reconciliation_exhausted"], 1)
            self.assertEqual(policy.active.state["state"], "SUBMITTING")
        finally:
            resume.set()
        b = await submit
        await asyncio.sleep(0)
        self.assertIs(policy.active, b)
        self.assertIsNone(policy._reconcile_task)
        self.assertEqual([p["action"] for p in calls], ["submit", "status", "submit"])

    async def test_cancelled_submit_is_reconciled_using_retained_identity(self):
        entered = asyncio.Event()
        calls = []

        async def handler(request):
            p = json.loads(request.content)
            calls.append(p)
            if p["action"] == "submit":
                entered.set()
                await asyncio.Event().wait()
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"], "SUCCESS"))
            )

        policy = self.policy(handler)
        submit = asyncio.create_task(policy.submit("A", [1]))
        await asyncio.wait_for(entered.wait(), 1)
        a = policy.active
        submit.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await submit
        await self.done(policy)
        self.assertIsNone(policy.active)
        self.assertEqual(a.state["state"], "SUCCESS")
        self.assertEqual([p["operation_id"] for p in calls], [a.operation_id] * 2)

    async def test_poll_and_explicit_cancel_remain_serialized(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        calls = []

        async def handler(request):
            p = json.loads(request.content)
            calls.append(p["action"])
            if p["action"] == "status":
                entered.set()
                await resume.wait()
            state = reply(
                p["operation_id"], "CANCELLED" if p["action"] == "cancel" else "RUNNING"
            )
            return httpx.Response(200, json=dict(success=True, result=state))

        policy = self.policy(handler)
        a = await policy.submit("A", [1])
        await asyncio.wait_for(entered.wait(), 1)
        cancel = asyncio.create_task(a.cancel())
        await asyncio.sleep(0)
        self.assertFalse(cancel.done())
        resume.set()
        await cancel
        await self.done(policy)
        self.assertEqual(calls, ["submit", "status", "cancel"])
        self.assertEqual(a.state["state"], "CANCELLED")
        self.assertIsNone(policy.active)

    async def test_replacement_during_old_poller_sleep_gets_its_own_budget(self):
        calls = []

        async def handler(request):
            p = json.loads(request.content)
            calls.append(p)
            state = reply(
                p["operation_id"], "SUCCESS" if p["action"] == "status" else "RUNNING"
            )
            return httpx.Response(200, json=dict(success=True, result=state))

        policy = self.policy(handler)
        a = await policy.submit("A", [1])
        old_task = policy._reconcile_task
        await a.status()  # Manual terminal response before the poller's first tick.
        b = await policy.submit("B", [2])
        await asyncio.wait_for(asyncio.shield(old_task), 1)
        await self.done(policy)
        self.assertIsNone(policy.active)
        self.assertEqual(b.state["state"], "SUCCESS")
        self.assertEqual(
            [(p["action"], p["operation_id"]) for p in calls],
            [
                ("submit", a.operation_id),
                ("status", a.operation_id),
                ("submit", b.operation_id),
                ("status", b.operation_id),
            ],
        )

    async def test_immediate_terminal_and_rejection_do_not_poll(self):
        calls = []

        async def handler(request):
            p = json.loads(request.content)
            calls.append(p["action"])
            if len(calls) == 1:
                return httpx.Response(
                    200,
                    json=dict(success=True, result=reply(p["operation_id"], "CACHED")),
                )
            return httpx.Response(400, json=dict(success=False, message="busy"))

        policy = self.policy(handler)
        self.assertEqual((await policy.submit("A", [1])).state["state"], "CACHED")
        self.assertEqual((await policy.submit("B", [2])).state["state"], "DECLINED")
        self.assertIsNone(policy._reconcile_task)
        self.assertEqual(calls, ["submit", "submit"])

    async def test_default_is_manual_and_options_are_validated(self):
        async def handler(request):
            p = json.loads(request.content)
            self.assertEqual(p["action"], "submit")
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"]))
            )

        client = PrefetchClient("http://engine", transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        policy = PrefetchAdmission(client)
        self.addAsyncCleanup(policy.aclose)
        a = await policy.submit("A", [1])
        await asyncio.sleep(0)
        self.assertIsNone(policy._reconcile_task)
        self.assertIs(policy.active, a)
        for name in (
            "reconcile_interval_ms",
            "reconcile_max_checks",
            "reconcile_timeout_ms",
        ):
            for value in (0, -1, True, 1.5, "10"):
                with (
                    self.subTest(name=name, value=value),
                    self.assertRaises(ValueError),
                ):
                    PrefetchAdmission(client, **{name: value})


if __name__ == "__main__":
    unittest.main()
