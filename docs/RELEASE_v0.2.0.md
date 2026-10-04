# ToolGap v0.2.0 — experimental real tool-loop integration

ToolGap restores an exact reusable KV prefix from file L3 into resident host L2
while an agent's tool performs work. The normal continuation then reuses it
through SGLang prefix matching, H2D and generation.

This release adds a thin asynchronous Python client, a real model → document
search → continuation demo, exact source/tokenizer guards, and matched L3-only
and resident-GPU controls. It adds no SGLang runtime patch beyond v0.1.

## Observed results

**73.8% lower median continuation TTFT when reusable KV is L3-only; no meaningful
change when KV is already GPU-resident.** **34.1% lower tool-dispatch-to-first-token
latency in the L3-only scenario**, excluding the initial tool-selection turn.

1× L4, Qwen2.5-1.5B-Instruct, file-backed L3, 3520-token reusable prefix,
single worker, full attention, TP1/PP1, three runs per condition.

| Initial state | Baseline median TTFT | ToolGap median TTFT | Baseline step | ToolGap step |
|---|---:|---:|---:|---:|
| L3-only | 512 ms | 134 ms | 1159 ms | 764 ms |
| Resident GPU | 128 ms | 127 ms | 748 ms | 759 ms |

The model selected the actual document-search tool; the subprocess scanned a fixed
10,000-record synthetic corpus. No tool `sleep` or fabricated model call. Initial
prefix and L3 payloads were verified identically in both treatments. All three
proactive L3 runs published 3520 tokens before continuation and consumed host KV.
All 12 outputs matched; duplicate reads=0; proactive H2D=0; cleanup baseline restored.
52 regressions and 12 real GPU runs passed with no failures/skips. The regressions
include CPU fixtures inside the GPU image, not 52 CUDA-specific tests.

## Reproduce

On an existing compatible GPU with the pinned SGLang/model dependencies prepared:

```bash
MODEL_PATH=/absolute/path/to/Qwen2.5-1.5B-Instruct \
SGLANG_CHECKOUT="$PWD/vendor/sglang" bash examples/tool_loop.sh
```

[Installation and demo](https://github.com/mks-hash/toolgap/blob/v0.2.0/docs/TOOL_LOOP.md),
[validation/provenance](https://github.com/mks-hash/toolgap/blob/v0.2.0/docs/TOOL_LOOP_VALIDATION.md),
[raw CSV](https://github.com/mks-hash/toolgap/blob/v0.2.0/results/tool-loop/tool-loop-trials.csv),
[chart](https://github.com/mks-hash/toolgap/blob/v0.2.0/results/tool-loop/ttft.png).

The release includes CSV/JSON/trace evidence and a Python client wheel. No model
weights or KV payloads are redistributed. The source demo was GPU-validated using
the recorded immutable CUDA image and source overlay; the public Docker recipe
was not newly built/GPU-executed for this release.

## Applicability and limits

ToolGap helps when a reusable prefix is in slower storage and tool work provides
time to restore it. Already GPU-resident KV needs no restore; very short tool
work can leave latency exposed. This remains experimental: n=3, controlled memory
eviction, a synthetic retrieval fixture, potentially warm OS page cache, and
variable I/O times. It is not a universal agent speedup or production-readiness claim.

Single trajectory/worker, full attention, file L3, TP1/PP1 only. No multi-session,
distributed recovery, SWA, new backend or proactive GPU load. Client cancellation
is bounded and can be uncertain after transport failure; permanently blocked I/O
remains unsupported. No new GPU run accompanied publication.

v0.1.0 and its 45-trial synthetic-gap benchmark remain intact. Upstream lifecycle
PR #42149 and feature PR #42434 remain separate; this release does not update them.
