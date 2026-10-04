# ToolGap v0.2 real-tool-loop GPU validation

![Measured TTFT: L3-only and resident control](../results/tool-loop/ttft.png)

One approved session, no rerun. GPU resources deleted and instance/disk lists empty.

52 regression tests passed, zero failures/skips, inside the GPU image. These
include CPU file/cache/client fixtures; they are not 52 CUDA-specific tests.
12 real model/tool/continuation GPU runs passed (3 repetitions ×4 conditions).

| Verified initial state | Request-time baseline TTFT | ToolGap TTFT | Baseline step | ToolGap step |
|---|---:|---:|---:|---:|
| L3-only | 511.96ms | 134.30ms | 1158.86ms | 763.89ms |
| Resident GPU | 128.16ms | 126.98ms | 748.39ms | 759.11ms |

All values medians, n=3 per condition. Step means tool dispatch → first continuation
token; it excludes the initial model's tool-selection generation. L3-only TTFT
fell 73.77%; measured step fell 34.08%. Resident TTFT difference 1.18ms is not evidence
of a useful speedup; resident full-step median was 10.71ms slower with ToolGap.

## Actual useful work and cache controls

Pinned Qwen2.5-1.5B-Instruct produced the actual tool call:
`search_documents(query="KV prefetch tool latency")`. No fabricated tool call.
A subprocess performed deterministic retrieval over 10000 synthetic fixture
records and returned DOC-00173; continuation returned the correct JSON document
ID. All 12 continuations produced identical 13 output IDs. No artificial sleep.

Prompt 3511 tokens, generated tool call 23 tokens, page-aligned exact saved prefix
3520 tokens. One model-created L3 source snapshot was copied for every run;
payload SHA256, prefix IDs, salt, model namespace, actual tool-call IDs and tool
results were checked for equality across all conditions. Each condition used a
fresh server and identical generation flags. Seeded run order was fixed before
measurement. L3-only uses an explicit normal memory-cache flush, preserving L3;
this does not claim tool calls themselves cause eviction. Before tool dispatch,
all L3-only probes found device0/host0/storage3520. All resident probes found
3520 device tokens and zero host tokens, with the same L3 pages available.

## Measured overlap and cleanup

Each L3-only baseline consumed 3520 storage tokens. Each proactive consumed 3520
host tokens and zero storage tokens on continuation. Both treatments read exactly
220 pages /100925440 bytes (96.25MiB). All 3 proactive L3 restores published before
both tool completion and continuation arrival; baseline publications occurred
after continuation submission. Tool duration 630.39ms median for L3 proactive.
All actual proactive I/O was hidden: 291.35–390.55ms, median 296.80ms. Client-send →
publication median 317.16ms includes controller/query/queue overhead. Submit RPC
median 9.40ms occurs concurrently with tool work, not as an added serial wait.

No proactive H2D, duplicate measured page reads or relevant host evictions.
Resident conditions issued zero measured L3 reads. After normal post-measurement
flush, every run returned to 139520 available host slots, inflight 0,
ongoing_prefetch 0, and no matching device/host prefix. Local ownership/reference
conservation and cancellation/TTL/failure regressions also passed in the image.
The actual GPU workload is the successful tool workflow; fault injection remains
in regression fixtures, not additional GPU tool trials.

## Provenance and limits

ToolGap implementation 0acfc10c6f0ec807e6588384da7fb59d8f383720.
SGLang 3e60ad803c6b01832b527f4a1dcbeb7a5449964b (pinned release runtime,
not the later upstream-main PR). No SGLang runtime change for v0.2.
Model revision 989aa7980e4cf806f80c7fef2b1adb7bc71aa306; same immutable image
sha256:4ae0bb2222247e51d146ff0cb9807240d5abbfe7d1b5d7eb1c9db0b072da07ec.
L4, driver 580.178.04, CUDA 13.0, PyTorch 2.13.0+cu130, Ubuntu 24.04, TP1/PP1,
full attention, resident cache, file L3, Python TreeCore, 4GiB host pool.

This is a small controlled experimental demo: n=3, synthetic document archive,
controlled memory eviction, single trajectory/worker, local file storage.
Payload copying/verification and initial generation can warm OS page cache.
Backend I/O duration varies (baseline median 355.97ms, proactive 296.80ms);
we do not identify the exact causal size of overlap from 12 observations or claim
statistical significance/general agent-wide performance. Identical initial cache
state and pre-arrival publication establish the intended mechanism. v0.1's
separate 45-trial benchmark and fresh-main 29-test smoke remain unchanged.

## Resource/accounting evidence

VM hicache-toolgap-v02-l4, us-central1-a, g2-standard-8, L4,
8 vCPU/32GiB, 150GiB pd-balanced auto-delete.
Created 2026-10-04T00:23:19.711Z; deletion confirmed 00:48:20Z.
Conservative full wall interval 25m00s, including setup/collection/delete.
At previously recorded 0.879172212 USD/hour: estimated $0.3664 (~$0.37), not invoice;
small storage/API/tax charges and pre-existing registry storage separate.
Absolute native DELETE 55m/local backup 60m were not extended; explicit deletion
occurred early. No quota/IAM/image change, automatic retry or additional run.

Public evidence: [verdict](../results/tool-loop/VERDICT.json),
[raw CSV](../results/tool-loop/tool-loop-trials.csv),
[complete trials/timestamps](../results/tool-loop/tool-loop-trials.json),
[trace](../results/tool-loop/tool-loop-trace.jsonl),
[regression XML](../results/tool-loop/local-regressions.xml).

Reproduce on an existing GPU with [TOOL_LOOP.md](TOOL_LOOP.md).
Generate the figure using matplotlib 3.10.8:
`python examples/tool_loop/plot_results.py results/tool-loop`.
