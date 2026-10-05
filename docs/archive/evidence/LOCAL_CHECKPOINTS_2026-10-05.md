# Local checkpoints: historical log, 2026-10-05

Archived from WORK_TRACKER at commit `ece4313bbd882f81a1aded3bcf301ff70703f107`. This preserves past
statuses, checks and decisions; historical pending tasks and approvals are not
current instructions. See [the active tracker](../../WORK_TRACKER.md) and the
[versioned local evidence](../../../research/agent_resume/local-review-2026-10-05.json).

## Local contract checkpoint (2026-10-05)

Evidence: [versioned validation summary](../../../research/agent_resume/contract-validation.json).
The declared base checkout has local edits identified by source hashes; it is not
represented as a clean released SHA.

- TG-002: [typed outcomes](../../../research/agent_resume/contracts.py), profile-bound
  adapter identity/capabilities and complete-response classification exist.
  Missing Mistral raw ID is a valid semantic call, followed by explicit
  `MISSING_HISTORY_ID` rejection for the pinned HF history before effects.
  Multiple native calls are recognized; the single-call runner rejects them.
  Mixed responses retain raw text and are unsupported; no trailing text is used
  to fabricate tool success.
- TG-003: an independent HF documentation example, native full-history rendering
  and `mistral_common` 1.12.0 serializer reference complement scripted negative
  fixtures. [Offline checker](../../../research/agent_resume/native_conformance.py)
  passes two rounds on pinned Qwen2.5-1.5B, Qwen2.5-7B and Mistral-7B-v0.3
  tokenizer profiles. Llama remains illustrative/unvalidated. Native references
  are not live model outputs; no alternate tokenizer stack was substituted.
- TG-004: [runner](../../../research/agent_resume/runner.py) checks tool arguments,
  static continuation and minimum envelope budget before tool/observer/control
  effects; actual result serialization/budget is checked after execution. Saved
  IDs stay unchanged. Result overflow cancels only owned restore, and normal
  continuation still does not await restore submission/completion.
- Relevant harness and SDK regression subset: **97 passed, 41 subtests passed,
  zero failures/skips**. [Contract regressions](../../../tests/test_agent_contract.py)
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

Evidence: [readiness validation](../../../research/agent_resume/readiness-validation.json).
Commands: [agent study guide](../../guides/AGENT_STUDY.md). The previous contract
checkpoint and historical pilot/report datasets retain their original bytes.

- TG-005: [readiness gates](../../../research/agent_resume/readiness.py) reject scripted,
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
- TG-007: [bounded sampling](../../../research/agent_resume/sampling.py) no longer
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
| 2026-10-05 | One approved Mistral GPU pilot stopped before pressure blocks | [Outcome](MISTRAL_PILOT_2026-10-05.md) |
| 2026-10-05 | Architecture and process review; local reproducer confirms tool execution precedes unsupported continuation rejection | [Review F-02](ENGINEERING_REVIEW_2026-10-05.md) |
| 2026-10-05 | Accepted direction: separate adapter/runner/cache contracts and staged evidence | [ADR-0001](../../decisions/0001-agent-integration-contract.md), [ADR-0002](../../decisions/0002-evidence-and-experiment-readiness.md) |
| 2026-10-05 | Consolidated active planning here; grouped user guides, decisions and historical records | [Documentation index](../../README.md) |
| 2026-10-05 | Implemented local evidence gates, file namespace/runtime guards and non-blocking sampling; 119 CPU tests + 69 subtests | [Readiness validation](../../../research/agent_resume/readiness-validation.json), [commands](../../guides/AGENT_STUDY.md); TG-007 live calibration/initialization still open |
| 2026-10-05 | Implemented local adapter/runner contract and effect ordering; 97 regressions + 41 subtests, three native tokenizer profiles | [Validation](../../../research/agent_resume/contract-validation.json); TG-005–TG-007 still open |
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
[study guide](../../guides/AGENT_STUDY.md#warmupreset-source-audit--local-preparation-not-live-validation)
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
- The [study guide](../../guides/AGENT_STUDY.md#bounded-useful-model-pilot-proposal)
  fixes useful-live-first ordering, a 60-minute proposed ceiling, off/on/on/off
  calibration, block-specific server environments/traces and a conditional
  bracketed B/C/B feasibility comparison (not independent replicated pairs).
  This does not authorize provisioning; actual server reset/calibration and
  natural opportunities remain NOT_RUN. TG-007 remains IN PROGRESS for its
  live criteria. No new framework, runtime API or pressure claim is added.

Local preparation evidence: [setup checkpoint](../../../research/agent_resume/study-preparation-2026-10-05.json).
Final relevant regression suite: **122 passed + 69 subtests**, no failures/skips;
12 are actual CPU FULL/file fixtures. Historical 119-test checkpoint, Mistral
pilot, report and GPU datasets retain their original bytes. Remaining paid-run
readiness is provisioning/fit verification plus the explicitly pending live
gates above; CPU setup success is not a pressure result.


## TG-008 provisioning checkpoint (2026-10-05; no execution)

The pinned Qwen7 pilot now has a frozen private provisioning/cleanup package.
[Final-image local summary](../../../research/agent_resume/provisioning-preflight-2026-10-05.json)
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

[Sanitized attempt record](../../../research/agent_resume/qwen7-pilot-attempt-2026-10-05.json)
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


## Post-capacity local review and resource audit (2026-10-05)

Read-only resource inventory found no ToolGap VM, leftover boot disk, reserved
external IP, snapshot, image, reservation, instance group or NAT/router. Cloud Run
jobs/services are empty in the configured region; no ToolGap scheduler or local
cleanup timer remains. Unrelated existing project workloads were left untouched.
Retain the one validated registry image (~14.03 GiB compressed), 88 historical
result objects (~6.98 MiB; no hidden versions found), and the existing narrow
service account. No deletion, quota/IAM change or GPU execution was performed.

Code review reproduced two measurement defects: cancelled block callers could
disappear from the aggregate, and throughput omitted final cleanup/recording.
The harness now preserves all declared outcomes and partial token evidence,
censors cancelled latencies, finalizes interrupted evidence with failed study
status, and measures throughput through caller finalization. The 5% descriptive
gate includes client queue and cleanup and fails closed for incomplete blocks.
Runtime and production SDK remain unchanged.

The next fixed pilot begins with an observed ordinary baseline. Without useful
quality/cleanup and a sampled L3 candidate, stop before more comparison blocks.
Otherwise finish on/off/off/on calibration, then conditional B/C/B under the
existing absolute budget. A sparse negative observation stays local to this
block; no global absence or speedup claim follows.

[Review checkpoint](../../../research/agent_resume/local-review-2026-10-05.json) contains
checksums and final offline results. Old v1 provisioning readiness is superseded
and its launcher flag disabled; its raw evidence/payload is preserved. Freeze a
new bundle/packet and rebind cleanup/provisioning checks before any separately
authorized paid retry. TG-007 live initialization/calibration remains NOT_RUN;
TG-008 remains blocked on external capacity. No new release, push or PR.

## Revised Qwen7 pilot authorized (2026-10-05)

Maxim Yakimov authorized pushing the reviewed branch and conducting one GPU pilot
in any available region. `d510156` is now on the remote branch. Preserve the
previous 60-minute / USD 1.50 session limit; do not change model, image or runtime.
The committed v2 bundle passed final-image native/scripted/CPU checks and mocked
orchestration again. Provider DELETE is now at minute 60, guest shutdown at 58,
and study cutoff at 55; result collection/deletion remains mandatory.

Read-only STANDARD Capacity Advice was unavailable to the project. An Oregon
zone creation failed on capacity without an instance/disk; a second Oregon zone
created the single intended L4 worker. No second paid VM or workload repetition.
TG-008 is now RUNNING for the approved session; live quality, initialization,
calibration and pressure remain pending until actual artifacts are evaluated.

## Qwen7 authorized session completed (2026-10-05)

[Sanitized live record](../../../research/agent_resume/qwen7-live-pilot-2026-10-05.json)
binds the preserved raw evidence to `d510156`, runtime `3e60ad8`, the existing
image and pinned Qwen2.5-7B weights/tokenizer. L4/driver 580.178.04,
PyTorch 2.13.0+cu130, BF16 FULL/file, TP1/PP1/DP1 loaded and generated; resolved
token capacity was 8192. Image/model setup finished within the declared setup
budget. The actual useful pilot made 11 generations and eight tool executions.

- `physical-cleanup`: three literal searches returned zero matches, then a
  prose-plus-call response was classified unsupported and stopped before its
  tool execution.
- `overlap-estimate`: four literal searches returned zero matches; the next
  generated call exceeded the frozen tool-round budget and was retained but
  not executed.
- `run-regression`: nine real CPU tests passed; the final response cited
  nonexistent `admission_hints/test_class.py:1` without retrieved evidence and
  failed grading. Procedure completion is not task success.

All eight submitted continuations preserve the **full** preceding input and
generated IDs, checked independently from aligned cache prefixes. The original
readiness record nevertheless says `exact_continuation=FAIL`, because that
summary couples the dimension to useful-task success; it also says
`model_fit=UNKNOWN` without inspecting resolved server pools. Preserve these
raw fields and document the separate checks instead of silently relabeling the
pilot successful. Baseline policy cleanup with no proactive operations does
not validate new live cancellation paths.

No useful task passed: no HTTP reset, observation calibration, pressure window
or proactive comparison was run. No speedup, window-absence or waste claim
follows. The host's normal exit code 0 records orderly finalization after the
failed gate. Runtime, image and published historical data remain unchanged.

VM creation through verified deletion took 16m51s. Conservative machine/disk/IP
plus inter-region image-pull estimate is approximately USD 0.40, not an invoice.
Named instances and boot disks are both zero; the backup timer is inactive.
No second paid worker or repeated workload ran.

Next local checkpoint: replay retained searches/citations against the pinned
corpus and review **generic tool discoverability and evidence retrieval**, not
model-specific JSON repairs. Keep the failing outputs and fixed grading; do not
increase tool rounds or manufacture evidence to pass this run. Any changed
workload/profile is new evidence and requires new pins before another paid run.

## Repository tools v2 local checkpoint (2026-10-05)

[ADR-0003](../../decisions/0003-repository-tool-evidence-contract.md) records the bounded
tool changes: word/identifier retrieval with literal priority, paginated pinned
file discovery, and actual test-class source evidence from the regression tool.
The executor contains no model/task-specific query aliases or answer lookup.
Listing metadata alone cannot satisfy grading; invented/unretrieved citations
and unsuccessful required tools remain rejected. Parser, four-tool-round limit,
runtime and production SDK are unchanged.

The original-corpus CPU replay now returns actual source lines for all seven
previously empty queries; it does not replay new model decisions or claim agent
success. Some lexical matches still need a follow-up identifier search/read.
The first search includes index construction in its measured duration. Token
sizes, retrieval latency and quality belong to this new workload, not the old
GPU results.

Local final-image checks passed **132 tests + 93 subtests**, zero failures/errors/
skips, including 12 actual CPU FULL/file fixtures. Official pinned-tokenizer
conformance passed two rounds with the new schema. A new CPU packet ran 12/12
scripted callers and 108 real CPU regression-test executions; native/scripted
success remains distinct from useful live behavior. Ruff/diff checks pass.
The initial container check's one provenance failure is retained: the host
worktree's gitdir was inaccessible in the container. Mounting the existing
clean checkout of the same runtime SHA resolved it; no code/test weakening or
image rebuild was used.

Evidence is appended as `repository_tool_contract_review` in the existing
[local review record](../../../research/agent_resume/local-review-2026-10-05.json).
Schema/executor/runner hashes are now bound into the measurement contract; a
checksum-valid old packet stops before live HTTP or tools. The previous paid
launcher's readiness flag is disabled and its original preflight preserved.

TG-008 is still incomplete; both historical live pilots remain 0/3. Before
another separately authorized live gate, freeze the new code/packet/evidence
and verify the launch/collection guards. Do not run pressure or claim cache
benefit until useful quality passes. No GPU, runtime/image change, new release
or upstream PR was performed at this local checkpoint.

## Hypothesis-alignment audit (2026-10-05)

[ADR-0004](../../decisions/0004-hypothesis-aligned-measurement.md) records the code and
measurement corrections. Exact saved IDs are now assessed independently of
final-answer quality; no continuation is `NOT_RUN`. A late task failure cannot
finalize earlier restores as unused without operation-specific proof. The useful
live gate must execute representatives from the actual pressure packet, with
the same context/initial IDs/salt and the existing six-round limit. Legacy
four-round diagnostics cannot satisfy it. Strict parsing and grading remain.

Physical traces now link ordinary request-time reads and H2D enqueue attempts
to continuation RIDs, alongside proactive publication, tool overlap and actual
whole-prompt device/host/storage counters. Missing/invalid counters are not zero;
enqueue is not GPU completion; operation-specific consumption/waste remain
unknown. Runtime `CACHED` does not monitor subsequent eviction, so distinguish
dispatch-reachable opportunities from those arising later before changing the
trigger. No new admission policy or runtime/SDK change was made.

Full local image verification passed **173 ToolGap tests + 124 subtests** and
**57 runtime tests + 14 subtests**, zero failures/errors/skips. The runtime suite
includes inherited finite-I/O fixtures and an existing two-rank lifecycle
regression; it does not validate distributed exception recovery. The official
Qwen7 tokenizer passed two native rounds. A newly frozen packet passed 12/12
scripted callers with 108 real CPU regression executions; actual model generation
is false. All checks used CPU, with container networking/GPU disabled. Setup
errors (image entrypoint and demo plugin import path) are retained; the corrected
command ran all selected tests without weakening/skipping them.

Evidence: `hypothesis_alignment_review` in the existing
[local review](../../../research/agent_resume/local-review-2026-10-05.json). Source/raw
artifact hashes and exact validation dimensions are retained there; raw traces
stay private. Historical 0/3 pilot outcomes and published v0.1/v0.2 data are
unchanged. TG-007 still needs live overhead/usage evidence; TG-008 still needs
useful live quality for this actual packet. TG-009/TG-010 remain `NOT_RUN`.

The next substantive experiment is still natural opportunity prevalence and
all-caller benefit at fixed resources. Before a separately authorized paid run,
freeze a fresh launch package/native proof for the committed code and bind the
useful gate to its pressure packet. Then calibrate and run baseline; a matched
comparison is conditional on useful quality and natural windows, with a no-win
or no-opportunity outcome retained. No new GPU session, release or PR occurred.
