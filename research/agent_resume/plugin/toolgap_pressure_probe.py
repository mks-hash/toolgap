"""Research-only plugin; use on BOTH treatments. No new runtime control API."""

import functools
import json
import os
import re
import time
import threading
from pathlib import Path

from research.agent_resume.observer import probe_prefix
from research.agent_resume.sampling import clock_domain
from research.agent_resume.readiness import runtime_provenance


def install():
    from sglang.srt.managers.scheduler import Scheduler
    from sglang.srt.mem_cache.unified_radix_cache import UnifiedRadixCache
    from sglang.srt.mem_cache.proactive_prefetch import ProactivePrefetch
    from sglang.srt.mem_cache.hybrid_cache.hybrid_cache_controller import (
        HybridCacheController,
    )
    from sglang.srt.mem_cache.hicache_storage import HiCacheFile
    import hicache_trace

    if getattr(Scheduler, "_toolgap_pressure_probe_installed", False):
        return
    Scheduler._toolgap_pressure_probe_installed = True
    domain = clock_domain()
    runtime_identity = runtime_provenance(UnifiedRadixCache)
    original_event = hicache_trace.event
    io_context = threading.local()

    def event(kind, **data):
        if kind == "read":
            data["rid"] = getattr(io_context, "rid", None)
        original_event(kind, clock_domain=domain, **data)

    hicache_trace.event = event
    hicache_trace.install()
    original_transfer = HybridCacheController._page_transfer

    @functools.wraps(original_transfer)
    def transfer(self, operation):
        previous = getattr(io_context, "rid", None)
        io_context.rid = operation.handle.rid
        try:
            return original_transfer(self, operation)
        finally:
            io_context.rid = previous

    HybridCacheController._page_transfer = transfer
    original_get = HiCacheFile.batch_get

    @functools.wraps(original_get)
    def get(self, keys, *args, **kwargs):
        started = time.monotonic_ns()
        try:
            return original_get(self, keys, *args, **kwargs)
        except Exception as exc:
            hicache_trace.event(
                "read_error",
                rid=getattr(io_context, "rid", None),
                keys=list(keys),
                start_ns=started,
                end_ns=time.monotonic_ns(),
                error=type(exc).__name__,
            )
            raise

    HiCacheFile.batch_get = get
    original_submit = ProactivePrefetch.submit

    @functools.wraps(original_submit)
    def submit(self, operation_id, *args, **kwargs):
        hicache_trace.event("control_submit_start", operation_id=operation_id)
        result = original_submit(self, operation_id, *args, **kwargs)
        hicache_trace.event(
            "control_accepted_end",
            operation_id=operation_id,
            rid=self.records[operation_id].handle.rid,
            state=result["state"],
            **hicache_trace.occupancy(self.cache),
        )
        return result

    ProactivePrefetch.submit = submit
    original_match = UnifiedRadixCache.match_prefix

    @functools.wraps(original_match)
    def match(self, params):
        rid = getattr(params.req, "rid", None)
        if (
            os.environ.get("TOOLGAP_PRESSURE_MATCH_OBSERVATION", "1") == "1"
            and isinstance(rid, str)
            and rid.startswith("tgp-")
            and len(params.key)
        ):
            started = time.monotonic_ns()
            try:
                if params.key.extra_key is not None or params.key.is_bigram:
                    raise ValueError(
                        "Only unspecialized full-attention keys are supported"
                    )
                state = probe_prefix(self, list(params.key), params.key.cache_salt)
                hicache_trace.event(
                    "before_request_match",
                    rid=rid,
                    state=state,
                    observation_overhead_ns=time.monotonic_ns() - started,
                )
            except Exception as exc:
                hicache_trace.event(
                    "observation_error", rid=rid, error=type(exc).__name__
                )
        return original_match(self, params)

    UnifiedRadixCache.match_prefix = match
    original_tick = Scheduler._process_hicache_events

    @functools.wraps(original_tick)
    def tick(self, *args, **kwargs):
        result = original_tick(self, *args, **kwargs)
        directory = os.environ.get("TOOLGAP_PRESSURE_PROBE_DIR")
        if directory:
            root = Path(directory)
            for request in sorted(root.glob("*.request.json"))[:8]:
                nonce = request.name.removesuffix(".request.json")
                if not re.fullmatch(r"[0-9a-f]{32}", nonce):
                    continue
                response = root / (nonce + ".response.json")
                if response.exists():
                    request.unlink(missing_ok=True)
                    continue
                started = time.monotonic_ns()
                try:
                    data = json.loads(request.read_text())
                    if data.get("clock_domain") != domain:
                        raise ValueError("Observer clocks differ")
                    value = probe_prefix(
                        self.tree_cache,
                        data["input_ids"],
                        data.get("cache_salt"),
                        include_storage=data.get("include_storage", False),
                    )
                except Exception as exc:
                    value = dict(error=type(exc).__name__)
                value["clock_domain"] = domain
                value["runtime_identity"] = runtime_identity
                value["scheduler_observation_overhead_ns"] = (
                    time.monotonic_ns() - started
                )
                value["scheduler_cost_scope"] = (
                    "REQUEST_READ_AND_PROBE; EXCLUDES_RESPONSE_WRITE_AND_TRACE"
                )
                temporary = response.with_suffix(".tmp")
                temporary.write_text(json.dumps(value))
                temporary.replace(response)
                request.unlink(missing_ok=True)
                hicache_trace.event(
                    "observer_service_complete",
                    nonce=nonce,
                    service_started_ns=started,
                    service_completed_ns=time.monotonic_ns(),
                )
        return result

    Scheduler._process_hicache_events = tick
