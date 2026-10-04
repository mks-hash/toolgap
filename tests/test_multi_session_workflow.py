"""CPU orchestration and trace attribution; no model/GPU claims."""

import asyncio
import importlib.util
import json
import sys
import unittest
from pathlib import Path

import httpx

from toolgap import PrefetchAdmission, PrefetchClient, PrefetchHint

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples/multi_session"))
from workflow import pair, trajectory  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "multi_demo", ROOT / "examples/multi_session/demo.py"
)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class Lease:
    def __init__(self):
        self.calls = []

    async def status(self):
        self.calls.append("status")
        return dict(state="SUCCESS", cleanup_pending=False, operation_id="owned")

    async def cancel(self):
        self.calls.append("cancel")
        return dict(state="CANCELLED", cleanup_pending=False, operation_id="owned")

    def finish(self, **kwargs):
        self.calls.append(kwargs)


class WorkflowTest(unittest.IsolatedAsyncioTestCase):
    session = dict(id="a", prefix=[1] * 64, salt="original")

    async def test_continuation_does_not_wait_for_submit(self):
        reached = asyncio.Event()
        lease = Lease()
        owner = self

        class Admission:
            async def submit(self, label, prefix, **kwargs):
                owner.assertEqual(kwargs["cache_salt"], "original")
                await reached.wait()
                return lease

        async def continuation(result):
            reached.set()
            return {}, {}

        gate = asyncio.Event()
        gate.set()
        row = await asyncio.wait_for(
            trajectory(self.session, gate, self.tool, continuation, Admission()), 1
        )
        self.assertIsNotNone(row["response"])
        self.assertEqual(lease.calls, ["status", {"used_tokens": None}])

    async def test_real_admission_poller_does_not_gate_workflow_continuation(self):
        polling, continuation_entered, publish = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        calls = []

        async def handler(request):
            p = json.loads(request.content)
            calls.append(p["action"])
            if p["action"] == "status":
                polling.set()
                await publish.wait()
            state = dict(
                operation_id=p["operation_id"],
                state="SUCCESS" if publish.is_set() else "RUNNING",
                cleanup_pending=False,
                restored_tokens=0,
                restored_bytes=0,
            )
            return httpx.Response(200, json=dict(success=True, result=state))

        async def tool():
            await polling.wait()
            return {"document_id": "DOC-00173"}

        async def continuation(result):
            continuation_entered.set()
            # The poller cannot complete until generation was submitted.
            publish.set()
            return {"correct": True}, {}

        async with PrefetchClient(
            "http://engine", transport=httpx.MockTransport(handler)
        ) as client:
            async with PrefetchAdmission(
                client, reconcile_interval_ms=1, reconcile_timeout_ms=500
            ) as admission:
                gate = asyncio.Event()
                gate.set()
                row = await asyncio.wait_for(
                    trajectory(self.session, gate, tool, continuation, admission), 1
                )
                self.assertTrue(continuation_entered.is_set())
                self.assertTrue(row["response"]["correct"])
                self.assertEqual(calls, ["submit", "status"])
                self.assertEqual(admission.metrics["active_slots"], 0)
                self.assertEqual(admission.metrics["usage_unknown_operations"], 1)

    async def tool(self):
        return {"document_id": "DOC-00173"}

    async def test_hint_decline_still_runs_tool_and_correct_continuation(self):
        async def forbidden(request):
            self.fail("Declined restore must send no control RPC")

        async def continuation(result):
            self.assertEqual(result["document_id"], "DOC-00173")
            return {"correct": True}, {"submitted_ns": 1}

        async with PrefetchClient(
            "http://engine", transport=httpx.MockTransport(forbidden)
        ) as client:
            async with PrefetchAdmission(client, min_overlap_ms=100) as admission:
                gate = asyncio.Event()
                gate.set()
                session = dict(
                    self.session, prefetch_hint=PrefetchHint("l3_only", 50, 350)
                )
                row = await trajectory(
                    session, gate, self.tool, continuation, admission
                )
                self.assertTrue(row["response"]["correct"])
                self.assertEqual(row["lease"]["state"], "LOCAL_LOW_OVERLAP")
                self.assertEqual(admission.metrics["active_slots"], 0)

    async def test_abandoned_tool_cancels_only_owned_restore(self):
        lease = Lease()

        class Admission:
            async def submit(self, *args, **kwargs):
                return lease

        async def forbidden(result):
            self.fail("Abandonment must not generate")

        gate = asyncio.Event()
        gate.set()
        row = await trajectory(
            self.session, gate, self.tool, forbidden, Admission(), abandon=True
        )
        self.assertIsNone(row["timing"])
        self.assertEqual(lease.calls, ["cancel", {"used_tokens": 0}])

    async def test_tool_failure_cleans_up(self):
        lease = Lease()

        class Admission:
            async def submit(self, *args, **kwargs):
                return lease

        async def broken():
            raise RuntimeError("tool failure")

        gate = asyncio.Event()
        gate.set()
        with self.assertRaisesRegex(RuntimeError, "tool failure"):
            await trajectory(self.session, gate, broken, None, Admission())
        self.assertEqual(lease.calls, ["cancel"])

    async def test_pair_failure_reaps_sibling(self):
        entered, reaped = asyncio.Event(), asyncio.Event()
        gate = asyncio.Event()

        async def sibling():
            await gate.wait()
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                reaped.set()

        async def failure():
            await entered.wait()
            raise RuntimeError("pair failure")

        with self.assertRaises(RuntimeError):
            await pair([sibling(), failure()], gate)
        self.assertTrue(reaped.is_set())

    async def test_caller_cancel_reconciles_pending_submit(self):
        entered, release = asyncio.Event(), asyncio.Event()
        lease = Lease()

        class Admission:
            async def submit(self, *args, **kwargs):
                entered.set()
                await release.wait()
                return lease

        async def long_tool():
            await asyncio.Event().wait()

        gate = asyncio.Event()
        gate.set()
        task = asyncio.create_task(
            trajectory(self.session, gate, long_tool, None, Admission())
        )
        await entered.wait()
        task.cancel()
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(lease.calls, ["cancel"])

    async def test_local_busy_still_generates(self):
        class BusyLease(Lease):
            async def status(self):
                return dict(state="LOCAL_BUSY", cleanup_pending=False)

        lease = BusyLease()

        class Admission:
            async def submit(self, *args, **kwargs):
                return lease

        async def continuation(result):
            return {"correct": True}, {"submitted_ns": 1}

        gate = asyncio.Event()
        gate.set()
        row = await trajectory(self.session, gate, self.tool, continuation, Admission())
        self.assertTrue(row["response"]["correct"])
        self.assertEqual(row["lease"]["state"], "LOCAL_BUSY")
        self.assertNotIn("cancel", lease.calls)


class TraceTest(unittest.TestCase):
    def test_other_agent_reads_and_publication_are_excluded(self):
        row = dict(
            t0_tool_dispatched=100,
            t3_tool_completed=300,
            lease=dict(operation_id="mine"),
            continuation_rid="req-a",
            timing=dict(submitted_ns=400, first_token_ns=500),
        )
        events = [
            dict(kind="read", at_ns=150, keys=["a", "b"]),
            dict(kind="read", at_ns=160, keys=["b"]),
            dict(
                kind="control_accepted_end",
                at_ns=120,
                operation_id="mine",
                rid="internal-a",
            ),
            dict(kind="publish", at_ns=200, rid="internal-a", restored_tokens=64),
            dict(kind="publish", at_ns=450, rid="internal-b", restored_tokens=64),
            dict(
                kind="restore_io", at_ns=200, start_ns=120, end_ns=200, rid="internal-a"
            ),
        ]
        client = [dict(operation_id="mine", action="submit", phase="send", at_ns=110)]
        result = demo.trace_for_session(
            events, row, dict(storage_key_hashes=["a"]), client
        )
        self.assertEqual(result["prefix_backend_read_pages"], 1)
        self.assertEqual(result["duplicate_prefix_read_pages"], 0)
        self.assertEqual(result["t2_l2_published"], 200)
        self.assertTrue(result["published_before_continuation"])

    def test_unmapped_publication_does_not_invent_overlap(self):
        row = dict(
            t0_tool_dispatched=100,
            t3_tool_completed=300,
            lease=dict(operation_id="local-busy"),
            continuation_rid="req-b",
            timing=dict(submitted_ns=400, first_token_ns=500),
        )
        result = demo.trace_for_session(
            [dict(kind="publish", at_ns=200, rid="other", restored_tokens=64)],
            row,
            dict(storage_key_hashes=[]),
            [],
        )
        self.assertIsNone(result["t2_l2_published"])
        self.assertIsNone(result["hidden_restore_path_ms"])

    def test_zero_token_terminal_does_not_claim_publication(self):
        row = dict(
            t0_tool_dispatched=100,
            t3_tool_completed=300,
            lease=dict(operation_id="cancelled"),
            continuation_rid="req-b",
            timing=dict(submitted_ns=400, first_token_ns=500),
        )
        events = [
            dict(
                kind="control_accepted_end",
                at_ns=110,
                operation_id="cancelled",
                rid="internal",
            ),
            dict(kind="publish", at_ns=200, rid="internal", restored_tokens=0),
        ]
        result = demo.trace_for_session(events, row, dict(storage_key_hashes=[]), [])
        self.assertFalse(result["published_before_continuation"])
        self.assertIsNone(result["t2_l2_published"])


if __name__ == "__main__":
    unittest.main()
