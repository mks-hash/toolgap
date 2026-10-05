"""Descriptive physical trace report; no inferred consumption or causal TTFT claim."""

import argparse
from collections import Counter
import json
from pathlib import Path
from .readiness import file_hash


def saved_span(state, length):
    device = host = 0
    for segment in state["segments"]:
        count = max(0, min(segment["end"], length) - segment["start"])
        if segment["device"]:
            device += count
        elif segment["host"]:
            host += count
    return dict(
        device_hit_tokens=device,
        host_hit_tokens=host,
        observed_prefix_tokens=min(length, state["prefix_tokens"]),
    )


def request_cache_usage(generation):
    """Actual request-tier counters, never ownership of a proactive operation."""
    unknown = dict(status="UNKNOWN", device=None, host=None, storage=None)
    meta = generation.get("meta_info", {})
    details = meta.get("cached_tokens_details")
    length = len(generation.get("input_ids", []))
    total = meta.get("cached_tokens")
    if not generation.get("rid") or not isinstance(details, dict):
        return unknown
    values = [details.get(k) for k in ("device", "host", "storage")]
    if (
        not all(type(v) is int and v >= 0 for v in values)
        or sum(values) > length
        or type(total) is not int
        or total != sum(values)
        or meta.get("prompt_tokens") != length
    ):
        return dict(unknown, status="INVALID")
    return dict(status="REPORTED", device=values[0], host=values[1], storage=values[2])


def physical_io(events, *, start=None, end=None):
    if start is None or end is None:
        return None
    return sum(
        max(0, min(e["end_ns"], end) - max(e["start_ns"], start)) / 1e6 for e in events
    )


def analyze(rows, events, domain):
    if any(e.get("clock_domain") != domain for e in events):
        raise ValueError("Server trace clocks differ or lack boot provenance")
    reads = [e for e in events if e["kind"] == "read"]
    errors = [e for e in events if e["kind"] == "read_error"]
    keys = Counter(k for e in reads for k in e["keys"])
    accepted = {
        e["operation_id"]: e["rid"]
        for e in events
        if e["kind"] == "control_accepted_end"
    }
    boundaries = []
    for row in rows:
        for index, step in enumerate(row.get("tools", [])):
            arrival = step.get("continuation_submitted_ns")
            op = step.get("prefetch_operation_id")
            rid = accepted.get(op)
            own_reads = [e for e in reads if rid is not None and e.get("rid") == rid]
            pubs = [
                e
                for e in events
                if rid is not None and e["kind"] == "publish" and e["rid"] == rid
            ]
            continuation_rid = (
                row["generations"][index + 1].get("rid")
                if index + 1 < len(row.get("generations", []))
                else None
            )
            generation = (
                row["generations"][index + 1] if continuation_rid is not None else {}
            )
            request_reads = [
                e
                for e in reads
                if continuation_rid is not None and e.get("rid") == continuation_rid
            ]
            loads = [
                e
                for e in events
                if continuation_rid is not None
                and e["kind"] == "request_h2d_enqueue"
                and e.get("rid") == continuation_rid
            ]
            publication = next(
                (
                    e["at_ns"]
                    for e in sorted(pubs, key=lambda e: e["at_ns"])
                    if e["restored_tokens"] > 0
                ),
                None,
            )
            matches = [
                e
                for e in events
                if continuation_rid is not None
                and e["kind"] == "before_request_match"
                and e["rid"] == continuation_rid
            ]
            boundaries.append(
                dict(
                    trajectory_id=row["trajectory_id"],
                    tool_index=index,
                    before_dispatch=step.get("cache_before_dispatch"),
                    cache_samples=step.get("cache_samples", []),
                    cache_window_summary=step.get("cache_window_summary"),
                    continuation_match_samples=[e["state"] for e in matches],
                    saved_prefix_match_samples=[
                        saved_span(e["state"], len(step["prefix_ids"])) for e in matches
                    ],
                    operation_id=op,
                    restore_rid=rid,
                    continuation_rid=continuation_rid,
                    timeline_ns=dict(
                        tool_dispatched=step.get("dispatched_ns"),
                        prefetch_submission_started=step.get(
                            "prefetch_submission_started_ns"
                        ),
                        prefetch_submission_completed=step.get(
                            "prefetch_submission_completed_ns"
                        ),
                        first_positive_l2_publication=publication,
                        tool_completed=step.get("completed_ns"),
                        continuation_submitted=arrival,
                        continuation_first_token=step.get(
                            "continuation_first_token_ns"
                        ),
                    ),
                    request_cache_usage=request_cache_usage(generation),
                    request_time_physical_read_batches=len(request_reads)
                    if continuation_rid is not None
                    else None,
                    request_time_physical_read_bytes=sum(
                        e["bytes"] for e in request_reads
                    )
                    if continuation_rid is not None
                    else None,
                    request_time_physical_io_ms=physical_io(
                        request_reads, start=arrival, end=generation.get("completed_ns")
                    ),
                    request_h2d_enqueue_events=loads,
                    pre_arrival_published_tokens=sum(
                        e["restored_tokens"]
                        for e in pubs
                        if arrival is not None and e["at_ns"] <= arrival
                    )
                    if rid is not None
                    else None,
                    physical_io_before_arrival_ms=sum(
                        max(0, min(e["end_ns"], arrival) - e["start_ns"]) / 1e6
                        for e in own_reads
                    )
                    if arrival is not None and rid is not None
                    else None,
                    physical_read_bytes=sum(e["bytes"] for e in own_reads)
                    if rid is not None
                    else None,
                    physical_io_overlapped_tool_ms=physical_io(
                        own_reads,
                        start=step.get("dispatched_ns"),
                        end=step.get("completed_ns"),
                    ),
                    continuation_ttft_ms=step.get("continuation_ttft_ms"),
                    tool_dispatch_to_first_token_ms=step.get(
                        "tool_dispatch_to_first_token_ms"
                    ),
                )
            )
    return dict(
        physical_read_batches=len(reads),
        physical_read_errors=len(errors),
        physical_read_bytes=sum(e["bytes"] for e in reads),
        unattributed_read_batches=sum(e.get("rid") is None for e in reads),
        repeated_successful_page_reads=sum(n - 1 for n in keys.values()),
        repeated_read_interpretation="May include legitimate rereads after eviction; not a duplicate-I/O bug count",
        host_eviction_events=[e for e in events if e["kind"] == "evict_host"],
        occupancy_samples=[
            {k: e[k] for k in ("at_ns", "host_used_tokens", "inflight_tokens")}
            for e in events
            if "host_used_tokens" in e
        ],
        boundaries=boundaries,
        consumed_restore_tokens=None,
        wasted_prefetch_bytes=None,
        usage_note="Publication and matching do not prove operation-specific consumption; waste remains unknown",
        request_usage_note="Server-reported disjoint tier counters cover the whole continuation prompt, including its suffix; not operation-specific consumption. Missing details are unknown. H2D events report CPU enqueue attempts, not GPU completion.",
        observation_errors=[e for e in events if e["kind"] == "observation_error"],
        scheduler_observer_service_ns=[
            e["service_completed_ns"] - e["service_started_ns"]
            for e in events
            if e["kind"] == "observer_service_complete"
        ],
        overhead_note="Service includes mailbox response write, excludes its trace event; client wait is not active CPU cost. Net perturbation needs matched observation-on/off live calibration.",
        performance_claim=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Never overwrite evidence")
    if args.trace.resolve() != (args.block / "server-trace.jsonl").resolve():
        parser.error("Retain the dedicated raw trace as BLOCK/server-trace.jsonl")
    rows = [
        json.loads(line)
        for line in (args.block / "tasks.jsonl").read_text().splitlines()
    ]
    events = [json.loads(line) for line in args.trace.read_text().splitlines()]
    manifest = json.loads((args.block / "manifest.json").read_text())
    if not events:
        raise ValueError("Empty server trace is not evidence of zero I/O")
    if any(e.get("label") != manifest["block_id"] for e in events):
        raise ValueError("Use a dedicated server trace with this block's label")
    events = [
        e
        for e in events
        if manifest["started_ns"] <= e["at_ns"] <= manifest["finalized_ns"]
    ]
    if not events:
        raise ValueError("No events in the measured block")
    report = analyze(rows, events, manifest["clock_domain"])
    report["source_artifacts_sha256"] = {
        name: file_hash(args.block / name)
        for name in (
            "manifest.json",
            "tasks.jsonl",
            "summary.json",
            "server-trace.jsonl",
        )
    }
    args.output.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
