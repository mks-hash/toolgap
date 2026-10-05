# v0.3: bounded admission across callers

This is an **experimental process-local coordinator**, included in v0.3.0.
The [two-caller GPU smoke](../archive/evidence/MULTI_SESSION_GPU_SMOKE.md) passed; broader load and
statistical performance evaluation remain unvalidated.
It uses the pinned v0.2 SGLang runtime and does not change the published benchmark,
runtime patches, storage format, scheduler, upstream PRs, or report.

## Scope and behavior

Share one `PrefetchAdmission` per worker in one orchestrator process/event loop.
Several agents can run tools and submit ordinary continuation requests. The
runtime still allows **one proactive restore at a time**. Another caller gets
`LOCAL_BUSY` immediately and falls back to normal generation, without a second
control submit, local queue, automatic retry, or waiting behind another tool.
This does not establish parallel inference performance or fairness.

`session_id` is a telemetry label, not a server session abstraction or cache key.
The caller supplies the actual saved token IDs and the original `cache_salt`.
The coordinator never derives salt from the label or retokenizes a prefix.
A unique operation ID is generated for each attempt, even when labels repeat.
The lease operation ID is read-only; control messages use that owned identity.
Same prefix and salt may intentionally share ordinary cache; separate salts
remain separate namespaces. This is ownership isolation, not authentication.

Local policy bounds each submitted prefix to 8192 tokens by default and retains
32 recent records, protecting the active record from eviction. Oversized inputs
are read only through the limit plus one token and return `LOCAL_LIMIT` without
HTTP. This bounds local admission; it is **not a host-memory reservation**, global
admission across orchestrator processes, or an L2 occupancy/eviction policy.
The existing server admission is authoritative across other clients.

Post-v0.3.0 development offers optional caller hints for known-resident prefixes
and estimated tool/restore overlap. [Design and API](../decisions/admission-policy.md) describe
`PrefetchHint`, local fallback decisions and reservation telemetry. Without hints
and a configured threshold, existing behavior is retained.

## Lifecycle and uncertainty

- `RUNNING`: retain the one local slot.
- Terminal outcome with `cleanup_pending=false`: release that slot. Published
  L2 remains ordinary shared, evictable cache; a lease does not pin it.
- Cancellation with pending cleanup: retain the slot until status confirms the
  physical terminal drain. Logical cancellation does not free read destinations.
- Submit timeout, cancelled transport, malformed/foreign reply, or unknown
  status/cancel: `UNKNOWN`, `accepted=null`; retain the slot. TTL is a server
  usefulness deadline, not a local reclamation timer.
- Explicit server rejection of a new submit: `DECLINED`; release local admission
  and fall back. A transport failure is not treated as such a rejection.

After terminal cleanup, `lease.status()` returns its historical snapshot without
a new server call; host availability in that snapshot is not live occupancy.

By default there is no background poller. The owner calls `lease.status()` or
`lease.cancel()` to reconcile unknown work. The post-v0.3.0 development branch
also offers [opt-in bounded status reconciliation](RECONCILIATION.md), which
releases local admission after confirmed cleanup independently of the owner's
tool/continuation completion. Calls for one lease are serialized so a late RUNNING
status cannot overwrite a confirmed cancellation. A permanently blocked backend
still has no safe automatic reclamation guarantee.

## Usage

```python
from toolgap import PrefetchAdmission, PrefetchClient

async with PrefetchClient(server_url, headers=admin_headers) as client:
    admission = PrefetchAdmission(client, max_prefix_tokens=8192)
    # Keep this instance shared by both agents; do not instantiate per tool.
    lease = await admission.submit("agent-A", exact_saved_ids,
                                   cache_salt=original_salt, ttl_ms=10000)
    # Dispatch submit concurrently with useful tool work in the orchestrator.
    # LOCAL_BUSY / LOCAL_LIMIT / DECLINED: ordinary continuation still proceeds.
    # Successful tool exit must not cancel useful pending restoration.
    # Tool failure/cancellation: cancel only this lease, then reconcile cleanup.
    state = await lease.status()
    if state["state"] != "RUNNING" and not state["cleanup_pending"]:
        # Default: consumption is unknown, not assumed to be zero or fully used.
        lease.finish()
    print(admission.metrics)
```

The example intentionally supplies exact IDs externally. It does not capture
model state, launch inference, or promise that historical publication is still
resident at continuation time. If submission is cancelled before returning a
lease, `admission.active` retains the pending owner; reconcile it before another
prefetch. Closing the HTTP client is not proof of server cleanup.

## What the counters mean

`finish(used_tokens=N)` accepts a **caller-reported count of tokens consumed from
this operation's published span**, bounded by `restored_tokens`. A generic host
hit can include previously cached/shared KV and must not be passed unadjusted.
Without attributable trace evidence, use `finish()` and report unknown usage.

- `published_tokens/bytes`: terminal server-reported restored span, counted once
  when finalized. Already-cached work publishes no new span.
- `caller_reported_used_tokens/bytes`: explicit attributed usage supplied by caller.
- `unused_published_tokens/bytes`: published span minus that explicit usage.
- `usage_unknown_operations/tokens/bytes`: finalized work with unknown consumption.
- `local_busy`, `local_limit`, `server_rejected`, `uncertain_control_events`:
  admission and control diagnostics. The last counter counts events, not leases.

`finish(used_tokens=0)` explicitly records an abandoned published restore. It
neither evicts L2 nor measures partial/cancelled backend I/O. These counters do
not claim duplicate reads, actual device/host hits, L2 eviction, or GPU latency;
those require runtime trace evidence such as the recorded two-caller GPU smoke.

## CPU verification

[Recorded local result: 70 passed / 1 tokenizer skip](../archive/evidence/MULTI_SESSION_VALIDATION.md).

Transport/admission races plus the existing client/tool tests:

```bash
bash scripts/test_client.sh
```

Real file backend, host allocator, controller and terminal drain fixtures, using
the pinned patched SGLang checkout and its compatible Python dependencies:

```bash
SGLANG_CHECKOUT=/absolute/path/to/pinned/sglang bash scripts/test_admission_cache.sh
```

No GPU or model download is performed. The native CPU hash extension may compile
on first use. Fixtures verify unrelated continuation eligibility, salt isolation,
cancellation while a read holds host slots, baseline accounting after drain,
next restore usability, and abandonment accounting. They do not run model
forward/H2D or measure simultaneous-agent TTFT.

The recorded two-caller smoke establishes correctness and fallback for one
repetition. It does not establish a pair-level speedup or validate 5–20 callers.
Larger-load and statistical performance evaluation remain future work.

The [two-trajectory demo harness](MULTI_SESSION_DEMO.md) covers baseline,
shared-admission and owned-abandonment treatments. Its
[one-repeat real-GPU smoke](../archive/evidence/MULTI_SESSION_GPU_SMOKE.md) has now completed.
