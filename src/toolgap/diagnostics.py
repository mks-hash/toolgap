"""Opt-in read-only checks. No model import, download, generation or submit."""

import hashlib
import importlib.metadata
import importlib.resources
import json
import shutil
import subprocess
from pathlib import Path

import httpx


def manifest():
    return json.loads(
        importlib.resources.files("toolgap")
        .joinpath("data/compatibility-files.json")
        .read_text(encoding="utf-8")
    )


def check_files(directory, expected, *, label):
    checks = []
    for name, digest in expected.items():
        path = Path(directory) / name
        try:
            with path.open("rb") as stream:
                actual = (
                    hashlib.file_digest(stream, "sha256").hexdigest()
                    if hasattr(hashlib, "file_digest")
                    else _hash(stream)
                )
            ok = actual == digest
            detail = (
                "Hash matches validated setup"
                if ok
                else "Hash differs from validated setup"
            )
            checks.append(
                dict(
                    name=f"{label}/{name}",
                    state="PASS" if ok else "FAIL",
                    detail=detail,
                )
            )
        except OSError:
            checks.append(
                dict(
                    name=f"{label}/{name}",
                    state="FAIL",
                    detail="Missing or unreadable file",
                )
            )
    return checks


def _hash(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def gpu_check():
    executable = shutil.which("nvidia-smi")
    if not executable:
        return dict(
            name="local_gpu_inventory",
            state="FAIL",
            detail="nvidia-smi is unavailable; install/configure the GPU host separately",
        )
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return dict(
            name="local_gpu_inventory",
            state="UNKNOWN",
            detail="GPU inventory command could not complete",
        )
    if result.returncode or not result.stdout.strip():
        return dict(
            name="local_gpu_inventory",
            state="FAIL",
            detail="nvidia-smi did not report an available GPU",
        )
    try:
        torch_version = importlib.metadata.version("torch")
    except importlib.metadata.PackageNotFoundError:
        torch_version = "not installed"
    return dict(
        name="local_gpu_inventory",
        state="PASS",
        detail=result.stdout.strip(),
        torch_package_version=torch_version,
        cuda_execution_tested=False,
    )


def _field(info, namespace, key):
    if key in info:
        return info[key]
    group = info.get(namespace)
    return group.get(key) if isinstance(group, dict) else None


async def server_checks(http):
    checks = []

    async def get(path, name):
        try:
            response = await http.get(path)
            if response.status_code in (401, 403):
                checks.append(
                    dict(
                        name=name,
                        state="UNKNOWN" if name == "live_backend" else "FAIL",
                        detail="Backend-status GET requires configured admin credentials; live backend cannot be confirmed"
                        if name == "live_backend"
                        else "Authentication rejected; check --api-key-env and server credentials",
                    )
                )
                return None
            if response.status_code == 404:
                checks.append(
                    dict(
                        name=name,
                        state="FAIL",
                        detail=f"{path} is unavailable on this server",
                    )
                )
                return None
            if not response.is_success:
                checks.append(
                    dict(
                        name=name,
                        state="UNKNOWN",
                        detail=f"{path} returned HTTP {response.status_code}",
                    )
                )
                return None
            value = response.json()
            if not isinstance(value, dict):
                checks.append(
                    dict(
                        name=name,
                        state="UNKNOWN",
                        detail=f"{path} returned a non-object response",
                    )
                )
                return None
            return value
        except httpx.HTTPError:
            checks.append(
                dict(
                    name=name,
                    state="UNKNOWN",
                    detail=f"Could not reach {path}; no state-changing request was sent",
                )
            )
        except ValueError:
            checks.append(
                dict(name=name, state="UNKNOWN", detail=f"{path} returned invalid JSON")
            )
        return None

    # /health can generate a token when its server flag is enabled. Metadata
    # checks deliberately avoid both /health and /health_generate.
    schema = await get("/openapi.json", "prefetch_route")
    if schema is not None:
        paths = schema.get("paths")
        route = paths.get("/hicache/prefetch", {}) if isinstance(paths, dict) else None
        declared = isinstance(route, dict) and "post" in route
        checks.append(
            dict(
                name="prefetch_route",
                state="UNKNOWN"
                if not isinstance(paths, dict)
                else "PASS"
                if declared
                else "FAIL",
                detail="OpenAPI paths cannot be read; route declaration is unverified"
                if not isinstance(paths, dict)
                else "POST /hicache/prefetch is declared; restore was not exercised"
                if declared
                else "Proactive-prefetch POST route is absent from OpenAPI; use the patched runtime",
            )
        )
    info = await get("/server_info", "startup_scope")
    if info is not None:
        checks.append(
            dict(
                name="server_metadata",
                state="PASS",
                detail="Server metadata answered; generation readiness is unverified",
            )
        )
        required = [
            ("memory", "enable_hierarchical_cache", True),
            ("memory", "hicache_host_memory_mode", "cache"),
            ("parallel", "tp_size", 1),
            ("parallel", "pp_size", 1),
            ("parallel", "dp_size", 1),
        ]
        if not isinstance(info, dict):
            checks.append(
                dict(
                    name="startup_scope",
                    state="UNKNOWN",
                    detail="Server configuration is not an object",
                )
            )
        else:
            for namespace, key, expected in required:
                value = _field(info, namespace, key)
                state = (
                    "UNKNOWN"
                    if value is None
                    else "PASS"
                    if type(value) is type(expected) and value == expected
                    else "FAIL"
                )
                checks.append(
                    dict(
                        name=key,
                        state=state,
                        detail=f"Expected {expected!r}; server reports {value!r}",
                    )
                )
    backend = await get("/hicache/storage-backend", "live_backend")
    if backend is not None:
        value = (
            backend.get("hicache_storage_backend")
            if isinstance(backend, dict)
            else None
        )
        checks.append(
            dict(
                name="live_backend",
                state="UNKNOWN"
                if value is None
                else "PASS"
                if value == "file"
                else "FAIL",
                detail="Live backend reports file"
                if value == "file"
                else "Live backend is unavailable or outside the file-backend scope",
            )
        )
    model = await get("/model_info", "server_model")
    if model is not None:
        architectures = model.get("architectures") if isinstance(model, dict) else None
        state = (
            "UNKNOWN"
            if architectures is None
            else "PASS"
            if architectures == ["Qwen2ForCausalLM"]
            else "FAIL"
        )
        checks.append(
            dict(
                name="server_model",
                state=state,
                detail="Qwen2 architecture reported; weight revision and local/remote model identity remain unverified"
                if state == "PASS"
                else "Expected the validated Qwen2 architecture; model identity is not established",
            )
        )
    return checks


async def doctor(*, sglang=None, model=None, gpu=False, http=None):
    checks = []
    pinned = manifest()
    if sglang:
        checks += check_files(sglang, pinned["source_files"], label="source")
    if model:
        checks += check_files(model, pinned["model_tokenizer_files"], label="model")
    if gpu:
        checks.append(gpu_check())
    if http is not None:
        checks += await server_checks(http)
    if not checks:
        checks.append(
            dict(
                name="targets",
                state="UNKNOWN",
                detail="Select --sglang, --model, --gpu or --url for checks",
            )
        )
    overall = (
        "FAIL"
        if any(c["state"] == "FAIL" for c in checks)
        else "UNKNOWN"
        if any(c["state"] == "UNKNOWN" for c in checks)
        else "PASS"
    )
    return dict(
        command="doctor",
        state=overall,
        checks=checks,
        validated_source_commit=pinned["release_source_commit"],
        restore_exercised=False,
        cache_state_verified=False,
        note="PASS applies only to requested checks. No download, generation, submit or cancellation was performed.",
    )
