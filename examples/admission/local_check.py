"""Offline control fixture, not a storage/model/tool performance benchmark."""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402

from toolgap import PrefetchAdmission, PrefetchClient, PrefetchHint  # noqa: E402


async def later_arrival(reconcile):
    completed, requests, observed = set(), [], asyncio.Event()

    async def handler(request):
        p = json.loads(request.content)
        requests.append(p)
        terminal = p["operation_id"] in completed
        if p["action"] == "status" and terminal:
            observed.set()
        return httpx.Response(
            200,
            json=dict(
                success=True,
                result=dict(
                    operation_id=p["operation_id"],
                    state="SUCCESS" if terminal else "RUNNING",
                    cleanup_pending=False,
                    restored_tokens=0,
                    restored_bytes=0,
                ),
            ),
        )

    async with PrefetchClient(
        "http://offline-fixture", transport=httpx.MockTransport(handler)
    ) as client:
        async with PrefetchAdmission(
            client, reconcile_interval_ms=1 if reconcile else None
        ) as admission:
            a = await admission.submit("owner", [1, 2], cache_salt="owner")
            early = await admission.submit("early", [3], cache_salt="early")
            assert early.state["state"] == "LOCAL_BUSY"
            early.finish(used_tokens=0)
            # Complete the simulated remote operation while owner remains busy.
            completed.add(a.operation_id)
            if reconcile:
                await asyncio.wait_for(observed.wait(), 1)

                async def released():
                    while admission.active is a:
                        await asyncio.sleep(0)

                await asyncio.wait_for(released(), 1)
            late = await admission.submit("late", [4], cache_salt="late")
            assert late.state["accepted"] is reconcile
            owner_timing_at_arrival = a.timing
            owner_state_at_arrival = a.state
            # Owner now finishes and performs its usual explicit reconciliation.
            await a.status()
            a.finish()
            if reconcile:
                completed.add(late.operation_id)
                await late.status()
                late.finish()
            else:
                late.finish(used_tokens=0)
            assert admission.metrics["active_slots"] == 0
            return dict(
                case="later-arrival",
                reconciliation=reconcile,
                early_state=early.state["state"],
                later_decision=late.decision,
                later_state=late.state["state"],
                owner_state_at_arrival=owner_state_at_arrival["state"],
                owner_timing_at_arrival=owner_timing_at_arrival,
                control_rpcs=dict(Counter(p["action"] for p in requests)),
                metrics=admission.metrics,
            )


async def eligibility():
    requests = []

    async def handler(request):
        p = json.loads(request.content)
        requests.append(p)
        return httpx.Response(
            200,
            json=dict(
                success=True,
                result=dict(
                    operation_id=p["operation_id"],
                    state="CACHED",
                    cleanup_pending=False,
                    restored_tokens=0,
                    restored_bytes=0,
                ),
            ),
        )

    rows = []
    async with PrefetchClient(
        "http://offline-fixture", transport=httpx.MockTransport(handler)
    ) as client:
        async with PrefetchAdmission(client, min_overlap_ms=100) as admission:
            for label, hint, expected in (
                ("resident", PrefetchHint("resident"), "LOCAL_RESIDENT"),
                ("short", PrefetchHint("l3_only", 50, 350), "LOCAL_LOW_OVERLAP"),
                ("long", PrefetchHint("l3_only", 600, 350), "CACHED"),
                ("unknown", None, "CACHED"),
            ):
                before = len(requests)
                lease = await admission.submit(label, [1, 2], hint=hint)
                assert lease.state["state"] == expected
                lease.finish()
                rows.append(
                    dict(
                        case=label,
                        decision=lease.decision,
                        state=lease.state["state"],
                        control_rpcs=len(requests) - before,
                        timing=lease.timing,
                    )
                )
            assert len(requests) == 2
    return rows


async def run():
    return dict(
        result="PASS",
        evidence_kind="offline CPU control fixture; synthetic completion events",
        exclusions="No real storage, GPU, model, tool-work or performance claim",
        later_arrivals=[await later_arrival(False), await later_arrival(True)],
        eligibility=await eligibility(),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(asyncio.run(run()), indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result)
    print(result, end="")
