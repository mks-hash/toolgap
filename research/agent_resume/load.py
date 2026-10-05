"""Pinned code-audit tasks and fixed open-loop arrivals; no padded contexts."""

import asyncio
import copy
import hashlib
import math
import statistics
import time
from collections import Counter

from .runner import initial_messages
from .workloads import SCHEMA


MAX_COMPARISON_DEGRADATION_FRACTION = 0.05
MAX_OBSERVER_RELATIVE_CHANGE_FRACTION = 0.05


AUDITS = [
    dict(
        id="ownership-audit",
        question="Audit whether a locally rejected hint may release another operation's "
        "unknown/pending ownership. Search/read the implementation and the regression proving ownership remains "
        "held, then run admission_hints. Return answer retain_until_cleanup if verified, with evidence from both files.",
        answer="retain_until_cleanup",
        path="src/toolgap/admission.py",
        needle='response.get("cleanup_pending")',
        evidence_requirements=[
            dict(
                path="src/toolgap/admission.py",
                needle='response.get("cleanup_pending")',
            ),
            dict(
                path="tests/test_admission_hints.py",
                needle="test_local_rejection_does_not_release_ambiguous_active_operation",
            ),
        ],
        required_tool="run_regression",
    ),
    dict(
        id="resident-audit",
        question="Audit whether a resident-prefix hint skips the remote submit. Find the "
        "decision and a regression proving no worker HTTP is sent. Run admission_hints. Return answer "
        "skip_remote_submit if verified, citing implementation and regression.",
        answer="skip_remote_submit",
        path="src/toolgap/admission.py",
        needle='reason = "LOCAL_RESIDENT"',
        evidence_requirements=[
            dict(path="src/toolgap/admission.py", needle='reason = "LOCAL_RESIDENT"'),
            dict(
                path="tests/test_admission_hints.py",
                needle="Local eligibility must not contact the worker",
            ),
        ],
        required_tool="run_regression",
    ),
    dict(
        id="overlap-audit",
        question="Audit whether absent overlap estimates preserve ordinary admission rather "
        "than pretending the prefix is resident. Find the conditional decision and its regression. Run "
        "admission_hints. Return answer preserve_admission if verified, citing both files.",
        answer="preserve_admission",
        path="src/toolgap/admission.py",
        needle="hint.estimated_hidden_ms is not None",
        evidence_requirements=[
            dict(
                path="src/toolgap/admission.py",
                needle="hint.estimated_hidden_ms is not None",
            ),
            dict(
                path="tests/test_admission_hints.py",
                needle="test_missing_estimates_and_disabled_threshold_preserve_admission",
            ),
        ],
        required_tool="run_regression",
    ),
]


def context_task(adapter, tokenizer, task, corpus, *, target_tokens=4000, variant=0):
    """Fill a bounded source-reading packet with unique, numbered real excerpts."""
    result = copy.deepcopy(task)
    if type(target_tokens) is not int or not 512 <= target_tokens <= 16384:
        raise ValueError("target_tokens must be in 512..16384")
    paths = sorted(corpus["files"])
    if not paths:
        raise ValueError("Empty source corpus")
    offset = variant % len(paths)
    paths = paths[offset:] + paths[:offset]
    priority = list(dict.fromkeys(r["path"] for r in task["evidence_requirements"]))
    paths = priority + [p for p in paths if p not in priority]
    priority_spans = []
    for requirement in task["evidence_requirements"]:
        lines = corpus["files"][requirement["path"]]["text"].splitlines()
        line = next(i for i, text in enumerate(lines) if requirement["needle"] in text)
        priority_spans.append((requirement["path"], line // 12 * 12))
    chunks = {}
    for path in paths:
        data = corpus["files"][path]
        lines = data["text"].splitlines()
        for start in range(0, len(lines), 12):
            chunks[(path, start)] = f"{path} sha256={data['sha256']}\n" + "\n".join(
                f"{i + 1}: {text}"
                for i, text in enumerate(lines[start : start + 12], start)
            )
    remaining = [span for span in chunks if span not in priority_spans]
    if remaining:
        offset = (variant * 3) % len(remaining)
        remaining = remaining[offset:] + remaining[:offset]
    chunks = [chunks[span] for span in dict.fromkeys(priority_spans + remaining)]
    # Binary search a packet boundary. No duplicated filler or cut token sequence.
    lo, hi = 0, len(chunks)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        result["context_pack"] = "\n\n".join(chunks[:mid])
        count = len(
            adapter.prompt(tokenizer, initial_messages(adapter, result), SCHEMA)
        )
        if count <= target_tokens:
            lo = mid
        else:
            hi = mid - 1
    result["context_pack"] = "\n\n".join(chunks[:lo])
    ids = adapter.prompt(tokenizer, initial_messages(adapter, result), SCHEMA)
    if len(ids) < target_tokens * 0.8:
        raise ValueError(
            f"Useful packet cannot reach 80% of context band: {task['id']} variant={variant} tokens={len(ids)}"
        )
    result["initial_input_ids"] = ids
    result["context_sha256"] = hashlib.sha256(
        result["context_pack"].encode()
    ).hexdigest()
    result["initial_tokens"] = len(ids)
    result["source_commit"] = corpus["commit"]
    return result


def fixed_trace(count=12):
    if type(count) is not int or not 2 <= count <= 32:
        raise ValueError("Use 2..32 bounded agent tasks")
    return [
        dict(
            trajectory_id=f"agent-{i:02d}",
            cache_salt=f"pressure-agent-{i:02d}",
            audit_id=AUDITS[i % len(AUDITS)]["id"],
            offset_ms=(i // 8) * 1200 + (i % 8) * 100,
            context_variant=i,
        )
        for i in range(count)
    ]


async def run_arrivals(trace, run, *, max_active=8, on_result=None):
    """Exogenous arrival times stay fixed; record client admission/queue delay."""
    if type(max_active) is not int or max_active < 1:
        raise ValueError("max_active must be positive")
    labels = [t["trajectory_id"] for t in trace]
    if len(set(labels)) != len(labels) or any(
        type(t["offset_ms"]) is not int or t["offset_ms"] < 0 for t in trace
    ):
        raise ValueError("Unique trajectories and nonnegative integer offsets required")
    gate = asyncio.Semaphore(max_active)
    start = time.monotonic_ns()
    active, peak = 0, 0

    outcomes = {}

    def retain(item, row, reached=None, admitted=None, released=None):
        ident = item["trajectory_id"]
        if ident in outcomes:
            raise ValueError("Caller outcome was already recorded")
        scheduled = start + item["offset_ms"] * 1_000_000
        cancelled = row["status"] == "CANCELLED"
        row.update(
            trajectory_id=ident,
            scheduled_arrival_ns=scheduled,
            arrival_reached_ns=reached,
            client_admitted_ns=admitted,
            client_released_ns=released,
            client_queue_ms=(admitted - reached) / 1e6
            if admitted is not None and reached is not None
            else None,
            arrival_lag_ms=(reached - scheduled) / 1e6 if reached is not None else None,
            arrival_to_completed_ms=(row["completed_ns"] - scheduled) / 1e6
            if not cancelled
            else None,
            arrival_to_finalized_ms=(released - scheduled) / 1e6
            if not cancelled and released is not None
            else None,
            latency_censored=cancelled,
            arrival_phase=(
                "RUNNING"
                if admitted is not None
                else "WAITING_CLIENT_GATE"
                if reached is not None
                else "NOT_YET_ARRIVED"
            ),
            cancellation_observed_ns=row["completed_ns"] if cancelled else None,
        )
        outcomes[ident] = row
        if on_result:
            on_result(row)

    async def arrival(item):
        nonlocal active, peak
        scheduled = start + item["offset_ms"] * 1_000_000
        reached = admitted = released = None
        row = None
        try:
            await asyncio.sleep(
                max(0, (scheduled - time.monotonic_ns()) / 1e9)
            )  # arrival pacing, never tool sleep
            reached = time.monotonic_ns()
            async with gate:
                admitted = time.monotonic_ns()
                active += 1
                peak = max(peak, active)
                try:
                    row = await run(item)
                except asyncio.CancelledError as exc:
                    row = getattr(exc, "task_evidence", None)
                    raise
                except Exception as exc:
                    row = dict(
                        status="FAILED",
                        task_success=False,
                        error=type(exc).__name__ + ": " + str(exc),
                        completed_ns=time.monotonic_ns(),
                    )
                finally:
                    active -= 1
            released = time.monotonic_ns()
        except asyncio.CancelledError:
            row = (
                row
                if row is not None
                else dict(
                    tools=[],
                    generations=[],
                    prefetch=[],
                    full_task_ms=None,
                )
            )
            row.update(
                status="CANCELLED", task_success=False, completed_ns=time.monotonic_ns()
            )
            released = time.monotonic_ns() if admitted is not None else None
            raise
        finally:
            if row is not None:
                retain(item, row, reached, admitted, released)

    def snapshot():
        return dict(
            rows=[outcomes[t["trajectory_id"]] for t in trace],
            block_started_ns=start,
            block_finalized_ns=time.monotonic_ns(),
            max_active_observed=peak,
        )

    tasks = [asyncio.create_task(arrival(item)) for item in trace]
    try:
        await asyncio.gather(*tasks)
    except BaseException as exc:
        # Reap once: another cancel would interrupt the caller's owned cleanup.
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for item in trace:
            if item["trajectory_id"] not in outcomes:
                # A child cancelled before its first instruction has no finally.
                retain(
                    item,
                    dict(
                        status="CANCELLED",
                        task_success=False,
                        completed_ns=time.monotonic_ns(),
                        tools=[],
                        generations=[],
                        prefetch=[],
                        full_task_ms=None,
                    ),
                )
        exc.block_evidence = snapshot()
        raise
    return snapshot()


def summarize(block):
    rows = block["rows"]
    completed = [r for r in rows if r["status"] == "COMPLETED"]
    success = [r for r in rows if r["task_success"]]
    elapsed = (block["block_finalized_ns"] - block["block_started_ns"]) / 1e9
    return dict(
        tasks=len(rows),
        completed=len(completed),
        successful=len(success),
        failed=len(rows) - len(completed),
        incorrect_completed=len(completed) - len(success),
        cancelled=sum(r["status"] == "CANCELLED" for r in rows),
        latency_censored_callers=sum(r.get("latency_censored", False) for r in rows),
        task_success_rate=len(success) / len(rows) if rows else None,
        block_elapsed_seconds=elapsed,
        successful_tasks_per_second=len(success) / elapsed if elapsed > 0 else None,
        max_active_observed=block["max_active_observed"],
        all_caller_arrival_to_completed_ms=[r["arrival_to_completed_ms"] for r in rows],
        all_caller_full_task_ms=[
            None if r.get("latency_censored") else r.get("full_task_ms") for r in rows
        ],
        all_caller_arrival_to_finalized_ms=[
            r.get("arrival_to_finalized_ms") for r in rows
        ],
        block_elapsed_scope="ARRIVAL_EPOCH_THROUGH_ALL_CALLER_FINALIZATION_AND_RECORDING",
        dispatch_residency_counts=dict(
            Counter(
                s.get("cache_window_summary", {}).get("dispatch_state", "UNKNOWN")
                for r in rows
                for s in r.get("tools", [])
            )
        ),
        admission_decision_counts=dict(
            Counter(
                s.get("prefetch_decision", {}).get("reason", "NOT_SUBMITTED_OR_UNKNOWN")
                for r in rows
                for s in r.get("tools", [])
            )
        ),
        cache_window_summaries=[
            s.get("cache_window_summary") for r in rows for s in r.get("tools", [])
        ],
        background_observer_wait_ms=[
            sample.get("client_wait_ms")
            for r in rows
            for s in r.get("tools", [])
            for sample in s.get("cache_samples", [])
        ],
        scheduler_observer_cost_ns=[
            sample.get("state", {}).get("scheduler_observation_overhead_ns")
            for r in rows
            for s in r.get("tools", [])
            for sample in s.get("cache_samples", [])
        ],
        experimental_unit="WHOLE_SHARED_WORKER_BLOCK",
        p95_claim=False,
        physical_io="SEPARATE_SERVER_TRACE",
        cross_family_performance_validated=False,
    )


def compare_complete_blocks(baseline, treatment, *, comparison="proactive"):
    """Descriptive gate including queue/finalization, never a significance test."""
    if comparison not in ("proactive", "observation"):
        raise ValueError("Declare proactive comparison or observation calibration")
    endpoint = "all_caller_arrival_to_finalized_ms"
    for summary in (baseline, treatment):
        values = summary.get(endpoint, [])
        if (
            summary.get("procedure_completed") is not True
            or summary.get("study_success") is not True
            or summary.get("cleanup_unresolved") is not False
            or summary.get("successful") != summary.get("tasks")
            or summary.get("latency_censored_callers") != 0
            or not values
            or len(values) != summary.get("tasks")
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or v <= 0
                for v in values
            )
            or type(summary.get("successful_tasks_per_second")) not in (int, float)
            or not math.isfinite(summary["successful_tasks_per_second"])
            or summary["successful_tasks_per_second"] <= 0
        ):
            raise ValueError(
                "Comparison requires complete successful uncensored blocks"
            )
    latency = (
        statistics.median(treatment[endpoint]) / statistics.median(baseline[endpoint])
        - 1
    )
    loss = (
        1
        - treatment["successful_tasks_per_second"]
        / baseline["successful_tasks_per_second"]
    )
    if comparison == "observation":
        acceptable = (
            abs(latency) <= MAX_OBSERVER_RELATIVE_CHANGE_FRACTION
            and abs(loss) <= MAX_OBSERVER_RELATIVE_CHANGE_FRACTION
        )
    else:
        acceptable = (
            latency <= MAX_COMPARISON_DEGRADATION_FRACTION
            and loss <= MAX_COMPARISON_DEGRADATION_FRACTION
        )
    return dict(
        comparison=comparison,
        latency_endpoint=endpoint,
        median_task_degradation_fraction=latency,
        throughput_loss_fraction=loss,
        descriptive_only=True,
        acceptable=acceptable,
    )
