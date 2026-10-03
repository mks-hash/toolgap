# Stage 2B — implemented and GPU validated

```
FEATURE_IMPLEMENTED: YES
FILES_CHANGED: 12 total; 5 runtime, 2 tests, 5 benchmark/docs/trace metadata
RUNTIME_LOC: 335 additions / 0 deletions relative to lifecycle base
API_SURFACE: POST /hicache/prefetch (submit, status, cancel)
SCHEDULER_REDESIGN_REQUIRED: NO
CACHE_OWNERSHIP_REDESIGN_REQUIRED: NO
CORRECTNESS: PASS
BENCHMARK: 45 trials, 3 repetitions per A/B/C × gap cell
TTFT_B_VS_C: measurable benefit with a tool gap; see table
TOOL_GAP_SCALING: partial benefit at 100ms; full pre-publication at 500/1000/3000ms
WASTED_PREFETCH: 4080 tokens / 116981760 bytes (111.56 MiB); ordinary flush reclaims it
UPSTREAMABLE: YES (bounded experimental MVP candidate for review)
FUNDAMENTAL_BLOCKER: NONE in the tested scope
FEATURE_PR_CREATED: NO
```

## Scope and code

Single worker/trajectory, resident FULL attention, TP1/PP1/DP1, file L3,
fixed text-generation model. L3→L2 only; generation uses the existing prefix
match, H2D and forward path. No new Req fields, GPU kernels, storage format,
TreeCore algorithm, retry protocol, worker recovery service, or distributed
exception recovery. Python TreeCore backend was used, as in Stage 2A.

Checkout: `[historical local workspace]/sglang-proactive`.
Branch: `experiment/proactive-kv-prefetch`.
Final commit: `4a7c68d30913cb084c821ad044ae4ef037933c29`.
Lifecycle base: `37d07d69b62181ca8713b31441218b0591da36de`.
The original bugfix checkout is clean at that base; PR #42149 is unchanged.
No feature branch push or feature PR was made.

Runtime files:

- `python/sglang/srt/mem_cache/proactive_prefetch.py`: bounded control manager;
  existing CacheRequestHandle/controller lifecycle owns slots and locks.
- `python/sglang/srt/managers/scheduler.py`: dispatch, idle/paused ACK drain,
  matching early-continuation join, cancellation during pause and idle guard.
- `python/sglang/srt/managers/io_struct.py`: control input/output structs.
- `python/sglang/srt/managers/tokenizer_control_mixin.py`: existing control transport;
  reject distributed fanout before sending.
- `python/sglang/srt/entrypoints/http_server.py`: one admin control route.

An exact page-aligned token prefix is required, with the same cache_salt as the
continuation. The backend prefetch threshold applies. One active restore and 32
recent outcomes are retained; duplicate IDs with the same normalized payload are
idempotent. TTL is 1–60000ms and cancels pending work, not a resident lease.
A completed prefix remains ordinary evictable cache. A matching early queued Req
compares its immutable origin prefix once; a replacement Req does not inherit
that join. Finite I/O failures reuse the separate lifecycle fix. Permanently
blocked I/O is outside the guarantee. Outcome counters describe completed work,
not a promise that cache residency will persist indefinitely.

## Benchmark result

Median client continuation TTFT, milliseconds. A is a fresh empty-L3 miss plus
recompute, B ordinary request-time restore, C pre-arrival control restore.
All model/server/generation flags are identical; fresh L1/L2 per trial.

| Gap ms | A TTFT | B TTFT | C TTFT | B − C | B full restore path | C hidden file I/O |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 572.0 | 501.5 | 490.0 | 11.5 | 338.7 | 0.0 |
| 100 | 568.7 | 513.6 | 438.4 | 75.2 | 346.7 | 0.0 |
| 500 | 576.8 | 528.5 | 165.7 | 362.8 | 364.1 | 200.6 |
| 1000 | 568.2 | 582.2 | 166.5 | 415.7 | 417.9 | 202.3 |
| 3000 | 571.3 | 508.4 | 162.9 | 345.5 | 344.3 | 200.1 |

The large-gap savings closely match the exposed **full** B restore path, which
includes query/hashing, allocation and ACK/publication, not only file read/copy.
At 100ms file-I/O overlap was zero, but the operation had already started and
query/allocation work overlapped the gap. At 500ms and above all 9 C trials
published L2 before continuation submission. No proactive H2D was observed.

Zero nominal gap includes about 7.9ms median control RPC overhead. The 11.5ms
median TTFT difference there is not evidence of meaningful zero-gap overlap;
one paired repetition was 78.7ms slower. Short-gap savings have visible variance
(100ms paired savings: 27.5/78.2/137.7ms). With n=3 per cell, this is a capability
and scaling demonstration, not a general latency guarantee or a statistical
significance claim. The C plateau is around 163–167ms; variation in B makes the
500/1000/3000 savings non-monotonic.

Model: Qwen/Qwen2.5-1.5B-Instruct, immutable revision
`989aa7980e4cf806f80c7fef2b1adb7bc71aa306`. Prompt 4096 tokens, restorable
prefix 4080, 32 deterministic output IDs. Temperature 0, seed 42, BF16,
Triton attention, PyTorch sampling, decode/prefill CUDA graphs disabled.
Client TTFT is the first SSE token event. No artificial I/O latency.
The local file backend may benefit from warm OS page cache after file copying;
this does not estimate remote-storage performance.

All 45 outputs matched the producer exactly. Every B consumed 4080 **storage**
tokens, every C consumed 4080 **host** tokens; initial device hits were zero.
Every B/C read 255 unique pages and 116981760 bytes. Duplicate backend read pages:
0. Relevant host evictions: 0. C terminal status: zero in-flight accounting and
no pending cleanup. Raw occupancy snapshots are retained in trials/trace.

## Wasted prefetch and lifecycle

The no-continuation run restored 4080 tokens (111.56MiB), occupying exactly 4080
host slots. Cancellation after SUCCESS correctly left ordinary resident KV;
there is no pin or post-publication lease. Normal cache flush returned host
availability to its full 139520-token baseline. This is wasted read traffic/L2
capacity when no continuation arrives, not leaked operation-owned memory.

Final CPU/controller tests: 25 passed. They were repeated inside the L4 CUDA
container: 25 passed, 0 failed, 0 skipped, including
10 inherited finite-I/O lifecycle cases. Requestless tests cover publication,
namespace matching, duplicate submission, cancellation during read, late ACK,
expiry, worker survival and bounded state. Earlier legacy CPU regression:
42 passed plus separate two-rank Gloo test passed with loopback access. Trace
instrumentation CPU fixture check: 21 passed. Applicable commit hooks passed;
Rust hooks had no matching files, so this is not Rust validation.

Stage 2A remains closed: 41 passed / 6 SWA-only skips. Its original 47/47 zero-skip
criterion erroneously included SWA outside the FULL-only scope.

## Execution provenance and corrections

The first prototype was deliberately stopped after 22 trials to fix repeated
prefix rescanning in join polling. Its results are excluded from the final
matrix. The final production code ran 22 valid trials, then the harness stopped
on an overstrict assertion that file I/O itself must begin before arrival even
at a 100ms gap. That failed trial was correct and consumed host KV. The assertion
was corrected to require the restore operation to start before arrival, recording
I/O overlap independently. CPU trace tests verified operation timestamps.

The remaining 23 trials were resumed. The saved 22 rows/trace events were kept;
failed/incomplete events were discarded before replay. The new producer checked
identical baseline output. All five production file hashes are identical across
both final sessions; only benchmark validation/trace/resume code changed.
`benchmark-seed-provenance.json` and `feature-provenance.json` preserve both
versions. Generation configuration did not change. The final matrix has exactly
45 distinct cells/repetitions; no prototype or failed trial is counted as a pass.

## GPU and cost

NVIDIA L4, driver 580.178.04, CUDA 13.0, PyTorch 2.13.0+cu130. Same validated
immutable image `sha256:4ae0bb2222247e51d146ff0cb9807240d5abbfe7d1b5d7eb1c9db0b072da07ec`,
source overlay only. No image rebuild or quota/IAM change.

Stage 2B powered VM time upper bound: 78.7 minutes, including prototype
and all retries. Wall time including stopped diagnosis intervals: 125.8
minutes. Conservative compute + 150GiB disk + IPv4 estimate: **$1.17**;
Stage 2A + Stage 2B estimate **$1.51**, below the $3 compute budget.
The final interval is conservatively charged until confirmed deletion, not an
invoice. Native DELETE deadline never moved; stopped debugging was unpaid GPU
time. VM and its boot disk were deleted at 01:26:38 MSK on 4 October 2026;
both resource lists are empty and the local deletion timer was cancelled.

## Artifacts

- `ANALYSIS.json`, `BENCHMARK.csv`, `COST.json`, `FEATURE.patch`.
- `results/validated/results/`: complete final raw evidence, tests, traces and logs.
- `results/prototype/`: excluded original prototype.
- `results/final/`: stopped overstrict-harness run, preserved for audit.
- Upstream benchmark: `sglang-proactive/benchmark/hicache/`.
- Successful GCS archive: `gs://[validation-project]-hicache-stage2a-results/ce-hicache-stage2b-l4-20261003T220303Z/host/results-1791066234351488430.tgz`.

No further GPU execution or feature PR is started. The implementation and
measured results are ready for user review.
