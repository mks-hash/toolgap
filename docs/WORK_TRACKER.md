# Current work tracker

Updated: 2026-10-06. Owner for the work below: the coding agent in this project.
Reviewer/approval authority: Maxim Yakimov. Work is local on
`feat/passive-pressure-workload`. Maxim Yakimov authorized committing and
pushing this branch on 2026-10-05. Both explicitly authorized single Qwen7 GPU
sessions are complete; the latest stopped at the useful-live gate. No further
paid session, release or upstream PR is authorized by this checkpoint.

## Outcome and current state

The current local work is [ADR-0005](decisions/0005-bounded-tools-and-diagnostic-study.md),
building on [ADR-0004](decisions/0004-hypothesis-aligned-measurement.md).
Its purpose is to measure the original L3 → L2 → ordinary continuation hypothesis,
not to expand the SDK or agent framework. Runtime and published benchmarks stay
at their existing pins. The previous full-image CPU verification passed; it is not
validation of the current uncommitted changes. The latest packet-bound live gate failed
0/3; pressure and performance remain NOT_RUN.

Answer whether useful competing agent trajectories naturally create L3 restore
opportunities, and whether prefetch improves all-caller outcomes without lowering
task quality at the same resource settings. Include larger models and a second
family after their integration is demonstrated.

The Mistral L4 pilot fitted the model and generated responses, but **0/3 live
tasks passed and no tools executed**. Pressure blocks did not run. Current
milestone status: **LOCAL_READINESS_CHECKPOINT_PASSED; PRESSURE_NOT_READY**, not a failed prefetch hypothesis. The pilot itself remains 0/3; local changes do not revise its outcome.
See [pilot evidence](archive/evidence/MISTRAL_PILOT_2026-10-05.md) and the
[engineering review](archive/evidence/ENGINEERING_REVIEW_2026-10-05.md).

The later [Qwen7 live pilot](../research/agent_resume/qwen7-live-pilot-2026-10-05.json)
loaded and generated on L4, executed eight real tools, and preserved all eight
actual continuation prefixes, but **0/3 useful tasks passed**. Literal searches
returned no matches and the regression answer cited an unretrieved nonexistent
path. Stop reason: `USEFUL_LIVE_GATE_FAILED`; no pressure/calibration/treatment
block ran. This is a workload-integration finding, not a prefetch result. The
single VM and boot disk were deleted; all failures are retained.

The [packet-bound Qwen7 pilot](../research/agent_resume/qwen7-packet-pilot-2026-10-05.json)
at `b6b42e4` then generated 13 actual responses, executed 12 tools and preserved
all 10 submitted continuation prefixes, but again passed **0/3 useful tasks**.
Two real tool results exceeded the 7936-input-token allowance (8192 context minus
256 output tokens); independent official-tokenizer replay found 8236 and 8058
required tokens. The remaining answer had the right answer value but invalid
source evidence. Three real regression invocations passed 27 CPU tests. The
gate stopped before calibration/pressure/treatment. Both VM and boot disk absence
were confirmed after 16.75 minutes; total estimated session plus image-transfer
cost was USD 0.386, not an invoice. This is not evidence against prefetch benefit.

## Ordered work

This is the sole active task/roadmap record. Earlier research/preparation plans
are [archived snapshots](archive/README.md); they do not introduce parallel tasks.

| ID | Priority / state | Deliverable and acceptance criteria | Dependencies |
|---|---|---|---|
| TG-001 | P1 / DONE | Documentation index, this tracker, dated review, accepted decision records and sanitized pilot outcome exist; links and privacy checks pass. Runtime fixes are not implied. | None |
| TG-002 | P1 / DONE (local contract scope) | Implement the minimal adapter/runner contract in ADR-0001: explicit response outcomes, distinct call/operation identities, pinned template capabilities, completion/invalid-output handling. First assess reuse of pinned native/upstream parsers; preserve raw output and classify unsupported forms. A reference-valid missing-ID case must receive a documented disposition without rewriting saved IDs. | ADR-0001 |
| TG-003 | P1 / DONE (local contract scope) | Independent reference/recorded-output fixtures for supported adapter profiles; whole responses, EOS/length boundaries, missing/malformed IDs, multi-call and mixed text. Differential checks identify the reference version and compare rendering/tokenization with actual submitted IDs; reference disagreement is not silently normalized. No discarded trailing text or fabricated tool success. Scripted fixtures remain explicitly labeled. | TG-002 |
| TG-004 | P1 / DONE (local contract scope) | Validate static continuation capability and tool argument contract before executing tools or submitting prefetch; validate actual result suffix and token budget afterward. Unsupported templates/inputs produce zero tool/control effects. Check multi-round exact-token preservation and cancellation ownership. | TG-002, TG-003 |
| TG-005 | P1 / DONE (local evidence enforcement) | Versioned capability/evidence report with independent statuses: transport, template contract, model fit, actual generation, useful tool loop, pressure opportunity, correctness and performance. Bind the profile to weights/revision, tokenizer/template, parser, dtype/quantization and resolved cache layout; distinguish declared identity from verified artifacts. Isolate file storage across incompatible profiles. Update software's preflight consumers, not just prose. CPU success cannot imply useful live model support. | TG-003, ADR-0002 |
| TG-006 | P2 / DONE (local evidence scope) | Validate stream/finish reason and record explicit truncated/malformed/unsupported outcomes; keep generated IDs and client-observed first-token semantics. Identify run/code/package/config/schema hashes and preserve all failed outcomes. Procedure completion and study success must be separate. | TG-002, TG-005 |
| TG-007 | P2 / IN PROGRESS | Close measurement design gaps: quantify observation delay/cost; specify bounded passive sampling at dispatch, during tool execution and before continuation, without delaying the tool or request. Separate L3 file availability, successful reads, publication and consumption. Report page-aligned spans and interval-censored transition times; unknown waste stays unknown. Freeze tool schema/executor, workload, grader, sampling budget and primary endpoints. | TG-004, TG-006 |
| TG-008 | P1 / LOCAL REWORK; useful live NOT_RUN; Qwen7 history 0/3 | One useful live compatibility pilot on a profile selected by local conformance and fit readiness, not family prestige or an obligation to rerun Mistral first. Actual tool execution, valid exact-prefix continuation, final grading and cleanup pass. Stop and retain all failures otherwise. CPU checks cannot satisfy this item. ADR-0005 adds bounded whole evidence pages and document search. Recorded failures remain failed; scripted checks cannot prove new model choices. Any new paid gate needs applicable approval and a new frozen package. | TG-002 through TG-007 |
| TG-009 | P1 / NOT_RUN; diagnostic/evidence separated | Baseline useful competing-agent block with no forced target eviction. Count opportunities at dispatch versus those arising during the tool gap, the remaining window, unknown/resident/missing spans and all-caller quality/latency. An L3 hit at continuation alone does not prove a usable pre-arrival opportunity. No opportunity is a feasibility result for this workload/resource point; do not manufacture one. Explicit diagnostic request-time observation may proceed on technical readiness even with failed final grading; it cannot qualify treatment or useful performance. Paid execution still needs approval. | TG-008 technical readiness for diagnostic; useful readiness for evidence |
| TG-010 | P1 / CONDITIONAL | Matched whole-worker baseline/prefetch comparisons if baseline supplies opportunities reachable by the specified trigger and quality/cleanup pass. Same model/config/arrivals/instrumentation; counterbalance treatment order and retain all callers/failures. Predeclare primary endpoint and acceptable competing-caller degradation. Report aggregate effects separately from conditional L3 effects, overhead/waste and uncertainty. No win is a valid outcome. Release/report decision follows evidence. | TG-009 |
| TG-011 | P2 / CONDITIONAL | Reuse the same evidence contract for a larger FULL/GQA profile and an independent family, changing one axis at a time after one trustworthy study. Publish compatibility and negative outcomes as well as measured benefit. No model sweep or unsupported architecture is implied. | TG-008 through TG-010, or a documented TG-009 feasibility stop |

TG-002 through TG-007 are local contract and methodology work, not separate
product milestones. Avoid expanding them into a generic agent framework. The
useful milestone remains TG-009/TG-010; contract corrections enable its validity.

## Study contract

- Scope: single worker, FULL resident host KV, file-backed L3; fixed pinned
  model/tokenizer/runtime and exact saved tokens/salt. Add size and family axes
  separately after useful live integration succeeds; do not infer support from
  a family name or silently change precision/backend to fit.
- Workload: primary document search over pinned real public documents; repository
  audit remains the secondary stress workload. Actual model-selected tools,
  fixed exogenous competing arrivals and bounded useful tool rounds. No artificial
  tool sleep, per-target flush or restart during measured pressure.
- Trigger: the existing treatment submits once at tool dispatch. A terminal
  `CACHED` response does not monitor later eviction. Separately identify a prefix
  that is already eligible at dispatch, becomes eligible during the gap, or is
  observed only at continuation. Passive sampling must not itself trigger cache
  matching/reads or become an unreported delay. Do not implement polling-based
  resubmission or a progress policy before this distinction is measured.
- Comparison: ordinary request-time restore versus proactive restore with the
  same generation settings, useful tasks and resource limits. Baseline opportunity
  counts precede a comparison; absent opportunities are an honest result.
- Outcomes: all-caller task quality/completion rate, full task latency,
  continuation TTFT and tool-dispatch-to-first-token. Retain unsuccessful callers,
  client queues, control overhead, cache state and physical I/O. Publication is
  not proof of consumption; unknown waste stays unknown.
- Measurement: record observation overhead and paired block configuration. Shared
  agents are not independent repetitions; whole-worker blocks are the unit.
  A small pilot is feasibility evidence, not a p95 or universal performance claim.
- Identity: use a profile fingerprint and isolated L3 directory for incompatible
  weights/layouts, with the same identity and initialization rules in both
  treatment arms. Do not hot-swap weights in this study. Record declared versus
  artifact-verified identity; a model name alone is insufficient provenance.
- Methodology detail and old command recipes remain available in the archived
  [research design](archive/plans/RESEARCH_PLAN.md) and
  [pressure preparation](archive/plans/PASSIVE_PRESSURE_PREPARATION.md).

## Research priorities after review of external proposals

Keep three questions separate: **opportunity prevalence**, **benefit conditional
on a usable opportunity**, and **whole-worker outcome at fixed resources**.
Conditional success alone does not establish deployment value. Define opportunity
strata from baseline observations; do not select favorable treatment runs by
their post-prefetch cache state. Sparse sampling provides bounds, not exact
eviction times. Missing samples remain unknown, and both arms use the same
instrumentation budget.

The first study uses one locally conformant profile. Qwen2.5-1.5B remains the
historical control; `Qwen/Qwen3-4B-Instruct-2507` is a candidate for a modern
FULL/GQA size extension, **not yet a supported/pinned ToolGap profile**. Its
[official config](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/main/config.json)
declares 36 layers, 8 KV heads, head dimension 128 and no sliding window. That
implies approximately 144 KiB/token of raw BF16 KV at TP1, before allocator and
runtime overhead; neither this estimate nor the card establishes L4 fit or tool
correctness. GQA is a KV-head organization, not an alternative to full attention.
The failed pinned Mistral profile remains an independent conformance case; fixing
it does not obligate another paid run. Select a second-family checkpoint only
after native protocol, actual engine support and KV memory headroom are checked.

Defer a model zoo, hybrid/SWA, new storage, predictive/progress-aware scheduling
and a generic research framework. Break-even characterization in KV bytes,
restore cost, natural tool window and capacity is valuable after trustworthy
opportunity/whole-worker results. No benefit at one resource point does not
prove there is no benefit elsewhere; any next configuration is a separately
declared experiment rather than a silent search for favorable numbers.

Primary-source checks on 2026-10-05 inform positioning, not ToolGap validation:

- [TokenCake](https://arxiv.org/abs/2510.18586) combines agent-aware scheduling
  with proactive offload and predictive upload. Do not claim discovery of the
  general idea of using tool stalls for cache movement.
- [EfficientAgent](https://arxiv.org/html/2609.33762v1) studies host-tier reuse
  working sets and write admission. Its HBM/host results motivate our retention
  measurements but do not prove file-L3 pre-arrival restore will help.
- [Ask the Tool, Don't Guess](https://arxiv.org/abs/2609.18849) studies runtime
  tool-progress signals. Dispatch without duration prediction is our current
  treatment, not evidence that it outperforms progress/prediction policies.

These are author-reported studies with different systems and baselines. Do not
rank their percentages against our benchmark. Our defensible scope is explicit
exact-prefix L3-to-resident-L2 restore through the ordinary continuation path,
with measured applicability, contention and failure economics. Full novelty
comparison and new report claims require a dedicated reading/comparison later;
published historical report/data remain unchanged.

## Current checkpoint and branch strategy

The code audit and hypothesis-alignment corrections are recorded in
[ADR-0004](decisions/0004-hypothesis-aligned-measurement.md) and the versioned
[local review](../research/agent_resume/local-review-2026-10-05.json).
Historical validation details and superseded pending statements moved to
[the archived checkpoint log](archive/evidence/LOCAL_CHECKPOINTS_2026-10-05.md).

Continue on `feat/passive-pressure-workload`. `main` remains unchanged; no new
PR or release is part of this checkpoint. A later PR should carry a bounded
reviewed research result, including a negative result, rather than combine
unfinished preparation with the stable product. Keep upstream lifecycle/feature
PRs and published benchmark pins separate.

The previous full CPU audit passed 173 ToolGap tests plus 124 subtests and 57
runtime tests plus 14 subtests, with no failures/errors/skips. The consistency
follow-up corrects symmetric observer calibration, shared output-budget and
request-parameter contracts, malformed metadata classification, duplicated
hashing and stale guide commands. The new committed bundle passed 176 ToolGap
tests plus 128 subtests and 57 runtime tests plus 14 subtests, with no
failures/errors/skips. Official-tokenizer two-round checks, 12 scripted callers
with 108 real CPU regression executions, orchestration mocks and cleanup
guards passed. The frozen private launch package was locally ready and was then used once
under explicit approval. Its session marker prevents reuse. The new 0/3 result
is separate from the historical pilots; natural pressure/performance remain
unvalidated.

## Next acceptance checks and execution limits

1. DONE: bounded consistency audit, CPU regression, code/decision commits and
   sanitized evidence; unrelated report working files remain untouched.
2. DONE: frozen committed packet and one separately approved live attempt,
   terminal failed useful gate, result collection, confirmed VM/disk deletion
   and offline replay of actual outputs. No automatic rerun.
3. IN PROGRESS locally under ADR-0005: close the tool-result budget gap using retained actual trajectories.
   Specify budget-aware, paginated evidence responses separately from exact-prefix
   serialization. The pre-dispatch empty envelope and ideal scripted sequence
   did not bound cumulative real result sizes. Exercise near-limit actual suffixes,
   repeated searches and reads without executing a model, trimming saved IDs,
   changing model/context/round limits or weakening source grading. Diagnose the
   cited-versus-retrieved lines independently of answer-value correctness.
4. IN PROGRESS locally: prepare real-document search and an explicit diagnostic
   request-time observation mode. Quality failures remain data; they do not by
   themselves forbid valid diagnostic observations. This mode cannot authorize
   proactive comparison or useful-agent performance claims. Evidence mode remains
   strict; its quality/opportunity conditions are separate from diagnostic safety.
5. Only after local preparation and a new separately approved GPU campaign:
   choose purpose before execution. Diagnostic request-time observation retains
   answer failures but stops unsafe/protocol/setup/cleanup failures and never
   runs treatment. Evidence campaign requires useful quality, baseline
   opportunities and symmetric calibration before conditional B/C/B. Preserve
   all callers, failures and unknown usage; no-window is an honest result.

Local fixes and the completed session do not authorize another paid run.
The fresh single-session package is consumed. Any proposed session must again
specify its budget and verify automatic cleanup before creation. No new
IAM/storage/image architecture, model sweep, SWA, distributed support, new
backend or proactive HBM expansion. Main and published benchmarks remain
unchanged; continue this branch until a bounded research result is reviewable.
