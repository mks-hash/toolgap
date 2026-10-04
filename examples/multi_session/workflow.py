"""Two-caller tool orchestration; polling is cleanup, never simulated tool work."""

import asyncio
import time


async def settle(lease, *, cancel=False, timeout=15):
    async def drain():
        state = await lease.cancel() if cancel else await lease.status()
        while state["cleanup_pending"] or state["state"] in {"RUNNING", "UNKNOWN"}:
            await asyncio.sleep(0.01)
            state = await lease.status()
        return state

    return await asyncio.wait_for(drain(), timeout)


async def trajectory(
    session, gate, tool, continuation, admission=None, *, abandon=False
):
    """Tool success preserves useful restore; abandonment cancels owned work.

    Submission never delays continuation. Exceptions cancel/reap the tool and
    reconcile any owned lease before propagating. No retries of generation.
    """
    await gate.wait()
    t0 = time.monotonic_ns()
    tool_task = asyncio.create_task(tool())
    submission = (
        asyncio.create_task(
            admission.submit(
                session["id"], session["prefix"], cache_salt=session["salt"]
            )
        )
        if admission is not None
        else None
    )
    lease = None
    try:
        result = await tool_task
        t3 = time.monotonic_ns()
        # Do not await control acceptance before sending ordinary continuation.
        response, timing = await continuation(result) if not abandon else (None, None)
        if submission:
            lease = await asyncio.shield(submission)
        state = await settle(lease, cancel=abandon) if lease else None
        if lease:
            # Only abandonment proves zero consumption. Hits alone are ambiguous.
            lease.finish(used_tokens=0 if abandon else None)
        return dict(
            session_id=session["id"],
            abandoned=abandon,
            tool_result=result,
            response=response,
            timing=timing,
            t0_tool_dispatched=t0,
            t3_tool_completed=t3,
            lease=state,
        )
    except BaseException:
        tool_task.cancel()
        await asyncio.gather(tool_task, return_exceptions=True)
        if submission:
            # Ordinary finite transport timeout is already bounded by the client.
            lease = await asyncio.shield(submission)
            await settle(lease, cancel=True)
        raise


async def pair(coroutines, gate):
    tasks = [asyncio.create_task(c) for c in coroutines]
    gate.set()
    try:
        return await asyncio.gather(*tasks)
    finally:
        # gather's first exception must not leave a sibling using a stopped server.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
