# Current work tracker

Updated: 2026-10-05. Owner for the work below: the coding agent in this project.
Reviewer/approval authority: Maxim Yakimov. Work is local on
`feat/passive-pressure-workload`. Maxim Yakimov authorized committing and
pushing this branch on 2026-10-05. No new GPU run, release or upstream PR is
authorized by this checkpoint.

## Outcome and current state

Answer whether useful competing agent trajectories naturally create L3 restore
opportunities, and whether prefetch improves all-caller outcomes without lowering
task quality at the same resource settings. Include larger models and a second
family after their integration is demonstrated.

The Mistral L4 pilot fitted the model and generated responses, but **0/3 live
tasks passed and no tools executed**. Pressure blocks did not run. Current
milestone status: **LOCAL_READINESS_CHECKPOINT_PASSED; PRESSURE_NOT_READY**, not a failed prefetch hypothesis. The pilot itself remains 0/3; local changes do not revise its outcome.
See [pilot evidence](archive/evidence/MISTRAL_PILOT_2026-10-05.md) and the
[engineering review](archive/evidence/ENGINEERING_REVIEW_2026-10-05.md).

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
| TG-008 | P1 / BLOCKED by zone capacity; one approved attempt used | One useful live compatibility pilot on a profile selected by local conformance and fit readiness, not family prestige or an obligation to rerun Mistral first. Actual tool execution, valid exact-prefix continuation, final grading and cleanup pass. Stop and retain all failures otherwise. CPU checks cannot satisfy this item. | TG-002 through TG-007 |
| TG-009 | P1 / TODO; separate execution approval | Baseline useful competing-agent block with no forced target eviction. Count opportunities at dispatch versus those arising during the tool gap, the remaining window, unknown/resident/missing spans and all-caller quality/latency. An L3 hit at continuation alone does not prove a usable pre-arrival opportunity. No opportunity is a feasibility result for this workload/resource point; do not manufacture one. | TG-008 |
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
- Workload: actual model-selected repository tools over pinned public source,
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

## Checkpoints and limits

- First checkpoint: TG-002/TG-003 now have a concrete local implementation and
  reference checks. TG-004 effect ordering is also verified; this is not a release
  or live model-support claim.
- Second checkpoint: TG-004/TG-005/TG-006 prevent unvalidated effects and
  misleading completion status, with explicit evidence dimensions. Pass the
  relevant SDK ownership/cleanup tests too.
- Third checkpoint: TG-007 combines those results with the frozen measurement
  design into a concrete local readiness package. State exactly what still
  requires live inference.
- No model switch, image/runtime architecture change, extra GPU attempt, PR,
  push or release is implicit in completion of local work.
- Keep lifecycle bugfix and upstream feature work separate from this harness.
  No SWA, distributed cache, new backend or proactive HBM expansion here.

## Local contract checkpoint (2026-10-05)

Evidence: [versioned validation summary](../research/agent_resume/contract-validation.json).
The declared base checkout has local edits identified by source hashes; it is not
represented as a clean released SHA.

- TG-002: [typed outcomes](../research/agent_resume/contracts.py), profile-bound
  adapter identity/capabilities and complete-response classification exist.
  Missing Mistral raw ID is a valid semantic call, followed by explicit
  `MISSING_HISTORY_ID` rejection for the pinned HF history before effects.
  Multiple native calls are recognized; the single-call runner rejects them.
  Mixed responses retain raw text and are unsupported; no trailing text is used
  to fabricate tool success.
- TG-003: an independent HF documentation example, native full-history rendering
  and `mistral_common` 1.12.0 serializer reference complement scripted negative
  fixtures. [Offline checker](../research/agent_resume/native_conformance.py)
  passes two rounds on pinned Qwen2.5-1.5B, Qwen2.5-7B and Mistral-7B-v0.3
  tokenizer profiles. Llama remains illustrative/unvalidated. Native references
  are not live model outputs; no alternate tokenizer stack was substituted.
- TG-004: [runner](../research/agent_resume/runner.py) checks tool arguments,
  static continuation and minimum envelope budget before tool/observer/control
  effects; actual result serialization/budget is checked after execution. Saved
  IDs stay unchanged. Result overflow cancels only owned restore, and normal
  continuation still does not await restore submission/completion.
- Relevant harness and SDK regression subset: **97 passed, 41 subtests passed,
  zero failures/skips**. [Contract regressions](../tests/test_agent_contract.py)
  include zero effects on unsupported history, malformed/truncated/parallel/mixed
  responses, multi-round saved IDs, failed-stream retention and result overflow.
- At this earlier checkpoint, TG-005/TG-006 remained incomplete: source/profile fingerprints and finish-reason
  handling exist, but readiness consumers, persistent-storage identity guards,
  full deployment/package provenance and evidence-dimension enforcement still
  need implementation. Weight identity remains operator-declared.
- At this earlier checkpoint, TG-007 remained open: the boundary observer was awaited before dispatch;
  bounded non-blocking temporal sampling and overhead/consumption measurement
  must be addressed before pressure work. **READY_FOR_NEW_GPU_PRESSURE_RUN: NO.**

Reproduce offline native checks with an existing pinned tokenizer directory:

```bash
PYTHONPATH=src:. python -m research.agent_resume.native_conformance \
  --profile research/agent_resume/profiles/mistral.json \
  --tokenizer "$TOKENIZER_DIR" --output "$NEW_EVIDENCE_FILE"
```

The recorded reference environment uses Transformers 5.17.0 and, for the Mistral
native serializer check, `mistral-common` 1.12.0. No weights or network fetches
are performed by this check. Keep each evidence output new; do not overwrite
historical results.

## Local readiness checkpoint (2026-10-05)

Evidence: [readiness validation](../research/agent_resume/readiness-validation.json).
Commands: [agent study guide](guides/AGENT_STUDY.md). The previous contract
checkpoint and historical pilot/report datasets retain their original bytes.

- TG-005: [readiness gates](../research/agent_resume/readiness.py) reject scripted,
  stale or missing native/live evidence. Both live and pressure consumers enforce
  the checks before generation/prefetch. Pressure requires useful live model
  execution for the exact packet profile/code/packages. Raw artifacts are hash
  bound; a failure cannot become readiness through clean process exit.
- File L3 is isolated by the full profile fingerprint. Actual private-mailbox
  observations verify the imported clean runtime SHA/source, package versions,
  directory, page size, host layout and KV storage dtype. This guards accidental
  cross-profile reuse; weight revision remains operator-declared. No weight
  attestation, generic packaged-runtime fallback or hot swapping is claimed.
- TG-006: failed streams preserve accepted IDs; finish/outcome and quality are
  explicit. Manifests capture dirty harness source hashes and packages rather
  than relying on HEAD alone. Live reports distinguish procedure completion,
  useful study success, resource-fit UNKNOWN and pressure/performance NOT_RUN.
- TG-007: [bounded sampling](../research/agent_resume/sampling.py) no longer
  blocks tool dispatch or continuation. Defaults are 100 ms, 8 samples, 50 ms
  timeout. Samples retain actual server observation intervals, late/unknown
  states, page-aligned spans, remaining useful tool windows and cleanup. Cache
  state exactly at dispatch stays UNKNOWN. Availability, reads, publication and
  consumption are distinct; unknown wasted bytes remain null.
- The packet freezes schema/executor/grader/source, arrivals, sample budget,
  primary successful-tasks-per-block-second endpoint and a 5% competing-caller
  median-degradation limit. These are predeclared feasibility criteria, not
  validated performance. Whole-worker blocks are the experimental unit.
- Baseline prerequisites gate exploratory proactive pressure: matched packet/
  observation, bound trace and rows, successful quality/cleanup and natural L3
  candidates. Later sampled eligibility does not prove fixed-dispatch trigger
  reachability. No delayed resubmission or cache runtime change was added.
- Final local tests: **119 passed + 69 subtests passed, zero failures/skips**,
  including 10 actual CPU FULL/file observer regressions. Three original native
  profiles and the derived Qwen pressure profile pass two-round offline reference
  checks. The Qwen 12-caller scripted workload check exercises real CPU tools;
  this is not useful live model behavior or natural pressure evidence.

Cold whole-worker initialization is now enforced before pressure: empty device
and host KV, no in-flight work, and an empty claimed file directory. A treatment
checks actual cache capacities, dtype/layout and threshold against its baseline.
This is block setup, not target eviction during a tool gap.

Remaining TG-007 work: validate this initialization on a real server, freeze
matched kernel/model warmup, complete live observation-on/off calibration and
the bounded live execution plan. Sampling
records overhead components, but local fixtures cannot establish live net
perturbation. The 5% criterion has no confidence/percentile claim from a pilot.
**READY_FOR_NEW_GPU_PRESSURE_RUN: NO.** No new GPU, model switch, image rebuild,
push or release occurred. The next useful outcome is actual model-selected tools,
continuation and correctness, followed by natural baseline opportunities; avoid
another SDK feature milestone.

## Recent record

| Date | Event | Evidence / decision |
|---|---|---|
| 2026-10-05 | One approved Mistral GPU pilot stopped before pressure blocks | [Outcome](archive/evidence/MISTRAL_PILOT_2026-10-05.md) |
| 2026-10-05 | Architecture and process review; local reproducer confirms tool execution precedes unsupported continuation rejection | [Review F-02](archive/evidence/ENGINEERING_REVIEW_2026-10-05.md) |
| 2026-10-05 | Accepted direction: separate adapter/runner/cache contracts and staged evidence | [ADR-0001](decisions/0001-agent-integration-contract.md), [ADR-0002](decisions/0002-evidence-and-experiment-readiness.md) |
| 2026-10-05 | Consolidated active planning here; grouped user guides, decisions and historical records | [Documentation index](README.md) |
| 2026-10-05 | Implemented local evidence gates, file namespace/runtime guards and non-blocking sampling; 119 CPU tests + 69 subtests | [Readiness validation](../research/agent_resume/readiness-validation.json), [commands](guides/AGENT_STUDY.md); TG-007 live calibration/initialization still open |
| 2026-10-05 | Implemented local adapter/runner contract and effect ordering; 97 regressions + 41 subtests, three native tokenizer profiles | [Validation](../research/agent_resume/contract-validation.json); TG-005–TG-007 still open |
| 2026-10-05 | Reviewed external AI/Deep Research proposals against selected harness/runtime paths and primary references; refined identity, trigger timing, estimands and profile-selection criteria | TG-002–TG-011 and updated ADRs; implementation was pending at that review |

Update this file at a material decision, scope change, completed acceptance
check or discovered blocker. Link implementation/tests when marking TODO items
done; discussion and a proposed design alone do not complete them.

## Continuation after branch publication (2026-10-05)

Committed local implementation as `d5dd49c` and documentation organization as
`bcd4241`; both were pushed to `feat/passive-pressure-workload` with explicit
user authorization. The immutable readiness checkpoint describes its earlier
pre-publication state and is not rewritten.

TG-007 source audit confirms that idle flush clears GPU/host state but retains
file L3, and startup warmup covers only a short generation. The existing
[study guide](guides/AGENT_STUDY.md#warmupreset-source-audit--local-preparation-not-live-validation)
now proposes fixed warmup plus idle detach/reset/reattach of the owned namespace
before whole blocks. Actual server validation, observation-on/off calibration
and useful live integration remain pending; pressure readiness remains NO.

## TG-007 local execution preparation (2026-10-05)

- Two new real CPU FULL/file fixtures exercise flush retention and idle
  detach/reset/owned-directory cleanup/reattach; restored state remains usable.
  These are controller tests, not an HTTP/GPU initialization result.
- The proposed server recipe requires admin auth. Harness live/pressure clients
  now pass a process-only key through the existing SDK transport, check the
  declared auth mode and exclude credentials/raw launch commands from retained
  server-info manifests. Runtime and production SDK are unchanged.
- Prepared the pinned Qwen2.5-7B pressure profile locally: 12 source contexts,
  3801–3994 tokens, two-round native conformance and 12/12 scripted CPU callers
  with 108 actual fixed CPU regression executions. It is the proposed size-axis
  pilot; live support/fit remain unverified and Mistral stays 0/3.
- The [study guide](guides/AGENT_STUDY.md#bounded-useful-model-pilot-proposal)
  fixes useful-live-first ordering, a 60-minute proposed ceiling, off/on/on/off
  calibration, block-specific server environments/traces and a conditional
  bracketed B/C/B feasibility comparison (not independent replicated pairs).
  This does not authorize provisioning; actual server reset/calibration and
  natural opportunities remain NOT_RUN. TG-007 remains IN PROGRESS for its
  live criteria. No new framework, runtime API or pressure claim is added.

Local preparation evidence: [setup checkpoint](../research/agent_resume/study-preparation-2026-10-05.json).
Final relevant regression suite: **122 passed + 69 subtests**, no failures/skips;
12 are actual CPU FULL/file fixtures. Historical 119-test checkpoint, Mistral
pilot, report and GPU datasets retain their original bytes. Remaining paid-run
readiness is provisioning/fit verification plus the explicitly pending live
gates above; CPU setup success is not a pressure result.


## TG-008 provisioning checkpoint (2026-10-05; no execution)

The pinned Qwen7 pilot now has a frozen private provisioning/cleanup package.
[Final-image local summary](../research/agent_resume/provisioning-preflight-2026-10-05.json)
records **122 regressions + 69 subtests**, zero failures/skips, two-round native
conformance, and 12 scripted callers with real CPU tools. These checks ran inside
the existing image with network and GPU disabled. Its actual CLI/imported clean
runtime match the profile. Additional mocked checks stop file removal on idle or
detach failure and always attempt VM deletion on collection failure.

Read-only provisioning checks confirmed current quota, machine/OS/image, existing
narrow service-account access, SSH source admission and pinned driver/runtime
package availability. Quota/catalog presence does not reserve physical capacity.
The reviewed private package pins harness `5d4d532` and runtime `3e60ad8`; historical
records remain unchanged. Private host/cloud configuration and raw logs are
outside the public Git repository; the summary binds them by checksums.

**READY_FOR_EXPLICIT_PROVISIONING_APPROVAL: YES.** This is readiness to attempt
one bounded pilot, not pressure readiness or live Qwen7 support. No VM, GPU,
weight download, quota/IAM change, image rebuild, upstream PR or release occurred.
TG-007 live reset/calibration and TG-008 useful model behavior remain pending.
The agreed financial gate still requires explicit approval for this new session.

The concrete runner gives setup including model download 15 minutes from the
creation-request timestamp; study cutoff at minute 55, guest shutdown at minute
60 and provider DELETE with auto-delete disk at minute 70. Stages share one
absolute deadline. Useful gate failure ends execution before pressure; calibration
failure or absent natural opportunity prevents C; degraded all-caller outcomes
are retained as a negative feasibility result. No second attempt or silent
model/resource/runtime change is authorized. This remains a single-worker
feasibility pilot rather than independent caller repetitions or a release claim.


## Qwen7 approved attempt — capacity stop (2026-10-05)

Maxim Yakimov approved one Qwen7 pressure pilot, up to 60 minutes / USD 1.50.
The single VM creation request failed with
`ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS`: the selected zone lacked the
requested machine/L4 capacity. **No VM was created; no GPU workload ran.**
This is a provisioning-capacity result, not a Qwen7 integration failure or a
prefetch performance result. GPU fit, useful live tools, HTTP reset, observation
calibration, pressure and treatment comparison remain NOT_RUN.

[Sanitized attempt record](../research/agent_resume/qwen7-pilot-attempt-2026-10-05.json)
binds the privately retained exact error and verification outputs by SHA256.
Post-failure checks found zero named instances and zero named boot disks; the
workstation backup timer is inactive. Estimated VM/GPU compute cost is USD 0
(no VM was created; an invoice was not inspected). Runtime/image, historical
report/datasets and Mistral 0/3 remain unchanged.

Stopped as agreed. No second creation, zone/model/hardware change, quota request,
GPU execution, push, PR or release was performed. TG-008 is blocked on external
capacity; another paid attempt requires a new applicable authorization. The
existing frozen local package remains available for review; do not imply that
this one-attempt authorization covers future retries.
