"""Small evidence gates for this study; evidence is not weight attestation."""

import argparse
import hashlib
import json
import platform
import inspect
import subprocess
from importlib import metadata
from pathlib import Path

from .adapters import FamilyAdapter
from .sampling import DEFAULT_SAMPLING

ROOT = Path(__file__).resolve().parents[2]
NATIVE_SOURCES = (
    "adapters.py",
    "contracts.py",
    "workloads.py",
    "native_conformance.py",
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def runtime_provenance(cache_class):
    """Once at plugin startup, inspect the actual imported runtime checkout."""
    try:
        source = Path(inspect.getfile(cache_class)).resolve()
        root = source.parents[4]
        if (
            source.relative_to(root).as_posix()
            != "python/sglang/srt/mem_cache/unified_radix_cache.py"
        ):
            raise ValueError("Unrecognized imported cache location")
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        clean = (
            subprocess.run(
                ["git", "diff", "--quiet", "HEAD", "--", "python/sglang"],
                cwd=root,
                check=False,
            ).returncode
            == 0
        )
        sources = [
            "python/sglang/srt/managers/cache_controller.py",
            "python/sglang/srt/mem_cache/unified_radix_cache.py",
            "python/sglang/srt/mem_cache/proactive_prefetch.py",
            "python/sglang/srt/mem_cache/hicache_storage.py",
        ]
        packages = {}
        for name in ("torch", "transformers", "triton", "sgl-kernel"):
            try:
                packages[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                packages[name] = "NOT_INSTALLED"
        return dict(
            status="OBSERVED_CHECKOUT",
            head=head,
            tracked_runtime_clean=clean,
            source_sha256={p: file_hash(root / p) for p in sources},
            packages=packages,
            python=platform.python_version(),
        )
    except (
        OSError,
        ValueError,
        TypeError,
        IndexError,
        subprocess.CalledProcessError,
    ) as exc:
        return dict(status="UNKNOWN", reason=type(exc).__name__)


def provenance(profile):
    sources = list((ROOT / "research/agent_resume").rglob("*.py")) + list(
        (ROOT / "src/toolgap").rglob("*.py")
    )
    packages = {}
    for name in ("transformers", "tokenizers", "httpx", "mistral_common", "torch"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = "NOT_INSTALLED"
    return dict(
        schema_version=1,
        profile_sha256=digest(profile),
        adapter_profile_id=FamilyAdapter.from_profile(profile).profile_id,
        source_sha256={str(p.relative_to(ROOT)): file_hash(p) for p in sorted(sources)},
        harness_head=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        python=platform.python_version(),
        packages=packages,
    )


def require_native(path, profile):
    evidence = json.loads(Path(path).read_text())
    if (
        evidence.get("validation_type") != "OFFLINE_NATIVE_REFERENCE_CONFORMANCE"
        or evidence.get("passed") is not True
        or evidence.get("profile_id") != FamilyAdapter.from_profile(profile).profile_id
        or evidence.get("tokenizer_files") != profile["tokenizer_files"]
        or evidence.get("transformers") != metadata.version("transformers")
        or len(evidence.get("checks", [])) != 2
        or any(
            not all(
                c.get(k) is True
                for k in (
                    "render_tokenize_agreement",
                    "native_full_text_agreement",
                    "exact_saved_ids",
                )
            )
            for c in evidence["checks"]
        )
    ):
        raise ValueError("Missing/current native reference conformance is required")
    for name in NATIVE_SOURCES:
        if evidence.get("source_sha256", {}).get(name) != file_hash(
            Path(__file__).parent / name
        ):
            raise ValueError("Native reference evidence uses stale source: " + name)
    reference = evidence.get("native_reference")
    if reference and reference["version"] != metadata.version(reference["package"]):
        raise ValueError("Native reference package changed")
    return file_hash(path)


def storage_key(profile):
    # Full profile includes declared weights/revision, tokenizer, dtype/precision,
    # resource/layout settings and runtime SHA. Conservative isolation is cheap.
    return dict(
        schema_version=1,
        profile_sha256=digest(profile),
        adapter_profile_id=FamilyAdapter.from_profile(profile).profile_id,
    )


def storage_namespace(profile):
    return "toolgap-" + digest(storage_key(profile))


def initialize_storage(profile, parent):
    directory = Path(parent) / storage_namespace(profile)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "toolgap-identity.json").write_text(
        json.dumps(storage_key(profile), indent=2)
    )
    return directory


def verify_storage(profile, deployment, state):
    path = Path(deployment["storage_path"]).resolve()
    expected = storage_key(profile)
    if (
        path.name != storage_namespace(profile)
        or json.loads((path / "toolgap-identity.json").read_text()) != expected
    ):
        raise ValueError("File L3 namespace does not match the exact profile")
    actual = state.get("storage_identity", {})
    runtime = state.get("runtime_identity", {})
    if (
        runtime.get("status") != "OBSERVED_CHECKOUT"
        or runtime.get("head") != profile["runtime_candidate_sha"]
        or runtime.get("tracked_runtime_clean") is not True
    ):
        raise ValueError(
            "Actual imported runtime is unknown, dirty or differs from the profile"
        )
    settings = profile["server_settings"]
    if (
        actual.get("namespace") != path.name
        or actual.get("root_sha256") != hashlib.sha256(str(path).encode()).hexdigest()
        or actual.get("page_size") != settings["page_size"]
        or actual.get("layout") != settings["hicache_mem_layout"]
        or actual.get("kv_dtype") != settings["dtype"]
        or type(actual.get("bytes_per_token")) is not int
        or actual["bytes_per_token"] <= 0
    ):
        raise ValueError("Observed backend namespace/KV layout differs or is unknown")
    return dict(
        **actual,
        runtime_identity=runtime,
        identity_claim="OPERATOR_DECLARED_WEIGHTS; OBSERVED_NAMESPACE_AND_LAYOUT",
    )


def live_result(rows, expected_ids, unresolved):
    transport = bool(rows) and all(
        r.get("generations")
        and all(
            g.get("rid")
            and isinstance(g.get("meta_info"), dict)
            and g.get("meta_info", {}).get("finish_reason") is not None
            and not g.get("validation_type", "").startswith("SCRIPTED")
            for g in r["generations"]
        )
        for r in rows
    )
    useful = (
        len(rows) == len(expected_ids)
        and {r["task_id"] for r in rows} == set(expected_ids)
        and all(
            r.get("status") == "COMPLETED"
            and r.get("task_success") is True
            and r.get("tools")
            and len(r["generations"]) > len(r["tools"])
            for r in rows
        )
    )
    pairs = [
        (a, b)
        for r in rows
        for a, b in zip(r.get("generations", []), r.get("generations", [])[1:])
    ]

    def token_ids(value):
        return (
            isinstance(value, list)
            and bool(value)
            and all(type(token) is int and token >= 0 for token in value)
        )

    exact = bool(pairs) and all(
        token_ids(a.get("input_ids"))
        and token_ids(a.get("output_ids"))
        and token_ids(b.get("input_ids"))
        and b["input_ids"][: len(a["input_ids"]) + len(a["output_ids"])]
        == a["input_ids"] + a["output_ids"]
        for a, b in pairs
    )
    cleanup = not unresolved and all(
        not any(
            p.get("cleanup_confirmed") is False
            or p.get("state", {}).get("cleanup_pending")
            or p.get("retained_owner")
            for p in r.get("prefetch", [])
        )
        for r in rows
    )
    passed = transport and useful and exact and cleanup
    return dict(
        schema_version=1,
        validation_type="LIVE_TOOL_LOOP",
        procedure_completed=True,
        study_success=passed,
        tasks=len(rows),
        successful=sum(r.get("task_success") is True for r in rows),
        dimensions=dict(
            transport="PASS" if transport else "FAIL",
            actual_generation="PASS" if transport else "FAIL",
            native_template="PASS",
            exact_continuation=("PASS" if exact else "FAIL") if pairs else "NOT_RUN",
            useful_tool_loop="PASS" if useful else "FAIL",
            correctness="PASS" if useful else "FAIL",
            cleanup="PASS" if cleanup else "FAIL",
            model_fit="UNKNOWN",
            pressure_opportunity="NOT_RUN",
            performance="NOT_RUN",
        ),
        consumed_restore_tokens=None,
        wasted_prefetch_bytes=None,
    )


def verify_initial_state(deployment, state):
    """Whole-block cold startup, not target eviction during useful tool work."""
    keys = ("host_used_tokens", "inflight_tokens", "ongoing_prefetch_count")
    if any(type(state.get(k)) is not int or state[k] != 0 for k in keys):
        raise ValueError(
            "Pressure requires empty resident host KV and no in-flight cache work"
        )
    capacity, available = (
        state.get("device_capacity_tokens"),
        state.get("device_available_tokens"),
    )
    if (
        type(capacity) is not int
        or capacity <= 0
        or type(available) is not int
        or available != capacity
    ):
        raise ValueError("Pressure requires a fresh empty device KV pool")
    host_capacity = state.get("host_available_tokens")
    if type(host_capacity) is not int or host_capacity <= 0:
        raise ValueError("Pressure requires a known empty host KV capacity")
    if any(
        p.name != "toolgap-identity.json"
        for p in Path(deployment["storage_path"]).iterdir()
    ):
        raise ValueError("Pressure requires a fresh empty file L3 directory")
    return dict(
        policy="EMPTY_DEVICE_HOST_AND_FILE_L3_AT_BLOCK_START",
        device_capacity_tokens=capacity,
        device_available_tokens=available,
        host_capacity_tokens=host_capacity,
        host_used_tokens=0,
        inflight_tokens=0,
        ongoing_prefetch_count=0,
        file_entries=0,
    )


def pressure_gate_workload(packet):
    """Representative actual packet tasks, not a different diagnostic workload."""
    from .load import AUDITS

    if packet.get("measurement_contract") != measurement_contract():
        raise ValueError("Prepare a packet with the current measurement contract")
    known = {t["id"] for t in AUDITS}
    representatives = {}
    for item in packet["arrivals"]:
        task = item["task"]
        if (
            item["audit_id"] not in known
            or task["id"] != item["audit_id"]
            or not task.get("initial_input_ids")
            or not task.get("context_pack")
        ):
            raise ValueError("Pressure gate requires prepared code-audit tasks")
        representatives.setdefault(task["id"], item)
    if not representatives:
        raise ValueError("Empty pressure workload")
    items = list(representatives.values())
    return items, dict(
        kind="PRESSURE_PACKET_REPRESENTATIVES",
        packet_sha256=digest(packet),
        expected_ids=[item["task"]["id"] for item in items],
        representatives_sha256=digest(items),
        max_tool_rounds=packet["measurement_contract"]["max_tool_rounds"],
        generation=packet["measurement_contract"]["generation"],
    )


def require_live(directory, profile, packet=None):
    directory = Path(directory)
    record = json.loads((directory / "readiness.json").read_text())
    if (
        record.get("validation_type") != "LIVE_TOOL_LOOP"
        or record.get("study_success") is not True
        or record.get("provenance") != provenance(profile)
    ):
        raise ValueError(
            "Pressure requires useful live evidence for the current profile/code/packages"
        )
    if set(record.get("artifacts_sha256", {})) != {
        "manifest.json",
        "tasks.jsonl",
        "control-events.json",
    }:
        raise ValueError("Live proof lacks raw artifact bindings")
    for name, expected in record["artifacts_sha256"].items():
        if Path(name).name != name or file_hash(directory / name) != expected:
            raise ValueError("Live evidence artifact changed")
    rows = [
        json.loads(line)
        for line in (directory / "tasks.jsonl").read_text().splitlines()
    ]
    from .workloads import TASKS

    expected_ids = [t["id"] for t in TASKS]
    if packet is not None:
        if packet["profile"] != profile:
            raise ValueError("Live gate profile differs from pressure packet")
        items, contract = pressure_gate_workload(packet)
        manifest = json.loads((directory / "manifest.json").read_text())
        if (
            manifest.get("task_contract") != contract
            or record.get("task_contract") != contract
            or manifest.get("profile") != profile
        ):
            raise ValueError("Live proof is not bound to this pressure workload")
        expected_ids = contract["expected_ids"]
        expected = {i["task"]["id"]: i for i in items}
        for row in rows:
            item = expected.get(row.get("task_id"))
            if (
                item is None
                or not row.get("generations")
                or row["generations"][0].get("input_ids")
                != item["task"]["initial_input_ids"]
                or row.get("cache_salt") != item["cache_salt"]
                or len(row.get("tools", [])) > contract["max_tool_rounds"]
                or any(
                    g.get("sampling_params") != contract["generation"]
                    for g in row["generations"]
                )
            ):
                raise ValueError("Live task inputs/limits differ from pressure packet")
    verified = live_result(rows, expected_ids, record.get("cleanup_unresolved", True))
    if not verified["study_success"] or verified["dimensions"] != record["dimensions"]:
        raise ValueError("Live evidence does not demonstrate a useful tool loop")
    return file_hash(directory / "readiness.json")


def measurement_contract():
    from .workloads import tool_contract
    from .runner import generation_contract
    from .load import (
        MAX_COMPARISON_DEGRADATION_FRACTION,
        MAX_OBSERVER_RELATIVE_CHANGE_FRACTION,
    )

    return dict(
        schema_version=3,
        max_tool_rounds=6,
        generation=generation_contract(),
        repository_tools=tool_contract(),
        sampling=DEFAULT_SAMPLING,
        experimental_unit="WHOLE_SHARED_WORKER_BLOCK",
        trigger="ONCE_AT_TOOL_DISPATCH",
        primary_endpoint="SUCCESSFUL_TASKS_PER_BLOCK_SECOND",
        block_elapsed_scope="ARRIVAL_EPOCH_THROUGH_ALL_CALLER_FINALIZATION_AND_RECORDING",
        median_degradation_endpoint="ALL_CALLER_ARRIVAL_TO_FINALIZED_MS",
        interrupted_callers="ALL_DECLARED_ROWS_RETAINED; CANCELLED_LATENCIES_CENSORED",
        quality_rule="ALL_DECLARED_CALLERS_PASS",
        max_competing_caller_median_degradation_fraction=MAX_COMPARISON_DEGRADATION_FRACTION,
        max_observer_relative_change_fraction=MAX_OBSERVER_RELATIVE_CHANGE_FRACTION,
        observer_calibration="SYMMETRIC_LATENCY_AND_THROUGHPUT_CHANGE; DESCRIPTIVE_ONLY",
        latency_secondary="ALL_CALLER_ARRIVAL_TO_COMPLETED; ALL_CALLER_ARRIVAL_TO_FINALIZED; CONTINUATION_TTFT; TOOL_DISPATCH_TO_FIRST_TOKEN",
        dispatch_state="UNKNOWN_WITH_BACKGROUND_SAMPLES",
        wasted_prefetch_bytes=None,
        opportunity_threshold_tokens="OBSERVED_CACHE_AND_CONTROLLER_MAXIMUM",
        reconcile_interval_ms=50,
        initial_state="EMPTY_DEVICE_HOST_AND_FILE_L3_AT_BLOCK_START",
        instrumentation_calibration="REQUEST_TIME_ON_OFF_COLD_WORKER_BLOCKS; SAME_PACKET; COUNTERBALANCE; FEASIBILITY_ONLY",
        comparison="MATCHED_CONFIGURATION_AND_INITIALIZATION; COUNTERBALANCED_BLOCK_ORDER",
        inference="FEASIBILITY_ONLY_UNTIL_REPEATED_WHOLE_WORKER_BLOCKS",
    )


def require_baseline(directory, packet_hash, observation):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    summary = json.loads((directory / "summary.json").read_text())
    # Trace report is mandatory: absence is not zero opportunities/I/O.
    trace = json.loads((directory / "trace-report.json").read_text())
    if set(trace.get("source_artifacts_sha256", {})) != {
        "manifest.json",
        "tasks.jsonl",
        "summary.json",
        "server-trace.jsonl",
    }:
        raise ValueError("Baseline lacks bound raw trace/outcomes")
    for name, expected in trace["source_artifacts_sha256"].items():
        if file_hash(directory / name) != expected:
            raise ValueError("Baseline artifact changed: " + name)
    if manifest.get("provenance") != provenance(manifest["profile"]):
        raise ValueError("Baseline source/profile/packages are stale")
    if (
        manifest.get("mode") != "request_time"
        or manifest.get("packet_sha256") != packet_hash
        or manifest.get("observation") != observation
        or manifest.get("measurement_contract") != measurement_contract()
        or manifest.get("initial_state", {}).get("policy")
        != measurement_contract()["initial_state"]
        or summary.get("procedure_completed") is not True
        or summary.get("study_success") is not True
        or summary.get("cleanup_unresolved") is not False
        or not summary.get("tasks")
        or summary.get("successful") != summary["tasks"]
        or not trace.get("physical_read_batches")
        or not any(
            (
                b.get("cache_window_summary", {}).get("first_eligible_during_tool")
                or {}
            ).get("admission_eligible")
            is True
            for b in trace.get("boundaries", [])
        )
    ):
        raise ValueError(
            "No matched quality/cleanup baseline with observed natural L3 candidates"
        )
    # Unconditional fixed-dispatch feasibility can expose a policy that misses
    # later windows. Do not infer dispatch eligibility or select treatment wins.
    return dict(
        baseline_manifest_sha256=file_hash(directory / "manifest.json"),
        baseline_trace_report_sha256=file_hash(directory / "trace-report.json"),
        comparison_kind="EXPLORATORY_FIXED_DISPATCH_WHOLE_WORKER",
        dispatch_trigger_reachability="UNKNOWN",
        performance_validated=False,
        resolved_resources={
            "device_capacity_tokens": manifest["initial_state"][
                "device_capacity_tokens"
            ],
            "host_capacity_tokens": manifest["initial_state"]["host_capacity_tokens"],
            **{
                k: manifest["observed_storage"][k]
                for k in (
                    "page_size",
                    "layout",
                    "kv_dtype",
                    "bytes_per_token",
                    "prefetch_threshold",
                )
            },
        },
    )


def main():
    parser = argparse.ArgumentParser(
        description="Claim a NEW isolated file L3 directory before server startup"
    )
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--storage-parent", required=True, type=Path)
    args = parser.parse_args()
    print(initialize_storage(json.loads(args.profile.read_text()), args.storage_parent))


if __name__ == "__main__":
    main()
