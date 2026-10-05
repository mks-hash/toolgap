"""Scripted native-tokenizer/real-tool CPU check; never a model or speed result."""

import argparse
import asyncio
import json
from pathlib import Path

from .adapters import FamilyAdapter, ToolCall
from .load import run_arrivals
from .prepare import ROOT, ScriptedModel, call_text, tokenizer_manifest
from .pressure import digest
from .readiness import measurement_contract, provenance
from .runner import run_task
from .workloads import RepositoryTools, snapshot


async def check(args):
    from transformers import AutoTokenizer

    envelope = json.loads(args.packet.read_text())
    packet = envelope["packet"]
    if digest(packet) != envelope["sha256"]:
        raise ValueError("Packet changed")
    profile = packet["profile"]
    if packet.get("measurement_contract") != measurement_contract():
        raise ValueError("Prepare a current measurement packet")
    if (
        tokenizer_manifest(args.tokenizer, profile["profile_id"])["tokenizer_files"]
        != profile["tokenizer_files"]
    ):
        raise ValueError("Tokenizer changed")
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer, local_files_only=True, trust_remote_code=False
    )
    adapter = FamilyAdapter.from_profile(profile)
    corpus = snapshot(ROOT, profile["source_commit"])

    async def run(item):
        task = item["task"]
        citations = []
        calls = []
        for index, r in enumerate(task["evidence_requirements"]):
            line = next(
                i
                for i, text in enumerate(
                    corpus["files"][r["path"]]["text"].splitlines(), 1
                )
                if r["needle"] in text
            )
            citations.append(dict(path=r["path"], line=line))
            calls.append(
                ToolCall(
                    "read_source",
                    dict(path=r["path"], start=line, end=line),
                    f"call{index:05d}" if adapter.family == "mistral" else None,
                )
            )
        calls.append(
            ToolCall(
                "run_regression",
                dict(suite="admission_hints"),
                "reg000000" if adapter.family == "mistral" else None,
            )
        )
        texts = [call_text(adapter.family, call) for call in calls]
        texts.append(json.dumps(dict(answer=task["answer"], evidence=citations)))
        tools = RepositoryTools(corpus, ROOT)
        row = await run_task(
            adapter,
            tokenizer,
            ScriptedModel(tokenizer, texts),
            tools,
            task,
            cache_salt=item["cache_salt"],
            max_tool_rounds=packet["measurement_contract"]["max_tool_rounds"],
        )
        row["exact_prefix_preserved"] = all(
            b["input_ids"][: len(a["input_ids"]) + len(a["output_ids"])]
            == a["input_ids"] + a["output_ids"]
            for a, b in zip(row["generations"], row["generations"][1:])
        )
        row["tool_artifacts"] = tools.artifacts
        row["validation_type"] = "SCRIPTED_CPU_FIXTURE"
        return row

    block = await run_arrivals(packet["arrivals"], run, max_active=packet["max_active"])
    passed = all(
        r["task_success"] and r["exact_prefix_preserved"] for r in block["rows"]
    )
    result = dict(
        profile_id=profile["profile_id"],
        packet_sha256=envelope["sha256"],
        passed=passed,
        validation_type="SCRIPTED_CPU_FIXTURE",
        model_generation=False,
        gpu_execution=False,
        provenance=provenance(profile),
        procedure_completed=True,
        useful_live_tool_loop="NOT_RUN",
        pressure_opportunity="NOT_RUN",
        performance="NOT_RUN",
        real_regression_tests=sum(
            s["result"].get("tests", 0) for r in block["rows"] for s in r["tools"]
        ),
        block=block,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "block"}))
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--tokenizer", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Never overwrite evidence")
    raise SystemExit(0 if asyncio.run(check(args)) else 1)


if __name__ == "__main__":
    main()
