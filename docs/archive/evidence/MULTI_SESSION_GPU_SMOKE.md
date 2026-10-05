# v0.3 two-caller real-GPU smoke

October 4, 2026. **Correctness smoke passed; not a statistical performance benchmark.**
These recorded data are included in experimental v0.3.0.
One authorized VM execution, one repetition of three paired treatments. Runtime
and image were not modified. No second execution or tuning followed these data.

## Configuration and provenance

- NVIDIA L4 24GB, GCP `g2-standard-8`, 8vCPU / 32GiB, `us-central1-a`.
- NVIDIA 580.178.04; PyTorch 2.13.0+cu130; CUDA 13.0; Ubuntu 24.04.
- ToolGap harness `0be389b39345a84281289ac8ca02a517551aec84`.
- SGLang `3e60ad803c6b01832b527f4a1dcbeb7a5449964b`.
- Image `sha256:4ae0bb2222247e51d146ff0cb9807240d5abbfe7d1b5d7eb1c9db0b072da07ec`.
- Qwen2.5-1.5B-Instruct, same pinned tokenizer/model compatibility checks as v0.2.
- Resident FULL cache, file L3, TP1/PP1, one worker; two ordinary requests may
  run concurrently, while proactive admission retains **one restore slot**.
- Two distinct salts, same document-search task over 10,000 synthetic documents;
  real model → useful retrieval subprocess → ordinary continuation.
- 3520-token reusable prefix per caller. Before tools in every treatment:
  device hit=0, host hit=0, storage availability=3520, disjoint prefix keys.

Source/model hashes, copied L3 payload hashes and exact saved first-turn IDs
passed guards. Exact server arguments match across treatments. Their one change
from the v0.2 server is `--max-running-requests 2` instead of `1`.

## Observed result

**80 regression tests passed, zero failed/errors/skipped.** These include CPU
orchestration/transport checks and real cache fixtures; they are not 80 separate
model inference trials. The offline pinned-tokenizer test passed in the image.

Three paired rounds completed: shared admission, ordinary baseline, then owned
abandonment. **Six useful tools, five correct continuations**, identical output
IDs for each caller across conditions. No failures, no duplicate saved-prefix
backend reads. Each prefix was read exactly 220 pages in each treatment.

Single observations, rounded to milliseconds:

| Caller | Baseline TTFT | Shared-admission TTFT | Baseline tool-dispatch → first token | Shared-admission tool-dispatch → first token | Outcome |
|---|---:|---:|---:|---:|---|
| agent-0 | 495.287ms | 141.595ms | 1119.564ms | 775.732ms | admitted; SUCCESS |
| agent-1 | 631.873ms | 607.748ms | 1264.005ms | 1289.746ms | LOCAL_BUSY; normal restore |

Agent0's observed TTFT reduction was 71.4%, and its dispatch-to-first-token
reduction 30.7%. Its 3520 tokens were published before continuation, then consumed
through host matching: cached details device0 / host3520 / storage0. Publication
preceded tool completion as well. Elapsed control-to-publication overlap was
359.004ms; traced I/O itself 337.605ms. These are distinct measurements.
Baseline continuations and fallback consumed 3520 storage tokens each.

**This does not establish a pair-level latency win.** The maximum observed
per-caller dispatch-to-first-token increased from 1264.005ms to 1289.746ms (+2.0%).
One caller benefits; a second still pays ordinary restore and shared execution
costs. Even its tool duration changed between treatments. With one repetition,
no statistical, throughput, fairness or tail-latency claim is supported.

Measured tool intervals overlap 623–636ms. Client-observed generation intervals
also overlap 1134ms in admission and 1269ms in baseline; that is overlap of request
lifetimes, not proof of simultaneous GPU execution throughout those intervals.
The abandonment treatment has only one continuation.

## Waste and cleanup

In `abandon_first`, agent0's restore had already published before cancellation
was requested, so terminal state correctly remained SUCCESS. No continuation
consumed that span. **3520 tokens  / 100,925,440 bytes (96.25MiB)** were reported as
unused published KV; they remained ordinary evictable L2 until final flush.
This is neither a cancelled-I/O byte count nor evidence of in-flight cancellation
on GPU. Pending-read cancellation and late completion remain covered by the
CPU/real-cache regression fixtures.

The other caller received LOCAL_BUSY, then generated correctly through ordinary
storage restore. This demonstrates rejection fallback and continued inference
usability, not a second concurrent proactive restore.

All three rounds returned host availability to the empty-worker baseline
**139,520 tokens**, with zero in-flight tokens, ongoing prefetch and active local
slot. Debug allocator checks produced no double-free error. Runtime lock/ref
invariants are covered by regressions; this GPU probe does not separately
export every anchor lock counter. No relevant host eviction was observed during
the measured intervals. Sampled host occupancy peaked at 7200 tokens in baseline
and admission, 7040 in abandonment; this is not an exhaustive allocator maximum.

Five H2D submission events occurred across the five continuations. **Zero H2D
submissions preceded the first continuation arrival in any measured round.**
Proactive work remained L3→L2; GPU movement followed ordinary generation.
Normal continuation consumption remains unknown in lease-specific accounting:
host hits alone are not treated as complete proof of newly published-span use.

## Runtime, cost and cleanup of infrastructure

VM creation 16:54:22.634UTC, deletion 17:11:53UTC: **17m30s** creation-to-deletion.
Guest suite exit0, results uploaded and downloaded. Explicit deletion verified
both named VM and boot-disk lists empty; backup deletion timer removed. No VM
or disk remains from this execution.

Conservative estimate **$0.26**, applying the previous all-in planning rate
$0.879172212/hour to the entire creation-to-deletion interval. This is not a
billing invoice or refreshed price quote; existing registry, result storage,
API/network charges and tax are outside that estimate. Driver/bootstrap and
image extraction dominate total session time. No image rebuild was needed.

## Raw evidence and reproduction

[Raw trials CSV](../../../results/multi-session-smoke/trials.csv),
[full trials](../../../results/multi-session-smoke/trials.json),
[round accounting](../../../results/multi-session-smoke/rounds.json),
[trace](../../../results/multi-session-smoke/tool-loop-trace.jsonl),
[regression XML](../../../results/multi-session-smoke/local-regressions.xml),
[verdict](../../../results/multi-session-smoke/verdict.json),
[source identity](../../../results/multi-session-smoke/source.json),
[configuration](../../../results/multi-session-smoke/config.json),
[provenance](../../../results/multi-session-smoke/provenance.json).
Exact producer/treatment server commands and NVIDIA inventory are alongside.
Full host/server logs remain in the local `stage2b/v03_gpu/results` archive.

Use the [prepared demo command](../../guides/MULTI_SESSION_DEMO.md) on a separately authorized
compatible host with `--repetitions 1` to reproduce this smoke plan. Do not silently
reinterpret it as the default three-repetition evaluation.

The next code question is admission under contention and publication waste:
when should scarce restore work be admitted, deferred or declined? This smoke
supports the current two-caller foundation. It does not validate 5–20 callers,
multiple active proactive restores, distribution, new backends, or a runtime
scheduler redesign. Published v0.1/v0.2 datasets/report are unchanged.
