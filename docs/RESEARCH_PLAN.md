# ToolGap: cross-family agent-resume research

Status: **planned, not executed**. Updated 2026-10-04 after inspection of the
existing harness and official candidate model cards/configuration. Existing
v0.1/v0.2/v0.3 GPU evidence remains unchanged. No GPU resources, model-weight
downloads, new runtime implementation or publication accompany this plan.

## User-facing objective

Determine when restoring reusable KV during real tool execution improves agent
completion latency under finite inference-cache capacity, across model families.
Deliver a usable integration and an open, reproducible agent-resume workload.
All-caller benefit, output quality and resource cost matter alongside TTFT.

The next research milestone is evidence on **multiple families plus realistic
cache pressure**. Admission and reconciliation are candidate mechanisms to
evaluate within that workload, not the whole product objective. Additional SDK
features should address an observed workload limitation.

## What is established and what is missing

| Established | Still untested |
|---|---|
| Exact-prefix L3→L2 publication and ordinary H2D reuse | Cross-family/model generalization |
| Qwen2.5-1.5B controlled tool-loop benefit, n=3/condition | Larger dense-model feasibility and benefit |
| Resident negative control | Frequency of useful L3 opportunities under workload-driven eviction |
| One two-caller correctness smoke, n=1 | Aggregate latency, throughput and fairness under sustained load |
| CPU ownership, cancellation and optional admission checks | GPU benefit/cost of the new reconciliation/hint policies |

The current tool-loop uses a synthetic document archive and explicit flush for
L3-only conditions. Its exact-token continuation and parser are Qwen-specific.
`Engine.start()` derives settings from the old 8192-token server command. Passing
a different `--model-path` alone does not make a valid cross-family experiment.

## Candidate models: change size and family separately

| Model | Role | Current status |
|---|---|---|
| Qwen/Qwen2.5-1.5B-Instruct | Historical reference and cheap harness checks | Existing GPU evidence only for pinned historical setup |
| Qwen/Qwen2.5-7B-Instruct | Size change within Qwen | Candidate; ToolGap GPU validation pending |
| mistralai/Mistral-7B-Instruct-v0.3 | Second family, comparable dense-model size | Candidate; template/runtime validation pending |
| meta-llama/Llama-3.1-8B-Instruct | Third family | Candidate; model-access and runtime validation pending |

These choices isolate useful axes rather than selecting models by popularity.
Mistral's official card documents function calling and tool-call IDs; its config
has `sliding_window=null`. Qwen7B's config has `use_sliding_window=false`.
Meta documents Llama3.1 tool use and access conditions. Actual resolved runtime
FULL attention/cache mode must still be checked; family names are insufficient.
Do not silently enable SWA, quantization, TP/PP or change storage to make a model
fit. Select an explicit supported profile or report the incompatibility.

Primary sources inspected:

- [Qwen2.5-7B model card](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct)
  and [configuration](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/raw/main/config.json).
- [Mistral-7B-v0.3 model card](https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3)
  and [configuration](https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3/blob/main/config.json).
- [Llama-3.1-8B model card and tool use](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct).

Pin exact model revisions, tokenizer/template hashes, configs and runtime SHA in
new per-model manifests before execution. The historical `compatibility.json`
must retain its original meaning. A future newer-family profile can be added if
its architecture provides a supported FULL KV path; it is not assumed compatible.

## Measurement axes and memory feasibility

Start with useful context bands near 4k, 8k and 16k tokens and staged concurrency
1, 4 and 8 trajectories. These are **planned axes, not a full Cartesian sweep**.
Choose a small core comparison first, then vary one factor at a time.

Use real document/code excerpts and conversation history, not repeated filler
solely to increase prefix size. Across families, equal token counts are not
equal KV sizes or identical textual contexts. Report both semantic workload and
actual token/byte counts; pair treatments within each model.

For dense FULL attention at TP1, the approximate raw KV payload is:

```text
2 × layers × KV heads × head dimension × KV dtype bytes × aligned prefix tokens
```

For the inspected BF16 configs, Qwen7B is approximately 56 KiB/token and
Mistral7B approximately 128 KiB/token (inference from config, not allocation
measurements). At 8192 tokens, that is 448 MiB versus 1 GiB. Actual allocations,
page alignment, storage payloads and overhead must be measured. Record weights,
GPU KV capacity, host capacity and transient headroom before claiming an L4
configuration fits. The existing 150 GiB disk/image assumptions must also be
checked against additional weights and result artifacts.

## Useful workloads

1. **Document investigation:** search a pinned public document corpus, retrieve
   cited passages and produce a checkable answer with source references. Include
   multiple tool rounds and growing conversation history.
2. **Repository investigation:** search/read files in a pinned repository and run
   selected real tests or analysis commands. Score file/line evidence and tool
   outputs against declared tasks; record subprocess cost and shared CPU load.
3. **Data investigation:** execute read-only SQLite queries over a documented
   dataset and answer verifiable numeric questions. Mark synthetic data as such.

Develop document/repository tasks first; data tasks add a distinct tool profile
after the common runner works. Tools perform actual work. Their input size,
algorithm, outputs and latency are recorded. Do not inject sleep to obtain a
favorable tool gap. Natural useful-work durations determine measured overlap.
Avoid uncontrolled remote tools in the initial reproducibility workload.

## Separate mechanism and workload experiments

**Controlled restoration:** retain explicitly constructed L3-only and resident
conditions as diagnostics. Compare ordinary request-time restoration with
proactive restoration, with the same exact saved prefix and tool input per pair.
This tests portability of the primitive and is labeled controlled eviction.

**Workload-driven eviction:** run a persistent worker with finite declared GPU/L2
budgets and competing trajectories. Targets reach a tool boundary, background
agents continue useful inference, and normal cache pressure may demote/evict KV.
There is no per-target `flush_cache` or restart during the measured workload.
Initialization and post-run cleanup stay outside measurement.

Capture the target state at tool dispatch and continuation arrival. Report
GPU-resident, L2-resident, partial-hit and L3-only opportunities separately. The
occurrence rate is a result, not a condition forced to equal 100%. Pressure is
explicitly configured to fit the workload; do not call it production traffic.
Existing probes call cache matching: audit recency/ref side effects before using
them during eviction measurements, and measure instrumentation overhead.

Use fixed exogenous arrival/task traces across treatments. Record timing shifts
caused by each treatment rather than claiming all subsequent cache states stayed
identical. Report all agents, not just targets that obtained proactive admission.

## Model adapters and exact-token contract

The first local implementation step is a small per-family harness adapter for
prompt/tool-call/result serialization. It must preserve the actual generated
prefix IDs; decoding/re-encoding the saved prefix is unacceptable. Verify the
official tokenizer/template, end-of-turn markers, tool-call IDs and aligned
reusable span. If a template cannot append a correct continuation without changing
saved IDs, report it explicitly rather than silently inventing a conversation.

Model-selected tool-call errors remain visible. Never fabricate a successful call
or exclude failed tasks from total task-success/latency accounting. Compare output
IDs where deterministic paired execution permits it, and separately evaluate task
correctness. Different models need not produce identical IDs or choose identical
calls. Within-model runtime treatments must not lower task quality.

Use two labeled modes: frozen first-turn/token/tool traces for causal paired
restore comparisons, and live multi-round agents for application-level evaluation.
The trace-replay result does not stand in for live agent behavior.

## Treatments and predictions

Core comparison: **ordinary request-time L3 restore versus proactive restore**.
Add recompute as a separately labeled cost reference; do not use it instead of
the real request-time baseline. To evaluate new policy, subsequently compare
manual local observation, bounded reconciliation, and reconciliation plus hints.

- L3 restoration may be hidden when useful work remains before continuation.
- Resident prefixes should show little/no restore benefit.
- Earlier slot release may help later arrivals; simultaneous busy callers still
  fall back. It may also increase I/O competition and unused publication.
- Hint policy may suppress low-value I/O, but wrong estimates can miss useful
  opportunities. Estimates must come from prior independent calibration, not
  ground truth from the same run or future continuation outcome.

Record both improvements and regressions, including early tools, abandonment,
partial residency, re-eviction after publication and misleading hints.

## Measurements and experimental discipline

Primary outcomes: completed-task success rate, full task latency, all-caller
tool-dispatch-to-first-token latency, aggregate completion rate, and tail latency
when sample size supports it. Full task latency includes initial generation,
tools and all continuation rounds; it is distinct from the existing step metric.

Also collect continuation TTFT; tool durations; submit/status overhead and counts;
local reservation/release; storage-query/read and publication timestamps; actual
KV bytes/tokens; attributable pre-arrival consumption; duplicate/partial reads;
GPU/L2 occupancy and eviction; cancellation cleanup and unused published bytes.
Instrument physical I/O separately from warm OS file/page-cache effects.

Freeze workloads, success graders, seeds, settings and treatment order before
timed execution. Separate warm-up/calibration from evaluation. Randomize paired
order and include independent workload blocks; agents within one block share
contention and are not independent repetitions. Report exact n and experimental
unit. A small pilot (e.g. 10 paired tasks) establishes feasibility, not a general
performance claim. Choose confirmation sample size/precision before examining
confirmation outcomes; do not treat repeated continuations as new independent
trials or use three repetitions for a credible p95 claim.

Keep precision, quantization, storage payloads and generation settings identical
within each comparison. Record per-family differences openly. Publish raw per-task
and per-block data, failures, source/model identities and reproduction commands.

## Execution order and useful decision criteria

1. Prepare family adapters, exact-prefix checks, useful tasks, configurable server
   profiles and a CPU-tested runner locally. No new runtime framework is required.
2. Run compatibility/pilot on at least one non-Qwen family after separately approved
   GPU provisioning; then add the other family and Qwen7B size control.
3. Run persistent-worker memory-pressure comparisons on validated profiles,
   followed by policy ablations. Avoid an unbounded all-model/all-axis sweep.
4. Produce an integration example, open workload/data and a report extension that
   separates new measurements from the existing historical benchmark.

An infrastructure smoke is not completion of this research milestone. The useful
deliverable answers which models/workloads exhibit restore opportunities, whether
agents complete their tasks sooner at equal resource settings, and what overhead
or waste the optimization introduces. Establish at least two validated families
before making a cross-family claim. A realistic scenario without an aggregate win
must be reported and should guide the next engineering change. Compatibility
failures narrow supported profiles; they must not silently disappear from results.

No new GPU execution or expanded compute budget is authorized by this document.
Existing per-session approval/time/cost constraints remain in force. Prepare
weights/adapters and commands locally before paying for exploratory GPU work.
