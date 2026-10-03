#!/usr/bin/env python3
"""Offline audit of published GPU evidence; this does not run CUDA."""
import csv, json, statistics
from pathlib import Path
root = Path(__file__).resolve().parents[1]
rows = json.loads((root / "results/raw/trials.json").read_text())
assert len(rows) == 45
assert len({(r["mode"],r["gap_ms"],r["repetition"]) for r in rows}) == 45
for r in rows:
    assert r["output_correct"] and r["duplicate_backend_read_pages"] == 0
    if r["mode"] in "BC":
        assert r["backend_read_pages"] == 255
        assert r["restored_bytes"] == 116981760
        details = r["cached_tokens_details"]
        assert details["device"] == 0
        assert details["storage" if r["mode"] == "B" else "host"] == 4080
    if r["mode"] == "C":
        assert r["status"]["inflight_tokens"] == 0
        assert not r["status"]["cleanup_pending"]
        if r["gap_ms"] >= 500: assert r["published_before_arrival"]
for row in csv.DictReader((root / "results/medians.csv").open()):
    for mode in "ABC":
        median = statistics.median(r["ttft_ms"] for r in rows if r["mode"] == mode and r["gap_ms"] == int(row["gap_ms"]))
        assert abs(median - float(row[f"{mode}_ttft_ms"])) < 1e-6
waste = json.loads((root / "results/raw/wasted-prefetch.json").read_text())
assert waste["restored_tokens"] == 4080 and waste["host_available_after_flush"] == 139520
print("EVIDENCE_REPLAY: PASS (45 recorded real-GPU trials; no GPU execution)")
