"""Private same-host scheduler mailbox; never a remotely exposed API."""

import asyncio
import json
import os
import time
import uuid
from pathlib import Path


DEFAULT_SAMPLING = dict(interval_ms=100, max_samples=8, timeout_ms=50)


def sampling_budget(config=None):
    value = dict(DEFAULT_SAMPLING if config is None else config)
    if set(value) != set(DEFAULT_SAMPLING) or any(
        type(v) is not int or v <= 0 for v in value.values()
    ):
        raise ValueError("Declare positive interval, sample count and timeout")
    if (
        value["max_samples"] > 32
        or value["timeout_ms"] > 1000
        or value["interval_ms"] > 1000
    ):
        raise ValueError("Observation budget exceeds bounded study scope")
    return value


class ToolWindowSamples:
    """Bounded background samples. Tools/continuations never await a sample."""

    def __init__(self, callback, ids, salt, step, *, config=None):
        self.config = sampling_budget(config)
        self.callback, self.ids, self.salt, self.step = callback, tuple(ids), salt, step
        self.boundary = asyncio.Event()
        self.step["cache_samples"] = []
        self.step["sampling_config"] = dict(self.config)
        self.task = asyncio.create_task(self._run())

    def continuation_boundary(self):
        self.boundary.set()

    async def _sample(self, phase):
        sample = dict(
            phase_requested=phase, requested_ns=time.monotonic_ns(), status="UNKNOWN"
        )
        self.step["cache_samples"].append(sample)
        try:
            state = await asyncio.wait_for(
                self.callback(list(self.ids), self.salt),
                self.config["timeout_ms"] / 1000,
            )
            if not isinstance(state, dict):
                raise ValueError("Observer returned no structured state")
            sample.update(status="OBSERVED", state=state)
        except asyncio.CancelledError:
            sample["reason"] = "CANCELLED_SAMPLE"
            raise
        except Exception as exc:
            sample["reason"] = type(exc).__name__
        finally:
            sample["returned_ns"] = time.monotonic_ns()
            sample["client_wait_ms"] = (
                sample["returned_ns"] - sample["requested_ns"]
            ) / 1e6

    async def _run(self):
        await self._sample("DISPATCH_REQUESTED")
        # Reserve one observation for the continuation boundary, if budget permits.
        for _ in range(max(0, self.config["max_samples"] - 2)):
            try:
                await asyncio.wait_for(
                    self.boundary.wait(), self.config["interval_ms"] / 1000
                )
                break
            except TimeoutError:
                await self._sample("TOOL_RUNNING_REQUESTED")
        if self.config["max_samples"] > 1:
            await self.boundary.wait()
            await self._sample("CONTINUATION_REQUESTED")

    async def finish(self):
        """Only after task completion; cancel/reap observations, not remote cache work."""
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        self.step["observer_cleanup_confirmed"] = self.task.done()
        self.step["observer_cleanup_scope"] = (
            "CLIENT_TASK_REAPED; LATE_MAILBOX_REPLY_POSSIBLE; NONCE_NOT_REUSED"
        )


def window_summary(step):
    """Observed file availability is a candidate, never proof of successful restore."""
    dispatch, arrival = step.get("dispatched_ns"), step.get("continuation_submitted_ns")
    completed = step.get("completed_ns")
    valid = []
    late = unknown = 0
    for sample in step.get("cache_samples", []):
        state = sample.get("state", {})
        start, end = (
            state.get("cache_read_started_ns"),
            state.get("observation_completed_ns"),
        )
        if (
            sample.get("status") != "OBSERVED"
            or state.get("clock_domain") != clock_domain()
            or not all(type(t) is int for t in (start, end, dispatch, arrival))
            or not start <= end
        ):
            unknown += 1
            continue
        if start < dispatch or end > arrival:
            late += 1
            continue
        available = state.get("storage_available_tokens")
        resident = state.get("resident_prefix_tokens")
        page_size = state.get("page_size")
        threshold = state.get("prefetch_threshold")
        length = len(step["prefix_ids"])
        if (
            state.get("storage_check") != "DIRECT_STAT_NO_BACKEND_CACHE"
            or type(page_size) is not int
            or page_size <= 0
            or type(threshold) is not int
            or threshold <= 0
            or any(
                type(v) is not int or not 0 <= v <= length or v % page_size
                for v in (available, resident, length)
            )
        ):
            unknown += 1
            continue
        count = max(0, available - resident)
        valid.append(
            dict(
                start_ns=start,
                end_ns=end,
                eligible_tokens=count,
                prefetch_threshold=threshold,
                admission_eligible=count >= threshold,
                eligible_span=[resident, available] if count else None,
                remaining_window_ms=(arrival - end) / 1e6,
                remaining_tool_ms=max(0, (completed - end) / 1e6)
                if type(completed) is int
                else None,
                observed_during_tool=type(completed) is int and end <= completed,
            )
        )
    valid.sort(key=lambda v: v["start_ns"])
    first = next((v for v in valid if v["admission_eligible"]), None)
    before = [
        v
        for v in valid
        if first is not None
        and v["end_ns"] < first["start_ns"]
        and not v["admission_eligible"]
    ]
    return dict(
        schema_version=1,
        dispatch_state="UNKNOWN",  # A background observation is not state exactly at dispatch.
        opportunity="OBSERVED_FILE_AVAILABLE"
        if first
        else "UNKNOWN"
        if unknown or not valid
        else "NOT_OBSERVED_AT_SAMPLES",
        samples=valid,
        late_samples=late,
        unknown_samples=unknown,
        transition_interval_ns=(
            [before[-1]["start_ns"], first["end_ns"]] if first and before else None
        ),
        first_eligible=first,
        first_eligible_during_tool=next(
            (v for v in valid if v["admission_eligible"] and v["observed_during_tool"]),
            None,
        ),
        consumed_restore_tokens=None,
        note="Sparse availability samples are interval-censored; NOT_OBSERVED does not mean no opportunity between samples.",
    )


def clock_domain():
    # Boot ID alone is insufficient when Linux time namespaces offset monotonic.
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    return boot + ":" + os.readlink("/proc/self/ns/time")


class FileObserver:
    def __init__(self, directory, *, include_storage=False, timeout=3, domain=None):
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise ValueError("Create a private shared observation directory first")
        self.include_storage = include_storage
        self.timeout = timeout
        self.domain = domain or clock_domain()

    async def snapshot(self, ids, salt):
        nonce = uuid.uuid4().hex
        request = self.directory / (nonce + ".request.json")
        response = self.directory / (nonce + ".response.json")
        temporary = self.directory / (nonce + ".request.tmp")
        started = time.monotonic_ns()
        try:
            temporary.write_text(
                json.dumps(
                    dict(
                        input_ids=ids,
                        cache_salt=salt,
                        include_storage=self.include_storage,
                        clock_domain=self.domain,
                    )
                )
            )
            temporary.replace(request)

            async def wait():
                while not response.exists():
                    await asyncio.sleep(
                        0.005
                    )  # measurement/control polling, not tool work
                result = json.loads(response.read_text())
                if result.get("clock_domain") != self.domain:
                    raise ValueError(
                        "Observer and client do not share a Linux boot clock"
                    )
                if "error" in result:
                    raise ValueError("Scheduler observation failed: " + result["error"])
                return result

            result = await asyncio.wait_for(wait(), self.timeout)
            result.update(
                client_observation_started_ns=started,
                client_observation_completed_ns=time.monotonic_ns(),
            )
            return result
        finally:
            for path in (temporary, request, response):
                path.unlink(missing_ok=True)
            # A cancelled request already being read may produce a late response.
            # Its unique nonce cannot be reused; clean orphan responses after the block.
