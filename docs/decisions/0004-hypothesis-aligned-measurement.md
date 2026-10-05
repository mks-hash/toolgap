# ADR-0004: bind the study to actual continuations and the pressure workload

Date: 2026-10-05. Status: accepted; local implementation.

## Context

The original capability is exact-prefix file L3 → resident host L2 restore
during useful tool execution, followed by ordinary matching/H2D/generation.
Historical controlled v0.1/v0.2 GPU evidence supports that capability at its
published pins. It does not establish natural opportunity prevalence or
aggregate benefit for competing agents.

The local audit found three measurement errors or gaps:

- `live_result` coupled exact token preservation to final answer quality and
  could pass the prefix check without any continuation. Missing IDs could crash
  classification. The Qwen7 pilot's 0/3 useful-task result remains unchanged;
  it is not evidence of a failed exact-prefix contract.
- A failed later step finalized all its earlier restores with `used_tokens=0`.
  An earlier continuation might already have used them. Cancellation/cleanup
  and operation-specific consumption are different facts.
- The useful-live gate ran three small diagnostic tasks with four tool rounds;
  pressure ran different source-audit tasks, long tokenized contexts and six
  rounds. Profile equality did not bind those workloads. Physical trace reports
  attributed proactive reads but omitted request-time reads and actual
  continuation tier counters.

## Decision

Keep the runtime primitive, strict response parser, grading and SDK unchanged.
Do not introduce a model-specific repair or new admission policy.

1. Classify exact continuation independently using actual prior input/generated
   IDs. No observed transition is `NOT_RUN`; malformed/changed IDs fail. Useful
   task quality and cleanup remain mandatory for study success.
2. Cancel only owned work on failure, drain/retain ownership as before, and
   finalize operation consumption as unknown without operation-specific proof.
   A whole-task failure cannot prove zero use of an earlier published restore.
3. Measurement contract v3 freezes the existing pressure limit of six tool
   rounds. `live --packet` executes the first declared representative of each
   task type in that exact packet, using its context, initial IDs and salt.
   Pressure accepts only current packet-bound live evidence. The four-round
   legacy diagnostic is still available but cannot authorize pressure. This
   supersedes ADR-0003's implicit treatment of the diagnostic limit as a shared
   study limit; neither limit is increased.
4. Correlate proactive publication, ordinary continuation reads and H2D enqueue
   attempts by actual request ID. Retain dispatch, control submission,
   publication, tool completion, continuation submission and first-token times;
   report physical I/O/tool interval intersections separately from TTFT.
   Retain server-reported disjoint device/host/storage counters for the whole
   continuation prompt, validating totals against its actual input. Missing
   metadata is unknown, not zero. These counters do not identify which specific
   proactive operation supplied consumed KV. H2D enqueue is not GPU completion.

The same research instrumentation belongs in both arms and needs live overhead
calibration. Repeated reads can be valid after eviction; publication alone does
not prove usage or absence of waste. Historical raw data and published results
are not overwritten with the new schema.

## Applicability and alternatives

At the pinned runtime, `CACHED` is an immediate terminal outcome; it does not
watch subsequent eviction. A submit once at tool dispatch therefore cannot
guarantee capture of opportunities arising later. Retain the fixed trigger and
measure dispatch-reachable versus later windows before proposing another
trigger. A no-opportunity result is useful evidence, not permission to force
eviction inside the pressure study.

Reject alternatives that loosen grading, synthesize tool/model success, count
publication as consumption, or switch models/backend/precision to get a green
result. Do not add a polling framework, storage abstraction, multi-worker
support or speculative trajectory prediction to solve measurement gaps.

## Verification and outstanding evidence

Local tests exercise independent dimensions, absent/malformed/changed IDs,
unknown usage after a late failure, packet/context/salt/budget mismatches,
request-ID isolation, invalid/missing tier counters, overlap clipping and
enqueue forwarding/error propagation. The actual CPU FULL/file fixture checks
real storage I/O attribution; a stub checks H2D enqueue instrumentation only.
Existing runtime tests cover requestless publication, early continuation,
TTL, cancellation, late ACK/replacement and finite I/O failures.

Full-image results are recorded in the existing
[local review](../../research/agent_resume/local-review-2026-10-05.json) and
[tracker](../WORK_TRACKER.md) after verification. Natural windows, useful live
quality for this new packet, calibration, operation-specific consumption and
whole-worker benefit remain unvalidated. No GPU run is authorized by this ADR.
