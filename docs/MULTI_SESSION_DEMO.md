# Two-trajectory demo plan

This harness is included in experimental v0.3.0 and uses the v0.2 pinned SGLang
runtime. One separately authorized
[single-repeat GPU smoke](MULTI_SESSION_GPU_SMOKE.md) has passed; the default
three-repetition evaluation below has not been run. Another paid GPU run
requires separate authorization.

## Experiment

One full-attention, resident-cache worker, TP1/PP1, file-backed L3,
Qwen2.5-1.5B-Instruct on an existing compatible L4 host. Two independent salted
trajectories execute the same document-search task against the deterministic
10,000-document fixture. The retrieval is real subprocess work; the corpus is
synthetic. This checks ownership and contention, not diversity of agent tasks.

The server uses the recorded v0.2 configuration with just
`--max-running-requests 2` instead of `1`. Proactive runtime admission remains
**one restore**. Shared `PrefetchAdmission` applies process-local fallback.
There is no queue, retry, new runtime patch, or artificial tool delay.

For each pair, both first model turns are actually generated and must reproduce
the producer's saved token IDs. Before dispatching tools, ordinary flush evicts
GPU/L2 while preserving L3. Serialized scheduler probes must confirm, for BOTH
prefixes, GPU hit=0, host hit=0, and storage availability equal to the saved
prefix length. Distinct salts must yield disjoint prefix storage keys. Copied
L3 payload hashes must match the producer. This is controlled eviction, not a
claim that normal tool execution necessarily evicts KV.

Three treatments, three repetitions each by default:

1. `baseline`: two tool loops, ordinary request-time restore, no control submit.
2. `admission`: both tool loops attempt proactive prefetch through one shared
   coordinator. A busy/rejected caller proceeds through ordinary generation.
3. `abandon_first`: the first dispatched caller runs its tool but intentionally
   abandons continuation, cancels only its owned prefetch and reconciles cleanup.
   The other caller still generates normally.

The order of treatments is shuffled with seed42; caller launch order alternates
by repetition. Nine paired rounds / eighteen tool executions / fifteen
continuations result from the default plan. Abandonment is a lifecycle probe,
not a paired performance baseline. If publication already completed, cancelling
does not evict ordinary shared L2; unused published bytes are reported instead.
A cancelled in-flight read may publish zero tokens; that is distinct from
published waste and total backend traffic.

Tools start from one gate. Continuation follows each tool immediately and never
waits for prefetch acceptance. Submission contention and inference overlap are
observed, not forced by blocking a tool or delaying a request. Two callers need
not both obtain an overlapping generation interval, nor must one be locally
rejected if the first restore finishes before the second submission. Report the
actual admission outcomes and overlap rather than inventing contention.

## Command on an authorized, existing GPU host

Use the pinned patched checkout and locally available pinned model, installed
with the same compatible dependencies as v0.2. The wrapper runs offline
source/model-file compatibility guards before starting the server. It does not
provision resources, download weights, push images, or upload results.

```bash
MODEL_PATH=/absolute/path/to/Qwen2.5-1.5B-Instruct \
SGLANG_CHECKOUT=/absolute/path/to/pinned/patched/sglang \
TOOLGAP_RUN_DIR=/absolute/path/to/new/output-directory \
bash examples/multi_session.sh --repetitions 3
```

A bounded first GPU smoke can use `--repetitions 1` (three paired rounds).
Do not interpret that smoke as the three-repetition evaluation. Retain the
recorded exact server commands, local logs, and full result directory.

## Evidence collected

- `config.json`: compatibility, corpus identity, treatment plan, and harness
  hashes. `source.json`: exact prompt/decision/prefix IDs, salts, L3 hashes.
- `server-command-*.json`, `server-*.log`: actual server configuration and logs.
- `tool-loop-trace.jsonl`: existing read/restore/publication/occupancy events;
  control submit additionally links the public operation ID to the internal rid.
- `trials.json` / `trials.csv`: per-caller timestamps, TTFT, tool duration,
  tool-dispatch-to-first-token, control state, correctness, cache hit details,
  prefix read counts, duplicate prefix reads, restore I/O, publication overlap.
- `rounds.json`: shared admission counters, observed tool/generation interval
  overlap, sampled host high-water mark, worker host evictions and final cleanup.
- `summary.json`: per-mode/per-agent medians and actual sample counts. Preserve
  admission outcomes alongside medians; successful and fallback callers differ.
- `failure.json` on error; completed trial rows are persisted incrementally.

Both modes use the same generation settings. Continuation must preserve the
actual saved token sequence and return the correct document ID. Output token
IDs must agree for each caller across treatments. Cached host/storage token
counts must cover the saved span; baseline specifically must consume storage.
After each pair, flush must restore host availability to the empty-worker
baseline, with zero in-flight tokens, zero ongoing prefetch and no active local
admission slot. Tool/submission exceptions reconcile owned prefetch, reap tool
and sibling tasks, and stop the server; failed cleanup is not reported as PASS.

Read attribution uses the verified per-salt prefix storage keys; proactive
publication uses the explicit internal-rid mapping. Unmapped events and
zero-token terminal drains do not count as successful L2 publication. Restore
I/O also includes the caller-selected continuation rid. Prefix read counters do
not count later suffix pages. Occupancy and eviction are **worker-level**, and
the sampled high-water mark is not the allocator's exhaustive maximum. H2D
remains the ordinary continuation path; this harness does not claim a
per-caller H2D latency measurement.

`hidden_restore_path_ms = max(0, min(publication, continuation_arrival) - submit)`
is elapsed control-to-publication overlap, not exact I/O time hidden or a causal
estimate of the TTFT reduction. Raw I/O intervals are retained separately.
Tool-dispatch-to-first-token excludes the initial model turn. Client and local
server use the same host monotonic clock.

Consumption from a newly published span remains **unknown** for ordinary
continuations: generic host hits alone do not prove lease-specific usage. Only
intentional abandonment reports zero consumption. Published/unused bytes and
unknown-usage counters must stay distinct; none measures partial cancelled I/O.

## Local checks (October 4, 2026)

Nine added CPU tests cover nonblocking continuation, local-busy fallback,
owned abandonment, failed tool cleanup, cancellation during pending submit,
sibling reaping, per-agent trace isolation, unmapped publication and zero-token
terminal outcomes. Combined with existing admission/cache/API tests:
**79 passed / 1 skipped / 0 failed** (80 collected, 11.71 s). The skip remains
the optional offline pinned-tokenizer fixture; no GPU/model inference occurred.
XML: local ignored `work/v03/multi-session-cpu-results.xml`.

```bash
bash scripts/test_client.sh
```

Ruff, shell syntax and command-line import/help checks passed. The subsequent
[GPU smoke](MULTI_SESSION_GPU_SMOKE.md) verifies live admission, model execution,
ordinary H2D and correctness for two callers in one repetition. Published
v0.1/v0.2 numbers, report, runtime patches and upstream PRs are unchanged.
