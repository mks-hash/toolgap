# Control CLI and read-only diagnostics (v0.3.0)

This CLI is included in experimental `v0.3.0`. Install from its tagged checkout
or its release wheel. The v0.2.0 package predates these commands.
SGLang runtime patches and existing GPU measurements are unchanged.

## Install from the v0.3.0 checkout

Use a Python 3.10+ environment. Only the existing httpx dependency is needed for
CLI commands; no SGLang, Torch or model package is imported by the CLI itself.

```bash
python -m pip install -e .
toolgap --help
# Equivalent module entry point:
python -m toolgap --help
```

The following commands use an **already running** compatible SGLang server.
They do not create infrastructure or download models. With no `--url` or
`TOOLGAP_URL`, control commands target `http://127.0.0.1:30000`.
Doctor makes network requests only when `--url` or `TOOLGAP_URL` is supplied.

## Exact-prefix input

`--prefix` accepts a JSON object file or `-` for stdin. Supply `input_ids` as the
actual saved nonnegative integer token sequence; supply its original
`cache_salt` if one was used. Do not decode/re-encode history or derive the salt
from an arbitrary session label. Optional fields are `operation_id` and `ttl_ms`.

The JSON must contain only those four fields, with no duplicate keys. Conflicting
file and flag values are rejected locally. JSON is bounded to 1MiB; token IDs must
be integers, not booleans/floats. TTL is 1..60000ms, default 10000ms. Operation ID is
1..128 characters; salt is at most 256 characters. These checks do not prove the
prefix exists in storage. Runtime storage threshold/page alignment still apply
(64-token threshold, 16-token pages in the validated setup).

Generate a **new unique operation ID per attempt**. If no ID is supplied, the
CLI generates a UUID and returns it. Repeating a retained ID can return a
historical outcome rather than rewarming an evicted prefix. An old ID must never
be redirected to replacement work.

For example, export from a `source-prefix.json` produced by your own successful
ToolGap tool-loop demo:

```bash
python - /path/to/your/demo/results/source-prefix.json <<'PY'
import json, sys, uuid
from pathlib import Path
saved = json.loads(Path(sys.argv[1]).read_text())
Path('prefix.json').write_text(json.dumps({
    'input_ids': saved['prefix_ids'],
    'cache_salt': saved['cache_salt'],
    'operation_id': uuid.uuid4().hex,
    'ttl_ms': 10000,
}))
PY
```

Preserve the same model/tokenizer and storage namespace. A file copied from
published benchmark data alone does not recreate the KV payloads on your server.

## Submit, status, cancel

```bash
toolgap submit --prefix prefix.json --url http://127.0.0.1:30000 --json
# Copy operation_id from the response:
toolgap status OPERATION_ID --url http://127.0.0.1:30000 --json
toolgap cancel OPERATION_ID --url http://127.0.0.1:30000 --json
# Explicit values are optional and must agree with any fields in the file:
toolgap submit --prefix exact-ids-and-salt.json --operation-id UNIQUE_ID --ttl-ms 10000
# Streaming input:
cat prefix.json | toolgap submit --prefix - --json
```

Each invocation sends one control RPC. There are no retries, automatic polling,
queues, generation calls, local admission state or implicit cleanup. Independent
CLI processes rely on server admission; they do not share `PrefetchAdmission`.
The CLI cannot replace an asynchronous tool-loop integration: run useful tool
work concurrently, and submit continuation when the tool completes without
waiting for a separate status/CLI process. See [integration policy](TOOL_LOOP.md).

Without `--json`, successful output goes to stdout, command errors to stderr.
With `--json`, one report including `exit_code` goes to stdout. Invalid argparse
syntax still prints standard usage to stderr and exits 2.

A successful RPC can report any valid runtime outcome, including MISS, FAILURE
or DECLINED. Inspect `state`, `fallback_recommended`, and `result.cleanup_pending`;
exit 0 alone does not imply a successfully restored prefix.

- `RUNNING`: restoration is in flight. No pre-arrival H2D is performed.
- `SUCCESS` / `CACHED`: the operation published KV or found resident KV. These
  are historical observations; L2 remains shared and evictable. They do not
  guarantee it will still be resident at a later request.
- `MISS` / `FAILURE` / `DECLINED`: use ordinary generation/cache matching. A MISS
  can have published a partial span; it is not a promise of a full prefix.
- `CANCELLED` / `EXPIRED` with `cleanup_pending=true`: logical termination has
  happened, but allocated read destinations may still be owned by in-flight I/O.
  Recheck status; do not reclaim slots speculatively.
- Cancellation after publication may return `SUCCESS`; it does not evict L2.
- `UNKNOWN` (CLI transport/protocol outcome): acceptance or cleanup is uncertain.
  Preserve the reported operation ID and explicitly reconcile status/cancel.
  No automatic resubmit occurs. `--timeout` is a per-request transport timeout,
  **not** a safe backend-I/O reclamation deadline.
- `REJECTED`: server rejected control and its reason is shown. Submit may fall
  back; a rejected status/cancel does not prove that remote work is gone.

Interrupting a control command exits 130 and retains the prepared operation ID
when available. The terminal can show that ID even if HTTP acceptance was lost.
Permanent blocked I/O still has no safe automatic reclamation guarantee.

## Authentication

Use an environment variable rather than putting a bearer key in argv:

```bash
# Set TOOLGAP_API_KEY privately in your shell/environment, if required by server.
toolgap status OPERATION_ID --json
# For an existing differently named variable:
toolgap status OPERATION_ID --api-key-env MY_SGLANG_ADMIN_KEY --json
```

The selected key is sent as `Authorization: Bearer ...` and redacted from reports.
URLs containing userinfo, query parameters or fragments are rejected. The CLI
prints a whitelist of result fields, not the entire server configuration.
Existing SGLang admin authorization governs access; no new auth scheme is added.

## Doctor

Offline source/tokenizer checks:

```bash
toolgap doctor --sglang /path/to/patched/sglang --model /path/to/pinned/model
```

Checks use the existing demo's pinned manifest: eight production source files
and five tokenizer/config files. `validated_source_commit` identifies the
reference manifest; it is not an assertion about checkout Git HEAD or all files
in the tree. Hash matches do not verify model weights, cached KV, dependency
compatibility or remote/local model equivalence.

Optional local GPU inventory:

```bash
toolgap doctor --gpu
```

This runs read-only `nvidia-smi` with a 5s limit and reports driver/GPU memory plus
installed Torch package metadata when present. It does not import Torch, call
CUDA, generate tokens or certify driver/CUDA compatibility. It applies to the
machine running the CLI, not a remote server behind `--url`.

Read-only remote diagnostics:

```bash
toolgap doctor --url http://127.0.0.1:30000 --json
# Combine only the checks you want:
toolgap doctor --sglang /path/to/sglang --model /path/to/model --gpu \
  --url http://127.0.0.1:30000 --json
```

Remote diagnostics send GET only to `/openapi.json`, `/server_info`,
`/hicache/storage-backend`, `/model_info`. They report route declaration, startup
resident-cache settings, TP1/PP1/DP1, live file backend and the reported Qwen2
architecture. They cannot prove resident FULL component ownership, source SHA
of the running process, exact model revision, valid payloads, successful restore
or GPU execution. A declared OpenAPI route alone does not prove runtime admission.
`/health` and `/health_generate` are deliberately excluded: the pinned server
can generate a token on `/health` when its generation flag is enabled.
Metadata availability does not establish generation readiness.

The backend-status GET requires configured admin credentials in the pinned
runtime, even when prefetch's ADMIN_OPTIONAL endpoint can operate without them.
In that case `live_backend` is UNKNOWN, not a claim that prefetch is disabled.
Non-object/missing configuration values and unreachable endpoints also remain
UNKNOWN. No substitute submit, generation or backend mutation is used to probe.

**PASS means only that the requested checks passed.** Every doctor report states
`restore_exercised=false` and `cache_state_verified=false`. Running doctor with
no targets reports UNKNOWN and explains the available options.

## Exit codes

| Code | Meaning |
|---:|---|
|0|Valid control reply (inspect state), or all requested doctor checks passed|
|1|A doctor check failed|
|2|Invalid local input/file/URL, or argparse usage error|
|3|Uncertain control transport/protocol, or incomplete/UNKNOWN doctor checks|
|4|Explicit server control rejection|
|130|Interrupted; remote control outcome may remain uncertain|

## Local verification

[Recorded result](../archive/evidence/CLI_VALIDATION.md): CPU regressions, installed wheel and
localhost HTTP fixture. This is separate from the existing
[two-caller GPU smoke](../archive/evidence/MULTI_SESSION_GPU_SMOKE.md); no new GPU run was performed
for this CLI increment. Model, runtime patches and benchmark data are unchanged.

```bash
bash scripts/test_client.sh
```
