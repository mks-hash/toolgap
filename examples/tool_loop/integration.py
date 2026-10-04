"""Example orchestration policy, not a session/framework abstraction."""

import asyncio
import time
from dataclasses import dataclass

import httpx

from toolgap import PrefetchRejected


@dataclass
class ToolRun:
    result: object
    tool_dispatched_ns: int
    tool_completed_ns: int
    submission: object  # Task: do not wait for it before continuation arrival.


async def run_with_prefetch(
    tool,
    client,
    operation_id,
    prefix,
    *,
    cache_salt=None,
    enabled=True,
    cleanup_timeout=3,
    on_cleanup=None,
):
    """Success never cancels restore. Error/cancel attempts bounded owned cleanup.

    Admission/transport rejection falls back to ordinary generation. A client
    transport timeout may leave acceptance uncertain; TTL remains the backstop.
    Caller must await submission later (after continuation), before closing client.
    """

    async def submit():
        try:
            state = await client.submit(operation_id, prefix, cache_salt=cache_salt)
            return dict(
                accepted=state["state"] not in ("DECLINED", "FAILURE", "MISS"),
                state=state,
            )
        except (PrefetchRejected, httpx.HTTPError) as exc:
            return dict(accepted=False, error=type(exc).__name__ + ": " + str(exc))

    dispatched = time.monotonic_ns()
    tool_task = asyncio.create_task(tool())
    submission = asyncio.create_task(submit()) if enabled else None
    try:
        result = await tool_task
        return ToolRun(result, dispatched, time.monotonic_ns(), submission)
    except BaseException:
        tool_task.cancel()
        cleanup_result = dict(operation_id=operation_id, confirmed=False)

        async def cleanup():
            if submission is None:
                cleanup_result["confirmed"] = True
                return
            try:
                await asyncio.wait_for(asyncio.shield(submission), cleanup_timeout / 2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                cleanup_result["acceptance_uncertain"] = True
            try:
                state = await client.cancel(operation_id)
                while state.get("cleanup_pending"):
                    await asyncio.sleep(0.01)
                    state = await client.status(operation_id)
                cleanup_result.update(confirmed=True, state=state)
            except (PrefetchRejected, httpx.HTTPError) as exc:
                cleanup_result["error"] = type(exc).__name__ + ": " + str(exc)

        try:
            await asyncio.wait_for(cleanup(), cleanup_timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            cleanup_result["timeout"] = True
        finally:
            if submission and not submission.done():
                submission.cancel()
                try:
                    await submission
                except asyncio.CancelledError:
                    pass
            if on_cleanup:
                on_cleanup(cleanup_result)
        raise
