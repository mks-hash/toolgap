"""Diagnostic live tasks on an existing server; not an eviction benchmark."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from toolgap import PrefetchAdmission, PrefetchClient

from .adapters import FamilyAdapter
from .prepare import ROOT, tokenizer_manifest
from .runner import GenerationTransport, run_task
from .workloads import RepositoryTools, TASKS, snapshot


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
    expected = dict(profile["server_settings"], model_path=deployment["model_path"])
    for key, value in expected.items():
        if config.get(key) != value:
            raise ValueError(f"Server setting differs: {key}")
    if len(deployment["runtime_sha"]) != 40 or any(
        c not in "0123456789abcdef" for c in deployment["runtime_sha"]
    ):
        raise ValueError("Declare the exact deployed runtime SHA")
    if deployment["runtime_sha"] != profile["runtime_candidate_sha"]:
        raise ValueError("Deployment declares a different runtime SHA")


async def execute(args):
    from transformers import AutoTokenizer

    profile = json.loads(args.profile.read_text())
    actual = tokenizer_manifest(args.tokenizer, profile["profile_id"])
    if actual["tokenizer_files"] != profile["tokenizer_files"]:
        raise ValueError("Local tokenizer files differ from pinned profile")
    deployment = json.loads(args.deployment.read_text())
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer, local_files_only=True, trust_remote_code=False
    )
    corpus = snapshot(ROOT, profile["source_commit"])
    args.output.mkdir(parents=True, exist_ok=True)

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
        (args.output / "manifest.json").write_text(
            json.dumps(
                dict(
                    profile=profile,
                    deployment=deployment,
                    server_info=info,
                    mode=args.mode,
                    validation_type="LIVE_DIAGNOSTIC",
                    cache_state="UNMEASURED",
                    physical_io="UNMEASURED",
                    weight_revision="OPERATOR_DECLARED",
                ),
                indent=2,
            )
        )
        rows = []
        unresolved_cleanup = False
        control_events = []
        async with PrefetchClient(
            args.server, on_event=control_events.append
        ) as client:
            async with PrefetchAdmission(
                client,
                max_prefix_tokens=profile["server_settings"]["context_length"],
                reconcile_interval_ms=args.reconcile_ms,
            ) as policy:
                for task in TASKS:
                    tools = RepositoryTools(corpus, ROOT)
                    row = await run_task(
                        FamilyAdapter(profile["family"]),
                        tokenizer,
                        GenerationTransport(http),
                        tools,
                        task,
                        policy=policy if args.mode == "proactive" else None,
                        context_limit=profile["server_settings"]["context_length"],
                        on_record=write,
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
    return (
        not unresolved_cleanup
        and all(r["task_success"] for r in rows)
        and len(rows) == len(TASKS)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--tokenizer", required=True, type=Path)
    parser.add_argument("--server", required=True)
    parser.add_argument("--mode", choices=("request_time", "proactive"), required=True)
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
