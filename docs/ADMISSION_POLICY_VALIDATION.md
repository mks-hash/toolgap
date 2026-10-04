# Caller-hint admission: CPU validation

Date: 2026-10-04. Local development based on ToolGap `5dbcd2b` (bounded
reconciliation) and pinned patched SGLang
`3e60ad803c6b01832b527f4a1dcbeb7a5449964b`. Python 3.12.14.

## Results

| Check | Result |
|---|---|
| Combined existing lifecycle/runtime/API and all ToolGap CPU tests | **130 passed**, 58 subtests passed, zero failures/skips |
| Standalone client/tool/admission/CLI suite | **85 passed**, zero failures/skips |
| New hint/decision/timing tests | **9 passed** |
| New real file-backend/allocator eligibility fixtures | **2 passed** |
| New ordinary tool/continuation fallback integration | **PASS** |
| Offline later-arrival and eligibility command | **PASS** |
| Local wheel build and imports/controls directly from wheel | **PASS** |
| Changed-source Ruff lint/format, compileall, shell syntax, diff whitespace | **PASS** |
| Original v0.1/v0.2 evidence replay | **PASS**, datasets unchanged |

The combined suite emitted 22 pre-existing dependency/configuration warnings;
none is a failure or skip. No GPU was provisioned or executed, and the SGLang
runtime checkout remains clean. The added policy does not have a GPU performance
result. Existing published datasets, report and upstream PR branches were not
changed.

## Behaviors covered

Resident and below-threshold hints decline before acquiring a local slot or
making HTTP requests. Their historical status/cancel operations remain local.
Unknown or partial estimates preserve ordinary admission; the overlap filter is
disabled by default. Boundary equality admits, and zero estimates can decline
when a positive threshold is explicitly selected. All hints/configuration are
validated before ownership mutation; frozen hints and copied decision snapshots
preserve the supplied prefix/salt and contain no inferred consumption.

Local decline cannot clear a pre-existing UNKNOWN or pending owner. An apparently
short job can be declined while a later eligible job uses the free slot. Existing
cancel, timeout, late-reply, replacement, budget and shutdown tests also pass.

Local reservation time keeps increasing while cleanup is pending and freezes at
confirmed release. Historic status/cancel does not double-count release or slot
duration. Locally declined work has no reservation or release count.

Real file-backend fixtures establish two additional checks:

- Below-threshold cold work causes **no control submit or backend read**, leaves
  host capacity at baseline, and a subsequent eligible operation restores the
  same 12-token prefix with one backend read. Conservation checks pass.
- A verified 12-token host-resident prefix can be locally declined without a
  control RPC/read or changing ordinary prefix matching and resident accounting.

The existing trajectory workflow forwards an optional hint, runs the tool and
correct mocked continuation on decline, and finalizes its local lease normally.
This is orchestration correctness, not new model inference evidence.

## Offline control fixture

```bash
python examples/admission/local_check.py --output work/admission-policy/local-check.json
```

| Case | Observed control outcome |
|---|---|
| Manual observation; remote owner completed, later caller arrives before owner reconciles | later caller `LOCAL_BUSY` |
| Bounded reconciliation; later caller arrives after confirmed cleanup while owner still unfinished | later caller `ELIGIBLE` |
| Explicit resident hint | `LOCAL_RESIDENT`, 0 RPCs |
| 50 ms tool / 350 ms restore estimate, 100 ms threshold | `LOCAL_LOW_OVERLAP`, 0 RPCs |
| 600 ms tool / 350 ms restore estimate | one submit; mock server outcome authoritative |
| Unknown estimates | one submit; mock server outcome authoritative |

Completion is explicitly synthetic. No useful tool work, storage, model or GPU
runs in this command. Its local timing values are fixture-specific, not TTFT or
agent latency. The reconciliation case makes two submits/two statuses versus
one/one in the manual case because it admits the second operation; that RPC
difference is not a same-workload polling-overhead measurement.

## Reproduction and artifacts

```bash
python -m pip install -e .
bash scripts/test_client.sh
SGLANG_CHECKOUT=/path/to/pinned/patched/sglang bash scripts/test_admission_cache.sh
```

The real-cache command needs the existing compatible CPU SGLang environment.
For the full 130-test suite, use the combined command/environment in
[reconciliation validation](RECONCILIATION_VALIDATION.md); it includes all added
tests. Provide the pinned local tokenizer via `TOOLGAP_TOKENIZER_PATH` for the
optional tokenizer identity fixture, as in this run.

Local ignored artifacts: `work/admission-policy/combined-cpu.log`,
`client-suite.log`, `local-check.json`, `wheel-build.log`, `wheel-import.log` and
`dist/`. The wheel was built using the installed setuptools build backend, then
imported directly from its archive in a fresh process. Resident/short hints sent
zero RPCs; an eligible prefix sent one. This is a **local development wheel**
with unchanged 0.3.0 package metadata, not a replacement published release.

No new throughput, fairness, optimal-threshold, waste reduction or net-latency
claim follows from these checks. See [design and future measurement](ADMISSION_DESIGN.md).
