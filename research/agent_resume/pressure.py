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
from .live import control_headers, retained_server_info, validate_server
from .load import AUDITS, context_task, fixed_trace, run_arrivals, summarize
from .prepare import ROOT, tokenizer_manifest
from .runner import GenerationTransport, run_task
from .sampling import FileObserver, clock_domain
from .workloads import RepositoryTools, snapshot
from .readiness import (
    measurement_contract,
    provenance,
    require_baseline,
    require_live,
    require_native,
    verify_storage,
    verify_initial_state,
)


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
    adapter = FamilyAdapter.from_profile(profile)
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
        measurement_contract=measurement_contract(),
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
    if packet.get("measurement_contract") != measurement_contract():
        raise ValueError("Prepare a new workload with the current measurement contract")
    if args.reconcile_ms != packet["measurement_contract"]["reconcile_interval_ms"]:
        raise ValueError("Reconciliation differs from the frozen study contract")
    native_hash = require_native(args.native_evidence, profile)
    live_hash = require_live(args.live_evidence, profile, packet)
    baseline_binding = None
    if args.mode == "proactive":
        baseline_binding = require_baseline(
            args.baseline, envelope["sha256"], args.observation
        )
    if (
        tokenizer_manifest(args.tokenizer, profile["profile_id"])["tokenizer_files"]
        != profile["tokenizer_files"]
    ):
        raise ValueError("Tokenizer differs from workload")
    deployment = json.loads(args.deployment.read_text())
    headers = control_headers(deployment)
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer, local_files_only=True, trust_remote_code=False
    )
    adapter = FamilyAdapter.from_profile(profile)
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
    interrupted = None
    started = time.monotonic_ns()

    async with httpx.AsyncClient(base_url=args.server.rstrip("/"), timeout=180) as http:
        response = await http.get("/get_server_info")
        response.raise_for_status()
        info = response.json()
        validate_server(info, deployment, profile)
        identity_observer = FileObserver(args.probe_dir)
        identity_state = await identity_observer.snapshot([0], None)
        observed_storage = verify_storage(profile, deployment, identity_state)
        initial_state = verify_initial_state(deployment, identity_state)
        if baseline_binding:
            resources = {**observed_storage, **initial_state}
            if any(
                resources.get(k) != v
                for k, v in baseline_binding["resolved_resources"].items()
            ):
                raise ValueError(
                    "Resolved cache resources/layout differ from the baseline"
                )
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
                    server_info=retained_server_info(info),
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
                    provenance=provenance(profile),
                    native_evidence_sha256=native_hash,
                    live_evidence_sha256=live_hash,
                    observed_storage=observed_storage,
                    initial_state=initial_state,
                    measurement_contract=packet["measurement_contract"],
                    baseline_binding=baseline_binding,
                ),
                indent=2,
            )
        )
        async with PrefetchClient(
            args.server, headers=headers, on_event=record_event
        ) as client:
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
                        max_tool_rounds=packet["measurement_contract"][
                            "max_tool_rounds"
                        ],
                        context_limit=profile["server_settings"]["context_length"],
                        cache_salt=item["cache_salt"],
                        on_boundary=observer.snapshot if observer else None,
                        sampling_config=packet["measurement_contract"]["sampling"],
                        on_record=record_outcome,
                    )
                    row["tool_artifacts"] = tools.artifacts
                    return row

                def write(row):
                    with (args.output / "tasks.jsonl").open("a") as out:
                        out.write(json.dumps(row) + "\n")

                try:
                    block = await run_arrivals(
                        packet["arrivals"],
                        task,
                        max_active=packet["max_active"],
                        on_result=write,
                    )
                except BaseException as exc:
                    block = getattr(exc, "block_evidence", None)
                    if block is None:
                        raise
                    interrupted = exc
                    # Retain the whole interrupted block before propagating timeout.
                    # This never converts cancelled work into a successful block.
                unresolved = policy.active is not None or any(
                    r.get("cleanup_confirmed") is False
                    for row in block["rows"]
                    for r in row.get("prefetch", [])
                )
        (args.output / "control-events.json").write_text(json.dumps(events, indent=2))
    manifest_path = args.output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["finalized_ns"] = time.monotonic_ns()
    manifest["procedure_completed"] = interrupted is None
    manifest["interruption_kind"] = type(interrupted).__name__ if interrupted else None
    manifest_path.write_text(json.dumps(manifest, indent=2))
    summary = summarize(block)
    summary.update(
        cleanup_unresolved=unresolved,
        gpu_opportunity_verdict="REQUIRES_SERVER_TRACE_ANALYSIS",
        performance_claim=False,
        procedure_completed=interrupted is None,
        interruption_kind=type(interrupted).__name__ if interrupted else None,
        study_success=interrupted is None
        and not unresolved
        and summary["successful"] == summary["tasks"],
    )
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))
    if interrupted is not None:
        try:
            raise interrupted
        finally:
            interrupted = (
                None  # Do not retain this exception in its own traceback frame.
            )
    return summary["study_success"]


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
    run.add_argument("--native-evidence", required=True, type=Path)
    run.add_argument("--live-evidence", required=True, type=Path)
    run.add_argument("--baseline", type=Path)
    run.add_argument("--server", required=True)
    run.add_argument("--mode", choices=("request_time", "proactive"), required=True)
    run.add_argument(
        "--observation", choices=("memory", "memory-and-stat", "off"), default="memory"
    )
    run.add_argument("--probe-dir", required=True, type=Path)
    run.add_argument("--reconcile-ms", type=int, default=50)
    run.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output path; never overwrite evidence")
    if args.command == "prepare":
        prepare(args)
    else:
        if args.mode == "proactive" and args.baseline is None:
            parser.error("--baseline is required for a comparison")
        raise SystemExit(0 if asyncio.run(execute(args)) else 1)


if __name__ == "__main__":
    main()
