"""Replay retained actual outputs on CPU; expected task/budget failure is evidence."""

import argparse
import hashlib
import json
from pathlib import Path

from .adapters import FamilyAdapter, ToolCall
from .budget import ToolResultBudget
from .prepare import tokenizer_manifest
from .workloads import RepositoryTools

FIXTURES = Path(__file__).resolve().parents[2] / "tests/fixtures/recorded_live"


def classifications():
    corpus = json.loads((FIXTURES / "model-outputs.json").read_text())
    schema = json.loads((FIXTURES / "qwen7-continuations.json").read_text())[
        "tools_schema"
    ]
    allowed = {s["function"]["name"] for s in schema}
    for case in corpus["cases"]:
        result = FamilyAdapter(case["family"]).classify(
            case["raw_text"], allowed, case["finish_reason"]
        )
        if type(result).__name__ != case["expected_classification"]:
            raise AssertionError("Recorded classification changed: " + case["id"])
    return dict(
        cases=len(corpus["cases"]),
        sources=len(corpus["sources"]),
        original_useful_passes=0,
    )


def continuations(directory):
    from transformers import AutoTokenizer

    recording = json.loads((FIXTURES / "qwen7-continuations.json").read_text())
    if (
        tokenizer_manifest(directory, "qwen")["tokenizer_files"]
        != recording["tokenizer_files"]
    ):
        raise ValueError("Recorded replay requires its pinned official tokenizer")
    tokenizer = AutoTokenizer.from_pretrained(
        directory, local_files_only=True, trust_remote_code=False
    )
    adapter = FamilyAdapter(recording["family"])
    tools = RepositoryTools(dict(commit="recorded", files={}))
    checks = []
    for row in recording["trajectories"]:
        ids = row["initial_input_ids"]
        messages = row["initial_messages"]
        if adapter.prompt(tokenizer, messages, recording["tools_schema"]) != ids:
            raise AssertionError("Recorded initial input changed")
        for index, generation in enumerate(row["generations"]):
            if (
                hashlib.sha256(json.dumps(ids).encode()).hexdigest()
                != generation["input_sha256"]
            ):
                raise AssertionError("Actual submitted input changed")
            if (
                tokenizer.decode(generation["output_ids"], skip_special_tokens=False)
                != generation["raw_text"]
            ):
                raise AssertionError("Actual output decode changed")
            outcome = adapter.classify(
                generation["raw_text"],
                {s["function"]["name"] for s in recording["tools_schema"]},
                generation["finish_reason"],
            )
            if type(outcome).__name__ != generation["response_outcome"]:
                raise AssertionError("Actual response classification changed")
            if index >= len(row["tools"]):
                continue
            step = row["tools"][index]
            call = ToolCall(**step["call"])
            plan = adapter.prepare_continuation(
                tokenizer,
                messages,
                recording["tools_schema"],
                ids,
                generation["output_ids"],
                call,
            )
            original_ids, messages = plan.append(tokenizer, step["result"])
            submitted = index + 1 < len(row["generations"])
            fits = len(original_ids) <= recording["max_input_tokens"]
            if fits != submitted:
                raise AssertionError("Historical budget outcome changed")
            if not submitted and len(original_ids) != row["expected_budget_tokens"]:
                raise AssertionError("Historical overflow token count changed")
            # This page is a counterfactual input. Never feed old later outputs to it.
            budget = ToolResultBudget(plan, tokenizer, recording["max_input_tokens"])
            budget.preflight()
            delivered, measured = budget.deliver(tools, call, step["result"])
            bounded_ids, _ = plan.append(
                tokenizer, delivered, max_input_tokens=recording["max_input_tokens"]
            )
            if bounded_ids[: len(plan.saved_ids)] != list(plan.saved_ids):
                raise AssertionError("Counterfactual page rewrote saved IDs")
            if (
                measured["continuation_tokens"] > recording["max_input_tokens"]
                or measured["suffix_tokens"] > measured["max_suffix_tokens"]
            ):
                raise AssertionError("Counterfactual page exceeds contract")
            checks.append(
                dict(
                    task_id=row["task_id"],
                    turn=index,
                    original_tokens=len(original_ids),
                    original_submitted=submitted,
                    original_fits=fits,
                    counterfactual_budget=measured,
                    counterfactual_useful_live="NOT_RUN",
                )
            )
            ids = original_ids
        final = row.get("final_output")
        if final is not None and tools.grade(row["grading_task"], final, row["tools"]):
            raise AssertionError("Historical invalid citation was promoted to success")
    return dict(
        actual_submitted_continuations=sum(c["original_submitted"] for c in checks),
        expected_budget_failures=sum(not c["original_fits"] for c in checks),
        counterfactual_pages=len(checks),
        original_useful_passes=0,
        checks=checks,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qwen-tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Never overwrite replay evidence")
    result = dict(
        validation_type="RECORDED_REAL_CPU_REPLAY",
        model_generation=False,
        gpu_execution=False,
        classification=classifications(),
        continuations=continuations(args.qwen_tokenizer),
        useful_live_under_new_policy="NOT_RUN",
        pressure="NOT_RUN",
        performance="NOT_RUN",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "continuations"}))


if __name__ == "__main__":
    main()
