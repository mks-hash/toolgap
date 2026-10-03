FROM nvidia/cuda:13.0.3-cudnn-devel-ubuntu24.04@sha256:0230b7f243483cb15969fa3cc724a9459599604427052fc2a0d4291c7c0647dd
ENV DEBIAN_FRONTEND=noninteractive PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends python3.12 python3.12-venv python3.12-dev git build-essential libnuma1 libssl-dev ca-certificates curl && rm -rf /var/lib/apt/lists/*
RUN python3.12 -m venv /opt/venv
ENV PATH=/opt/venv/bin:/usr/local/cuda/bin:${PATH} CUDA_HOME=/usr/local/cuda
COPY . /opt/toolgap
WORKDIR /opt/toolgap
RUN bash scripts/install.sh
RUN pip install uv==0.12.21 && uv pip install --python /opt/venv/bin/python -r repro/requirements.lock --index-url https://pypi.org/simple --extra-index-url https://download.pytorch.org/whl/cu130 --index-strategy unsafe-best-match
RUN uv pip install --python /opt/venv/bin/python wheel==0.45.1 setuptools-scm==8.3.1 && SGLANG_BUILD_RUST_EXTS=none uv pip install --python /opt/venv/bin/python --no-build-isolation --no-deps -e vendor/sglang/python
RUN HF_HUB_DISABLE_XET=1 python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen2.5-1.5B-Instruct',revision='989aa7980e4cf806f80c7fef2b1adb7bc71aa306',local_dir='/opt/model',allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.jinja'])"
ENV SGLANG_CHECKOUT=/opt/toolgap/vendor/sglang MODEL_PATH=/opt/model PYTHONPATH=/opt/toolgap/vendor/sglang/python:/opt/toolgap/vendor/sglang/test/registered/unit/mem_cache SGLANG_UNIFIED_RADIX_TREE_CORE_BACKEND=python TORCH_CUDA_ARCH_LIST=8.9 MAX_JOBS=4 CUBLAS_WORKSPACE_CONFIG=:4096:8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 SGLANG_DEBUG_MEMORY_POOL=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["bash", "/opt/toolgap/repro/run.sh"]
CMD ["demo"]
