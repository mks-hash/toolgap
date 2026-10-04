"""Scheduler-thread observation of Python FULL cache without matching/touching.

Direct file stat is optional: no KV payload read or backend metadata-cache lookup.
OS metadata-cache effects and scheduler time remain instrumentation overhead.
"""

import os
import stat
import time
from array import array
from pathlib import Path


def walk_residency(core, key, page_size):
    """Count page-aligned FULL spans without splitting partial radix nodes."""
    node, offset, device, host_copy = core.root_node, 0, 0, 0
    host_tail = False
    segments = []
    while offset < len(key):
        child = node.children.get(key.child_key_at(offset, page_size))
        if child is None:
            break
        length = child.key.match_at(key, offset, page_size=page_size)
        if length == 0:
            break
        full = child.component_data[0]  # ComponentType.FULL in pinned Python core
        on_device, on_host = full.value is not None, full.host_value is not None
        if not on_device and not on_host:
            break
        if on_device and host_tail:
            raise ValueError(
                "Noncontiguous device residency is outside this observer's scope"
            )
        segments.append(
            dict(start=offset, end=offset + length, device=on_device, host=on_host)
        )
        if on_device:
            device += length
        else:
            host_tail = True
        if on_host:
            host_copy += length
        offset += length
        node = child
        if length < len(child.key):
            break
    return dict(
        device_hit_tokens=device,
        host_hit_tokens=offset - device,
        host_copy_tokens=host_copy,
        resident_prefix_tokens=offset,
        segments=segments,
    )


def classify(state):
    length = state["prefix_tokens"]
    if length == 0:
        return "EMPTY"
    if state["device_hit_tokens"] == length:
        return "GPU_RESIDENT"
    if state["resident_prefix_tokens"] == length:
        return "HOST_RESIDENT"
    if state["resident_prefix_tokens"]:
        return "PARTIAL"
    storage = state.get("storage_available_tokens")
    if storage is None:
        return "UNKNOWN_STORAGE"
    if storage == length:
        return "L3_ONLY"
    return "PARTIAL_STORAGE" if storage else "COLD"


def probe_prefix(cache, input_ids, cache_salt=None, *, include_storage=False):
    """Call exclusively on the scheduler thread; no allocation/lock/IO transfer."""
    from sglang.srt.mem_cache.hicache_storage import HiCacheFile
    from sglang.srt.mem_cache.radix_cache import RadixKey
    from sglang.srt.mem_cache.unified_cache.component_type import ComponentType
    from sglang.srt.mem_cache.unified_cache.unified_tree_core import UnifiedTreeCore
    from sglang.srt.mem_cache.utils import get_storage_hash_str

    core = cache.tree_core
    if (
        not isinstance(core, UnifiedTreeCore)
        or cache._tree_core_backend != "python"
        or core.component_types != (ComponentType.FULL,)
        or core.is_eagle
        or core.enable_session_radix_cache
        or cache.host_memory_mode != "cache"
        or not core.enable_hicache
        or cache.tp_world_size != 1
        or cache.pp_size != 1
    ):
        raise ValueError(
            "Observer requires Python FULL resident cache, TP1/PP1, no session radix/EAGLE"
        )
    backend = cache.cache_controller.storage_backend
    if type(backend) is not HiCacheFile:
        raise ValueError("Observer requires the existing file backend")
    if (
        not input_ids
        or any(type(t) is not int or t < 0 for t in input_ids)
        or len(input_ids) > 32768
    ):
        raise ValueError("Supply 1..32768 exact nonnegative token IDs")
    if cache_salt is not None and (
        not isinstance(cache_salt, str) or len(cache_salt) > 256
    ):
        raise ValueError("Invalid cache salt")
    key = RadixKey(array("q", input_ids), cache_salt=cache_salt).page_aligned(
        cache.page_size
    )
    started = time.monotonic_ns()
    state = walk_residency(core, key, cache.page_size)
    pool = cache.cache_controller.mem_pool_host
    state.update(
        prefix_tokens=len(key),
        cache_read_started_ns=started,
        cache_read_completed_ns=time.monotonic_ns(),
        host_used_tokens=pool.anchor_entry.host_pool.size - pool.available_size(),
        host_available_tokens=pool.available_size(),
        device_available_tokens=cache.token_to_kv_pool_allocator.available_size(),
        inflight_tokens=cache.cache_controller.prefetch_tokens_occupied,
        ongoing_prefetch_count=len(cache.ongoing_prefetch),
        storage_available_tokens=None,
        storage_file_bytes=None,
        observation="PASSIVE_PYTHON_FULL",
        storage_check="NOT_REQUESTED",
    )
    if include_storage:
        state["storage_check_started_ns"] = time.monotonic_ns()
        pages, size = 0, 0
        try:
            for digest in get_storage_hash_str(key, page_size=cache.page_size):
                # _get_component_key is a pure filename transform in the pinned backend.
                path = Path(backend.file_path) / (
                    backend._get_component_key(digest) + ".bin"
                )
                try:
                    entry = os.stat(path)
                except FileNotFoundError:
                    break
                if not stat.S_ISREG(entry.st_mode):
                    break
                pages += 1
                size += entry.st_size
            state.update(
                storage_available_tokens=pages * cache.page_size,
                storage_file_bytes=size,
                storage_check="DIRECT_STAT_NO_BACKEND_CACHE",
            )
        except OSError as exc:
            # Filesystem errors are unknown availability, never evidence of a MISS.
            state["storage_check"] = "ERROR"
            state["storage_error"] = type(exc).__name__
        state["storage_check_completed_ns"] = time.monotonic_ns()
    state["residency"] = classify(state)
    state["observation_completed_ns"] = time.monotonic_ns()
    return state
