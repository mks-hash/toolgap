"""Offline native-tokenizer checks. Scripted decisions are never model evidence."""

import argparse
import asyncio
import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path

from .adapters import FamilyAdapter, ToolCall, UnsupportedTemplate
from .runner import run_task
from .workloads import RepositoryTools, SCHEMA, TASKS, snapshot

ROOT = Path(__file__).resolve().parents[2]
MODEL_IDENTITIES = {
    "qwen": dict(
        family="qwen",
        model="Qwen/Qwen2.5-1.5B-Instruct",
        revision="989aa7980e4cf806f80c7fef2b1adb7bc71aa306",
    ),
    "qwen7": dict(
        family="qwen",
        model="Qwen/Qwen2.5-7B-Instruct",
        revision="a09a35458c702b33eeacc393d103063234e8bc28",
    ),
    "mistral": dict(
        family="mistral",
        model="mistralai/Mistral-7B-Instruct-v0.3",
        revision="c170c708c41dac9275d15a8fff4eca08d52bab71",
    ),
    "llama": dict(
        family="llama",
        model="meta-llama/Llama-3.1-8B-Instruct",
        revision="0e9e39f249a16976918f6564b8830bc894c89659",
    ),
}


def tokenizer_manifest(path, family):
    config = json.loads((path / "config.json").read_text())
    if config.get("use_sliding_window") or (
        config.get("model_type") != "qwen2" and config.get("sliding_window") is not None
    ):
        raise ValueError("This preparation supports FULL attention only")
    expected = {"qwen": "qwen2", "mistral": "mistral", "llama": "llama"}[
        MODEL_IDENTITIES[family]["family"]
    ]
    if config["model_type"] != expected:
        raise ValueError("Tokenizer/config family mismatch")
    dim = config.get("head_dim", config["hidden_size"] // config["num_attention_heads"])
    raw_bytes = (
        2 * config["num_hidden_layers"] * config["num_key_value_heads"] * dim * 2
    )
    files = {
        p.name: dict(
            bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest()
        )
        for p in sorted(path.iterdir())
        if p.name
        in {
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "merges.txt",
            "vocab.json",
        }
    }
    # Identity is declared; hashes allow reproducibility, not model-weight attestation.
    return dict(
        **MODEL_IDENTITIES[family],
        tokenizer_files=files,
        dtype="bfloat16",
        approximate_raw_kv_bytes_per_token=raw_bytes,
        gpu_fit="NOT_VALIDATED",
        model_weights="NOT_LOADED",
        date_string="04 Oct 2026",
    )


def call_text(family, call):
    body = dict(
        name=call.name,
        **{("parameters" if family == "llama" else "arguments"): call.arguments},
    )
    if family == "mistral":
        body["id"] = call.call_id
        return "[TOOL_CALLS] " + json.dumps([body], separators=(",", ":"))
    text = json.dumps(body, separators=(",", ":"))
    return (
        "<tool_call>\n" + text + "\n</tool_call>"
        if family == "qwen"
        else "<|python_tag|>" + text
    )


class ScriptedModel:
    """Transport fixture; native tokenizer, deliberately scripted decisions."""

    def __init__(self, tokenizer, texts):
        self.tokenizer, self.texts = tokenizer, iter(texts)

    async def generate(self, ids, salt):
        now = time.monotonic_ns()
        return dict(
            output_ids=self.tokenizer.encode(
                next(self.texts), add_special_tokens=False
            ),
            submitted_ns=now,
            first_token_ns=now,
            completed_ns=now,
            validation_type="SCRIPTED_CPU_FIXTURE",
            meta_info=dict(finish_reason=dict(type="stop")),
        )


async def local_check(
    family, path, *, revision="fe6217292ce4f01c592a2d7274137d826a75e1a0"
):
    import transformers

    manifest = tokenizer_manifest(path, family)
    expected = json.loads(
        (ROOT / "research/agent_resume/profiles" / (family + ".json")).read_text()
    )
    if manifest["tokenizer_files"] != expected["tokenizer_files"]:
        raise ValueError("Local tokenizer/config differs from the pinned profile")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        path, local_files_only=True, trust_remote_code=False
    )
    adapter = FamilyAdapter(MODEL_IDENTITIES[family]["family"])
    template_family = adapter.family
    initial = [
        dict(role="system", content="Read source"),
        dict(role="user", content="Question"),
    ]
    messages = adapter.normalize_messages(initial)
    prompt = adapter.prompt(tokenizer, messages, SCHEMA)
    call = ToolCall(
        "search_repository",
        dict(query="KV"),
        "abc123XYZ" if template_family == "mistral" else None,
    )
    boundary_checks = []
    for ending in (
        "",
        adapter.markers[0],
        adapter.markers[0] + ("\n" if template_family == "qwen" else ""),
    ):
        decision = tokenizer.encode(
            call_text(template_family, call) + ending, add_special_tokens=False
        )
        new, _ = adapter.continuation(
            tokenizer, messages, SCHEMA, prompt, decision, call, dict(matches=[])
        )
        boundary_checks.append(
            dict(
                ending=ending,
                exact_ids_preserved=new[: len(prompt) + len(decision)]
                == prompt + decision,
            )
        )
    system_guard = None
    if template_family == "mistral":
        try:
            adapter.continuation(
                tokenizer,
                initial,
                SCHEMA,
                adapter.prompt(tokenizer, initial, SCHEMA),
                decision,
                call,
                dict(matches=[]),
            )
        except UnsupportedTemplate:
            system_guard = "UNNORMALIZED_HISTORY_REJECTED"
        else:
            raise AssertionError("Mistral system-history change was not detected")
    corpus = snapshot(ROOT, revision)
    rows = []
    for task in TASKS:
        tool = RepositoryTools(corpus, ROOT)
        line = next(
            i
            for i, text in enumerate(
                corpus["files"][task["path"]]["text"].splitlines(), 1
            )
            if task["needle"] in text
        )
        calls = [
            ToolCall(
                "search_repository",
                dict(query=task["needle"]),
                "abc123XYZ" if template_family == "mistral" else None,
            )
        ]
        calls.append(
            ToolCall(
                "run_regression",
                dict(suite="admission_hints"),
                "def456XYZ" if template_family == "mistral" else None,
            )
            if task.get("required_tool")
            else ToolCall(
                "read_source",
                dict(path=task["path"], start=line, end=line),
                "def456XYZ" if template_family == "mistral" else None,
            )
        )
        final = json.dumps(
            dict(answer=task["answer"], evidence=[dict(path=task["path"], line=line)])
        )
        model = ScriptedModel(
            tokenizer, [call_text(template_family, c) for c in calls] + [final]
        )
        row = await run_task(adapter, tokenizer, model, tool, task)
        row["tool_artifacts"] = tool.artifacts
        row["validation_type"] = "SCRIPTED_CPU_FIXTURE"
        row["exact_prefix_preserved"] = all(
            b["input_ids"][: len(a["input_ids"]) + len(a["output_ids"])]
            == a["input_ids"] + a["output_ids"]
            for a, b in zip(row["generations"], row["generations"][1:])
        )
        rows.append(row)
    # Check malformed model decisions are retained, not replaced by a valid call.
    malformed = (
        '<tool_call>{"name":"unknown","arguments":{}}</tool_call>'
        if template_family == "qwen"
        else '[TOOL_CALLS] [{"name":"unknown","arguments":{},"id":"abc123XYZ"}]'
        if template_family == "mistral"
        else '<|python_tag|>{"name":"unknown","parameters":{}}'
    )
    failed = await run_task(
        adapter,
        tokenizer,
        ScriptedModel(tokenizer, [malformed]),
        RepositoryTools(corpus, ROOT),
        TASKS[0],
    )
    rows.append(
        dict(failed, validation_type="SCRIPTED_CPU_FIXTURE", expected_failure=True)
    )
    return dict(
        validation_type="SCRIPTED_CPU_FIXTURE",
        family=family,
        provenance=manifest,
        source_commit=corpus["commit"],
        python=platform.python_version(),
        transformers=transformers.__version__,
        rows=rows,
        native_boundary_checks=boundary_checks,
        mistral_system_guard=system_guard,
        gpu_execution=False,
        model_generation=False,
        harness_files={
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "research/agent_resume").glob("*.py"))
        },
        passed=all(c["exact_ids_preserved"] for c in boundary_checks)
        and all(
            r["status"] == "COMPLETED"
            and r["task_success"]
            and r["exact_prefix_preserved"]
            for r in rows[:-1]
        )
        and failed["status"] == "FAILED",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True, choices=MODEL_IDENTITIES)
    parser.add_argument("--tokenizer", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = asyncio.run(local_check(args.family, args.tokenizer.resolve()))
    result["harness_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            dict(
                family=args.family,
                passed=result["passed"],
                validation_type=result["validation_type"],
                output=str(args.output),
            )
        )
    )
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
