"""Prepare/run one observed shared-worker block. Never provision or launch a server."""

import argparse
import asyncio
import copy
import hashlib
import json
import subprocess
import time
from pathlib import Path

import httpx

from toolgap import PrefetchAdmission, PrefetchClient
from .adapters import FamilyAdapter
from .live import validate_server
from .load import AUDITS, context_task, fixed_trace, run_arrivals, summarize
from .prepare import ROOT, tokenizer_manifest
from .runner import GenerationTransport, run_task
from .sampling import FileObserver, clock_domain
from .workloads import RepositoryTools, snapshot


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def pressure_profile(profile):
    result = copy.deepcopy(profile)
    result["server_settings"].update(max_running_requests=4, hicache_size=1)
    result["status"] = "PRESSURE_CANDIDATE_NOT_GPU_VALIDATED"
    return result


def prepare(args):
    from transformers import AutoTokenizer

    profile = pressure_profile(json.loads(args.profile.read_text()))
    actual = tokenizer_manifest(args.tokenizer, profile["profile_id"])
    if actual["tokenizer_files"] != profile["tokenizer_files"]:
        raise ValueError("Tokenizer differs from pinned profile")
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer, local_files_only=True, trust_remote_code=False
    )
    adapter = FamilyAdapter(profile["family"])
    corpus = snapshot(ROOT, profile["source_commit"])
    trace = fixed_trace(args.count)
    audits = {task["id"]: task for task in AUDITS}
    for item in trace:
        item["task"] = context_task(
            adapter,
            tokenizer,
            audits[item["audit_id"]],
            corpus,
            target_tokens=args.target_tokens,
            variant=item["context_variant"],
        )
    packet = dict(
        profile=profile,
        arrivals=trace,
        max_active=8,
        useful_tool="pinned repository audit and admission_hints CPU regression",
        artificial_tool_delay=False,
        gpu_validated=False,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(dict(packet=packet, sha256=digest(packet)), indent=2)
    )
    print(
        json.dumps(
            dict(
                prepared=len(trace),
                initial_tokens=[i["task"]["initial_tokens"] for i in trace],
                gpu_execution=False,
            )
        )
    )


async def execute(args):
    from transformers import AutoTokenizer

    envelope = json.loads(args.packet.read_text())
    packet = envelope["packet"]
    if digest(packet) != envelope["sha256"]:
        raise ValueError("Prepared workload packet changed")
    profile = packet["profile"]
    if (
        tokenizer_manifest(args.tokenizer, profile["profile_id"])["tokenizer_files"]
        != profile["tokenizer_files"]
    ):
        raise ValueError("Tokenizer differs from workload")
    deployment = json.loads(args.deployment.read_text())
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer, local_files_only=True, trust_remote_code=False
    )
    adapter = FamilyAdapter(profile["family"])
    corpus = snapshot(ROOT, profile["source_commit"])
    observer = (
        None
        if args.observation == "off"
        else FileObserver(
            args.probe_dir, include_storage=args.observation == "memory-and-stat"
        )
    )
    args.output.mkdir(parents=True, exist_ok=False)
    events = []

    def record_event(event):
        events.append(event)
        with (args.output / "control-events.jsonl").open("a") as out:
            out.write(json.dumps(event) + "\n")

    block_id = args.output.name
    unresolved = False
    started = time.monotonic_ns()

    async with httpx.AsyncClient(base_url=args.server.rstrip("/"), timeout=180) as http:
        response = await http.get("/get_server_info")
        response.raise_for_status()
        info = response.json()
        validate_server(info, deployment, profile)
        if deployment.get("clock_domain") != clock_domain():
            raise ValueError("Run client and server on the same Linux boot")
        expected_match = args.observation != "off"
        if deployment.get("pressure_match_observation") is not expected_match:
            raise ValueError(
                "Declare the matching observation toggle used at server startup"
            )
        (args.output / "manifest.json").write_text(
            json.dumps(
                dict(
                    validation_type="LIVE_PRESSURE_BLOCK",
                    packet_sha256=envelope["sha256"],
                    profile=profile,
                    deployment=deployment,
                    server_info=info,
                    mode=args.mode,
                    observation=args.observation,
                    block_id=block_id,
                    started_ns=started,
                    clock_domain=clock_domain(),
                    harness_commit=subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                    ).strip(),
                    weight_revision="OPERATOR_DECLARED",
                    reconcile_interval_ms=args.reconcile_ms,
                    experimental_unit="WHOLE_SHARED_WORKER_BLOCK",
                ),
                indent=2,
            )
        )
        async with PrefetchClient(args.server, on_event=record_event) as client:
            async with PrefetchAdmission(
                client,
                max_prefix_tokens=profile["server_settings"]["context_length"],
                reconcile_interval_ms=args.reconcile_ms,
            ) as policy:

                async def task(item):
                    tools = RepositoryTools(corpus, ROOT)
                    model = GenerationTransport(http)
                    model.request_id_prefix = "tgp-"

                    def record_outcome(row):
                        row["trajectory_id"] = item["trajectory_id"]
                        row["tool_artifacts"] = tools.artifacts
                        (
                            args.output / (item["trajectory_id"] + ".outcome.json")
                        ).write_text(json.dumps(row, indent=2))

                    row = await run_task(
                        adapter,
                        tokenizer,
                        model,
                        tools,
                        item["task"],
                        policy=policy if args.mode == "proactive" else None,
                        max_tool_rounds=6,
                        context_limit=profile["server_settings"]["context_length"],
                        cache_salt=item["cache_salt"],
                        on_boundary=observer.snapshot if observer else None,
                        on_record=record_outcome,
                    )
                    row["tool_artifacts"] = tools.artifacts
                    return row

                def write(row):
                    with (args.output / "tasks.jsonl").open("a") as out:
                        out.write(json.dumps(row) + "\n")

                block = await run_arrivals(
                    packet["arrivals"],
                    task,
                    max_active=packet["max_active"],
                    on_result=write,
                )
                unresolved = policy.active is not None or any(
                    r.get("cleanup_confirmed") is False
                    for row in block["rows"]
                    for r in row.get("prefetch", [])
                )
        (args.output / "control-events.json").write_text(json.dumps(events, indent=2))
    manifest_path = args.output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["finalized_ns"] = time.monotonic_ns()
    manifest_path.write_text(json.dumps(manifest, indent=2))
    summary = summarize(block)
    summary.update(
        cleanup_unresolved=unresolved,
        gpu_opportunity_verdict="REQUIRES_SERVER_TRACE_ANALYSIS",
        performance_claim=False,
    )
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))
    return not unresolved and summary["successful"] == summary["tasks"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--profile", required=True, type=Path)
    prep.add_argument("--tokenizer", required=True, type=Path)
    prep.add_argument("--count", type=int, default=12)
    prep.add_argument("--target-tokens", type=int, default=4000)
    prep.add_argument("--output", required=True, type=Path)
    run = sub.add_parser("run")
    run.add_argument("--packet", required=True, type=Path)
    run.add_argument("--deployment", required=True, type=Path)
    run.add_argument("--tokenizer", required=True, type=Path)
    run.add_argument("--server", required=True)
    run.add_argument("--mode", choices=("request_time", "proactive"), required=True)
    run.add_argument(
        "--observation", choices=("memory", "memory-and-stat", "off"), default="memory"
    )
    run.add_argument("--probe-dir", type=Path)
    run.add_argument("--reconcile-ms", type=int, default=50)
    run.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output path; never overwrite evidence")
    if args.command == "prepare":
        prepare(args)
    else:
        if args.observation != "off" and args.probe_dir is None:
            parser.error("--probe-dir is required when observing")
        raise SystemExit(0 if asyncio.run(execute(args)) else 1)


if __name__ == "__main__":
    main()
