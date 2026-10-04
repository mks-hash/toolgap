"""Eligibility estimates are local hints; remote ownership remains authoritative."""

import json
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import httpx

from toolgap import PrefetchAdmission, PrefetchClient, PrefetchHint
from test_admission import reply


class TestHints(unittest.IsolatedAsyncioTestCase):
    def policy(self, handler, **options):
        client = PrefetchClient("http://engine", transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        policy = PrefetchAdmission(client, **options)
        self.addAsyncCleanup(policy.aclose)
        return policy

    async def test_resident_and_short_work_skip_http_without_acquiring_slot(self):
        async def forbidden(request):
            self.fail("Local eligibility must not contact the worker")

        policy = self.policy(forbidden, min_overlap_ms=100, reconcile_interval_ms=1)
        for hint, reason in [
            (PrefetchHint("resident", 1000, 350), "LOCAL_RESIDENT"),
            (PrefetchHint("l3_only", 50, 350), "LOCAL_LOW_OVERLAP"),
            (PrefetchHint("unknown", 1000, 20), "LOCAL_LOW_OVERLAP"),
        ]:
            lease = await policy.submit("A", [1], hint=hint)
            self.assertEqual(lease.state["state"], reason)
            self.assertEqual(lease.decision["reason"], reason)
            self.assertIsNone(lease.timing["slot_reserved_ns"])
            self.assertIsNone(policy.active)
            self.assertIsNone(policy._reconcile_task)
            await lease.status()
            await lease.cancel()
            lease.finish(used_tokens=0)
        self.assertNotIn("slot_releases", policy.metrics)
        self.assertNotIn("released_slot_hold_ms", policy.metrics)

    async def test_declined_short_job_leaves_slot_for_later_long_job(self):
        requests = []

        async def handler(request):
            p = json.loads(request.content)
            requests.append(p)
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"]))
            )

        policy = self.policy(handler, min_overlap_ms=100)
        short = await policy.submit("short", [1], hint=PrefetchHint("l3_only", 50, 350))
        long = await policy.submit("long", [2], hint=PrefetchHint("l3_only", 600, 350))
        self.assertEqual(short.state["state"], "LOCAL_LOW_OVERLAP")
        self.assertIs(policy.active, long)
        self.assertEqual(long.decision["estimated_hidden_ms"], 350)
        self.assertEqual(len(requests), 1)
        self.assertNotIn("hint", requests[0])
        self.assertEqual(requests[0]["input_ids"], [2])

    async def test_missing_estimates_and_disabled_threshold_preserve_admission(self):
        requests = []

        async def handler(request):
            p = json.loads(request.content)
            requests.append(p)
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"], "SUCCESS"))
            )

        policy = self.policy(handler, min_overlap_ms=100)
        for hint in (None, PrefetchHint(), PrefetchHint("l3_only", 0, None)):
            lease = await policy.submit("A", [1], hint=hint)
            self.assertEqual(lease.decision["reason"], "ELIGIBLE")
            self.assertIsNone(lease.decision["estimated_hidden_ms"])
        disabled = self.policy(handler)
        lease = await disabled.submit("A", [1], hint=PrefetchHint("l3_only", 0, 350))
        self.assertEqual(lease.state["state"], "SUCCESS")
        self.assertEqual(len(requests), 4)

    async def test_overlap_boundary_and_zero_values(self):
        requests = []

        async def handler(request):
            p = json.loads(request.content)
            requests.append(p)
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"], "SUCCESS"))
            )

        policy = self.policy(handler, min_overlap_ms=100)
        for tool_ms, restore_ms, accepted in (
            (100, 350, True),
            (600, 100, True),
            (99, 350, False),
            (600, 99, False),
            (0, 350, False),
            (600, 0, False),
        ):
            with self.subTest(tool_ms=tool_ms, restore_ms=restore_ms):
                lease = await policy.submit(
                    "A", [1], hint=PrefetchHint("l3_only", tool_ms, restore_ms)
                )
                self.assertEqual(lease.state["accepted"], accepted)
        self.assertEqual(len(requests), 2)

    async def test_local_rejection_does_not_release_ambiguous_active_operation(self):
        calls = []

        async def handler(request):
            p = json.loads(request.content)
            calls.append(p)
            raise httpx.ReadTimeout("ACK unknown")

        policy = self.policy(handler, min_overlap_ms=100)
        a = await policy.submit("A", [1])
        for hint in (PrefetchHint("resident"), PrefetchHint("l3_only", 50, 350)):
            b = await policy.submit("B", [2], hint=hint)
            b.finish(used_tokens=0)
            self.assertIs(policy.active, a)
            self.assertIsNone(a.timing["slot_released_ns"])
        self.assertEqual(a.state["state"], "UNKNOWN")
        self.assertEqual(len(calls), 1)
        self.assertEqual(policy.metrics["active_slots"], 1)

    async def test_bad_hints_fail_before_ownership_or_http(self):
        async def forbidden(request):
            self.fail("Invalid hints must not contact the worker")

        for residency in ([], None, True, "partially_resident", "L3"):
            with self.subTest(residency=residency), self.assertRaises(ValueError):
                PrefetchHint(residency)
        for field in ("expected_tool_ms", "estimated_restore_ms"):
            for value in (-1, True, float("inf"), float("nan"), "100"):
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(ValueError),
                ):
                    PrefetchHint(**{field: value})
        policy = self.policy(forbidden)
        for hint in ({}, "resident", 42):
            with self.assertRaises(ValueError):
                await policy.submit("A", [1], hint=hint)
        for threshold in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                PrefetchAdmission(policy.client, min_overlap_ms=threshold)
        with self.assertRaises(ValueError):
            await policy.submit("A", [True], hint=PrefetchHint("resident"))
        self.assertIsNone(policy.active)
        self.assertNotIn("submissions", policy.metrics)

    async def test_decision_snapshot_does_not_mutate_hint_or_prefix_identity(self):
        requests = []

        async def handler(request):
            p = json.loads(request.content)
            requests.append(p)
            return httpx.Response(
                200, json=dict(success=True, result=reply(p["operation_id"]))
            )

        policy = self.policy(handler, min_overlap_ms=100)
        hint = PrefetchHint("l3_only", 600, 350)
        lease = await policy.submit("A", [2, 4], cache_salt="original", hint=hint)
        with self.assertRaises(FrozenInstanceError):
            hint.expected_tool_ms = 0
        snapshot = lease.decision
        snapshot["hint"]["cache_residency"] = "resident"
        self.assertEqual(lease.decision["hint"]["cache_residency"], "l3_only")
        self.assertEqual(requests[0]["cache_salt"], "original")
        self.assertEqual(requests[0]["input_ids"], [2, 4])

    async def test_timing_measures_local_hold_and_counts_release_once(self):
        terminal = False

        async def handler(request):
            p = json.loads(request.content)
            state = reply(p["operation_id"], "SUCCESS" if terminal else "RUNNING")
            return httpx.Response(200, json=dict(success=True, result=state))

        policy = self.policy(handler)
        with patch("toolgap.admission.time.monotonic_ns", return_value=1_000_000):
            a = await policy.submit("A", [1])
        with patch("toolgap.admission.time.monotonic_ns", return_value=6_000_000):
            self.assertEqual(a.timing["slot_hold_ms"], 5)
            self.assertEqual(policy.metrics["active_slot_age_ms"], 5)
        terminal = True
        with patch("toolgap.admission.time.monotonic_ns", return_value=11_000_000):
            await a.status()
        await a.status()
        await a.cancel()
        self.assertEqual(a.timing["slot_hold_ms"], 10)
        self.assertEqual(a.timing["slot_released_ns"], 11_000_000)
        self.assertEqual(policy.metrics["slot_releases"], 1)
        self.assertEqual(policy.metrics["released_slot_hold_ms"], 10)
        self.assertIsNone(policy.metrics["active_slot_age_ms"])

    async def test_cancel_pending_timing_keeps_increasing_until_confirmed_cleanup(self):
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
        await a.cancel()
        self.assertIsNone(a.timing["slot_released_ns"])
        self.assertNotIn("slot_releases", policy.metrics)
        drained = True
        await a.status()
        self.assertIsNotNone(a.timing["slot_released_ns"])
        self.assertEqual(policy.metrics["slot_releases"], 1)


if __name__ == "__main__":
    unittest.main()
