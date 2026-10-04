# ToolGap: admission design after v0.3

Development increment on top of `5dbcd2b` (bounded reconciliation). Published
releases, runtime patches and recorded GPU results keep their original
provenance. This implementation changes the local Python coordinator.

## Concept and evidence

ToolGap restores an exact prefix from file-backed L3 into resident L2 during
useful tool work. H2D and generation remain ordinary inference. Value depends on
prefix residency, remaining tool time and exposed restoration latency.

The [v0.2 real tool-loop evaluation](TOOL_LOOP_VALIDATION.md) observed L3-only
median continuation TTFT of 512 → 134 ms, while GPU-resident control was
128 → 127 ms (three runs per condition). That supports conditional value, rather
than prefetching every tool call.

In the [v0.3 two-caller smoke](MULTI_SESSION_GPU_SMOKE.md), one caller benefited
but the pair's maximum dispatch-to-first-token did not improve (+2.0%, one
repetition). One proactive slot cannot eliminate ordinary restore contention.
An abandoned successful restore left 96.25 MiB of unused published L2: ordinary
evictable cache, not a leak or a measured cancelled-I/O cost.

Publication occurred ~359 ms after submit, but the first client status request
was ~1815 ms after submit. Bounded reconciliation closes this local observation
gap for **later arrivals**. It does not reverse an earlier rejection, create
another runtime slot, guarantee residency or establish fairness.

## Engineering decisions

Keep eligibility, scarcity and ownership separate:

1. Caller hints can decline apparently unhelpful work before any control RPC.
2. One local slot remains immediate admission or fallback, without a queue/retry.
3. Terminal outcome **and** confirmed cleanup release that slot. Estimates,
   cancellation and local TTL never replace physical cleanup proof.

Add an immutable `PrefetchHint`, an optional minimum overlap, and local decision
and reservation telemetry. Caller hints avoid a new runtime cache-probe interface
or an estimator trained on a few single-model samples. Hints may be wrong or
stale; declining a useful prefetch still leaves normal inference available.

```text
estimated_hidden_ms = min(expected remaining tool time, estimated restore time)
```

This is a screening estimate, **not expected net speedup**. It omits control
overhead, queueing, contention, eviction, failures and cancellation probability.
The threshold is caller policy, not optimized or validated by our GPU benchmark.
A short tool can still benefit; the caller chooses how little overlap to pursue.

## API

```python
from toolgap import PrefetchAdmission, PrefetchClient, PrefetchHint

async with PrefetchClient(url, headers=admin_headers) as client:
    async with PrefetchAdmission(
        client,
        min_overlap_ms=100,          # illustrative, not empirically optimal
        reconcile_interval_ms=100,
        reconcile_max_checks=100,
        reconcile_timeout_ms=500,
    ) as admission:
        lease = await admission.submit(
            "agent-A", exact_saved_ids, cache_salt=original_salt,
            hint=PrefetchHint(
                cache_residency="l3_only",
                expected_tool_ms=600,      # remaining work from submission
                estimated_restore_ms=350,  # comparable exposed L3→L2 path
            ),
        )
        print(lease.decision)  # estimates and local reason
        print(lease.timing)    # local reservation/release, not I/O duration
        # Dispatch submit concurrently with useful tool work. Continuation
        # proceeds even when restore is locally declined or server-rejected.
```

`PrefetchHint` takes residency `unknown`, `l3_only` or `resident` and optional
nonnegative integer millisecond estimates. `resident` means the **entire exact
reusable prefix** is believed available in GPU or host L2, not a partial hit.
The hint neither establishes nor alters model/backend compatibility, token IDs
or salt; existing exact-prefix guards remain necessary.

After input validation, decisions have this precedence:

| Condition | Local outcome | Worker HTTP |
|---|---|---|
| Prefix exceeds token limit | `LOCAL_LIMIT` | none |
| Explicit `resident` hint | `LOCAL_RESIDENT` | none |
| Both estimates known; overlap below configured minimum | `LOCAL_LOW_OVERLAP` | none |
| Another operation owns the slot | `LOCAL_BUSY` | none |
| Otherwise | `ELIGIBLE` decision; server outcome authoritative | submit |

Known-resident screening is activated by supplying that hint. The overlap
threshold defaults to `None` (disabled). Missing estimates bypass the overlap
filter; values are not invented. Residency hints do not prove L3 availability.
The server may still return CACHED, MISS, DECLINED or another result. `ELIGIBLE`
is not proof of successful server admission.

Declining another caller never releases an existing UNKNOWN/pending owner.
The optional `prefetch_hint` key in the trajectory example forwards a
`PrefetchHint`. Tools and ordinary continuations still run after local rejection;
failed tools cancel only their owned operation. Successful publication remains
shared evictable cache, not a pin or lease on physical L2.

## Observability

`lease.decision` copies its local reason, hints and `estimated_hidden_ms`. These
stay separate from server-reported `lease.state`.

`lease.timing` returns local monotonic `slot_reserved_ns`, `slot_released_ns` and
`slot_hold_ms`. The duration increases while cleanup is uncertain and freezes at
confirmed local release. Locally declined work has no reservation. Transport
and delayed observation are included; these times cannot locate publication or
prove physical host occupancy.

Metrics add `active_slot_age_ms`, `slot_releases`, `released_slot_hold_ms`,
`local_resident` and `local_low_overlap`. Release totals count each remotely
attempted reservation once, including server-rejected submits; historical status
does not count another release. `finish()` still separately accounts unknown or
attributable usage. Hints never imply consumption.

Run the offline control fixture with explicit synthetic completion events:

```bash
python examples/admission/local_check.py --output work/admission-policy/local-check.json
```

It records decisions, RPC counts and local timings. It has **no** real storage,
GPU, model, useful tool workload or performance claim. Real file I/O/allocator
safety is checked separately in CPU fixtures.

## Alternatives and limits

- A deferred/priority queue needs deadline, ordering and waiter-cancellation
  semantics. Without a measured contention win, immediate fallback stays clearer.
- Remote residency probes add control traffic and still race eviction. Explicit
  caller hints preserve a small API; unknown hints retain the existing path.
- A local byte budget cannot reserve shared L2 against normal inference. The
  current token and single-slot limits remain honest local bounds.
- Automatic estimates need measurements stratified by prefix size, storage
  conditions and concurrent load. The published samples do not supply that model.
- Cancellation cannot reclaim a blocked read, undo completed I/O, or safely evict
  shared KV. Unknown usage cannot be reported as zero waste.

No multi-process/global admission guarantee, distributed coordination, new
backend, GPU prefetch, SWA or runtime scheduler change is introduced.

## Next measurement

This focused policy comparison is one part of the broader
[cross-family agent-resume research plan](RESEARCH_PLAN.md). That milestone
includes useful multi-round tools and workload-driven cache pressure; policy
microbenchmarks alone do not establish application value.

A future focused GPU comparison should vary **later caller arrival** relative
to measured restoration: manual admission, reconciliation alone, then
reconciliation plus hints. Keep verified L3-only prefixes, model, generation and
useful tool work identical. Add short-tool/resident controls and stale/wrong
estimates; randomize treatment order and repeat each condition.

Measure local slot hold/release, status RPC count/duration, server publication,
continuation arrival/TTFT, dispatch-to-first-token, duplicate prefix reads, host
occupancy/evictions and attributable unused publication. Evaluate all callers
and aggregate latency, not just the admitted winner. GPU execution needs separate
approval. [Local validation](ADMISSION_POLICY_VALIDATION.md) is complete.
