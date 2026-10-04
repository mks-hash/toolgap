"""Demo-only scheduler-thread residency probe; never loads KV payloads."""

import functools
import json
import os
import time
from array import array
from pathlib import Path


def probe_prefix(cache, input_ids, cache_salt):
    from sglang.srt.mem_cache.base_prefix_cache import MatchPrefixParams
    from sglang.srt.mem_cache.radix_cache import RadixKey
    from sglang.srt.mem_cache.utils import get_storage_hash_str

    key = RadixKey(array("q", input_ids), cache_salt=cache_salt).page_aligned(
        cache.page_size
    )
    match = cache.match_prefix(MatchPrefixParams(key=key))
    hashes = get_storage_hash_str(key, page_size=cache.page_size)
    backend = cache.cache_controller.storage_backend
    # exists/stat only, not get/batch_get or the prefetch queue.
    available = backend.batch_exists(hashes)
    pool = cache.cache_controller.mem_pool_host
    accounting = dict(
        host_available_tokens=pool.available_size(),
        inflight_tokens=cache.cache_controller.prefetch_tokens_occupied,
        ongoing_prefetch_count=len(cache.ongoing_prefetch),
    )
    return dict(
        **accounting,
        at_ns=time.monotonic_ns(),
        prefix_tokens=len(key),
        device_hit_tokens=len(match.device_indices),
        host_hit_tokens=match.host_hit_length,
        storage_available_tokens=available * cache.page_size,
        storage_expected_pages=len(hashes),
        storage_key_hashes=hashes,
        storage_model_namespace=getattr(
            getattr(cache.cache_controller, "storage_config", None), "model_name", None
        ),
    )


def install():
    import hicache_trace

    hicache_trace.install()
    from sglang.srt.managers.scheduler import Scheduler
    from sglang.srt.mem_cache.proactive_prefetch import ProactivePrefetch

    if getattr(Scheduler, "_toolgap_probe_installed", False):
        return
    Scheduler._toolgap_probe_installed = True
    original = Scheduler._process_hicache_events

    @functools.wraps(original)
    def tick(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        directory = os.environ.get("TOOLGAP_DEMO_PROBE_DIR")
        if directory:
            request = Path(directory) / "request.json"
            if request.exists():
                data = json.loads(request.read_text())
                response = Path(directory) / (data["nonce"] + ".json")
                if not response.exists():
                    try:
                        value = probe_prefix(
                            self.tree_cache, data["input_ids"], data.get("cache_salt")
                        )
                    except Exception as exc:
                        value = dict(error=type(exc).__name__ + ": " + str(exc))
                    temporary = response.with_suffix(".tmp")
                    temporary.write_text(json.dumps(value))
                    temporary.replace(response)
        return result

    Scheduler._process_hicache_events = tick
    submit_original = ProactivePrefetch.submit

    @functools.wraps(submit_original)
    def submit(self, operation_id, *args, **kwargs):
        hicache_trace.event("control_accepted_start", operation_id=operation_id)
        result = submit_original(self, operation_id, *args, **kwargs)
        hicache_trace.event(
            "control_accepted_end",
            operation_id=operation_id,
            rid=self.records[operation_id].handle.rid,
            state=result["state"],
            **hicache_trace.occupancy(self.cache),
        )
        return result

    ProactivePrefetch.submit = submit
