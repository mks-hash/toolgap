# Engineering review: agent integration and experiment readiness

Date: 2026-10-05. Reviewed code baseline:
`1a5e34c8374d641becf9dc63975a7b62382cfa0a` on `feat/passive-pressure-workload`.

## Conclusion and scope

The research harness is **not ready for another paid pressure/performance run**.
Its adapter/runner contract and evidence promotion need correction. These findings
do not demonstrate a defect requiring redesign of the existing KV prefetch runtime.
The useful product objective remains measuring real all-caller benefit under
workload-driven cache pressure, including non-Qwen integration.

This is one code/evidence audit across eight engineering perspectives. It is not
eight independent expert reviews, a seniority certification, or an exhaustive
audit of all SGLang code. Previous reviews checked runtime lifecycle, release
correctness and local ownership; they did not close the new cross-family live
workflow contract. The implementation contains useful safeguards, but the broader
integration was insufficiently reviewed before paying for the Mistral pilot.

Inspected: `research/agent_resume/` adapters, runner, live/profile validation,
workloads/grading, preparation, arrivals, observer/plugin and trace reporting;
associated research/pressure tests; selected client/admission ownership paths;
research/preparation/validation docs; current CPU workflow; and the private
Mistral pilot's saved token IDs, verdict, launch configuration and cleanup proof.
No GPU, runtime implementation changes or publication accompanied this audit.

## Findings with code evidence

### F-01 — P1: required history ID was treated as required raw model output

**Confirmed contract assumption; not proof of the entire pilot's root cause.**
[Adapter](../../../research/agent_resume/adapters.py#L106) requires exactly
`name/arguments/id` for Mistral; missing IDs are rejected before continuation.
[Unit test](../../../tests/test_research_harness.py#L101) explicitly enforces that
assumption. [Native CPU preparation](../../../research/agent_resume/prepare.py#L140)
and subsequent scripted calls provide IDs selected by our harness.

The pinned [model card](https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3/blob/c170c708c41dac9275d15a8fff4eca08d52bab71/README.md)
requires nine-character IDs in history; it does not establish that every raw
generation supplies one. The official
[V3 serializer](https://github.com/mistralai/mistral-common/blob/main/src/mistral_common/tokens/tokenizers/instruct.py)
adds a call ID conditionally. This exposes a distinction our contract did not
handle. Current reference-library behavior alone does not prove every alternate
history form is compatible with the pinned HF template.

The actual pilot also contained trailing narrative/multiple call-like objects;
accepting an absent ID would not make those outputs successful tool executions.
Do not silently insert IDs into the cached prefix or discard trailing tokens.
Resolution: ADR-0001; TG-002/TG-003.

### F-02 — P1: continuation compatibility is checked after tool/control effects

**Confirmed by an offline reproducer against the existing runner.**
[Runner](../../../research/agent_resume/runner.py#L227) dispatches the tool and
optionally submits prefetch, awaits the tool result, then calls
`adapter.continuation()` at line 241. History/template rejection occurs inside
[continuation](../../../research/agent_resume/adapters.py#L139).

A changing-template fixture with a valid Qwen-format call executed one spy tool,
then returned `FAILED / UnsupportedTemplate`. It performed no real inference or
GPU work. Existing tools are bounded/read-only or execute a fixed regression
command, which limits impact; the ordering still invalidates a clean integration
contract and can spend tool/control work on an unsupported continuation.

Split pre-dispatch static/history compatibility and argument checks from the
post-result serialization/context check. Arbitrary result size cannot be known
before a tool runs; that limitation must remain explicit. Resolution: TG-004.

### F-03 — P1: fixtures verify our format assumptions, not reference conformance

**Confirmed coverage gap.** Current tests preserve IDs, reject malformed calls,
retain failed grading and test cleanup. Those are valuable. However,
[format tests](../../../tests/test_research_harness.py#L88) and
[script generation](../../../research/agent_resume/prepare.py#L191) derive valid output
from the same `ToolCall`/`call_text` assumptions. The test suite can pass while
the raw-output contract excludes a reference-valid form.

Add independent complete reference/recorded-output fixtures and an explicit
support matrix per pinned template: optional IDs, mixed text, multiple calls,
unfinished/truncated calls, EOS boundaries, system handling and multi-round
continuation. Keep model-selection quality separate from parser conformance.
Resolution: TG-003/TG-005; ADR-0002.

### F-04 — P2: parser outcome and transport completion are underspecified

**Confirmed interface limitation; truncation handling is unverified.**
[Parser](../../../research/agent_resume/adapters.py#L72) yields a single call, `None`
or an exception. It combines supported final text, malformed formats and
unsupported capabilities into limited classifications.
[Transport](../../../research/agent_resume/runner.py#L35) validates the last output
IDs and retains metadata, but response parsing does not interpret finish reason.

Record explicit normalized outcomes and retain complete generated tokens. Define
what EOS, length truncation, invalid/mixed output and unsupported multi-call mean
before any tool executes. Rejecting unsupported multiple calls is acceptable for
this MVP; silently picking one is not. First-token timestamps are client-observed
stream delivery, not device execution timestamps. Resolution: TG-002/TG-006.

### F-05 — P1: current task, decision and evidence records were fragmented

**Confirmed process/data gap.** Before this change, documentation lived in
`docs/`, the research objective in `RESEARCH_PLAN.md`, and decisions were embedded
in design/validation files and chat. There was no task tracker, decision index,
or root agent navigation file. The latest failed pilot was documented only
outside the OSS repository. Preparation prose still said GPU work had not run.

This change adds navigation, tracker, ADRs, a sanitized pilot summary and current
status corrections. Machine-readable stage enforcement is **still pending**.
Existing profile files remain preparation snapshots, not live readiness proofs.
`live.execute()` records configuration but not a full code/dependency manifest;
`pressure.execute()` includes HEAD but does not identify dirty file content.
The private orchestrator distinguishes stop reason yet exits normally after a
failed gate. A normal process exit must not be presented as workload success.
Resolution: TG-001/TG-005/TG-006.

### F-06 — P2: observation is non-mutating but still changes workload timing

**Known measurement limitation, not an observer purity failure.**
[Runner](../../../research/agent_resume/runner.py#L221) awaits a mailbox observation
before tool dispatch. [Observer](../../../research/agent_resume/observer.py#L130)
can stat files on the scheduler thread. It avoids prefix matching/touch/split,
but scheduler time, client waiting and OS metadata warming remain costs.
Matching observation also runs at each instrumented request.

Both treatments must use identical instrumentation, and its delay/cost must be
reported. A small observation-disabled diagnostic is needed if observation
materially alters pressure opportunities. File existence/size is an availability
hint, not integrity or successful KV restore proof. `UNKNOWN_STORAGE` must remain
unknown when storage checks are omitted. Resolution: TG-007.

### F-07 — P2: consumption/waste and broad task quality remain incomplete

**Explicitly unmeasured, not fabricated zeroes.**
[Trace report](../../../research/agent_resume/trace_report.py#L105) deliberately leaves
consumed restore tokens and wasted bytes unknown. Publication plus a later match
does not prove operation-specific consumption. Repeated page reads can follow
legitimate eviction and are not automatically duplicate-I/O bugs.

[Grader](../../../research/agent_resume/workloads.py#L222) requires fixed answers and
actual retrieved file/line evidence, and regression PASS requires a real tool
result. This is appropriate for bounded repository diagnostics but not evidence
of general agent usefulness or semantic answer quality. Expand meaningful tasks
only after the integration works; freeze graders/settings before comparison.
Track failed/cancelled/incorrect callers and resource cost. Whole-worker blocks,
not individual sharing agents, are the independent units. Resolution: TG-007
and TG-009/TG-010.

## Assessment across requested engineering perspectives

`NPL` is interpreted here as NLP engineering. These are review lenses, not claims
that independent specialists were assigned.

| Perspective | Assessment grounded in code/evidence | Required correction / useful result |
|---|---|---|
| System Design | Cache control is separate from generation, but integration readiness and pre-dispatch effects are not sufficiently staged. | Validate contract before effects; separate setup, live behavior, pressure and performance. F-02/F-05 |
| Senior Python Developer | Async tool/control cleanup and bounded fixed commands are useful; `None`/exceptions, dictionary records and one family switch leave important states implicit. | Minimal typed adapter outcomes/protocol; validate finish state/arguments; focused independent tests, not a framework. F-01/F-03/F-04 |
| ML Engineer | BF16 fit and three initial generations were observed; they establish neither useful tool quality nor cross-family cache correctness. | Pin weights/config/precision; useful model-selected loop and grading before latency comparisons. F-03/F-07 |
| LLM Engineer | Provider history metadata, raw calls, boundaries and exact continuation are conflated; scripted tool decisions substitute for an unproven contract. | Separate identities and reference conformance; retain full response and actual generated IDs. F-01/F-04 |
| NLP Engineer | Native system formatting and lexical evidence grading are bounded choices; generic final-JSON instructions may confuse tool formatting, but that cause is not established. | Explicit prompt/tool contract, independent examples, graded useful tasks; report invalid outputs without parser repair or cherry-picking. F-01/F-03/F-07 |
| Data Engineer | Hashes, per-caller records, clock domains and unknown waste are strengths; schema/version/code identity and public/private evidence navigation remain incomplete. | Versioned manifests/statuses, immutable outcomes, sanitized summaries; no missing-as-zero interpretation. F-05/F-07 |
| Systems Architect | The cache primitive remains model-format independent; research adapters lack a declared pinned capability boundary. One unified raw parser would not solve native-format differences. | Three explicit contracts in ADR-0001; supported template profiles, ownership identities and fail-closed unsupported continuation. F-01/F-02 |
| Principal-level engineering | Useful objective and bounded paid early-stop are sound; architecture decisions and readiness criteria were insufficiently persistent and reference-grounded. | ADRs, tracker and evidence stages; close local gaps once, then run the meaningful study rather than repeatedly patching models or polishing SDK microfeatures. F-03/F-05/F-07 |

## Strengths retained and limits of this audit

- Actual prompt/output IDs are retained; continuation appends rather than
  replacing the saved token sequence. Failed tasks are not removed from totals.
- Fixed tools validate repository paths/arguments and do not execute arbitrary
  model-provided shell commands; regression output is retained separately.
- Unknown cleanup retains the local slot; owned cancellation does not release
  another caller. Existing finite-I/O runtime evidence remains separate.
- Passive reads avoid normal match recency/split behavior. Clocks and request
  identities support correlation; unavailable attribution remains explicit.
- The paid run stopped at its live gate, and VM/disk deletion was verified.

No new GPU cache-consumption, distributed recovery, long-run fairness or production
traffic result was established. No finding asserts a host-slot leak in this run.
The audit checks selected ownership paths, not every possible lifetime in SGLang.

## Verification performed for this review

1. Read the sources/tests and pinned primary model/template references.
2. Replayed saved Mistral IDs: two whole-response JSON errors and one incorrect
   final response; no successful executed tool or continuation.
3. Ran the no-GPU changing-template/spy-tool reproducer: one executed tool before
   `UnsupportedTemplate`, confirming F-02. Missing model-ID rejection reproduced.
4. Targeted research/pressure tests: **29 passed in 0.56 s** outside the sandbox.
   Inside the sandbox, the initial run stalled after 13 reported passes and was
   interrupted; a bounded verbose rerun timed out at executor cleanup. A minimal
   standard-library `asyncio.to_thread(lambda: 1)` probe returned its value but
   timed out during shutdown inside the sandbox; the same probe exited cleanly
   outside it. Do not classify that environment timeout as a ToolGap test failure
   or reuse the guest's historical 168-pass count as this new local run.
5. New documentation links, source references and personal-path checks are
   verified: 14 touched/new documentation/summary files, 101 local links, no
   missing files or invalid source-line anchors, and no personal host paths in
   those files. Historical evidence replay also passes for the 45 v0.1 trials
   and 12 v0.2 runs; these are offline checks of existing data, not new GPU runs.
   Runtime fixes and new readiness enforcement remain TODO; documentation alone
   cannot pass them.

Portable targeted command from the repository root, in an installed development
environment:

```bash
PYTHONPATH=src python -m pytest tests/test_research_harness.py tests/test_pressure_workload.py -q -p no:cacheprovider
```

The [compact audit record](../../../research/agent_resume/engineering-audit-2026-10-05.json)
retains the reproduction/check outcomes without personal host paths. The passing
suite verifies current behavior, including the disputed ID assumption; it is not
acceptance of the proposed replacement contract.

## Implementation order and final verdict

Use [the task map](../../WORK_TRACKER.md): TG-002/TG-003 first, then TG-004/TG-006,
then TG-005/TG-007. A further live pilot and pressure comparison require their
own session authorization. The corrected local package must name what CPU can
prove and what still requires model execution.

`ARCHITECTURE_REVIEW: COMPLETED_FOR_STATED_SCOPE`

`HARNESS_CONTRACT_READY: NO`

`READY_FOR_NEW_GPU_PRESSURE_RUN: NO`

`RUNTIME_REDESIGN_DEMONSTRATED_NECESSARY: NO`

`NATURAL_OPPORTUNITIES_AND_ALL_CALLER_BENEFIT: NOT_EVALUATED`


## Follow-up after capacity stop: accounting and residual resources

A bounded local review reproduced dropped cancelled callers and an understated
block duration before final cleanup. The research harness now retains every
declared outcome, censors cancelled latency, rejects interrupted baselines and
includes client queue/owned finalization in the descriptive competing-caller gate.
The [checkpoint](../../../research/agent_resume/local-review-2026-10-05.json) binds
the exact changed sources, private evidence and the regenerated v2 packet.

Inside the existing image, without network/GPU: **125 tests + 77 subtests**,
zero failures/errors/skips, including 12 actual CPU FULL/file fixtures. Native
reference conformance and 12 scripted callers with 108 real CPU regression
executions passed. Mocked orchestration checks cover useful-gate failure, safe
reset failure and stopping after the first observed baseline has no candidate.
Process-sandbox test stalls are retained as diagnostics; normal local/container
runs passed. These are not live generation or performance results.

Read-only inventory found no forgotten ToolGap compute/disk/address resources.
The single needed validated image, small historical result bucket and narrow
service account are retained; unrelated workloads were untouched. No cloud
mutation occurred. The old provisioning readiness is superseded and disabled;
a revised frozen package still needs binding before another paid attempt. No
runtime redesign or production SDK change was needed. Historical reported
benchmarks and Mistral 0/3 remain unchanged.
