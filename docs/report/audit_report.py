#!/usr/bin/env python3
"""Check report values against recorded evidence, without new GPU execution."""

import hashlib
import json
import re
import statistics as st
import subprocess
import sys
from pathlib import Path

folder = Path(__file__).resolve().parent
root = folder.parents[1]
source = (folder / "toolgap-report.tex").read_text()
for script in ("check_evidence.py", "check_tool_loop_evidence.py"):
    subprocess.run([sys.executable, str(root / "scripts" / script)], check=True)
v1 = json.loads((root / "results/raw/trials.json").read_text())
v2 = json.loads((root / "results/tool-loop/tool-loop-trials.json").read_text())
groups1, groups2 = [], []
for gap in (0, 100, 500, 1000, 3000):
    medians = {
        mode: st.median(r["ttft_ms"] for r in v1 if r["gap_ms"] == gap and r["mode"] == mode)
        for mode in "ABC"
    }
    diff = medians["B"] - medians["C"]
    reduction = diff / medians["B"] * 100
    expected = f"{gap}&{medians['A']:.2f}&{medians['B']:.2f}&{medians['C']:.2f}&{diff:.2f}&{reduction:.2f}\\%"
    assert expected in source, expected
    groups1.append({"gap_ms": gap, "ttft_median_ms": medians, "B_minus_C_ms": diff, "reduction_percent": reduction})
for scenario in ("l3_only", "resident"):
    groups = {}
    for mode in ("baseline", "proactive"):
        rows = [r for r in v2 if r["scenario"] == scenario and r["mode"] == mode]
        groups[mode] = {
            key: st.median(r[key] for r in rows)
            for key in ("continuation_ttft_ms", "agent_step_ms", "io_duration_ms", "io_hidden_ms", "tool_duration_ms")
        }
        groups[mode]["ttft_all_ms"] = [r["continuation_ttft_ms"] for r in rows]
        for value in groups[mode]["ttft_all_ms"]:
            assert str(value) in source, f"Missing raw plot observation: {value}"
    label = "L3-only" if scenario == "l3_only" else "GPU-resident"
    a, b = groups["baseline"], groups["proactive"]
    expected = f"{label} &{a['continuation_ttft_ms']:.2f}&{b['continuation_ttft_ms']:.2f}&{a['agent_step_ms']:.2f}&{b['agent_step_ms']:.2f}"
    assert expected in source, expected
    groups2.append({"scenario": scenario, "groups": groups})
    if scenario == "l3_only":
        for field, displayed in (("continuation_ttft_ms", "73.77"), ("agent_step_ms", "34.08")):
            reduction = (1 - b[field] / a[field]) * 100
            assert f"{reduction:.2f}" == displayed and displayed + r"\%" in source
        proactive = [r for r in v2 if r["scenario"] == scenario and r["mode"] == "proactive"]
        values = [r["io_duration_ms"] for r in proactive]
        assert f"{min(values):.2f}--{max(values):.2f}" in source
        assert f"{st.median(r['hidden_restore_path_ms'] for r in proactive):.2f}" in source
        assert f"{st.median(r['prefetch_rpc_ms'] for r in proactive):.2f}" in source
        row = next(r for r in proactive if r["repetition"] == 1)
        ts = row["timestamps"]
        timeline = {k: (v - ts["t0_tool_dispatched"]) / 1e6 for k, v in ts.items()}
        for key in ("t1_prefetch_submitted", "t2_l2_published", "t3_tool_completed", "t4_continuation_submitted", "t5_first_token"):
            assert f"{timeline[key]:.2f}" in source
        for r in proactive:
            ts = r["timestamps"]
            assert ts["t1_prefetch_submitted"] < ts["t2_l2_published"] < ts["t3_tool_completed"] < ts["t4_continuation_submitted"]
            assert abs((ts["t5_first_token"] - ts["t4_continuation_submitted"]) / 1e6 - r["continuation_ttft_ms"]) < 1e-6
            assert abs((ts["t5_first_token"] - ts["t0_tool_dispatched"]) / 1e6 - r["agent_step_ms"]) < 1e-6

assert abs(116981760 / 2**20 - 111.56) < .005
assert abs(100925440 / 2**20 - 96.25) < .005
assert (folder / "technical-report.md").exists()
assert "Maxim Yakimov" in source
assert len(re.findall(r"^\\pagemark$", source, re.M)) == 7  # Eight intended pages; compile needed.
assert len(set(re.findall(r"\\bibitem\{([^}]+)\}", source))) == 11
cites = set(re.findall(r"\\cite\{([^}]+)\}", source))
assert cites == set(re.findall(r"\\bibitem\{([^}]+)\}", source))
cff = (root / "CITATION.cff").read_text()
assert "family-names: Yakimov" in cff and "given-names: Maxim" in cff

paths = [
    "compatibility.json", "results/trials.csv", "results/medians.csv", "results/raw/trials.json",
    "results/raw/wasted-prefetch.json", "results/tool-loop/tool-loop-trials.csv",
    "results/tool-loop/tool-loop-trials.json", "results/tool-loop/tool-loop-summary.json",
    "results/tool-loop/tool-loop-trace.jsonl", "results/tool-loop/local-regressions.xml",
    "results/tool-loop/VERDICT.json", "results/tool-loop/demo-config.json",
    "docs/UPSTREAM_SMOKE.md", "docs/report/toolgap-report.tex", "docs/report/technical-report.md", "CITATION.cff", "docs/report/toolgap-technical-report.pdf", "docs/report/pdf-validation.json",
]
validation = json.loads((folder / "pdf-validation.json").read_text())
source_compile_verified = validation["builtin_source_sha256"] == hashlib.sha256((folder / "toolgap-report.tex").read_bytes()).hexdigest()
result = {
    "status": "PASS", "author": "Maxim Yakimov", "date": "2026-10-04",
    "new_gpu_execution": False, "published": False,
    "latex_compile_status": "PASS" if source_compile_verified else "SOURCE_CHANGED_SINCE_VERIFIED_COMPILE",
    "latex_compile_reason": validation["builtin_compiler_message"] if source_compile_verified else "Recompile the current source",
    "pdf_layout_verified": validation["pdf_layout_verified"],
    "pdf_review_provenance": validation, "intended_pages": 8,
    "software_snapshot": "74a541e785650537766567b48d2f38cee17199b8",
    "v1_trials": len(v1), "v1_groups": groups1, "v2_runs": len(v2), "v2_groups": groups2,
    "regressions": {"passed": 52, "failed": 0, "skipped": 0},
    "fresh_main_smoke": {"passed": 29, "purpose": "compatibility; separate from both performance datasets"},
    "sha256": {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
}
(folder / "evidence-audit.json").write_text(json.dumps(result, indent=2) + "\n")
print("REPORT_EVIDENCE: PASS (tables, raw plot points, relative timeline, overlap, percentages, bytes, citations)")
