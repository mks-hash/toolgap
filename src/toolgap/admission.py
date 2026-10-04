"""Process-local admission over the existing one-restore SGLang contract."""

import asyncio
import uuid
from collections import Counter, OrderedDict
from itertools import islice


from .client import PrefetchRejected, _validate_prefix

_TERMINAL = {"SUCCESS", "CACHED", "MISS", "FAILURE", "CANCELLED", "EXPIRED", "DECLINED"}


class PrefetchLease:
    """An operation owned by one caller; session_id is only a telemetry label."""

    def __init__(self, owner, session_id, operation_id, tokens, salt):
        self._owner = owner
        self.session_id = session_id
        self._operation_id = operation_id
        self._tokens = tuple(tokens)
        self._salt = salt
        self._control_lock = asyncio.Lock()
        self._remote = False
        self._settled = False
        self._finished = False
        self._reconciliation_started = False
        self._state = dict(state="SUBMITTING", accepted=None, cleanup_pending=True)

    @property
    def operation_id(self):
        return self._operation_id

    @property
    def state(self):
        return dict(
            self._state, session_id=self.session_id, operation_id=self.operation_id
        )

    async def status(self):
        if self._remote and not self._settled:
            await self._owner._control(self, "status")
        return self.state

    async def cancel(self):
        # Even a published success remains ordinary shared cache, not a lease.
        if self._remote and not self._settled:
            await self._owner._control(self, "cancel")
        return self.state

    def finish(self, *, used_tokens=None):
        """Account once after cleanup. Usage must refer to THIS restored span.

        None means consumption is unknown. Zero explicitly marks an abandoned
        published restore; it does not evict shared L2 or count unread I/O bytes.
        """
        if self._finished:
            raise ValueError("Operation usage was already finalized")
        if not self._settled:
            raise ValueError("Observe a terminal outcome with cleanup complete first")
        restored = self._state.get("restored_tokens", 0)
        if used_tokens is not None and (
            type(used_tokens) is not int or not 0 <= used_tokens <= restored
        ):
            raise ValueError(
                "used_tokens must be within this operation's restored span"
            )
        self._finished = True
        self._owner._account(self, used_tokens)


class PrefetchAdmission:
    """Share ONE instance per worker in one orchestrator process/event loop.

    No queue, GPU movement, host reservation, or eviction. Background status
    reconciliation is opt-in and bounded per operation; default behavior is manual.
    The runtime still admits one restore; competing sessions fall back normally.
    An ambiguous transport/cancellation outcome retains the local slot until
    status/cancel confirms terminal cleanup. Other processes are still
    governed by server admission. This is not an authentication boundary.
    """

    def __init__(
        self,
        client,
        *,
        max_prefix_tokens=8192,
        history_size=32,
        reconcile_interval_ms=None,
        reconcile_max_checks=100,
        reconcile_timeout_ms=1000,
    ):
        if type(max_prefix_tokens) is not int or max_prefix_tokens < 1:
            raise ValueError("max_prefix_tokens must be a positive integer")
        if type(history_size) is not int or history_size < 1:
            raise ValueError("history_size must be a positive integer")
        for name, value in (
            ("reconcile_interval_ms", reconcile_interval_ms),
            ("reconcile_max_checks", reconcile_max_checks),
            ("reconcile_timeout_ms", reconcile_timeout_ms),
        ):
            if name == "reconcile_interval_ms" and value is None:
                continue
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.client = client
        self.max_prefix_tokens = max_prefix_tokens
        self.history_size = history_size
        self.reconcile_interval_ms = reconcile_interval_ms
        self.reconcile_max_checks = reconcile_max_checks
        self.reconcile_timeout_ms = reconcile_timeout_ms
        self._lock = asyncio.Lock()
        self._active = None
        self._records = OrderedDict()
        self._metrics = Counter()
        self._reconcile_task = None
        self._closed = False

    async def __aenter__(self):
        if self._closed:
            raise RuntimeError("Admission is closed")
        return self

    async def __aexit__(self, *exc):
        await self.aclose()

    async def aclose(self):
        """Stop/reap local polling; do not cancel or reclaim remote work.

        Close admission before its borrowed HTTP client. Existing leases remain
        available for explicit status/cancel while that client is still open.
        """
        self._closed = True
        task = self._reconcile_task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # A task cancelled before its first tick never enters its finally.
            if self._reconcile_task is task:
                self._reconcile_task = None

    def _start_reconciliation(self):
        if (
            self._closed
            or self.reconcile_interval_ms is None
            or self._active is None
            or self._active._reconciliation_started
            or self._reconcile_task is not None
        ):
            return
        self._active._reconciliation_started = True
        self._reconcile_task = asyncio.create_task(
            self._reconcile(self._active), name="toolgap-reconciliation"
        )

    async def _reconcile(self, lease):
        try:
            for _ in range(self.reconcile_max_checks):
                await asyncio.sleep(self.reconcile_interval_ms / 1000)
                if lease._settled:
                    return
                self._metrics["reconciliation_checks"] += 1
                try:
                    # Includes waiting for the lease's control lock. Cancellation
                    # during transport retains UNKNOWN through _control_locked.
                    await asyncio.wait_for(
                        lease.status(), self.reconcile_timeout_ms / 1000
                    )
                except asyncio.TimeoutError:
                    self._metrics["reconciliation_timeouts"] += 1
                if lease._settled:
                    return
            self._metrics["reconciliation_exhausted"] += 1
        finally:
            self._reconcile_task = None
            # A later caller may have acquired the slot during the last status
            # response. Only transfer polling to that new identity; never reset
            # an exhausted operation's budget or retry a rejected submission.
            if self._active is not lease:
                self._start_reconciliation()

    @property
    def metrics(self):
        return dict(
            self._metrics,
            active_slots=int(self._active is not None),
            retained_records=len(self._records),
        )

    @property
    def active(self):
        return self._active

    def _remember(self, lease):
        self._records[lease.operation_id] = lease
        while len(self._records) > self.history_size:
            key = next(
                k for k, value in self._records.items() if value is not self._active
            )
            self._records.pop(key)

    def _settle(self, lease):
        lease._settled = True
        if self._active is lease:
            self._active = None

    async def submit(self, session_id, input_ids, *, cache_salt=None, ttl_ms=10000):
        if self._closed:
            raise RuntimeError("Admission is closed")
        if not isinstance(session_id, str) or not 1 <= len(session_id) <= 128:
            raise ValueError("session_id must contain 1..128 characters")
        tokens = list(islice(input_ids, self.max_prefix_tokens + 1))
        _validate_prefix(tokens, cache_salt, ttl_ms)
        # IDs are never caller-selected, so late events cannot target new work.
        lease = PrefetchLease(self, session_id, uuid.uuid4().hex, tokens, cache_salt)
        async with self._lock:
            if self._closed:
                raise RuntimeError("Admission is closed")
            self._metrics["submissions"] += 1
            if len(tokens) > self.max_prefix_tokens:
                reason = "LOCAL_LIMIT"
            elif self._active is not None:
                reason = "LOCAL_BUSY"
            else:
                reason = None
            if reason:
                lease._state = dict(state=reason, accepted=False, cleanup_pending=False)
                self._settle(lease)
                self._metrics[reason.lower()] += 1
            else:
                self._active = lease
                lease._remote = True
            self._remember(lease)
        if not lease._settled:
            try:
                await self._control(
                    lease,
                    "submit",
                    input_ids=tokens,
                    cache_salt=cache_salt,
                    ttl_ms=ttl_ms,
                )
            finally:
                # Also reconcile an ambiguous/cancelled submit: active retains
                # the owned ID even when the caller did not receive its lease.
                self._start_reconciliation()
        return lease

    async def _control(self, lease, action, **kwargs):
        async with lease._control_lock:
            if not lease._settled:
                await self._control_locked(lease, action, **kwargs)

    async def _control_locked(self, lease, action, **kwargs):
        try:
            response = await getattr(self.client, action)(lease.operation_id, **kwargs)
            state = response["state"]
            if response.get("operation_id") != lease.operation_id:
                raise ValueError("Control reply belongs to another operation")
            if state not in _TERMINAL | {"RUNNING"}:
                raise ValueError("Unknown server outcome")
            if type(response.get("cleanup_pending")) is not bool:
                raise ValueError("Missing cleanup confirmation")
            restored = response.get("restored_tokens")
            restored_bytes = response.get("restored_bytes")
            if (
                type(restored) is not int
                or not 0 <= restored <= len(lease._tokens)
                or type(restored_bytes) is not int
                or restored_bytes < 0
            ):
                raise ValueError("Invalid published-span accounting")
            lease._state = dict(
                response, accepted=state not in {"DECLINED", "FAILURE", "MISS"}
            )
            if state in _TERMINAL and not response["cleanup_pending"]:
                self._settle(lease)
        except PrefetchRejected as exc:
            # Only a rejected SUBMIT proves no operation was admitted. An unknown
            # status/cancel can race a late submit and must not free our slot.
            if action == "submit":
                lease._state = dict(
                    state="DECLINED",
                    accepted=False,
                    cleanup_pending=False,
                    error=str(exc),
                )
                self._metrics["server_rejected"] += 1
                self._settle(lease)
            else:
                self._uncertain(lease, exc)
        except Exception as exc:
            # An unexpected transport/protocol error cannot prove no remote I/O.
            self._uncertain(lease, exc)
        except asyncio.CancelledError:
            self._uncertain(lease, "Caller cancelled control transport")
            raise

    def _uncertain(self, lease, error):
        lease._state = dict(
            lease._state,
            state="UNKNOWN",
            accepted=None,
            cleanup_pending=True,
            error=str(error),
        )
        self._metrics["uncertain_control_events"] += 1

    def _account(self, lease, used_tokens):
        restored = lease._state.get("restored_tokens", 0)
        restored_bytes = lease._state.get("restored_bytes", 0)
        self._metrics["finalized_operations"] += 1
        self._metrics["published_tokens"] += restored
        self._metrics["published_bytes"] += restored_bytes
        if used_tokens is None:
            self._metrics["usage_unknown_operations"] += 1
            self._metrics["usage_unknown_tokens"] += restored
            self._metrics["usage_unknown_bytes"] += restored_bytes
        else:
            self._metrics["caller_reported_used_tokens"] += used_tokens
            self._metrics["unused_published_tokens"] += restored - used_tokens
            # Server pages are uniform-sized in the scoped resident FULL cache.
            if restored:
                used_bytes = restored_bytes * used_tokens // restored
                self._metrics["caller_reported_used_bytes"] += used_bytes
                self._metrics["unused_published_bytes"] += restored_bytes - used_bytes
