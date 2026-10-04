# Passive observation and competing repository agents

Status (2026-10-05): **local CPU preparation implemented and checked**. No new GPU
run, model-weight download, runtime patch, cloud resource or publication. This is
an experimental research harness, not a new performance result or production
agent workload. Existing v0.1/v0.2/v0.3 datasets and compatibility pins are unchanged.

## What question the next experiment answers

Does proactive restoration help **all callers** on a finite-cache worker when
other useful agent trajectories naturally compete for residency? The initial
comparison is ordinary request-time restore versus the existing proactive policy
with bounded reconciliation. No residency/overlap hints derived from future
measurements are fed into admission. A pressure block, rather than its twelve
interacting trajectories, is the experimental unit.

The workload contains three code-audit questions over ToolGap's immutable public
source snapshot `fe6217292ce4f01c592a2d7274137d826a75e1a0`: ownership after local
rejection, avoiding remote submit for a resident prefix, and admission without
an overlap estimate. Each answer requires retrieved implementation **and** test
file/line evidence plus a successful real `admission_hints` CPU regression.
The grader is a constrained source-evidence check, not an open-ended code-audit
quality assessment. Model-selected tool errors and wrong answers remain failures.

Each initial packet contains about 4k native tokens of unique, numbered source
excerpts. Different agents rotate the additional excerpts; there is no repeated
filler, context truncation or synthetic tool sleep. The packet saves exact initial
IDs, model/tokenizer identity and source hashes. Generated decisions remain their
actual IDs when appending results. Admission always uses the exact aligned saved
prefix and salt, never re-tokenized text.

The default trace has twelve agents, eight possible active clients, arrivals at
0/100/.../700 ms and 1200/1300/1400/1500 ms, and up to four generation requests on
one worker. The semaphore's queue time and event-loop arrival lag are retained.
Useful search/read and CPU regression work determine tool duration. A bounded
post-generation ownership settlement is outside `full_task_ms`; it has a separate
finalization timestamp and holds the client slot until returning. Report that
cost alongside task latency rather than treating it as free throughput.

## Observation contract

`research/agent_resume/observer.py` reads the Python FULL tree's children and
component values directly. Partial-node observation compares keys without
splitting a node. It never calls `match_prefix`, touches recency, acquires refs,
allocates slots, restores payload or queries backend metadata caches. Scope is
Python TreeCore, resident cache, FULL attention, TP1/PP1, existing file backend,
no EAGLE/session radix/specialized key. Unsupported layouts fail explicitly.

The default sample is **memory only**. Missing GPU/L2 residency then means
`UNKNOWN_STORAGE`, not `COLD` or proven `L3_ONLY`. Optional `memory-and-stat` checks
consecutive prefix page files with direct `stat`, bypassing backend `exists()` and
its metadata cache. This establishes file presence/size, **not valid KV payloads**.
Filesystem errors remain unknown. It can warm OS metadata and costs scheduler
time; cache and filesystem timestamps are separate and not an atomic snapshot.

The research plugin runs mailbox samples on the scheduler thread before tool
dispatch. Before an ordinary request's real cache match it reads residency again,
without an awaited client roundtrip before continuation. This avoids creating an
artificial extra restoration window at submission. Sample overhead is recorded;
passive cache semantics do not imply zero timing perturbation. Observer-off
calibration is required before publishing a workload speedup.

The private file mailbox is for a trusted **same-host Linux boot**, not a remote
HTTP control API. A boot ID labels client, samples and server trace timestamps.
Unique nonce files isolate concurrent observations. Timeout/cancel removes owned
mailbox files; a request already being serviced can leave an orphan late response.
Remove orphan response files only after the block and all clients have stopped.
This is measurement cleanup, not cache-slot reclamation.

The plugin reuses the existing trace hooks and adds explicit operation-ID → cache
handle/RID mapping and thread-local RID tagging of physical file reads. Read
exceptions get separate events. It records ordinary cache matching, publication,
host eviction, sampled occupancy, H2D and generation receipt. Byte counts refer to
returned payload, not disk-controller traffic. Repeated successful page reads may
be legitimate re-reads after eviction, not duplicate-I/O bugs. Publication and a
later prefix match do not prove operation-specific consumption; consumed/wasted
bytes remain **unknown** until attributed. Empty/mismatched traces cannot prove
zero I/O.

## Local reproduction

Run from the repository in its Python environment. No model weights are needed
for these CPU-only steps. Tokenizers must match the pinned files in
`research/agent_resume/profiles/`.

```bash
python -m pip install -e .
python -m research.agent_resume.pressure prepare \
  --profile research/agent_resume/profiles/qwen.json \
  --tokenizer "$TOKENIZER_DIR" --output work/pressure/qwen-packet.json
python -m research.agent_resume.check_pressure \
  --packet work/pressure/qwen-packet.json --tokenizer "$TOKENIZER_DIR" \
  --output work/pressure/qwen-scripted.json
bash scripts/test_client.sh
```

Repeat preparation/check with `qwen7.json` and `mistral.json`, their pinned native
tokenizers and new output paths. The check uses deliberately scripted model
choices with actual native templates and real CPU tools. Its latencies are never
GPU/model/performance evidence. Llama remains gated on access to official files.

[Compact local verification record](../research/agent_resume/passive-pressure-validation.json).
The real observer tests additionally use the existing SGLang CPU FULL/file fixtures;
see `tests/test_passive_observer_real_cache.py` and the pinned runtime regression
instructions in [cross-family preparation](CROSS_FAMILY_PREPARATION.md).

## Candidate GPU setup and exact block commands

**No execution is authorized by this document.** Use an independently validated,
separately approved server and run the client on the same host. The packet contains
all resolved settings checked by the runner. Relative to the diagnostic profile,
only `max_running_requests=4` and `hicache_size=1` GiB are changed. GPU KV budget is
8192 tokens, context limit 8192, TP1/PP1/DP1, BF16/FULL, page size 16, resident
write-through/file cache and deterministic sampling. Runtime candidate is
`3e60ad803c6b01832b527f4a1dcbeb7a5449964b`. GPU fit, model-selected tool quality and
natural L3 opportunities are **not validated**, particularly for 7B models. Do not
silently alter the budget/model when a fit fails.

At approved server startup, load **only this research plugin** (avoid the historical
matching-based demo probe), with:

```bash
mkdir -p work/pressure/mailbox
chmod 700 work/pressure/mailbox
export PYTHONPATH="$PWD:$PWD/src:$PWD/benchmark/trace:$PWD/research/agent_resume/plugin:$SGLANG_ROOT/python:${PYTHONPATH:-}"
export SGLANG_UNIFIED_RADIX_TREE_CORE_BACKEND=python
export TOOLGAP_PRESSURE_PROBE_DIR="$PWD/work/pressure/mailbox"
export TOOLGAP_PRESSURE_MATCH_OBSERVATION=1
export HICACHE_BENCH_LABEL=block-baseline-01
export HICACHE_BENCH_TRACE="$PWD/work/pressure/block-baseline-01.server.jsonl"
```

Use the pinned profile's resolved server settings, with its pressure overrides,
for the ordinary SGLang launch. The harness never launches/provisions a server or
flushes cache. In the deployment JSON, retain the model/revision, resolved model
path, FULL mode and runtime SHA fields described in `CROSS_FAMILY_PREPARATION.md`.
Also record the server's Linux boot ID as `clock_domain` and actual startup toggle
as `pressure_match_observation: true`. These are operator declarations; the client
does not attest model weights. Mailbox replies/trace domain are checked separately.

```bash
python -m research.agent_resume.pressure run \
  --packet work/pressure/qwen-packet.json --tokenizer "$TOKENIZER_DIR" \
  --deployment work/pressure/deployment.json --server http://127.0.0.1:30000 \
  --mode request_time --observation memory \
  --probe-dir work/pressure/mailbox --output work/pressure/block-baseline-01
python -m research.agent_resume.trace_report \
  --block work/pressure/block-baseline-01 \
  --trace work/pressure/block-baseline-01.server.jsonl \
  --output work/pressure/block-baseline-01-physical.json
```

The proactive block uses the **same prepared packet and settings**,
`--mode proactive`, a new output path, and matching trace label/path. Reinitialize
worker and isolated storage **between whole comparison blocks**, never between
measured target requests. Fix the startup/warmup recipe across blocks; do not run
treatments successively on an already warmed shared cache and call them a paired
benchmark. Cache salts are fixed per trajectory in the packet, isolating sessions
while remaining identical across clean comparison blocks. Check saved prefix
sizes after generated tool turns; they grow beyond the initial ~4k packet.

For an observation ablation, restart with
`TOOLGAP_PRESSURE_MATCH_OBSERVATION=0`, declare the false toggle in deployment,
and use `--observation off`. Compare instrumentation cost under the same workload.
Optional direct-stat samples use `--observation memory-and-stat` in **both**
treatments. Never add polling or useful-work delay to obtain a favorable gap.

Outputs retain every caller, failed/wrong answers, actual IDs, all tools, measured
queue delay, TTFT, tool-dispatch-to-first-token, full task latency, policy decisions,
control events and bounded cleanup. Per-trajectory `*.outcome.json` and streaming
control JSONL survive an interrupted block; incomplete blocks are not performance
results. Physical reports use the manifest's clock/window and dedicated trace
label. Unknown consumption/waste must not become a zero.

Stop before another block if ownership cleanup is unresolved. Local timeout never
frees host KV. Stop a paid session for prolonged exploratory debugging, fit failure
or a fundamental runtime blocker and continue locally under the existing budget.

## Decision criteria

First validate live model-selected tool calls and correctness on a non-Qwen model.
Then run repeated whole blocks with balanced treatment order and identical fixed
arrivals. Report all-caller quality and completion rate, full latency distributions,
real opportunity rate, bytes/occupancy/evictions and observer overhead. Twelve
interacting tasks do not support a p95 or cross-family speedup claim.

A zero natural-L3-opportunity workload is a valid result: this optimization cannot
help it. A TTFT improvement that harms other agents or task completion is not a
workload win. Improve workload relevance or policy only in response to measured
causes; no SWA/distributed/new backend/API expansion belongs to this step.
