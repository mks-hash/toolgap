# Opt-in bounded status reconciliation (development)

This increment is on `feat/bounded-reconciliation`, after the published v0.3.0
release. It changes the Python admission coordinator only. It does not change
the SGLang patches, the CLI's one-RPC contract or existing measured results.

## Purpose and evidence

The recorded [v0.3 two-caller smoke](MULTI_SESSION_GPU_SMOKE.md) published the
admitted prefix about 359 ms after submit, but the first client status request
was about 1815 ms after submit. The demo queried status after the full
continuation response. The local slot therefore remained occupied after the
restore had finished on the server.

Opt-in reconciliation lets **later arrivals** use that local slot once status
confirms terminal cleanup, even if the earlier owner's tool or continuation is
still running. It cannot reverse a `LOCAL_BUSY` decision made by a simultaneous
caller. The recorded pair-level result was not improved by admission; these new
CPU tests do not establish a new latency or throughput improvement.

## API

```python
from toolgap import PrefetchAdmission, PrefetchClient

async with PrefetchClient(server_url, headers=admin_headers) as client:
    async with PrefetchAdmission(
        client,
        reconcile_interval_ms=100,   # None (default): manual status only
        reconcile_max_checks=100,    # attempts per admitted operation
        reconcile_timeout_ms=500,   # lock wait + status RPC per attempt
    ) as admission:
        # Share this admission instance across callers of one worker.
        # Start submit concurrently with useful tool work as in the demo.
        lease = await admission.submit(
            "agent-A", exact_saved_ids, cache_salt=original_salt, ttl_ms=10000
        )
        # Tool work and ordinary generation never await background polling.
        # On tool failure/cancellation: explicitly cancel the owned lease.
        # On success: do not cancel useful restore or evict published L2.
        # After attributable consumption and confirmed cleanup:
        # lease.finish(used_tokens=N), or lease.finish() for unknown usage.
```

The three reconciliation options accept positive integer milliseconds/counts;
only `reconcile_interval_ms` also accepts `None`. Defaults are `None`, 100 checks,
and 1000 ms per check. Explicitly close admission before closing its borrowed
HTTP client, either with the nested context managers above or `await
admission.aclose()`. Closing admission rejects new submissions, stops and awaits
its poller, but does not close the borrowed client.

There is at most one poller per coordinator. It waits the interval before each
attempt, then calls the existing owned `lease.status()` under the same lock as
explicit status/cancel. A new operation receives its own bounded budget. The
budget includes attempts that time out while waiting for that lock. With the
example above, 100 intervals plus 100 timed attempts allow roughly 60 seconds of
polling in the worst case, assuming cooperative async transport cancellation.
Ordinary successful replies typically finish much earlier. No submit is retried,
and a rejected/busy caller is not queued or resubmitted.

## Safety and uncertainty

Only a reply for the owned operation ID with a recognized terminal state and
`cleanup_pending=false` releases local admission. `RUNNING`, a terminal state
with pending cleanup, an unknown ID, malformed/foreign replies, and transport
errors retain the slot. A timed-out or interrupted in-flight status becomes
`UNKNOWN`; waiting for the lock without sending HTTP does not change remote
state. The existing accounting validation is also applied to poller replies.

After the budget is exhausted, polling stops **without** freeing the slot. The
owner can still reconcile with `lease.status()` or `lease.cancel()`. Busy callers
do not restart the exhausted budget. Cancelled submit transport retains the
owned ID at `admission.active`; opt-in polling can observe its late outcome.

`aclose()` stops observation only. It neither cancels the remote operation nor
proves physical cleanup. The active lease remains accessible for explicit
status/cancel while the HTTP client is still open. This also applies if close
races an in-flight submit. Do not discard that ownership record when uncertain.
No timeout or local TTL reclaims backend read destinations, and permanently
blocked backend I/O remains outside the guarantee.

Terminal leases return historical snapshots without further HTTP. An old
lease/poller cannot release or cancel a new operation. Published L2 stays
ordinary shared, evictable cache; reconciliation does not reserve memory, pin
the prefix, count consumption, or call `finish()` for the owner.

## Diagnostics and verification

- `reconciliation_checks`: background attempts, including lock waits.
- `reconciliation_timeouts`: attempts that hit the local timeout.
- `reconciliation_exhausted`: operations still unsettled at the attempt limit.
- Existing `uncertain_control_events`, `active_slots` and usage counters retain
  their meanings. There is no automatic zero-waste or full-consumption claim.

Run `bash scripts/test_client.sh` for transport, ownership, later-arrival and
shutdown tests. With the pinned patched SGLang checkout, run
`SGLANG_CHECKOUT=/path/to/sglang bash scripts/test_admission_cache.sh` for real
file I/O, host allocation and cancelled-read terminal drain on CPU.

See [local validation](RECONCILIATION_VALIDATION.md). No new GPU result is claimed.
