"""Pinned code-audit tasks and fixed open-loop arrivals; no padded contexts."""

import asyncio
import copy
import hashlib
import time
from collections import Counter

from .runner import initial_messages
from .workloads import SCHEMA


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

    async def arrival(item):
        nonlocal active, peak
        scheduled = start + item["offset_ms"] * 1_000_000
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
            except asyncio.CancelledError:
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
        row.update(
            trajectory_id=item["trajectory_id"],
            scheduled_arrival_ns=scheduled,
            arrival_reached_ns=reached,
            client_admitted_ns=admitted,
            client_queue_ms=(admitted - reached) / 1e6,
            arrival_lag_ms=(reached - scheduled) / 1e6,
            arrival_to_completed_ms=(row["completed_ns"] - scheduled) / 1e6,
        )
        if on_result:
            on_result(row)
        return row

    tasks = [asyncio.create_task(arrival(item)) for item in trace]
    try:
        rows = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return dict(
        rows=rows,
        block_started_ns=start,
        block_finalized_ns=time.monotonic_ns(),
        max_active_observed=peak,
    )


def summarize(block):
    rows = block["rows"]
    completed = [r for r in rows if r["status"] == "COMPLETED"]
    success = [r for r in rows if r["task_success"]]
    elapsed = (
        max((r["completed_ns"] for r in rows), default=block["block_started_ns"])
        - block["block_started_ns"]
    ) / 1e9
    return dict(
        tasks=len(rows),
        completed=len(completed),
        successful=len(success),
        failed=len(rows) - len(completed),
        incorrect_completed=len(completed) - len(success),
        task_success_rate=len(success) / len(rows) if rows else None,
        block_elapsed_seconds=elapsed,
        successful_tasks_per_second=len(success) / elapsed if elapsed > 0 else None,
        max_active_observed=block["max_active_observed"],
        all_caller_arrival_to_completed_ms=[r["arrival_to_completed_ms"] for r in rows],
        all_caller_full_task_ms=[r.get("full_task_ms") for r in rows],
        dispatch_residency_counts=dict(
            Counter(
                s.get("cache_before_dispatch", {}).get("residency", "UNMEASURED")
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
        observation_wait_ms=[
            s.get("observation_wait_ms") for r in rows for s in r.get("tools", [])
        ],
        experimental_unit="WHOLE_SHARED_WORKER_BLOCK",
        p95_claim=False,
        physical_io="SEPARATE_SERVER_TRACE",
        cross_family_performance_validated=False,
    )
