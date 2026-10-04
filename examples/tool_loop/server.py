"""Shared demo transport/server helpers, with no paid-resource provisioning."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


class Engine:
    def __init__(
        self, model_path, work, results, port=30000, *, max_running_requests=None
    ):
        self.model = model_path
        self.work, self.results, self.port = Path(work), Path(results), port
        self.trace = self.results / "tool-loop-trace.jsonl"
        self.url = f"http://127.0.0.1:{port}"
        self.process = None
        self.max_running_requests = max_running_requests
        self.http = httpx.AsyncClient(base_url=self.url, timeout=180)

    async def start(self, label, storage):
        command = json.loads((ROOT / "results/raw/server-command.json").read_text())
        command[:3] = [sys.executable, "-m", "sglang.launch_server"]
        for flag, value in [("--model-path", self.model), ("--port", str(self.port))]:
            command[command.index(flag) + 1] = str(value)
        if self.max_running_requests is not None:
            command[command.index("--max-running-requests") + 1] = str(
                self.max_running_requests
            )
        self.probe_dir = self.work / (label + "-probe")
        self.probe_dir.mkdir()
        paths = [str(ROOT / "examples/tool_loop/plugin"), str(ROOT / "benchmark/trace")]
        env = dict(
            os.environ,
            SGLANG_HICACHE_FILE_BACKEND_STORAGE_DIR=str(storage),
            HICACHE_BENCH_TRACE=str(self.trace),
            HICACHE_BENCH_LABEL=label,
            SGLANG_PLUGINS="toolgap_demo_trace",
            TOOLGAP_DEMO_PROBE_DIR=str(self.probe_dir),
        )
        env["PYTHONPATH"] = ":".join(paths + [env.get("PYTHONPATH", "")])
        (self.results / f"server-command-{label}.json").write_text(json.dumps(command))
        with (self.results / f"server-{label}.log").open("w") as log:
            self.process = subprocess.Popen(
                command,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.monotonic() + 180
        try:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(
                        f"Server {label} exited: {self.process.returncode}"
                    )
                try:
                    response = await self.http.get("/health", timeout=2)
                    if response.is_success:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.2)  # readiness polling, never simulated tool work
            raise TimeoutError(f"Server {label} startup exceeded180s")
        except BaseException:
            await self.stop()
            raise

    async def stop(self):
        proc = self.process
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                await asyncio.to_thread(proc.wait, timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                await asyncio.to_thread(proc.wait, timeout=10)
        self.process = None

    async def generate(self, input_ids, cache_salt, *, limit=128, rid=None):
        started = time.monotonic_ns()
        first, last = None, None
        payload = dict(
            input_ids=input_ids,
            cache_salt=cache_salt,
            sampling_params=dict(temperature=0, max_new_tokens=limit, sampling_seed=42),
            return_logprob=True,
            stream=True,
        )
        if rid is not None:
            payload["rid"] = rid
        async with self.http.stream("POST", "/generate", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: ") or line[6:] == "[DONE]":
                    continue
                last = json.loads(line[6:])
                if "error" in last:
                    raise RuntimeError(last)
                if last.get("output_ids") and first is None:
                    first = time.monotonic_ns()
        if last is None or first is None:
            raise ValueError("No generated tokens")
        return last, dict(
            submitted_ns=started,
            first_token_ns=first,
            generation_completed_ns=time.monotonic_ns(),
        )

    async def probe(self, prefix, salt):
        nonce = uuid.uuid4().hex
        data = dict(nonce=nonce, input_ids=prefix, cache_salt=salt)
        temporary = self.probe_dir / "request.tmp"
        temporary.write_text(json.dumps(data))
        temporary.replace(self.probe_dir / "request.json")
        target = self.probe_dir / (nonce + ".json")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if target.exists():
                result = json.loads(target.read_text())
                if "error" in result:
                    raise RuntimeError(result)
                return result
            await asyncio.sleep(0.01)
        raise TimeoutError("Scheduler residency probe timed out")

    async def ensure_storage(self, prefix, salt):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = await self.probe(prefix, salt)
            if state["storage_available_tokens"] == len(prefix):
                return state
            await asyncio.sleep(0.02)
        raise TimeoutError("Exact saved prefix was not persisted; cannot claim L3-only")

    async def flush(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = await self.http.post("/flush_cache", json={})
            if response.is_success:
                return
            await asyncio.sleep(0.02)
        raise RuntimeError("Memory-cache flush was not accepted")
