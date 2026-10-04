#!/usr/bin/env python3
"""Audit the recorded v0.2 dataset without a model, GPU, or network call."""

import csv
import json
import math
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parents[1]
folder = root / "results/tool-loop"
rows = json.loads((folder / "tool-loop-trials.json").read_text())
verdict = json.loads((folder / "VERDICT.json").read_text())
summary = json.loads((folder / "tool-loop-summary.json").read_text())
assert len(rows) == 12
assert {(r["scenario"], r["mode"], r["repetition"]) for r in rows} == {
    (scenario, mode, repetition)
    for scenario in ("l3_only", "resident")
    for mode in ("baseline", "proactive")
    for repetition in range(3)
}
assert len({tuple(r["output_ids"]) for r in rows}) == 1
assert len({r["source_manifest_sha256"] for r in rows}) == 1
assert len({json.dumps(r["tool_result"], sort_keys=True) for r in rows}) == 1
assert len({json.dumps(r["tool_call"], sort_keys=True) for r in rows}) == 1
for row in rows:
    assert row["output_correct"] and len(row["output_ids"]) == 13
    assert row["saved_prefix_tokens"] == 3520
    assert row["duplicate_backend_read_pages"] == row["relevant_host_evictions"] == 0
    assert not row["proactive_h2d"]
    before, after = row["cache_state_before_tool"], row["cleanup_after_flush"]
    assert before["storage_available_tokens"] == 3520
    assert (
        after["host_available_tokens"]
        == row["empty_cache_baseline"]["host_available_tokens"]
        == 139520
    )
    assert after["inflight_tokens"] == after["ongoing_prefetch_count"] == 0
    assert after["device_hit_tokens"] == after["host_hit_tokens"] == 0
    times = row["timestamps"]
    assert (
        times["t0_tool_dispatched"]
        < times["t3_tool_completed"]
        < times["t4_continuation_submitted"]
        < times["t5_first_token"]
    )
    details = row["cached_tokens_details"]
    if row["scenario"] == "l3_only":
        assert before["device_hit_tokens"] == before["host_hit_tokens"] == 0
        assert row["backend_read_pages"] == 220 and row["restored_bytes"] == 100925440
        assert row["restored_tokens"] == 3520
        if row["mode"] == "proactive":
            assert (
                times["t0_tool_dispatched"]
                <= times["t1_prefetch_submitted"]
                < row["scheduler_control_start_ns"]
                < times["t2_l2_published"]
                < times["t3_tool_completed"]
            )
            assert row["io_hidden_ms"] == row["io_duration_ms"] > 0
            assert details["host"] == 3520 and details["storage"] == 0
            assert (
                row["status"]["state"] == "SUCCESS"
                and not row["status"]["cleanup_pending"]
            )
        else:
            assert times["t2_l2_published"] > times["t4_continuation_submitted"]
            assert row["io_hidden_ms"] == 0 and details["storage"] == 3520
    else:
        assert before["device_hit_tokens"] == details["device"] == 3520
        assert row["backend_read_pages"] == row["restored_bytes"] == 0
for group in summary:
    subset = [
        r
        for r in rows
        if (r["scenario"], r["mode"]) == (group["scenario"], group["mode"])
    ]
    assert group["repetitions"] == len(subset) == 3
    for field, metric in [
        ("continuation_ttft_median_ms", "continuation_ttft_ms"),
        ("agent_step_median_ms", "agent_step_ms"),
    ]:
        assert math.isclose(
            group[field], statistics.median(r[metric] for r in subset), abs_tol=1e-8
        )
        assert math.isclose(
            group[field],
            verdict["groups"][group["scenario"] + "/" + group["mode"]][metric],
            abs_tol=1e-8,
        )
with (folder / "tool-loop-trials.csv").open() as file:
    csv_rows = list(csv.DictReader(file))
assert len(csv_rows) == len(rows)
for saved, row in zip(csv_rows, rows):
    assert saved["scenario"] == row["scenario"] and saved["mode"] == row["mode"]
    for field in (
        "continuation_ttft_ms",
        "agent_step_ms",
        "io_hidden_ms",
        "restored_bytes",
    ):
        assert math.isclose(float(saved[field]), row[field], abs_tol=1e-8)
suites = ET.parse(folder / "local-regressions.xml").getroot().iter("testsuite")
tests = 0
for suite in suites:
    tests += int(suite.attrib["tests"])
    assert all(
        int(suite.attrib.get(key, 0)) == 0 for key in ("failures", "errors", "skipped")
    )
assert tests == 52
print(
    "TOOL_LOOP_EVIDENCE: PASS (12 recorded GPU runs, 52 regressions; no GPU execution)"
)
