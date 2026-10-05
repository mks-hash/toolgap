# ADR-0001: model adapter, agent runner, and exact-prefix cache contracts

Date: 2026-10-05.
Status: **accepted; TG-002 through TG-004 implemented and locally checked.
Deployment identity guards (TG-005) and live validation remain pending.**

## Context and evidence

The current research adapter treats family-specific raw formatting and required
history metadata as one contract. It requires a Mistral model-generated ID and
returns either a `ToolCall`, `None`, or an exception. CPU fixtures generate the
same required IDs. The live pilot failed; a local code audit also confirmed that
tool execution occurs before the adapter checks continuation compatibility.
See [review F-01/F-02/F-03](../archive/evidence/ENGINEERING_REVIEW_2026-10-05.md).

ToolGap's runtime consumes exact token IDs and salt. It needs no knowledge of
model-produced JSON, tool names, or conversation message schemas. Native model
formats differ, so adapters are necessary; a universal raw parser is not a
credible contract. An adapter is registered for a pinned format/profile, not for
every model ever sharing a family name.

## Decision

Keep three boundaries:

1. **Model adapter:** native prompt rendering, response classification, supported
   tool-call shapes, turn completion, tool-result suffix serialization, and
   append compatibility for a pinned tokenizer/template. It must declare which
   forms it supports and fail explicitly for other forms.
2. **Agent runner:** schema validation, tool execution, correlation and bounded
   tool rounds, correctness grading, cancellation and accounting. It operates
   on normalized response outcomes, not family names or repaired raw text.
3. **Cache control:** exact reusable token IDs, salt, operation ID, status/cancel
   and physical-cleanup ownership. The existing runtime primitive remains
   independent of model formatting.

The proposed response interface distinguishes `ToolCalls`, `FinalAnswer`,
`InvalidOutput` and `UnsupportedOutput`. A single-call runner may explicitly
reject multiple calls; it must not silently select one. Use a small typed
protocol/data records, not a new framework or a dependency-heavy orchestration
layer. Exact class/function names will be finalized in TG-002.

Keep identities separate:

- `model_call_id`: optional raw provider/model metadata, retained unchanged.
- `tool_execution_id`: runner-owned identity for an executed call and result.
- `prefetch_operation_id`: the existing unique cache-control operation identity.

If a provider requires a history ID absent from raw output, host assignment is
permitted only when its pinned format supports a valid append without changing
saved token IDs. Otherwise mark the profile unsupported for exact-prefix
continuation. An ID requirement in an API/history is not automatically a
requirement on the raw generation. Missing and malformed IDs are different
cases and need separate conformance fixtures.

### Exact-token and effect invariants

Let `S` be actual input IDs plus actual generated IDs, including observed turn
markers. Continuation construction may append a validated suffix. It cannot
decode/re-encode, reorder, trim or inject bytes into `S` to repair a call. The
result's leading `len(S)` IDs must equal `S` exactly. Any altered initial system
formatting happens before first inference and is declared in the profile.

Before dispatching tools or prefetch, validate response disposition, declared
tool arguments, and static/history continuation capability. Tool output does not
exist yet: validate its actual serialization and context budget after execution.
The pre-dispatch check cannot guarantee arbitrary future output fits. If the
post-result check fails, retain executed-tool evidence and cancel only owned
prefetch. Never report a tool as executed merely because a model asserted it.

Successful tool execution does not require waiting for prefetch submission or
completion. Restore failure/rejection preserves ordinary generation fallback.
Cancelled/ambiguous control retains physical ownership until cleanup is confirmed.

## Alternatives rejected

- Add per-model missing-ID exceptions to the shared runner: this spreads format
  assumptions into execution and measurement.
- Require every model to emit one synthetic common JSON schema: this changes
  native inference/task behavior. A constrained-output treatment may be evaluated
  separately with identical settings across comparisons, but is not silently
  substituted for the current native workflow.
- Re-render the full conversation with inserted IDs: this can invalidate the
  exact KV prefix and hides a change in the measured continuation.
- Accept the first JSON object and ignore trailing content: this conceals
  unsupported/malformed whole responses and alleged tool execution.
- Build a generic multi-agent framework: unnecessary for the stated workload.

## Consequences and acceptance

Adapters still encode provider differences, but every adapter satisfies the
same runner/token invariants. Reference conformance is different from a model's
ability to use tools. A profile can pass CPU conformance and fail live behavior.
The current Mistral profile has not been repaired by accepting this ADR.

### Native implementations and profile identity

Reuse the pinned official tokenizer/template and assess the pinned serving
engine's parser before writing another syntax implementation. Pin the chosen
reference and state supported forms. Parser output alone is not acceptance:
some upstream detectors accept multiple calls, extract partial regions or return
normal text alongside calls. Our runner must classify the complete response,
retain unconsumed text and finish metadata, and reject unsupported workflows
before effects. A semantic parser does not prove append-only token compatibility.
Do not silently switch HF and native tokenizer stacks: compare their actual
IDs and declare any different stack as a different profile.

The profile records model/weight revision and available artifact identity,
tokenizer files, template hash/options, parser version, dtype/quantization and
resolved cache layout/parallelism. Record capability separately from measured
live behavior. Bind immutable executed-turn records to this profile and retain
actual input/generated IDs, raw output and finish reason. Weight identity is
not interchangeable with a served-model alias; declared revision and verified
artifact hashes are distinct evidence.

For this fixed-model experiment, isolate persistent file storage by profile
fingerprint and reject incompatible profile/config reuse. Existing cache salt
and operation IDs retain their roles. These are harness/deployment guards, not
a change to the runtime cache-key format or a claim to support weight hot updates.
Differential fixtures must name an independent native/reference implementation
and any disagreement; comparing two helpers built on the same assumptions is
not external conformance.

TG-002/TG-003 must include externally grounded complete-call fixtures, no-ID
cases, mixed/multiple/truncated output, finish reasons, exact-token multi-round
checks and explicit unsupported forms. TG-004 must demonstrate zero tool/control
effects on pre-dispatch contract failures. Existing cancellation/ownership
regressions must remain passing. No runtime redesign is justified by this ADR.

### Local implementation checkpoint (2026-10-05)

[Contracts](../../research/agent_resume/contracts.py),
[adapter](../../research/agent_resume/adapters.py) and
[runner](../../research/agent_resume/runner.py) implement the response/effect
boundaries above. `prepare_continuation` is pure; its plan appends the actual
result after execution and checks the context budget. `parse` remains a
format-only compatibility helper for CPU fixtures, not the runner's acceptance
gate. Model ID, runner execution ID and prefetch operation ID are separate.

The pinned runtime's Mistral/Qwen detectors were assessed as syntax references,
not substituted as whole-response acceptance: they expose normal text and/or
extract calls permissively. The harness keeps its declared narrow protocol
subset without depending on the serving engine's full import stack. Native
rendering remains owned by the pinned official HF templates. The independent
Mistral serializer check pins `mistral_common` 1.12.0 and its method hash; it does
not replace the experiment's HF tokenizer with a different protocol stack.

Mistral no-ID calls are no longer classified as malformed solely for missing ID.
The pinned HF template serializes IDs into assistant history, so an unverified
host-assigned ID is not inserted into saved raw output: the pre-dispatch result
is explicitly unsupported. This closes the hidden-assumption/effect-ordering
defects, not the failed model's live task capability. See
[local evidence](../../research/agent_resume/contract-validation.json).
