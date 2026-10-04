# ToolGap technical report

**Maxim Yakimov · October 4, 2026 · Revision 2 · 8 pages**

[Zenodo / DOI](https://doi.org/10.5281/zenodo.23130933) ·
[Read the PDF](toolgap-technical-report.pdf) ·
[Readable Markdown](technical-report.md) ·
[LaTeX source](toolgap-report.tex) ·
[Evidence audit](evidence-audit.json)

**ToolGap: Hiding KV-Cache Restore Latency During LLM Agent Tool Execution**

This report describes experimental exact-prefix restoration from file-backed L3
into SGLang's resident host L2 during tool execution, followed by ordinary
prefix matching, H2D, and continuation generation. It presents three distinct
bodies of evidence:

- **v0.1:** 45 synthetic-gap trials; 67–71% lower median continuation TTFT at
  500–3000 ms gaps, with three repetitions per condition.
- **v0.2:** 12 real model–document-search–continuation runs; L3-only median TTFT
  511.96 → 134.30 ms, and tool-dispatch-to-first-token latency
  1158.86 → 763.89 ms. This interval excludes the earlier tool-selection turn.
  The GPU-resident control shows no meaningful TTFT benefit.
- **Fresh-main smoke:** 29 tests and a separate one-run-per-mode compatibility
  check; these observations are not a replacement performance benchmark.

Scope: one NVIDIA L4, Qwen2.5-1.5B-Instruct, one worker/trajectory, full attention,
TP1/PP1, file-backed L3. The report discloses n=3, controlled cache-state creation,
OS page-cache effects, the synthetic retrieval corpus, variable I/O durations,
and the absence of load or head-to-head prior-system evaluation. It claims
neither first invention of KV prefetch nor production readiness.

## Reproduce the evidence audit

From the repository root, without a GPU or model download:

```bash
python docs/report/render_readable.py
python docs/report/audit_report.py
```

The audit checks recorded datasets, table rounding, reductions, all 12 real-tool
plot points, a selected run's relative timestamps, overlap, byte conversions,
and citation consistency. It does not execute new experiments. Runtime/model
identities and GPU reproduction commands are in the report and
[REPRODUCE.md](../REPRODUCE.md).

## Build and provenance

All plots and references are embedded in `toolgap-report.tex`; no external TeX
project files are required. Compile with pdfLaTeX twice, or Tectonic:

```bash
pdflatex -interaction=nonstopmode -halt-on-error toolgap-report.tex
pdflatex -interaction=nonstopmode -halt-on-error toolgap-report.tex
```

The supplied PDF was exported by the author through Overleaf and all eight pages
were visually reviewed. The editable source subsequently compiled successfully
with the desktop editor's bundled Tectonic runtime. Two source-only line-wrap
adjustments followed the Overleaf export; measurements and conclusions are
identical. [Verification provenance](pdf-validation.json) records the distinct
PDF and source hashes. No benchmark or runtime changed for this report release.

The measured software remains pinned to ToolGap `v0.2.0`; the separate report tag
is `report-v1.0.0`. The initial public report retains manuscript label revision 2,
reflecting its local editorial history. Report and source use the repository's
[Apache-2.0 license](../../LICENSE).

## Cite

Yakimov, Maxim. *ToolGap: Hiding KV-Cache Restore Latency During LLM Agent Tool
Execution*. Technical report, revision 2, October 4, 2026.
[Report release](https://github.com/mks-hash/toolgap/releases/tag/report-v1.0.0).
Software citation metadata and the preferred report citation are in
[CITATION.cff](../../CITATION.cff). The report is published in Zenodo as **Report**
with DOI **[10.5281/zenodo.23130933](https://doi.org/10.5281/zenodo.23130933)**, including the PDF and editable source.
This is the report DOI; it is not a DOI for the software archive.
