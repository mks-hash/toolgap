import asyncio
import json
import unittest

import httpx
from integration import run_with_prefetch

from toolgap import PrefetchClient


class TestClientPolicy(unittest.IsolatedAsyncioTestCase):
    async def test_exact_payload_and_admin_header(self):
        received = []

        async def handler(request):
            received.append((json.loads(request.content), request.headers))
            return httpx.Response(
                200, json=dict(success=True, result=dict(state="RUNNING"))
            )

        async with PrefetchClient(
            "http://engine",
            headers={"Authorization": "Bearer demo"},
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.submit("mine", [1, 2, 3], cache_salt="namespace", ttl_ms=500)
            await client.status("mine")
            await client.cancel("mine")
        self.assertEqual(
            received[0][0],
            dict(
                action="submit",
                operation_id="mine",
                input_ids=[1, 2, 3],
                cache_salt="namespace",
                ttl_ms=500,
            ),
        )
        self.assertEqual(received[0][1]["authorization"], "Bearer demo")
        self.assertNotIn("input_ids", received[1][0])

    async def test_early_tool_success_does_not_wait_or_cancel_pending_submit(self):
        entered, release = asyncio.Event(), asyncio.Event()
        actions = []

        async def handler(request):
            action = json.loads(request.content)["action"]
            actions.append(action)
            entered.set()
            await release.wait()
            return httpx.Response(
                200, json=dict(success=True, result=dict(state="RUNNING"))
            )

        async def tool():
            await entered.wait()
            return "useful-result"

        async with PrefetchClient(
            "http://engine", transport=httpx.MockTransport(handler)
        ) as client:
            run = await asyncio.wait_for(
                run_with_prefetch(tool, client, "mine", [1]), 0.5
            )
            self.assertEqual(run.result, "useful-result")
            self.assertFalse(run.submission.done())
            self.assertEqual(actions, ["submit"])
            release.set()
            self.assertTrue((await run.submission)["accepted"])

    async def test_admission_rejection_preserves_tool_result_and_falls_back(self):
        actions = []

        async def handler(request):
            actions.append(json.loads(request.content)["action"])
            return httpx.Response(
                400, json=dict(success=False, message="another operation active")
            )

        async def tool():
            return "normal-generation-may-use-this"

        async with PrefetchClient(
            "http://engine", transport=httpx.MockTransport(handler)
        ) as client:
            run = await run_with_prefetch(tool, client, "mine", [1])
            self.assertEqual(run.result, "normal-generation-may-use-this")
            self.assertFalse((await run.submission)["accepted"])
            self.assertEqual(actions, ["submit"])

    async def test_tool_failure_cancels_only_owned_operation(self):
        entered = asyncio.Event()
        payloads = []
        cleanup = []

        async def handler(request):
            payload = json.loads(request.content)
            payloads.append(payload)
            entered.set()
            state = "RUNNING" if payload["action"] == "submit" else "CANCELLED"
            return httpx.Response(
                200,
                json=dict(
                    success=True, result=dict(state=state, cleanup_pending=False)
                ),
            )

        async def tool():
            await entered.wait()
            raise ValueError("tool failed")

        async with PrefetchClient(
            "http://engine", transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaisesRegex(ValueError, "tool failed"):
                await run_with_prefetch(
                    tool, client, "mine", [1], on_cleanup=cleanup.append
                )
        self.assertEqual([p["action"] for p in payloads], ["submit", "cancel"])
        self.assertTrue(all(p["operation_id"] == "mine" for p in payloads))
        self.assertTrue(cleanup[0]["confirmed"])

    async def test_cancellation_terminates_tool_and_confirms_owned_cleanup(self):
        entered = asyncio.Event()
        exited = asyncio.Event()
        cleanup = []
        actions = []

        async def handler(request):
            action = json.loads(request.content)["action"]
            actions.append(action)
            entered.set()
            return httpx.Response(
                200,
                json=dict(
                    success=True,
                    result=dict(
                        state="RUNNING" if action == "submit" else "CANCELLED",
                        cleanup_pending=False,
                    ),
                ),
            )

        async def tool():
            try:
                await asyncio.Event().wait()
            finally:
                exited.set()

        async with PrefetchClient(
            "http://engine", transport=httpx.MockTransport(handler)
        ) as client:
            task = asyncio.create_task(
                run_with_prefetch(tool, client, "mine", [1], on_cleanup=cleanup.append)
            )
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(exited.is_set())
        self.assertEqual(actions, ["submit", "cancel"])
        self.assertTrue(cleanup[0]["confirmed"])

    async def test_transport_error_does_not_fabricate_cleanup_confirmation(self):
        cleanup = []

        async def handler(request):
            raise httpx.ReadTimeout("control unavailable")

        async def tool():
            raise ValueError("original tool failure")

        async with PrefetchClient(
            "http://engine", transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaisesRegex(ValueError, "original tool failure"):
                await run_with_prefetch(
                    tool, client, "mine", [1], on_cleanup=cleanup.append
                )
        self.assertFalse(cleanup[0]["confirmed"])
        self.assertIn("error", cleanup[0])

    async def test_bad_local_prefix_rejected_before_http(self):
        async def handler(request):
            raise AssertionError("must not send")

        async with PrefetchClient(
            "http://engine", transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ValueError):
                await client.submit("mine", [True, 2])


if __name__ == "__main__":
    unittest.main()
