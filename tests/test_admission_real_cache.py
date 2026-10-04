"""Admission over real SGLang file I/O, host allocation and terminal drain (CPU)."""

import asyncio
import json
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import httpx
import test_prefetch_finite_io as finite
from sglang.srt.mem_cache.base_prefix_cache import MatchPrefixParams
from sglang.srt.mem_cache.proactive_prefetch import ProactivePrefetch
from sglang.srt.mem_cache.radix_cache import RadixKey

from toolgap import PrefetchAdmission, PrefetchClient


class TestAdmissionRealCache(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = finite.TestFiniteIO("test_finite_read_exception_worker_survives")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.manager = ProactivePrefetch(self.f.cache)
        self.requests = []

    async def asyncSetUp(self):
        async def handler(request):
            p = json.loads(request.content)
            self.requests.append(p)
            self.f.cache.drain_storage_control_queues()
            self.manager.tick()
            try:
                if p["action"] == "submit":
                    state = self.manager.submit(
                        p["operation_id"], p["input_ids"], p["cache_salt"], p["ttl_ms"]
                    )
                else:
                    state = getattr(self.manager, p["action"])(p["operation_id"])
                return httpx.Response(200, json=dict(success=True, result=state))
            except (ValueError, KeyError) as exc:
                return httpx.Response(400, json=dict(success=False, message=str(exc)))

        self.client = PrefetchClient(
            "http://engine", transport=httpx.MockTransport(handler)
        )
        self.addAsyncCleanup(self.client.aclose)
        self.policy = PrefetchAdmission(self.client)

    def drain(self):
        def done():
            self.manager.tick()
            return self.manager.active is None

        self.f.pump_until(done)
        self.f.cache.drain_storage_control_queues()
        self.manager.tick()

    async def test_background_reconciliation_waits_for_real_cancelled_read_drain(self):
        self.policy = PrefetchAdmission(
            self.client,
            reconcile_interval_ms=1,
            reconcile_max_checks=100,
            reconcile_timeout_ms=100,
        )
        self.addAsyncCleanup(self.policy.aclose)
        entered, resume = threading.Event(), threading.Event()
        original = self.f.backend.batch_get
        reads = []

        def blocked(*args, **kwargs):
            reads.append(1)
            entered.set()
            if not resume.wait(5):
                raise RuntimeError("fixture read timed out")
            return original(*args, **kwargs)

        async def observed_cleanup():
            while self.policy.active is not None:
                await asyncio.sleep(0.001)

        try:
            with mock.patch.object(self.f.backend, "batch_get", side_effect=blocked):
                a = await self.policy.submit("A", self.f.tokens)
                self.f.pump_until(entered.is_set)
                self.assertTrue((await a.cancel())["cleanup_pending"])
                await asyncio.sleep(0.005)
                self.assertGreater(self.policy.metrics["reconciliation_checks"], 0)
                self.assertIs(self.policy.active, a)
                self.assertLess(self.f.pool.available_size(), self.f.initial_slots)
                self.assertEqual(
                    (await self.policy.submit("early-B", self.f.tokens)).state["state"],
                    "LOCAL_BUSY",
                )
                resume.set()
                self.drain()
                await asyncio.wait_for(observed_cleanup(), 1)
        finally:
            resume.set()
        self.assertEqual(a.state["state"], "CANCELLED")
        self.assertFalse(a.state["cleanup_pending"])
        self.f.conservation(self.manager.records[a.operation_id].handle)
        a.finish(used_tokens=0)
        b = await self.policy.submit("later-B", self.f.tokens)
        self.drain()
        await asyncio.wait_for(observed_cleanup(), 1)
        self.assertEqual(b.state["state"], "SUCCESS")
        self.assertEqual(b.state["restored_tokens"], 12)
        b.finish(used_tokens=12)
        self.f.conservation(self.manager.records[b.operation_id].handle, resident=12)
        self.assertEqual(len(reads), 1)
        self.assertEqual(self.policy.metrics["active_slots"], 0)
        self.assertTrue(self.f.cc.prefetch_io_aux_thread.is_alive())

    async def test_two_sessions_cancel_ownership_cleanup_then_next_real_restore(self):
        entered, resume = threading.Event(), threading.Event()
        original = self.f.backend.batch_get
        reads = []

        def blocked(*args, **kwargs):
            reads.append(1)
            entered.set()
            if not resume.wait(5):
                raise RuntimeError("fixture read timed out")
            return original(*args, **kwargs)

        try:
            with mock.patch.object(self.f.backend, "batch_get", side_effect=blocked):
                a = await self.policy.submit("A", self.f.tokens)
                self.f.pump_until(entered.is_set)
                b = await self.policy.submit("B", self.f.tokens, cache_salt="B")
                self.assertEqual(b.state["state"], "LOCAL_BUSY")
                b.finish(used_tokens=0)
                req_a = SimpleNamespace(
                    origin_input_ids=list(self.f.tokens) + [13],
                    extra_key=None,
                    cache_salt=None,
                )
                req_b = SimpleNamespace(
                    origin_input_ids=list(self.f.tokens) + [13],
                    extra_key=None,
                    cache_salt="B",
                )
                self.assertTrue(self.manager.blocks(req_a))
                self.assertFalse(self.manager.blocks(req_b))
                self.assertTrue((await a.cancel())["cleanup_pending"])
                self.assertLess(self.f.pool.available_size(), self.f.initial_slots)
                self.assertEqual(
                    (await self.policy.submit("B", self.f.tokens)).state["state"],
                    "LOCAL_BUSY",
                )
                self.assertEqual(len(reads), 1)
                resume.set()
                self.drain()
                await a.status()
                a.finish(used_tokens=0)
        finally:
            resume.set()
        self.f.conservation(self.manager.records[a.operation_id].handle)
        b = await self.policy.submit("B", self.f.tokens)
        self.drain()
        await b.status()
        self.assertEqual(b.state["state"], "SUCCESS")
        self.assertEqual(b.state["restored_tokens"], 12)
        before = len(self.requests)
        await a.cancel()
        self.assertEqual(len(self.requests), before)
        b.finish(used_tokens=12)
        self.f.conservation(self.manager.records[b.operation_id].handle, resident=12)
        self.assertTrue(self.f.cc.prefetch_io_aux_thread.is_alive())
        self.assertEqual(self.policy.metrics["unused_published_tokens"], 0)

    async def test_same_tokens_different_salt_cannot_reuse_published_other_namespace(
        self,
    ):
        a = await self.policy.submit("A", self.f.tokens)
        self.drain()
        await a.status()
        a.finish(used_tokens=0)
        b = await self.policy.submit("B", self.f.tokens, cache_salt="other-salt")
        self.drain()
        await b.status()
        b.finish(used_tokens=0)
        self.assertEqual(b.state["state"], "MISS")
        self.assertEqual(b.state["restored_tokens"], 0)
        match = self.f.cache.match_prefix(
            MatchPrefixParams(key=RadixKey(self.f.tokens, cache_salt="other-salt"))
        )
        self.assertEqual(match.host_hit_length, 0)
        self.assertEqual(len(match.device_indices), 0)
        self.assertEqual(self.policy.metrics["unused_published_tokens"], 12)
        self.assertEqual(self.policy.metrics["published_tokens"], 12)
        self.f.conservation(self.manager.records[a.operation_id].handle, resident=12)
