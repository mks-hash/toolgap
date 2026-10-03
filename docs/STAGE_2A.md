# Stage 2A GPU validation — 2026-10-03

**The intended resident full-attention, file-backend, TP1/PP1 correctness scope passed on a real L4.** The original preflight assertion “47 passes, zero skips” did not hold: the unchanged 47-test selection contains six explicitly SWA-only skips in full-attention fixtures. Exact outcome is **41 passed / 0 failed / 6 skipped**. These skips are not missing CUDA support and are not counted as passes. SWA validation, distributed recovery, permanent backend hangs, proactive prefetch and performance claims remain outside this result.

```text
STAGE_2A_VALIDATED: YES — resident full-attention / file / TP1 PP1
47_TESTS: 41 passed / 0 failed / 6 skipped
STRICT_47_ZERO_SKIPS_GATE: NO
REAL_L3_L2_H2D: PASS
DETERMINISTIC_GENERATION: PASS — exact output token IDs
LIFECYCLE_FAILURE_PATHS: PASS — 10/10
GPU/DRIVER/CUDA: NVIDIA L4 / 580.178.04 / CUDA 13.0
PyTorch: 2.13.0+cu130
TOTAL_RUNTIME: 23m06s, from create-command start through cleanup
ESTIMATED_COST: ~$0.34 conservative VM+disk+IPv4 estimate, not a billing invoice
BLOCKER: none within the tested scope
SAFE_TO_START_STAGE_2B: YES — limited scope above
VM_DELETED: YES
BOOT_DISK_DELETED: YES
```

## Environment and provenance

Project `[validation-project]`; VM `hicache-stage2a-l4`; `us-central1-a`, STANDARD `g2-standard-8`, 1×L4 (device reports 23034MiB), 8vCPU/32GiB, 150GiB pd-balanced. Exact Ubuntu image `ubuntu-2404-noble-amd64-v20260918`. Driver loaded without an installation reboot; Container Toolkit1.20.1-1 and Docker29.1.3. L4 SM89, actual CUDA arithmetic and imports passed. FlashInfer0.7.0.post1, sgl-kernel0.4.8.

The same immutable image was pulled and used for both attempts:

`us-central1-docker.pkg.dev/[validation-project]/hicache-validation/stage2a@sha256:4ae0bb2222247e51d146ff0cb9807240d5abbfe7d1b5d7eb1c9db0b072da07ec`

No image rebuild, image filesystem edit, source commit change, new model download, quota request, region fallback or Cloud Run operation occurred. SGLang commit `37d07d69b62181ca8713b31441218b0591da36de`; reverse-apply check of the lifecycle patch passed in the corrected execution. Only existing repository-scoped Artifact Registry reader was added for the runtime service account; bucket objectCreator was reused.

## Setup failure and correction

First attempt: 21 passed,20 failed,6 skipped. The JIT-built native hash extension could not map an executable segment from `/work/cache/extensions/...so`. Docker's tmpfs mount was missing explicit `exec`. All failure traces and JUnit were uploaded and downloaded before repair. VM was stopped for the correction.

Runtime correction used `/work:rw,exec,size=6g,mode=1777`. The container verified `/proc/self/mounts` contains no `noexec` for `/work`. The same source, image and exact47-test node selection then passed all applicable tests. The image's original `cuda_tests.sh` has an unconditional zero-skips assertion which cannot accept six built-in SWA-only skips. Consequently, `runtime_setup_correction.sh` invoked the identical pytest command and existing unmodified `real_model.py` separately through a host-side entrypoint override. It saved `strict_47_zero_skips_gate=false` explicitly; this report does not claim that the original image ENTRYPOINT became green. The host-side harness continued only after zero test failures/errors and verification that every skip reason was exactly the SWA-only reason.

The controlled correction restarted the same VM once. There was no automatic failure retry loop or extended deletion deadline. Future runs must use the explicit exec mount and an accurate test-selection/skip policy; the historical original zero-skips runner should not be presented as validated.

## GPU lifecycle tests

All ten finite failure/cancellation regression tests passed:

- cancel before host allocation;
- cancel allocated slots before read;
- cancel during read followed by late success and duplicate terminal acknowledgement;
- nonroot anchor-lock release after failure;
- file disappearing after query;
- late completion with replacement operation;
- partial progress followed by read failure;
- query exception with surviving worker;
- arbitrary read exception with surviving worker;
- short file/read failure with surviving worker.

Exact names and traces are in `results/validated/results/cuda.xml`. These are existing regression assertions, not a guarantee for a permanently blocked backend or distributed exception recovery. The six skipped tests are `test_release_aborted_request_l3_prefetch_io_in_progress` and `...io_done`, each in FULL page-size1/4/16 classes, with reason `SWA-only fixture required to exercise extra pool`.

## Actual model/cache proof

Unmodified validator `/opt/plan/real_model.py`, baked Qwen/Qwen2.5-1.5B-Instruct revision `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`, BF16, deterministic inference seed42, temperature0, 4096 input tokens and32 output tokens. Resident host pool4GiB, file L3, kernel I/O, page_first/page16, write_through and wait_complete, TP1/PP1; local-only servers.

Producer cold generation cached0 tokens. Producer warm request hit4080 device tokens. Producer was stopped. A fresh consumer with initially empty L1/L2 used the same L3 files:

- response `cached_tokens_details`: device0,host0,**storage4080**;
- `sglang:prefetched_tokens_total`: **4080**;
- `sglang:prefill_effective_tokens_total{mode="storage_hit"}`: **4080**, demonstrating the restored prefix was consumed by inference;
- subsequent ordinary request used4080 device tokens and completed successfully;
- cold, warm, restored and subsequent outputs had identical32 token IDs;
- 258 L3 files were recorded in the hash manifest.

`real-model-result.json` reports PASS. Host and container exit statuses are both0. This is output-token determinism, not a bitwise claim for every intermediate tensor/log probability, and not a benchmark of proactive prefetch.

## Timing, cost and cleanup

Create command18:53:08UTC; initial allocation/start18:53:18.219UTC. First stop timestamp19:05:53.190UTC. Corrected start19:09:18.761UTC; suite final evidence approximately19:14:45UTC; cleanup completed19:16:14UTC. Whole wall interval23m06s. The estimate conservatively charges the entire wall interval, including the stopped interval, at $0.879172212/hour (VM/L4 +150GiB balanced disk +ephemeral IPv4): **$0.3385**, rounded **$0.34**. Taxes, existing registry storage and small result-storage/API charges are separate. Actual billing has not been fetched.

Original native DELETE deadline21:43:08UTC remained unchanged after restart. Guest shutdown and explicit deletion completed much earlier. Read-only lists confirmed both VM and boot disk are absent (`evidence/instances-after-cleanup.json`, `evidence/disks-after-cleanup.json`). Local deletion timer was cancelled by cleanup. Registry image, service account and result bucket were retained as planned; no GPU resource remains.

## Durable evidence

Successful artifacts:

`gs://[validation-project]-hicache-stage2a-results/ce-hicache-stage2a-l4-setupfix-20261003T190957Z/`

First-attempt artifacts:

`gs://[validation-project]-hicache-stage2a-results/ce-hicache-stage2a-l4-20261003T190217Z/`

Both prefixes were downloaded under `compute_l4_preflight/results/`. Final host archive was safely extracted to `results/validated/results/`, including `cuda.xml`, `cuda-outcomes.json`, `real-model-result.json`, model responses, metrics, L3 manifest, source patch/provenance, stack.json, logs and both exit statuses. `VERDICT.json` is the machine-readable final result.

Stage2B implementation has not started. This evidence supports beginning the bounded single-worker resident full-attention proactive-prefetch experiment; it supplies no proactive performance result.
