"""Scripted native-tokenizer/real-tool CPU check; never a model or speed result."""

import argparse
import asyncio
import json
from pathlib import Path

from .adapters import FamilyAdapter, ToolCall
from .load import run_arrivals
from .prepare import ROOT, ScriptedModel, call_text, tokenizer_manifest
from .readiness import digest, measurement_contract, provenance
from .runner import run_task
from .workloads import snapshot
from .workload import tools_factory
from .documents import DocumentTools


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
    factory = tools_factory(packet, ROOT)
    corpus = (
        snapshot(ROOT, profile["source_commit"])
        if packet.get("workload_kind", "repository-audit") == "repository-audit"
        else None
    )

    async def run(item):
        task = item["task"]
        citations = []
        calls = []
        for index, r in enumerate(task.get("evidence_requirements", [])):
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
        tools = factory()
        if isinstance(tools, DocumentTools):
            # Oracle-guided fixture, deliberately NOT model navigation evidence.
            call = ToolCall(
                "search_documents",
                dict(query=task["needle"]),
                "doc000000" if adapter.family == "mistral" else None,
            )
            raw = tools.search(**call.arguments)
            match = next(r for r in raw["matches"] if task["needle"] in r["text"])
            calls = [call]
            citations = [dict(document_id=match["document_id"], quote=task["needle"])]
        else:
            calls.append(
                ToolCall(
                    "run_regression",
                    dict(suite="admission_hints"),
                    "reg000000" if adapter.family == "mistral" else None,
                )
            )
        texts = [call_text(adapter.family, call) for call in calls]
        texts.append(json.dumps(dict(answer=task["answer"], evidence=citations)))
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
        r["task_success"]
        and r["exact_prefix_preserved"]
        and all(
            len(g["output_ids"])
            <= packet["measurement_contract"]["generation"]["max_new_tokens"]
            for g in r["generations"]
        )
        for r in block["rows"]
    )
    result = dict(
        profile_id=profile["profile_id"],
        packet_sha256=envelope["sha256"],
        passed=passed,
        validation_type="SCRIPTED_CPU_FIXTURE",
        navigation="ORACLE_GUIDED_NOT_LIVE_EVIDENCE",
        workload_kind=packet.get("workload_kind", "repository-audit"),
        model_generation=False,
        generation_contract=packet["measurement_contract"]["generation"],
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
