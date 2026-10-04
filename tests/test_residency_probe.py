"""Real file/cache fixture: the probe must not restore or acquire ownership."""

import unittest
from unittest import mock

import test_prefetch_finite_io as finite
from sglang.srt.mem_cache.base_prefix_cache import CacheRequestHandle
from sglang.srt.mem_cache.proactive_prefetch import ProactivePrefetch
from toolgap_demo_trace import probe_prefix


class TestResidencyProbe(unittest.TestCase):
    def setUp(self):
        self.fixture = finite.TestFiniteIO(
            methodName="test_finite_read_exception_worker_survives"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_l3_probe_reports_exact_namespace_without_get_or_allocation(self):
        f = self.fixture
        before = f.allocator.available_size()
        with mock.patch.object(
            f.backend, "batch_get", side_effect=AssertionError("probe warmed KV")
        ):
            state = probe_prefix(f.cache, list(f.tokens), None)
            wrong = probe_prefix(f.cache, list(f.tokens), "wrong-namespace")
        self.assertEqual(state["device_hit_tokens"], 0)
        self.assertEqual(state["host_hit_tokens"], 0)
        self.assertEqual(state["storage_available_tokens"], len(f.tokens))
        self.assertEqual(wrong["storage_available_tokens"], 0)
        self.assertEqual(f.allocator.available_size(), before)
        f.conservation(CacheRequestHandle("probe", 0))

    def test_resident_probe_does_not_repeat_storage_read(self):
        f = self.fixture
        manager = ProactivePrefetch(f.cache)
        manager.submit("first", list(f.tokens))
        f.pump_until(lambda: not f.cache.ongoing_prefetch)
        manager.tick()
        with mock.patch.object(
            f.backend, "batch_get", side_effect=AssertionError("repeat read")
        ):
            state = probe_prefix(f.cache, list(f.tokens), None)
        self.assertEqual(state["host_hit_tokens"], len(f.tokens))
        self.assertEqual(state["device_hit_tokens"], 0)
        f.conservation(manager.records["first"].handle, resident=len(f.tokens))
