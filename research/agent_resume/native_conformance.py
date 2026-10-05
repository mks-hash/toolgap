"""Offline differential template checks; never loads model weights or a server."""

import argparse
import hashlib
import inspect
import json
from pathlib import Path

from .adapters import FamilyAdapter, UnsupportedTemplate
from .contracts import ToolCalls
from .prepare import tokenizer_manifest
from .workloads import SCHEMA


def check(profile, directory):
    from transformers import AutoTokenizer
    import transformers

    actual = tokenizer_manifest(directory, profile["profile_id"])
    if actual["tokenizer_files"] != profile["tokenizer_files"]:
        raise ValueError("Tokenizer differs from pinned profile")
    tokenizer = AutoTokenizer.from_pretrained(
        directory, local_files_only=True, trust_remote_code=False
    )
    adapter = FamilyAdapter.from_profile(profile)
    messages = adapter.normalize_messages(
        [
            dict(role="system", content="Read source"),
            dict(role="user", content="Find evidence"),
        ]
    )
    checks = []
    for number in range(2):
        # Reference history is rendered directly by the official pinned template;
        # no production call_text/parser serialization generates the input.
        native_call = dict(
            type="function",
            function=dict(name="search_repository", arguments=dict(query="KV")),
        )
        if adapter.family == "mistral":
            native_call["id"] = "abc123XYZ" if number == 0 else "def456XYZ"
        assistant = dict(role="assistant", tool_calls=[native_call])
        initial = adapter.render(tokenizer, messages, SCHEMA, generate=True)
        closed = adapter.render(
            tokenizer, messages + [assistant], SCHEMA, generate=False
        )
        if not closed.startswith(initial):
            raise UnsupportedTemplate("Native reference is not append-compatible")
        raw = closed[len(initial) :]
        parsed = adapter.classify(raw, {"search_repository"}, "stop")
        if not isinstance(parsed, ToolCalls) or len(parsed.calls) != 1:
            raise AssertionError("Native generated-form reference not classified")
        prompt = adapter.prompt(tokenizer, messages, SCHEMA)
        native_prompt = tokenizer.apply_chat_template(
            messages,
            tools=SCHEMA,
            tokenize=True,
            return_dict=False,
            add_generation_prompt=True,
            date_string=adapter.date_string,
        )
        if prompt != native_prompt:
            raise AssertionError(
                "Rendered/encoded IDs differ from native tokenize=True"
            )
        decision = tokenizer.encode(raw, add_special_tokens=False)
        plan = adapter.prepare_continuation(
            tokenizer, messages, SCHEMA, prompt, decision, parsed.calls[0]
        )
        ids, next_messages = plan.append(tokenizer, dict(matches=[]))
        # Independent full native reference; saved IDs are still checked separately.
        reference_full = adapter.render(tokenizer, next_messages, SCHEMA, generate=True)
        actual_text = tokenizer.decode(ids, skip_special_tokens=False)
        if actual_text != reference_full:
            raise AssertionError(
                "Appended text differs from native full-history reference"
            )
        if ids[: len(prompt) + len(decision)] != prompt + decision:
            raise AssertionError("Previously executed IDs were changed")
        checks.append(
            dict(
                round=number + 1,
                render_tokenize_agreement=True,
                native_full_text_agreement=True,
                exact_saved_ids=True,
            )
        )
        messages = next_messages

    missing_id = "NOT_APPLICABLE"
    native_reference = None
    if adapter.family == "mistral":
        from mistral_common.tokens.tokenizers.instruct import InstructTokenizerV3
        from mistral_common.protocol.instruct.tool_calls import ToolCall, FunctionCall
        from importlib.metadata import version

        # Versioned native serializer is an independent protocol reference,
        # not a substitute for this checkpoint's HF tokenizer stack.
        native = object.__new__(InstructTokenizerV3)
        body = native._prepare_function_call(
            ToolCall(
                function=FunctionCall(
                    name="search_repository", arguments='{"query":"KV"}'
                )
            )
        )
        raw = "[TOOL_CALLS] " + json.dumps([body])
        result = adapter.classify(raw, {"search_repository"}, "stop")
        if (
            not isinstance(result, ToolCalls)
            or result.calls[0].model_call_id is not None
        ):
            raise AssertionError(
                "Native no-ID reference incorrectly rejected as malformed"
            )
        try:
            adapter.prepare_continuation(
                tokenizer,
                messages,
                SCHEMA,
                adapter.prompt(tokenizer, messages, SCHEMA),
                tokenizer.encode(raw, add_special_tokens=False),
                result.calls[0],
            )
        except UnsupportedTemplate as exc:
            if "MISSING_HISTORY_ID" not in str(exc):
                raise
            missing_id = "UNSUPPORTED_HF_HISTORY_WITHOUT_REWRITING"
        else:
            raise AssertionError("Unverified no-ID HF history was accepted")
        native_reference = dict(
            package="mistral_common",
            version=version("mistral_common"),
            method="InstructTokenizerV3._prepare_function_call",
            source_sha256=hashlib.sha256(
                inspect.getsource(InstructTokenizerV3._prepare_function_call).encode()
            ).hexdigest(),
            body=body,
        )
    return dict(
        schema_version=1,
        validation_type="OFFLINE_NATIVE_REFERENCE_CONFORMANCE",
        profile_id=adapter.profile_id,
        model=profile["model"],
        revision=profile["revision"],
        tokenizer_files=actual["tokenizer_files"],
        transformers=transformers.__version__,
        checks=checks,
        missing_id=missing_id,
        native_reference=native_reference,
        source_sha256={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(__file__).parent.glob("*.py"))
        },
        model_generation=False,
        gpu_execution=False,
        passed=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new evidence file")
    result = check(json.loads(args.profile.read_text()), args.tokenizer)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            dict(
                passed=result["passed"],
                validation_type=result["validation_type"],
                model_generation=False,
            )
        )
    )


if __name__ == "__main__":
    main()
