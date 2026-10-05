# ToolGap v0.3.0 — experimental admission and diagnostics

This release adds process-local admission across callers, explicit published-KV
usage accounting, a two-trajectory tool-loop harness, and a thin control CLI.
It retains the pinned SGLang runtime and existing L3 → resident L2 → normal H2D
path. There are no new runtime patches, storage backends or scheduler changes.

## What is included

- Share one `PrefetchAdmission` per worker in one orchestrator process/event loop.
  One active proactive restore; another caller falls back immediately with
  `LOCAL_BUSY`. No queue, retry, fairness guarantee or cross-process reservation.
- Each lease owns a unique operation ID. Unknown acceptance and pending cleanup
  retain the local slot until reconciliation; cancellation never frees a running
  backend read's destinations speculatively.
- Published, explicitly caller-reported used, unused and unknown-consumption
  bytes are distinct. Completed restoration remains shared, evictable L2;
  cancelling completed work does not evict it.
- `toolgap submit`, `status`, `cancel` preserve exact IDs/salt and send one RPC.
  JSON reports and exit codes distinguish rejection, uncertain transport and
  incomplete cleanup. Independent CLI processes do not share local admission.
- `toolgap doctor` checks selected local source/tokenizer hashes, optional local
  NVIDIA inventory and remote metadata. It never submits prefetch or generation.
  A PASS does not prove model weights, live cache residency or successful restore.

## Evidence and limits

The two-caller NVIDIA L4 smoke completed one repetition of baseline, shared
admission and owned abandonment: **80 regressions, six useful tools and five
correct continuations**, no duplicate saved-prefix reads, cleanup to baseline.

| Caller | Baseline TTFT | Admission TTFT | Baseline tool → first token | Admission tool → first token |
|---|---:|---:|---:|---:|
| Admitted agent-0 | 495 ms | 142 ms | 1120 ms | 776 ms |
| Fallback agent-1 | 632 ms | 608 ms | 1264 ms | 1290 ms |

**The pair's maximum observed tool-dispatch-to-first-token latency did not
improve: 1264 → 1290 ms (+2.0%).** These are single observations, not a supported
throughput, fairness, tail-latency or aggregate speedup claim. The interval starts
at tool dispatch and excludes the preceding model turn.

In the abandonment treatment, restoration had already completed. Its 3520 tokens
(96.25 MiB) remained unused evictable L2 until flush. This tests cancellation
after publication, not pending GPU I/O cancellation or cancelled backend traffic.
Pending-read cancellation is covered by CPU real-cache fixtures.

Scope: one worker, one active proactive restore, two tested salted trajectories,
Qwen2.5-1.5B-Instruct, full-attention resident cache, file L3, TP1/PP1/DP1.
The three-repetition default harness and larger loads have not been GPU-run.

The later local CLI suite passed **102 tests plus 22 subtests**, with no failures
or skips, and an installed-wheel localhost HTTP fixture. No new GPU execution
accompanies release packaging. The Docker recipe has not been rebuilt or tested
on GPU for this release.

Historical evidence remains separate: v0.1's 45 synthetic-gap trials, v0.2's
12 real tool-loop runs (three repetitions per condition), and fresh-main
29-test compatibility smoke. Their measured versions and data are unchanged.
The published technical report/DOI describes those earlier experiments; it has
not been revised to report v0.3.

## Install and use

```bash
git clone https://github.com/mks-hash/toolgap.git
cd toolgap
git checkout v0.3.0
python -m pip install -e .
toolgap --help
# Optional: prepare pinned runtime source for a compatible GPU environment.
bash scripts/install.sh
```

The release wheel installs the Python client/CLI only. Runtime setup still
requires the guarded patches and the documented compatible GPU environment.
No model weights or KV payloads are redistributed.

[CLI and input contract](https://github.com/mks-hash/toolgap/blob/v0.3.0/docs/guides/CLI.md) ·
[Admission policy](https://github.com/mks-hash/toolgap/blob/v0.3.0/docs/guides/MULTI_SESSION.md) ·
[Two-caller demo](https://github.com/mks-hash/toolgap/blob/v0.3.0/docs/guides/MULTI_SESSION_DEMO.md) ·
[GPU smoke and raw evidence](https://github.com/mks-hash/toolgap/blob/v0.3.0/docs/archive/evidence/MULTI_SESSION_GPU_SMOKE.md) ·
[Local CLI validation](https://github.com/mks-hash/toolgap/blob/v0.3.0/docs/archive/evidence/CLI_VALIDATION.md).

This remains experimental. No distributed recovery, SWA, remote backend,
proactive GPU load, permanently blocked-I/O reclamation, or production-readiness
claim. The separate upstream lifecycle and feature PRs are unchanged.
