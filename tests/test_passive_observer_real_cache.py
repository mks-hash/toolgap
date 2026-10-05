"""Real CPU FULL/file cache: observation must not change eviction/ownership."""

import copy
import json
import sys
import tempfile
import types
from contextlib import ExitStack
from pathlib import Path
import unittest
from array import array
from unittest import mock

import test_prefetch_finite_io as finite
from sglang.srt.mem_cache.base_prefix_cache import (
    CacheRequestHandle,
    InsertParams,
    MatchPrefixParams,
)
from sglang.srt.mem_cache.radix_cache import RadixKey
from sglang.srt.mem_cache.unified_cache.components import base
from sglang.srt.mem_cache.unified_cache.unified_tree_core import UnifiedTreeNode

from research.agent_resume.observer import probe_prefix


def fingerprint(f):
    core = f.cache.tree_core
    nodes = []
    for ident, node in sorted(core._node_arena.items()):
        full = node.component_data[0]
        nodes.append(
            (
                ident,
                node.parent.id if node.parent else None,
                tuple(sorted((str(k), v.id) for k, v in node.children.items())),
                tuple(node.key or []),
                node.last_access_time,
                node.creation_time,
                node.hit_count,
                full.lock_ref,
                full.host_lock_ref,
                full.session_ref,
                tuple(
                    full.value.tolist() if hasattr(full.value, "tolist") else full.value
                )
                if full.value is not None
                else None,
                tuple(full.host_value.tolist())
                if full.host_value is not None
                else None,
                node.write_through_pending_id,
                node.load_back_pending_id,
            )
        )
    return (
        (
            tuple(f.backend._evictor._lru.items()),
            frozenset(f.backend._evictor._pending_writes),
            f.backend._evictor._total_bytes,
        )
        if f.backend._evictor is not None
        else None,
        nodes,
        UnifiedTreeNode.counter,
        base._LAST_ACCESS_TIME_COUNTER_FLOAT,
        f.allocator.available_size(),
        f.pool.available_size(),
        f.pool.anchor_entry.host_pool.slot_used.tolist(),
        tuple(f.cache.ongoing_prefetch),
        f.cc.prefetch_tokens_occupied,
        copy.deepcopy(f.backend.metadata_cache.cache)
        if f.backend.metadata_cache is not None
        else None,
    )


class TestPassiveObserver(unittest.TestCase):
    def setUp(self):
        self.f = finite.TestFiniteIO("test_finite_read_exception_worker_survives")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def check_unchanged(self, ids, *, salt=None, storage=False, repeats=20):
        f = self.f
        before = fingerprint(f)
        with (
            mock.patch.object(
                f.cache,
                "match_prefix",
                side_effect=AssertionError("matching changes recency"),
            ),
            mock.patch.object(
                f.backend, "batch_get", side_effect=AssertionError("KV read")
            ),
            mock.patch.object(
                f.backend,
                "batch_exists",
                side_effect=AssertionError("backend metadata-cache lookup"),
            ),
            mock.patch.object(
                f.backend, "exists", side_effect=AssertionError("metadata cache warmed")
            ),
            mock.patch.object(
                f.allocator, "alloc", side_effect=AssertionError("device allocation")
            ),
            mock.patch.object(
                f.pool, "alloc", side_effect=AssertionError("host allocation")
            ),
        ):
            for _ in range(repeats):
                result = probe_prefix(f.cache, list(ids), salt, include_storage=storage)
                self.assertEqual(fingerprint(f), before)
        return result

    def test_l3_only_and_wrong_salt_without_backend_cache_side_effects(self):
        from sglang.srt.mem_cache.hicache_storage import MetadataCache

        self.f.backend.metadata_cache = MetadataCache(5)
        state = self.check_unchanged(self.f.tokens, storage=True)
        self.assertEqual(state["residency"], "L3_ONLY")
        self.assertEqual(state["storage_available_tokens"], 12)
        self.assertGreater(state["storage_file_bytes"], 0)
        wrong = self.check_unchanged(self.f.tokens, salt="another", storage=True)
        self.assertEqual(wrong["residency"], "COLD")

    def test_observed_backend_layout_and_imported_runtime_identity_are_real(self):
        from research.agent_resume.readiness import runtime_provenance

        state = self.check_unchanged(self.f.tokens)
        identity = state["storage_identity"]
        self.assertEqual(identity["page_size"], self.f.cache.page_size)
        self.assertEqual(identity["layout"], "page_first")
        self.assertEqual(identity["kv_dtype"], "bfloat16")
        self.assertGreater(identity["bytes_per_token"], 0)
        runtime = runtime_provenance(type(self.f.cache))
        self.assertEqual(runtime["status"], "OBSERVED_CHECKOUT")
        self.assertTrue(runtime["tracked_runtime_clean"])
        self.assertEqual(len(runtime["head"]), 40)

    def test_idle_reset_clears_resident_kv_but_preserves_file_l3(self):
        f = self.f
        handle = f.submit()
        f.settle(handle)
        f.conservation(handle, resident=len(f.tokens))
        device = f.allocator.alloc(4)
        f.cache.insert(InsertParams(key=RadixKey(f.tokens[:4]), value=device))
        files = {p.name: p.read_bytes() for p in Path(f.directory.name).iterdir()}
        self.assertEqual(
            probe_prefix(f.cache, list(f.tokens), None)["device_hit_tokens"], 4
        )
        f.cache.reset()
        f.allocator.clear()  # Scheduler.flush_cache also clears the device allocator.
        state = probe_prefix(f.cache, list(f.tokens), None, include_storage=True)
        self.assertEqual(state["device_hit_tokens"], 0)
        self.assertEqual(state["host_hit_tokens"], 0)
        self.assertEqual(state["storage_available_tokens"], len(f.tokens))
        self.assertEqual(
            {p.name: p.read_bytes() for p in Path(f.directory.name).iterdir()}, files
        )
        self.assertEqual(f.pool.available_size(), f.initial_slots)
        self.assertEqual(f.allocator.available_size(), f.cfg.kv_size)
        self.assertEqual(f.cache.ongoing_prefetch, {})
        self.assertEqual(f.cc.prefetch_tokens_occupied, 0)
        self.assertTrue(f.cc.prefetch_io_aux_thread.is_alive())
        f.next_prefetch()

    def test_detach_reset_owned_directory_reattach_starts_empty_and_reusable(self):
        f = self.f
        handle = f.submit()
        f.settle(handle)
        f.conservation(handle, resident=len(f.tokens))
        model_name = f.cc.storage_config.model_name
        threads = [
            f.cc.prefetch_thread,
            f.cc.prefetch_io_aux_thread,
            f.cc.prefetch_sync_thread,
            f.cc.backup_thread,
        ]
        ok, message = f.cache.detach_storage_backend()
        self.assertTrue(ok, message)
        self.assertTrue(all(not t.is_alive() for t in threads))
        self.assertFalse(f.cache.enable_storage)
        f.cache.reset()
        f.allocator.clear()
        # Only a fixture-owned temporary directory is touched; no active backend.
        claim = Path(f.directory.name) / "toolgap-identity.json"
        claim.write_text('{"fixture": true}')
        archived = {
            p.name: p.read_bytes() for p in Path(f.directory.name).glob("*.bin")
        }
        self.assertEqual(len(archived), len(f.hashes))
        for path in Path(f.directory.name).glob("*.bin"):
            path.unlink()
        ok, message = f.cache.attach_storage_backend(
            storage_backend="file",
            storage_backend_extra_config_json=json.dumps({"prefetch_threshold": 4}),
            served_model_name=model_name,
            hicache_storage_prefetch_policy="wait_complete",
            hicache_write_policy="write_through",
        )
        self.assertTrue(ok, message)
        f.backend = f.cc.storage_backend
        f.cc.prefetch_capacity_limit = max(f.cc.prefetch_capacity_limit, f.pool.size)
        state = probe_prefix(f.cache, list(f.tokens), None, include_storage=True)
        self.assertEqual(state["device_hit_tokens"], 0)
        self.assertEqual(state["host_hit_tokens"], 0)
        self.assertEqual(state["storage_available_tokens"], 0)
        self.assertEqual(f.pool.available_size(), f.initial_slots)
        self.assertEqual(f.allocator.available_size(), f.cfg.kv_size)
        self.assertEqual(f.cache.ongoing_prefetch, {})
        self.assertEqual(f.cc.prefetch_tokens_occupied, 0)
        self.assertEqual(
            [p.name for p in Path(f.directory.name).iterdir()], [claim.name]
        )
        self.assertEqual(claim.read_text(), '{"fixture": true}')
        self.assertTrue(f.cc.prefetch_io_aux_thread.is_alive())
        # A subsequent genuine L3 restore works after the block reset.
        for name, payload in archived.items():
            (Path(f.directory.name) / name).write_bytes(payload)
        f.next_prefetch()

    def test_default_observation_performs_no_filesystem_query(self):
        with mock.patch(
            "research.agent_resume.observer.os.stat", side_effect=AssertionError("stat")
        ):
            state = self.check_unchanged(self.f.tokens)
        self.assertEqual(state["residency"], "UNKNOWN_STORAGE")

    def test_partial_host_match_does_not_split_node(self):
        f = self.f
        handle = f.submit()
        f.settle(handle)
        state = self.check_unchanged(f.tokens[:8], storage=True)
        self.assertEqual(state["host_hit_tokens"], 8)
        self.assertEqual(state["residency"], "HOST_RESIDENT")
        before = fingerprint(f)
        normal = f.cache.match_prefix(MatchPrefixParams(key=RadixKey(f.tokens[:8])))
        self.assertEqual(normal.host_hit_length, state["host_hit_tokens"])
        self.assertNotEqual(fingerprint(f), before)  # ordinary matching splits/touches
        f.conservation(handle, resident=12)

    def test_device_partial_and_shared_prefix_classification(self):
        f = self.f
        value = f.allocator.alloc(12)
        f.cache.insert(InsertParams(key=f.key, value=value))
        state = self.check_unchanged(f.tokens[:8])
        self.assertEqual(state["device_hit_tokens"], 8)
        self.assertEqual(state["residency"], "GPU_RESIDENT")
        other = array("q", list(f.tokens[:8]) + [99, 100, 101, 102])
        state = self.check_unchanged(other, storage=True)
        self.assertEqual(state["device_hit_tokens"], 8)
        self.assertEqual(state["residency"], "PARTIAL")

    def test_host_and_device_counts_agree_with_normal_matching(self):
        f = self.f
        handle = f.submit()
        f.settle(handle)
        first = f.allocator.alloc(4)
        f.cache.insert(InsertParams(key=RadixKey(f.tokens[:4]), value=first))
        state = self.check_unchanged(f.tokens, storage=True)
        match = f.cache.match_prefix(MatchPrefixParams(key=f.key))
        self.assertEqual(state["device_hit_tokens"], len(match.device_indices))
        self.assertEqual(state["host_hit_tokens"], match.host_hit_length)
        self.assertEqual((state["device_hit_tokens"], state["host_hit_tokens"]), (4, 8))

    def test_stat_failure_is_unknown_not_miss(self):
        with mock.patch(
            "research.agent_resume.observer.os.stat", side_effect=PermissionError
        ):
            state = self.check_unchanged(self.f.tokens, storage=True, repeats=1)
        self.assertIsNone(state["storage_available_tokens"])
        self.assertEqual(state["residency"], "UNKNOWN_STORAGE")

    def test_trace_maps_real_storage_transfer_to_handle(self):
        import hicache_trace
        from research.agent_resume.plugin import toolgap_pressure_probe
        from research.agent_resume.sampling import clock_domain
        from sglang.srt.mem_cache.hicache_storage import HiCacheFile
        from sglang.srt.mem_cache.hybrid_cache.hybrid_cache_controller import (
            HybridCacheController,
        )
        from sglang.srt.mem_cache.unified_radix_cache import UnifiedRadixCache
        from sglang.srt.mem_cache.proactive_prefetch import ProactivePrefetch

        class Scheduler:
            def _process_hicache_events(self):
                return None

            def handle_generate_request(self, obj):
                return None

        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            path = Path(folder) / "trace.jsonl"
            stack.enter_context(
                mock.patch.dict(
                    sys.modules,
                    {
                        "sglang.srt.managers.scheduler": types.SimpleNamespace(
                            Scheduler=Scheduler
                        )
                    },
                )
            )
            stack.enter_context(
                mock.patch.dict(
                    "os.environ",
                    {
                        "HICACHE_BENCH_TRACE": str(path),
                        "HICACHE_BENCH_LABEL": "cpu-fixture",
                    },
                )
            )
            for cls, name in [
                (HiCacheFile, "batch_get"),
                (HybridCacheController, "_page_transfer"),
                (UnifiedRadixCache, "_handle_prefetch_result"),
                (UnifiedRadixCache, "evict_host"),
                (UnifiedRadixCache, "load_back"),
                (UnifiedRadixCache, "match_prefix"),
                (ProactivePrefetch, "submit"),
                (hicache_trace, "event"),
            ]:
                stack.enter_context(mock.patch.object(cls, name, getattr(cls, name)))
            stack.enter_context(
                mock.patch.object(
                    HiCacheFile, "_benchmark_trace_installed", False, create=True
                )
            )
            loads = []

            def cpu_enqueue(cache, node_id, mem_quota=None, req=None):
                loads.append((node_id, mem_quota, req))
                if node_id == -1:
                    raise RuntimeError("enqueue failure")
                return node_id == 1

            stack.enter_context(
                mock.patch.object(UnifiedRadixCache, "load_back", cpu_enqueue)
            )
            toolgap_pressure_probe.install()
            handle = self.f.submit()
            self.f.settle(handle)
            self.f.conservation(handle, resident=12)
            req = types.SimpleNamespace(rid="tgp-continuation")
            self.assertTrue(self.f.cache.load_back(1, mem_quota=8, req=req))
            self.assertFalse(self.f.cache.load_back(0, req=req))
            with self.assertRaisesRegex(RuntimeError, "enqueue failure"):
                self.f.cache.load_back(-1, req=req)
            self.assertEqual(loads, [(1, 8, req), (0, None, req), (-1, None, req)])
            events = [json.loads(line) for line in path.read_text().splitlines()]
            enqueues = [e for e in events if e["kind"] == "request_h2d_enqueue"]
            self.assertEqual([e["accepted"] for e in enqueues], [True, False, False])
            self.assertTrue(all(e["rid"] == req.rid for e in enqueues))
            reads = [e for e in events if e["kind"] == "read"]
            self.assertTrue(reads)
            self.assertTrue(all(e["rid"] == handle.rid for e in reads))
            self.assertTrue(all(e["clock_domain"] == clock_domain() for e in events))
            self.assertGreater(sum(e["bytes"] for e in reads), 0)

    def test_unsupported_configuration_fails_without_matching(self):
        self.f.cache.host_memory_mode = "buffer_only"
        with self.assertRaises(ValueError):
            probe_prefix(self.f.cache, list(self.f.tokens))

    def test_probe_keeps_future_eviction_choice_and_recovery_usable(self):
        f = self.f
        handle = f.submit()
        f.settle(handle)
        core = f.cache.tree_core
        candidate = min(
            (n for n in core._node_arena.values() if n.parent is not None),
            key=lambda n: core.eviction_strategy.get_priority(n),
        ).id
        self.check_unchanged(f.tokens[:4], storage=True, repeats=100)
        after = min(
            (n for n in core._node_arena.values() if n.parent is not None),
            key=lambda n: core.eviction_strategy.get_priority(n),
        ).id
        self.assertEqual(after, candidate)
        f.conservation(handle, resident=12)
        f.cache.reset()
        next_handle = CacheRequestHandle("after-observation", 0)
        f.submit(next_handle)
        f.settle(next_handle)
        f.conservation(next_handle, resident=12)


if __name__ == "__main__":
    unittest.main()
