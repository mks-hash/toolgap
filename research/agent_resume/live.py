"""Diagnostic live tasks on an existing server; not an eviction benchmark."""

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from toolgap import PrefetchAdmission, PrefetchClient

from .adapters import FamilyAdapter
from .prepare import ROOT, tokenizer_manifest
from .runner import GenerationTransport, run_task
from .workload import tools_factory
from .workloads import RepositoryTools, TASKS, snapshot
from .readiness import (
    file_hash,
    live_result,
    provenance,
    pressure_gate_workload,
    digest,
    require_native,
    verify_storage,
)
from .sampling import FileObserver, clock_domain


def control_headers(deployment):
    """Admin credentials are process-only; never put them in the study manifest."""
    key = os.environ.get("TOOLGAP_STUDY_ADMIN_KEY")
    if deployment.get("admin_auth_required") and not key:
        raise ValueError("Set TOOLGAP_STUDY_ADMIN_KEY for the approved local server")
    return {"Authorization": "Bearer " + key} if key else None


def retained_server_info(info):
    """Keep resolved settings, excluding credentials and the raw launch command."""
    if isinstance(info, dict):
        return {
            k: retained_server_info(v)
            for k, v in info.items()
            if k not in ("api_key", "admin_api_key", "launch_command")
        }
    if isinstance(info, list):
        return [retained_server_info(v) for v in info]
    return info


def validate_server(info, deployment, profile):
    """Compare resolved settings and declared identity; no weight attestation."""
    if (
        deployment["model"] != profile["model"]
        or deployment["revision"] != profile["revision"]
    ):
        raise ValueError("Deployment declares a different model/revision")
    if deployment["resolved_cache_mode"] != "FULL":
        raise ValueError("An independently checked FULL cache mode is required")
    config = info.get("server_args", info)
    if bool(config.get("admin_api_key")) != bool(deployment.get("admin_auth_required")):
        raise ValueError("Declared admin authentication differs from the server")
    expected = dict(profile["server_settings"], model_path=deployment["model_path"])
    for key, value in expected.items():
        if config.get(key) != value:
            raise ValueError(f"Server setting differs: {key}")
    for key in (
        "quantization",
        "kv_cache_dtype",
        "hicache_storage_backend_extra_config",
    ):
        if config.get(key) not in (None, "auto") and config.get(key) != profile[
            "server_settings"
        ].get(key):
            raise ValueError(f"Unexpected precision setting: {key}")
    if len(deployment["runtime_sha"]) != 40 or any(
        c not in "0123456789abcdef" for c in deployment["runtime_sha"]
    ):
        raise ValueError("Declare the exact deployed runtime SHA")
    if deployment["runtime_sha"] != profile["runtime_candidate_sha"]:
        raise ValueError("Deployment declares a different runtime SHA")


async def execute(args):
    from transformers import AutoTokenizer

    purpose = getattr(args, "purpose", "evidence")
    if purpose not in ("evidence", "diagnostic") or (
        purpose == "diagnostic" and args.mode != "request_time"
    ):
        raise ValueError("Diagnostic live observation is request-time only")
    profile = json.loads(args.profile.read_text())
    task_contract = dict(kind="LEGACY_DIAGNOSTIC", max_tool_rounds=4)
    items = [dict(task=t) for t in TASKS]
    if getattr(args, "packet", None) is not None:
        envelope = json.loads(args.packet.read_text())
        packet = envelope["packet"]
        if digest(packet) != envelope["sha256"] or packet["profile"] != profile:
            raise ValueError("Packet hash/profile differs from live gate")
        items, task_contract = pressure_gate_workload(packet)
    native_hash = (
        require_native(args.native_evidence, profile, workload="document-search")
        if getattr(args, "packet", None) is not None
        and packet.get("workload_kind") == "document-search"
        else require_native(args.native_evidence, profile)
    )
    actual = tokenizer_manifest(args.tokenizer, profile["profile_id"])
    if actual["tokenizer_files"] != profile["tokenizer_files"]:
        raise ValueError("Local tokenizer files differ from pinned profile")
    deployment = json.loads(args.deployment.read_text())
    headers = control_headers(deployment)
    if deployment.get("clock_domain") != clock_domain():
        raise ValueError("Live diagnostic and server must share a Linux boot")
    observer = FileObserver(args.probe_dir)
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer, local_files_only=True, trust_remote_code=False
    )
    legacy_corpus = (
        snapshot(ROOT, profile["source_commit"])
        if getattr(args, "packet", None) is None
        else None
    )
    factory = (
        tools_factory(packet, ROOT)
        if getattr(args, "packet", None) is not None
        else lambda: RepositoryTools(legacy_corpus, ROOT)
    )
    args.output.mkdir(parents=True, exist_ok=False)

    # Retain failed tasks and raw IDs. Never silently retry generation.
    def write(row):
        operations = {r.get("state", {}).get("operation_id") for r in row["prefetch"]}
        operations |= {
            r.get("retained_owner", {}).get("operation_id") for r in row["prefetch"]
        }
        row["control_events"] = [
            dict(e) for e in control_events if e["operation_id"] in operations
        ]
        row["tool_artifacts"] = list(tools.artifacts)
        with (args.output / "tasks.jsonl").open("a") as output:
            output.write(json.dumps(row) + "\n")

    async with httpx.AsyncClient(base_url=args.server.rstrip("/"), timeout=180) as http:
        response = await http.get("/get_server_info")
        response.raise_for_status()
        info = response.json()
        validate_server(info, deployment, profile)
        observed_storage = verify_storage(
            profile, deployment, await observer.snapshot([0], None)
        )
        (args.output / "manifest.json").write_text(
            json.dumps(
                dict(
                    profile=profile,
                    deployment=deployment,
                    server_info=retained_server_info(info),
                    mode=args.mode,
                    purpose=purpose,
                    validation_type="LIVE_DIAGNOSTIC",
                    cache_state="UNMEASURED",
                    physical_io="UNMEASURED",
                    weight_revision="OPERATOR_DECLARED",
                    provenance=provenance(profile),
                    native_evidence_sha256=native_hash,
                    observed_storage=observed_storage,
                    task_contract=task_contract,
                ),
                indent=2,
            )
        )
        rows = []
        unresolved_cleanup = False
        control_events = []
        async with PrefetchClient(
            args.server, headers=headers, on_event=control_events.append
        ) as client:
            async with PrefetchAdmission(
                client,
                max_prefix_tokens=profile["server_settings"]["context_length"],
                reconcile_interval_ms=args.reconcile_ms,
            ) as policy:
                for item in items:
                    task = item["task"]
                    tools = factory()
                    row = await run_task(
                        FamilyAdapter.from_profile(profile),
                        tokenizer,
                        GenerationTransport(http),
                        tools,
                        task,
                        policy=policy if args.mode == "proactive" else None,
                        context_limit=profile["server_settings"]["context_length"],
                        on_record=write,
                        max_tool_rounds=task_contract["max_tool_rounds"],
                        cache_salt=item.get("cache_salt"),
                    )
                    rows.append(row)
                    (args.output / (task["id"] + "-tool-artifacts.json")).write_text(
                        json.dumps(tools.artifacts, indent=2)
                    )
                    if policy.active is not None:
                        # No following task after ambiguous physical cleanup.
                        unresolved_cleanup = True
                        break
        (args.output / "control-events.json").write_text(
            json.dumps(control_events, indent=2)
        )
    result = live_result(rows, [i["task"]["id"] for i in items], unresolved_cleanup)
    result.update(
        purpose=purpose,
        provenance=provenance(profile),
        cleanup_unresolved=unresolved_cleanup,
        task_contract=task_contract,
        artifacts_sha256={
            name: file_hash(args.output / name)
            for name in ("manifest.json", "tasks.jsonl", "control-events.json")
        },
    )
    (args.output / "readiness.json").write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            dict(
                procedure_completed=True,
                study_success=result["study_success"],
                diagnostic_ready=result["diagnostic_ready"],
                purpose=purpose,
                dimensions=result["dimensions"],
            )
        )
    )
    return (
        result["diagnostic_ready"]
        if purpose == "diagnostic"
        else result["study_success"]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument(
        "--packet",
        type=Path,
        help="Prepared pressure packet: run representative actual tasks/contexts/limits",
    )
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--tokenizer", required=True, type=Path)
    parser.add_argument("--native-evidence", required=True, type=Path)
    parser.add_argument("--probe-dir", required=True, type=Path)
    parser.add_argument("--server", required=True)
    parser.add_argument("--mode", choices=("request_time", "proactive"), required=True)
    parser.add_argument(
        "--purpose", choices=("evidence", "diagnostic"), default="evidence"
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reconcile-ms", type=int)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(
            "Use a new output directory; existing evidence is never appended/overwritten"
        )
    raise SystemExit(0 if asyncio.run(execute(args)) else 1)


if __name__ == "__main__":
    main()
