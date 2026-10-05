# Agent study: local readiness and evidence gates

The active plan is [WORK_TRACKER](../WORK_TRACKER.md). This guide describes
commands; it does not authorize a GPU session, launch a server or select a new
model. The Mistral live pilot remains 0/3. The later
[Qwen7 pilot](../../research/agent_resume/qwen7-live-pilot-2026-10-05.json)
also remains 0/3 useful tasks despite real tool execution and eight preserved
continuation prefixes. Pressure has not run; review repository retrieval and
source-evidence discoverability locally before another paid session.

Use a reviewed pinned profile and its cached tokenizer. Commands below run from
the repository root. Every output path must be new. Keep raw runs in ignored
`work/`; sanitize summaries before public inclusion.

## Prepare locally

```bash
export PYTHONPATH="$PWD/src:$PWD"
python -m research.agent_resume.pressure prepare \
  --profile "$PROFILE_FILE" --tokenizer "$TOKENIZER_DIR" \
  --output work/study/packet.json
python - <<'PY'
import json
from pathlib import Path
p = json.loads(Path('work/study/packet.json').read_text())['packet']['profile']
Path('work/study/profile.json').write_text(json.dumps(p, indent=2))
PY
python -m research.agent_resume.native_conformance \
  --profile work/study/profile.json --tokenizer "$TOKENIZER_DIR" \
  --output work/study/native.json
python -m research.agent_resume.check_pressure \
  --packet work/study/packet.json --tokenizer "$TOKENIZER_DIR" \
  --output work/study/scripted.json
```

The packet uses 4 maximum running server requests, 1 GB configured host pool,
12 fixed arrivals by default and at most 8 active clients. It includes exact
initial token IDs over pinned public source, not artificial filler or a tool
sleep. The scripted check runs real fixed repository tools with fabricated
model decisions. It cannot satisfy the useful-live gate.

Generate native evidence for the **packet profile**, not the original diagnostic
profile: changed resource settings change its fingerprint. Native reference
checks cover two canonical tool rounds and reference agreement; they do not
establish whether a model generates valid calls. The pinned Mistral no-ID native
call remains semantic-valid but unsupported for its HF continuation history.

## File storage and an existing approved server

Before starting the reviewed server, claim a new isolated directory:

```bash
python -m research.agent_resume.readiness \
  --profile work/study/profile.json --storage-parent "$L3_PARENT"
# Use the printed absolute directory as SGLANG_HICACHE_FILE_BACKEND_STORAGE_DIR.
```

Use a canonical absolute directory path. Do not reuse another profile's directory. Keep the generated identity file.
The namespace binds declared weights/revision, tokenizer, runtime, precision and
settings. Deployment JSON must include `storage_path`, `clock_domain` (Linux
boot ID plus time-namespace identity), model/revision/model_path, runtime_sha, resolved_cache_mode=`FULL`,
and the actual `pressure_match_observation` toggle. Declare
`admin_auth_required: true` for the detach/attach recipe below. The private plugin mailbox
must be mounted on the same host and named by `TOOLGAP_PRESSURE_PROBE_DIR`.
Use the existing research plugin/trace setup from the archived
[preparation](../archive/plans/PASSIVE_PRESSURE_PREPARATION.md); its older CLI
recipes are superseded by this guide.

The preflight probes metadata only. It checks the actual imported clean runtime
checkout, file directory, page size, host layout and KV storage dtype before
`/generate` or prefetch. Server package versions and relevant runtime source
hashes are retained. This is **not weight attestation**; fixed weights and no
hot swap remain study requirements. A packaged runtime without an inspectable
matching Git checkout fails closed in this study harness.

Pressure enforces cold whole-worker initialization: empty device/host KV, no
in-flight work and an empty claimed file directory. Restart/reset the whole
worker and use a fresh claimed directory between the useful diagnostic and
measured blocks. Do not flush/evict a target inside a measured tool gap. A
treatment checks observed capacities/layout/dtype/threshold against its baseline.
Freeze equal kernel/model warmup outside the measured blocks and validate the
cold-start procedure on the real server before interpreting performance. Empty
KV alone does not prove equal JIT/filesystem warmth.

## Warmup/reset source audit — local preparation, not live validation

Source inspected at SGLang runtime `3e60ad803c6b01832b527f4a1dcbeb7a5449964b`:

- `http_server._execute_server_warmup` uses a short text/input-ID request with
  at most 8 generated tokens. Startup readiness does not prove that the study's
  long prefill, continuation or concurrent request shapes are warmed.
- `Scheduler.flush_cache` requires full idle, including ongoing HiCache
  writes, loads, backups and prefetch. `UnifiedRadixCache._reset_full` resets
  the tree and host pool; `HiCacheController.reset` stops/restarts storage
  threads and clears controller queues/accounting. It does **not** delete L3
  files. A successful flush alone cannot satisfy the empty-file guard.
- `HiCacheFile` selects its directory from the server process environment.
  Its extra config is not a general directory-switch API. Do not assume an
  attach request can redirect a running server to a new namespace.

The next approved pilot must first validate this initialization recipe on the
actual server, outside all measured blocks:

1. Use the same startup settings and fixed warmup inputs in both arms. Retain
   the warmup request/config hashes and terminal outcomes. Include the packet's
   longest initial request and a real saved continuation from the useful live
   pilot, at the declared concurrency; use two fixed passes, not an adaptive
   loop until the timings look favorable. Native startup warmup is additional.
2. Drain all requests and cache transfers with authenticated
   `POST /flush_cache?timeout=30`, requiring HTTP success. This idle-gated
   flush preserves file L3. Detach the file backend using the existing
   idle-gated API and require success; flush device/host state again and
   require success. With storage workers detached and no callers, retain a private inventory
   of owned warmup-file names, sizes and streaming SHA256s (not a bulk upload
   of KV bytes), then reset only this dedicated study
   directory, retaining its profile claim. Never clear a shared cache or remove
   files while storage workers are active.
3. Reattach the same file backend/config/directory, require success, and verify
   the actual imported runtime, layout, zero GPU/L2 use, no in-flight operations
   and a file directory containing only its claim. This preserves the warmed
   model process while separating warmup KV from the measured workload.
4. Start a new raw trace segment and the frozen arrivals. No detach, flush,
   directory reset or target eviction is allowed inside a measured block.
   Repeat the same preparation for every calibration/treatment block.

Two actual CPU FULL/file fixtures now exercise reset and detach/reset/reattach:
resident pools return to baseline, flush preserves L3 bytes, the detached
fixture directory can be cleared, and the next genuine restore works. This is
a locally prepared execution recipe, not a claim that live HTTP/GPU
reset/warmup equivalence passes. Validate detach/reattach and the probe's
post-reset view before using it; failure stops the pressure path. The owned
warmup directory remains profile-bound and raw warmup records stay private.
Persistent compiler caches and OS file-cache warmth must be recorded and held
constant where possible; residual first-use effects remain a limitation, not a
reason to discard slow or failed callers. Live observation-on/off calibration
is still required. No GPU/server action is performed by this source audit.

## Admin setup prerequisite

The pinned HTTP detach/attach endpoints require a configured admin key. Start
only a same-host study server bound to `127.0.0.1`, with `--admin-api-key` set to
an ephemeral private key. Keep normal generation API authentication unset for
this study. Set the matching `TOOLGAP_STUDY_ADMIN_KEY` only in the client process
environment; never put the value in a profile, deployment JSON, recorded command
or public log. `admin_auth_required` records presence, not the credential.
The live/pressure harness passes it to the existing `PrefetchClient(headers=...)`
and rejects a mismatched declaration. Returned keys and `launch_command` are
excluded from its retained server-info manifest.

Before warmup, test authenticated DELETE/PUT on the **dedicated idle study
worker**. The endpoints are `DELETE /hicache/storage-backend` and
`PUT /hicache/storage-backend`; PUT JSON is:

```json
{
  "hicache_storage_backend": "file",
  "hicache_storage_backend_extra_config_json": null,
  "hicache_storage_prefetch_policy": "wait_complete",
  "hicache_write_policy": "write_through"
}
```

Use the exact declared extra config if non-null. Send the private Bearer header,
require HTTP 200, and bound each attempt at 30 seconds. POST `/flush_cache`
also uses that header and must return 200. A rejected/failed operation stops the
block; do not continue with a changed backend, retry indefinitely or perform
an unauthenticated fallback. Directory archival/cleanup occurs only after
successful detach, with no callers, inside this worker's owned namespace.
Reset requests are outside measurement and never evict a measured target.

## Bounded useful-model pilot proposal

The proposed first profile is the already pinned `Qwen/Qwen2.5-7B-Instruct`
revision `a09a35458c702b33eeacc393d103063234e8bc28`, using its pressure overrides.
This is a size extension of the historical Qwen control, not independent-family
evidence or a declaration of live support. Qwen3 remains an unprepared candidate;
Mistral's 0/3 live failure is unchanged. No model is silently substituted on fit
or task failure.

Local packet preparation produced 12 distinct source-audit contexts of
3801–3994 tokens. The derived profile passed two-round native reference checks,
and scripted model decisions ran all 12 useful CPU-tool trajectories, including
108 fixed regression executions. These checks validate mechanics; actual model
selection/continuation/grading remains NOT_RUN.

The pinned config declares FULL attention (`use_sliding_window=false`), 28
layers and 4 KV heads of dimension 128. Raw BF16 KV is 57,344 bytes/token:
8192 device tokens occupy 448 MiB before pool/runtime overhead; one decimal-GB
host budget could hold about 17,424 page-aligned tokens before overhead. Actual
resolved pools must be observed. Config-derived dense parameter accounting is
about 7.616 billion parameters (14.19 GiB of BF16 weights), excluding runtime,
activations, graphs and allocator overhead. This is **not an L4 fit guarantee**.
Use TP1/PP1, BF16, context/device budget 8192, host budget 1 GB, four server
requests and eight active clients. No precision or resource change on failure.

Proposed session has a 60-minute execution ceiling including setup and cleanup;
VM creation/time/cost and automatic deletion remain subject to a separate
reviewed provisioning preflight and explicit authorization. This guide never
creates a VM. Do not spend paid time rewriting the image or debugging model
protocols; retain failures and stop. Stages consume the remaining ceiling, not
independent renewable budgets:

| Stage | Maximum allocated time | Stop rule |
|---|---:|---|
| Existing image/runtime setup and model load | 15 min | Setup/fit fails or needs architecture/image changes |
| Useful live gate, 3 declared tasks | 10 min | Any task fails, lacks actual tools/continuation, or cleanup is ambiguous |
| Fixed warmup and actual reset check | 5 min | Idle/auth/reset/namespace guard fails |
| Observation calibration and baseline | 20 min | Quality fails, instrumentation perturbs outcomes, or no usable observed window |
| Conditional proactive feasibility | 5 min | No time remains, quality/cleanup fails, or aggregate outcome degrades |
| Result archival and VM cleanup | 5 min reserved | Always execute, including earlier failures |

Before spending time on repeated blocks, verify that a single block fits its
allocation. Do not truncate a slow caller to label the block successful. Timeout
retains it as failed/cancelled and terminates the study. If the proposed sequence
cannot fit, report incomplete calibration/performance rather than exceed the
ceiling or add a paid retry.

The first observed ordinary block is an early feasibility gate. If its useful
quality, cleanup, trace or natural-candidate gate fails, retain the block and
stop before the remaining calibration. No candidate at the sampled instants is
not proof of no possible window; report only this block/workload point.

Calibration uses four ordinary request-time blocks in fixed **on/off/off/on**
order, with this identical frozen packet. Each worker process starts with its
own mailbox, owned storage directory, `HICACHE_BENCH_LABEL` matching its output
basename and dedicated trace. Set `TOOLGAP_PRESSURE_MATCH_OBSERVATION=0` for off,
`1` for on, and match deployment metadata plus `--observation off` or
`memory-and-stat`. The toggle and label are process environment; changing the
client shell does not reconfigure an existing server. Restart only between
whole blocks, then repeat the identical fixed warmup/reset protocol. Keep the
same persistent compiler-cache policy, no global OS cache drop, and retain
residual warmup/order effects as limitations.

Report all-caller quality, successful tasks/block-second, arrival-to-finalization
latency (including client queue and owned cleanup), useful full task latency,
continuation TTFT and tool-dispatch-to-first-token for every block, including
failures. Also retain scheduler service time, sample completeness and natural
L3 candidates in the on blocks. As a conservative feasibility stop, any quality
loss or more than 5% median arrival-to-finalization-latency degradation / throughput loss in
either matched on-versus-off pair prevents a speedup interpretation. Two pairs
are descriptive calibration, not a statistical non-inferiority claim.

Only after a successful useful gate, reset and calibration, and baseline
observed windows, run proactive C then ordinary B with observation on if time
remains. Bind C to an earlier on-baseline with `--baseline`. This gives a bracketed
B/C/B feasibility sequence, not a replicated counterbalanced experiment; the
single C block must not be counted twice as independent evidence. All blocks retain all 12 callers. Later
observed eligibility can be unreachable by the once-at-dispatch trigger;
`dispatch_state=UNKNOWN` stays explicit. No adaptive resubmission, favorable-run
selection or manufactured target eviction. The comparison remains exploratory:
no confidence/p95 claim, no release claim, and no automatic second session.

## Live gate, then baseline — only with applicable execution approval

```bash
python -m research.agent_resume.live \
  --profile work/study/profile.json --tokenizer "$TOKENIZER_DIR" \
  --native-evidence work/study/native.json --deployment "$DEPLOYMENT_JSON" \
  --server "$SERVER_URL" --probe-dir "$PROBE_DIR" \
  --mode request_time --output work/study/live
# Proceed only if readiness.json records study_success=true.
python -m research.agent_resume.pressure run \
  --packet work/study/packet.json --tokenizer "$TOKENIZER_DIR" \
  --native-evidence work/study/native.json --live-evidence work/study/live \
  --deployment "$DEPLOYMENT_JSON" --server "$SERVER_URL" \
  --probe-dir "$PROBE_DIR" --observation memory-and-stat \
  --mode request_time --output work/study/baseline
# Retain the dedicated raw server trace as baseline/server-trace.jsonl.
python -m research.agent_resume.trace_report \
  --block work/study/baseline --trace work/study/baseline/server-trace.jsonl \
  --output work/study/baseline/trace-report.json
```

`readiness.json` separates procedure completion from useful study success.
Failed tasks stay in the denominator. Pressure rejects missing/stale native or
live evidence before HTTP effects; it binds the exact profile, harness/SDK source
hashes, packages and raw artifacts. Live checks do not promote resource fit,
pressure or performance to PASS.

A proactive feasibility block additionally requires `--baseline` and the same
packet/instrumentation, bound raw trace, quality/cleanup success and observed
natural L3 candidates. Missing opportunities stop this path. The gate labels it
an **exploratory whole-worker comparison**, with dispatch reachability UNKNOWN;
it cannot establish statistical performance or matched initialization by itself.
Counterbalance block order and retain all callers. No automatic retry or delayed
prefetch/resubmission policy is introduced.

## What the samples mean

The frozen budget is 100 ms intervals, at most 8 samples per tool round, 50 ms
per sample. Tools and continuation requests never await samples. An initial
request, periodic requests and a continuation-boundary request run in the
background; cleanup reaps client tasks after the trajectory timing ends. A
cancelled request already read by the scheduler may leave a late private mailbox
reply; the nonce is never reused. Client task cleanup is not a claim about
operation-specific KV consumption or completion of all server file writes.

Each sample records requested/returned time, server read/observation times,
boot/time-namespace clock domain, page-aligned residency and optional direct file stat. File presence
is only a candidate: a nonresident available span meeting the observed cache/controller prefetch
threshold is reported (256 tokens in the default pinned runtime),
not successful reads, publication or consumption. Late, missing, invalid and
cross-clock samples remain UNKNOWN. A sample crossing continuation arrival is
excluded from pre-arrival opportunity summaries. Samples after tool completion
cannot establish overlap with useful tool work. Sparse negative samples do not
prove that no opportunity existed between them.

A background sample cannot establish cache state exactly at dispatch.
`dispatch_state=UNKNOWN` is intentional. Transitions have interval bounds and
observed remaining tool/continuation windows. The once-at-dispatch prefetch may
miss later eviction after a terminal CACHED response; do not condition the
whole-worker result on treatment-induced cache state.

Client observer wait is not active CPU cost or imposed tool delay. Probe cost
and full mailbox-service duration are recorded separately; service duration
excludes its trace write. Net contention/perturbation still needs matched live
observation-on/off calibration: use the same request-time packet on cold workers,
with `--observation off` and `--observation memory-and-stat`, counterbalance
order and retain quality failures. Set the matching server toggle in each
deployment. A small calibration is descriptive feasibility evidence. Operation-specific consumption and wasted bytes
remain null when unproved. Primary endpoint: successful tasks per block second,
subject to all-caller quality/cleanup and an explicit competing-caller degradation
limit. Caller-level samples are not independent worker repetitions.

## Accounting review after the capacity stop (2026-10-05)

Measurement contract **v2** retains every declared caller on interruption, even
those still queued or not yet arrived. Cancelled latencies are censored (`null`),
not successful short executions. Partial generated token IDs remain evidence.
An interrupted block records `procedure_completed=false` and
`study_success=false`, finalizes its manifest and cannot serve as a baseline.

Throughput uses the arrival epoch through the last caller's finalization and
row recording, including owned cleanup. The descriptive 5% gate uses
`all_caller_arrival_to_finalized_ms`; completed useful latency remains separately
reported. Comparison rejects incomplete/censored/incorrect blocks or unresolved
cleanup rather than filtering those callers. Server setup, warmup and teardown
remain outside this endpoint and are separately bounded.

The old provisioning packet/bundle implements v1 and is superseded. Its launch
readiness flag is disabled; historical evidence is retained unchanged. A local
reviewed runner uses the early on-baseline gate and the v2 comparator, without
launching any server. Before another authorized paid attempt, freeze the revised
clean source, regenerate the packet, run its offline checks and rebind the
launch/package hashes. No GPU/live reset/calibration/pressure result is implied.
