# Reproduce on an existing NVIDIA L4 machine

No script provisions a VM or executes a Cloud Run job. Supply your own existing
GPU machine. The measured setup: Ubuntu 24.04, NVIDIA L4 24GB, driver 580.178.04,
8 vCPU / 32GiB RAM, 150GiB disk, Docker NVIDIA Container Toolkit 1.20.1.
The lock uses CUDA 13.0.3, PyTorch 2.13.0+cu130, Triton 3.7.1 and matching SGLang
kernels. Building downloads large CUDA layers, Python packages and the model;
allow at least ~50GB free disk. Driver must support CUDA 13.0. Use the validated
580.178.04 setup rather than assuming compatibility with an older driver.

## Source install

```bash
bash scripts/install.sh
# Checks HEAD against compatibility.json, requires pristine checkout,
# applies lifecycle first then feature, and checks whitespace.
```
A pre-existing checkout can be used with `python3 scripts/apply.py /path/to/sglang`
only at the exact upstream SHA and with no tracked/untracked changes. Apply is
one-shot; an already patched checkout is intentionally rejected. The installer
prepares source; dependencies below are a separate step.

## Container (recommended reproduction environment)

```bash
docker build -f repro/Dockerfile -t toolgap:v0.1 .
docker run --rm --gpus all --shm-size=2g toolgap:v0.1 tests
mkdir -p results/local
docker run --rm --gpus all --shm-size=2g \
  -v "$PWD/results/local:/results" toolgap:v0.1 demo
# Full 45 trials, no injected delays; save logs/JSON/trace:
docker run --rm --gpus all --shm-size=2g \
  -v "$PWD/results/local:/results" toolgap:v0.1 benchmark
```
These run on your host GPU, with no cloud API calls. Each run creates a unique
results directory. No automatic retries or automatic second execution. Docker
removes the container on completion; the bind-mounted evidence survives. A host
VM remains your responsibility to stop/delete. The historical Stage2B execution
had an absolute deletion deadline and was deleted; this repo never creates one.

The Dockerfile builds from the public pinned CUDA base and upstream SHA, applies
both local patches, installs the locked environment, and downloads
`Qwen/Qwen2.5-1.5B-Instruct` at
`989aa7980e4cf806f80c7fef2b1adb7bc71aa306`. No model or KV binary is redistributed.
The combined release image was not newly built/GPU-executed at publication;
the source patches and CPU/controller imports/tests were checked from a clean
checkout, and the recorded L4 results validate the pinned measured implementation.
The six-line backend guard added for release was tested on CPU only.

## Native commands inside that environment

```bash
export SGLANG_CHECKOUT="$PWD/vendor/sglang"
export PYTHONPATH="$SGLANG_CHECKOUT/python:$SGLANG_CHECKOUT/test/registered/unit/mem_cache"
export SGLANG_UNIFIED_RADIX_TREE_CORE_BACKEND=python
export CUBLAS_WORKSPACE_CONFIG=:4096:8 TORCH_CUDA_ARCH_LIST=8.9
export MODEL_PATH=/absolute/path/to/pinned-model
bash scripts/test.sh
bash examples/demo.sh
python benchmark/run.py --model-path "$MODEL_PATH" \
  --work-dir /tmp/toolgap-fresh-work --results-dir results/local/full \
  --repetitions 3 --gaps-ms 0 100 500 1000 3000
```
Use a fresh work directory; the benchmark refuses accidentally reusing its L3
source. Test files include inherited lifecycle fixtures. The 27 tests are
controller/API fixtures, not standalone GPU kernel coverage.

Runner flags: BF16, deterministic seed42, temperature0, 32 output tokens,
4096 inputs, TP1/PP1, max-running1, page16, context8192, max-total-tokens8192,
4GB resident HiCache, kernel/page_first/write_through, file backend,
wait_complete threshold64, Triton attention/PyTorch sampling, CUDA graphs off.
`server-command.json` preserves the exact flags.

## Recorded evidence / chart

```bash
bash examples/demo.sh --replay  # no GPU; verifies recorded data only
python -m pip install matplotlib==3.10.8
python scripts/plot.py
```
`results/trials.csv` is all 45 observations; `medians.csv` is the five-gap
aggregation. Raw JSON/trace preserve host occupancy, operation timing and backend
reads. TTFT is submit→first nonempty SSE output_ids. Full restore includes query,
allocation, read and ACK publication; it differs from file-I/O timing. At100ms
query work overlapped even when no file read finished before arrival.
