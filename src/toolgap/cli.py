"""Thin control CLI. One RPC per action, no implicit retries or generation."""

import argparse
import asyncio
import json
import math
import os
import sys
import uuid
from pathlib import Path

import httpx

from .client import PrefetchClient, PrefetchRejected, _validate_prefix
from .diagnostics import doctor

MAX_PREFIX_BYTES = 1024 * 1024
STATES = {
    "RUNNING",
    "SUCCESS",
    "CACHED",
    "MISS",
    "FAILURE",
    "CANCELLED",
    "EXPIRED",
    "DECLINED",
}


def positive_timeout(text):
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("Timeout must be a finite positive number")
    return value


def parser(environ):
    root = argparse.ArgumentParser(prog="toolgap", description=__doc__)
    actions = root.add_subparsers(dest="command", required=True)
    for action in ["submit", "status", "cancel", "doctor"]:
        p = actions.add_parser(action)
        default_url = environ.get("TOOLGAP_URL") or (
            None if action == "doctor" else "http://127.0.0.1:30000"
        )
        p.add_argument(
            "--url",
            default=default_url,
            help="Server base URL; defaults to TOOLGAP_URL (or localhost for control)",
        )
        p.add_argument(
            "--timeout",
            type=positive_timeout,
            default=2.0,
            help="Per-request transport timeout in seconds (not an I/O reclamation deadline)",
        )
        p.add_argument(
            "--api-key-env",
            default="TOOLGAP_API_KEY",
            help="Environment variable containing the bearer key; value is never a CLI argument",
        )
        p.add_argument(
            "--json",
            action="store_true",
            help="One JSON report on stdout, including command errors",
        )
        if action == "submit":
            p.add_argument(
                "--prefix",
                required=True,
                help="Exact-prefix JSON object file, or - for stdin; max1MiB",
            )
            p.add_argument(
                "--operation-id",
                help="Unique ID; otherwise read from prefix file or generate a UUID",
            )
            p.add_argument(
                "--cache-salt",
                help="Original salt; conflicting file/flag values are rejected",
            )
            p.add_argument(
                "--ttl-ms",
                type=int,
                help="Usefulness TTL, default10000ms; never a timeout reclamation policy",
            )
        elif action in {"status", "cancel"}:
            p.add_argument("operation_id", help="The exact ID returned by submit")
        else:
            p.add_argument(
                "--sglang", type=Path, help="Local patched source checkout/archive"
            )
            p.add_argument(
                "--model",
                type=Path,
                help="Local pinned config/tokenizer directory; no download",
            )
            p.add_argument(
                "--gpu",
                action="store_true",
                help="Read local NVIDIA inventory; does not run CUDA/model code",
            )
    return root


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def read_prefix(path, stdin):
    if path == "-":
        stream = getattr(stdin, "buffer", stdin)
        data = stream.read(MAX_PREFIX_BYTES + 1)
    else:
        with Path(path).open("rb") as stream:
            data = stream.read(MAX_PREFIX_BYTES + 1)
    size = len(data.encode("utf-8")) if isinstance(data, str) else len(data)
    if size > MAX_PREFIX_BYTES:
        raise ValueError("Prefix JSON exceeds1MiB; provide a bounded saved prefix")
    value = json.loads(data, object_pairs_hook=_unique_object)
    if not isinstance(value, dict) or not isinstance(value.get("input_ids"), list):
        raise ValueError("Prefix must be an object containing an input_ids list")
    unknown = set(value) - {"input_ids", "cache_salt", "operation_id", "ttl_ms"}
    if unknown:
        raise ValueError("Unknown prefix fields: " + ", ".join(sorted(unknown)))
    return value


def validate_url(url):
    parsed = httpx.URL(url)
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise ValueError("Provide an http:// or https:// server URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "URL must not contain credentials, query or fragment; use --api-key-env"
        )


def prepare(args, stdin):
    if args.url is not None:
        validate_url(args.url)
    if args.command == "doctor":
        return None
    if args.command == "submit":
        payload = read_prefix(args.prefix, stdin)
        for key in ["operation_id", "cache_salt", "ttl_ms"]:
            flag = getattr(args, key)
            if (
                flag is not None
                and key in payload
                and (type(flag) is not type(payload[key]) or flag != payload[key])
            ):
                raise ValueError(f"Conflicting {key} in prefix JSON and command flag")
            if flag is not None:
                payload[key] = flag
        payload.setdefault("operation_id", uuid.uuid4().hex)
        payload.setdefault("cache_salt", None)
        payload.setdefault("ttl_ms", 10000)
        _validate_prefix(payload["input_ids"], payload["cache_salt"], payload["ttl_ms"])
    else:
        payload = dict(operation_id=args.operation_id)
    if (
        not isinstance(payload["operation_id"], str)
        or not 1 <= len(payload["operation_id"]) <= 128
    ):
        raise ValueError("operation_id must contain1..128 characters")
    return payload


def control_report(action, operation_id, state):
    if (
        not isinstance(state, dict)
        or state.get("operation_id") != operation_id
        or state.get("state") not in STATES
    ):
        raise ValueError("Unrecognized or foreign control result")
    if type(state.get("cleanup_pending")) is not bool:
        raise ValueError("Control result omitted cleanup confirmation")
    for key in [
        "requested_tokens",
        "restored_tokens",
        "restored_bytes",
        "host_available_tokens",
        "inflight_tokens",
    ]:
        if type(state.get(key)) is not int or state[key] < 0:
            raise ValueError(f"Control result contains invalid {key}")
    if state["restored_tokens"] > state["requested_tokens"]:
        raise ValueError("Published token count exceeds requested span")
    outcome = state["state"]
    fallback = outcome in {"DECLINED", "FAILURE", "MISS"}
    if state["cleanup_pending"]:
        message = "Logical termination is not physical cleanup. Recheck this operation with status; do not reclaim its host slots."
    elif outcome == "RUNNING":
        message = "Restore is in flight. Ordinary continuation need not wait for this CLI response."
    elif outcome in {"SUCCESS", "CACHED"}:
        message = "Prefix was published or already resident. L2 remains shared and evictable; cancelling completed work does not evict it."
    elif fallback:
        message = "Proceed with ordinary generation/cache matching. This control outcome does not promise a complete restored prefix."
    else:
        message = "Operation is terminal and cleanup is complete. Published shared L2, if any, remains evictable."
    # Do not relay arbitrary backend fields or credentials in machine output.
    keys = [
        "operation_id",
        "state",
        "cleanup_pending",
        "requested_tokens",
        "restored_tokens",
        "restored_bytes",
        "host_available_tokens",
        "inflight_tokens",
    ]
    if isinstance(state.get("elapsed_ms"), (int, float)) and math.isfinite(
        state["elapsed_ms"]
    ):
        keys.append("elapsed_ms")
    return dict(
        command=action,
        state=outcome,
        operation_id=operation_id,
        fallback_recommended=fallback,
        result={k: state[k] for k in keys},
        message=message,
    )


async def execute(args, payload, *, headers, transport=None):
    if args.command == "doctor":
        if args.url:
            async with httpx.AsyncClient(
                base_url=args.url.rstrip("/"),
                headers=headers,
                timeout=args.timeout,
                transport=transport,
            ) as http:
                report = await doctor(
                    sglang=args.sglang, model=args.model, gpu=args.gpu, http=http
                )
        else:
            report = await doctor(sglang=args.sglang, model=args.model, gpu=args.gpu)
        return {"PASS": 0, "FAIL": 1, "UNKNOWN": 3}[report["state"]], report
    operation_id = payload["operation_id"]
    try:
        async with PrefetchClient(
            args.url, headers=headers, timeout=args.timeout, transport=transport
        ) as client:
            if args.command == "submit":
                state = await client.submit(**payload)
            else:
                state = await getattr(client, args.command)(operation_id)
            return 0, control_report(args.command, operation_id, state)
    except PrefetchRejected as exc:
        # A 400 on status/cancel is not proof that remote work no longer exists.
        return 4, dict(
            command=args.command,
            state="REJECTED",
            operation_id=operation_id,
            fallback_recommended=True if args.command == "submit" else None,
            reason=str(exc),
            message="Server rejected the control request: "
            + str(exc)
            + ". Ordinary generation may fall back after rejected submit. Status/cancel rejection does not confirm cleanup.",
        )
    except Exception as exc:
        status = (
            exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        )
        return 3, dict(
            command=args.command,
            state="UNKNOWN",
            operation_id=operation_id,
            http_status=status,
            fallback_recommended=None,
            error_kind=type(exc).__name__,
            message=(
                "Authentication failed; check --api-key-env. "
                if status in {401, 403}
                else "Prefetch route is unavailable; check the patched runtime URL. "
                if status == 404
                else ""
            )
            + "Control outcome is uncertain. Use this operation ID to reconcile status/cancel; do not assume a timeout freed host slots.",
        )


def _redact(value, secret):
    if isinstance(value, str):
        return (value.replace(secret, "[redacted]") if secret else value)[:4096]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value


def emit(report, *, as_json, code, stdout, stderr, secret=None):
    report = _redact(report, secret)
    if as_json:
        text = json.dumps(dict(report, exit_code=code), ensure_ascii=False)
    elif "checks" in report:
        text = (
            "Requested checks: "
            + report["state"]
            + "\n"
            + "\n".join(
                f"[{c['state']}] {c['name']}: {c['detail']}" for c in report["checks"]
            )
            + "\n"
            + report["note"]
        )
    else:
        text = f"{report['command']}: {report['state']}"
        if report.get("operation_id"):
            text += "\noperation_id: " + report["operation_id"]
        if "result" in report:
            result = report["result"]
            text += f"\nrestored: {result['restored_tokens']} tokens / {result['restored_bytes']} bytes; cleanup_pending: {result['cleanup_pending']}"
        text += "\n" + report["message"]
    print(text, file=stdout if as_json or code == 0 else stderr)


def main(
    argv=None, *, stdout=None, stderr=None, stdin=None, environ=None, transport=None
):
    stdout, stderr, stdin = (
        stdout or sys.stdout,
        stderr or sys.stderr,
        stdin or sys.stdin,
    )
    environ = os.environ if environ is None else environ
    args = parser(environ).parse_args(argv)
    secret = environ.get(args.api_key_env)
    headers = {"Authorization": "Bearer " + secret} if secret else None
    payload = None
    try:
        payload = prepare(args, stdin)
        code, report = asyncio.run(
            execute(args, payload, headers=headers, transport=transport)
        )
    except (OSError, ValueError, httpx.InvalidURL) as exc:
        code, report = (
            2,
            dict(command=args.command, state="INVALID_INPUT", message=str(exc)),
        )
    except KeyboardInterrupt:
        code, report = (
            130,
            dict(
                command=args.command,
                state="UNKNOWN",
                operation_id=payload["operation_id"] if payload else None,
                message="Interrupted during read-only checks; no prefetch was submitted."
                if args.command == "doctor"
                else "Interrupted; remote work may still exist. Reconcile this operation ID before considering cleanup complete.",
            ),
        )
    emit(
        report,
        as_json=args.json,
        code=code,
        stdout=stdout,
        stderr=stderr,
        secret=secret,
    )
    return code
