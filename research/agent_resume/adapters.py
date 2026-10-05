"""Native-template suffixes appended to actual saved IDs; no model execution."""

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .contracts import FinalAnswer, InvalidOutput, ToolCalls, UnsupportedOutput


class UnsupportedTemplate(ValueError):
    """Appending would change saved conversation or use an unverified boundary."""


class UnsupportedResponse(ValueError):
    """A native response shape outside this adapter's declared subset."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict
    call_id: str | None = None

    @property
    def model_call_id(self):
        return self.call_id

    def message(self):
        call = dict(
            type="function",
            function=dict(name=self.name, arguments=copy.deepcopy(self.arguments)),
        )
        if self.call_id is not None:
            call["id"] = self.call_id
        return dict(role="assistant", tool_calls=[call])


class FamilyAdapter:
    def __init__(self, family):
        if family not in {"qwen", "mistral", "llama"}:
            raise ValueError("Unsupported family")
        self.family = family
        # This constructor names a format, not validated model support.
        self.profile_id = "unbound-format:" + family
        self.markers = {
            "qwen": ("<|im_end|>",),
            "mistral": ("</s>",),
            "llama": ("<|eom_id|>", "<|eot_id|>"),
        }[family]

    @classmethod
    def from_profile(cls, profile):
        """Bind records to the declared experiment; no claim of weight attestation."""
        adapter = cls(profile["family"])
        identity = dict(
            schema_version=1,
            family=profile["family"],
            model=profile["model"],
            revision=profile["revision"],
            tokenizer_files=profile["tokenizer_files"],
            runtime=profile["runtime_candidate_sha"],
            settings=profile["server_settings"],
            date_string=profile.get("date_string", "04 Oct 2026"),
            adapter_source_sha256=hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        )
        adapter.profile_id = hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode()
        ).hexdigest()
        adapter.date_string = identity["date_string"]
        return adapter

    def capabilities(self):
        return dict(
            schema_version=1,
            profile_id=self.profile_id,
            supported_responses=["single_native_tool_call", "final_text"],
            mixed_text_and_calls="UNSUPPORTED",
            multiple_calls="UNSUPPORTED_BY_RUNNER",
            missing_model_call_id=(
                "UNSUPPORTED_HF_HISTORY" if self.family == "mistral" else "OPTIONAL"
            ),
            model_generation="NOT_RUN",
            useful_live_loop="NOT_RUN",
        )

    def normalize_messages(self, messages):
        messages = copy.deepcopy(messages)
        if self.family == "mistral" and messages and messages[0]["role"] == "system":
            # v0.3's official template inserts system only for a last user turn;
            # later tool messages otherwise remove it from the saved prompt.
            system = messages.pop(0)["content"]
            if not messages or messages[0]["role"] != "user":
                raise UnsupportedTemplate("Mistral requires an initial user turn")
            messages[0]["content"] = system + "\n\n" + messages[0]["content"]
        return messages

    def render(self, tokenizer, messages, tools, *, generate):
        return tokenizer.apply_chat_template(
            messages,
            tools=tools,
            tokenize=False,
            add_generation_prompt=generate,
            date_string=getattr(self, "date_string", "04 Oct 2026"),
        )

    def prompt(self, tokenizer, messages, tools):
        text = self.render(tokenizer, messages, tools, generate=True)
        return tokenizer.encode(text, add_special_tokens=False)

    def strip_end(self, raw):
        text = raw.strip()
        for marker in self.markers:
            if text.endswith(marker):
                return text[: -len(marker)].strip()
        return text

    def classify(self, raw, allowed_tools, finish_reason):
        """Classify the whole completed response without repairing any tokens."""
        reason = (
            finish_reason.get("type")
            if isinstance(finish_reason, dict)
            else finish_reason
        )
        if reason == "length":
            return InvalidOutput("TRUNCATED_GENERATION")
        if reason == "abort":
            return InvalidOutput("ABORTED_GENERATION")
        if reason != "stop":
            return UnsupportedOutput("UNVERIFIED_FINISH_REASON")
        try:
            return self._classify_complete(raw, allowed_tools)
        except UnsupportedResponse as exc:
            return UnsupportedOutput(str(exc))
        except (ValueError, TypeError) as exc:
            return InvalidOutput(str(exc))

    def parse(self, raw, allowed_tools):
        """Legacy format-only helper; never establishes turn completion."""
        outcome = self.classify(raw, allowed_tools, "stop")
        if isinstance(outcome, FinalAnswer):
            return None
        if isinstance(outcome, ToolCalls) and len(outcome.calls) == 1:
            return outcome.calls[0]
        raise ValueError(getattr(outcome, "reason", "Only one tool call is supported"))

    def _classify_complete(self, raw, allowed_tools):
        text = self.strip_end(raw)
        if self.family == "qwen":
            if "<tool_call>" not in text and "</tool_call>" not in text:
                return FinalAnswer(text)
            matches = list(
                re.finditer(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.S)
            )
            if not matches:
                raise ValueError("Expected one complete Qwen tool call")
            calls = tuple(
                self._call(json.loads(m[1]), "arguments", allowed_tools)
                for m in matches
            )
            residue = re.sub(
                r"<tool_call>\s*.*?\s*</tool_call>", "", text, flags=re.S
            ).strip()
            if "<tool_call>" in residue or "</tool_call>" in residue:
                raise ValueError("Incomplete Qwen tool envelope")
            if residue:
                return UnsupportedOutput("MIXED_TEXT_AND_TOOL_CALLS")
            return ToolCalls(calls)
        elif self.family == "mistral":
            if "[TOOL_CALLS]" not in text:
                return FinalAnswer(text)
            if not text.startswith("[TOOL_CALLS]"):
                return UnsupportedOutput("MIXED_TEXT_AND_TOOL_CALLS")
            payload = text[len("[TOOL_CALLS]") :].lstrip()
            if "[ARGS]" in payload and not payload.startswith("["):
                return UnsupportedOutput("MISTRAL_COMPACT_FORMAT")
            calls, end = json.JSONDecoder().raw_decode(payload)
            if not isinstance(calls, list) or not calls:
                raise ValueError("Expected a nonempty tool-call array")
            parsed = tuple(
                self._call(body, "arguments", allowed_tools) for body in calls
            )
            if payload[end:].strip():
                return UnsupportedOutput("MIXED_TEXT_AND_TOOL_CALLS")
            return ToolCalls(parsed)
        else:
            tagged = text.startswith("<|python_tag|>")
            if tagged:
                text = text[len("<|python_tag|>") :]
            try:
                body = json.loads(text)
            except json.JSONDecodeError:
                if tagged:
                    return UnsupportedOutput("LLAMA_NON_JSON_TOOL_FORMAT")
                return FinalAnswer(text)
            if not tagged and (not isinstance(body, dict) or "name" not in body):
                return FinalAnswer(text)
            argument_key = "parameters"
        return ToolCalls((self._call(body, argument_key, allowed_tools),))

    def _call(self, body, argument_key, allowed_tools):
        required = {"name", argument_key}
        optional = {"id"} if self.family == "mistral" else set()
        if not isinstance(body, dict) or not required <= set(body):
            raise ValueError("Tool call has missing fields")
        if set(body) - required - optional:
            raise UnsupportedResponse("UNSUPPORTED_CALL_FIELDS")
        name, arguments = body["name"], body[argument_key]
        if (
            not isinstance(name, str)
            or name not in allowed_tools
            or not isinstance(arguments, dict)
        ):
            raise ValueError("Unknown tool or invalid arguments")
        call_id = body.get("id")
        if (
            self.family == "mistral"
            and "id" in body
            and (
                not isinstance(call_id, str)
                or not re.fullmatch(r"[A-Za-z0-9]{9}", call_id)
            )
        ):
            raise ValueError("Malformed Mistral call ID")
        return ToolCall(name, arguments, call_id)

    def continuation(
        self, tokenizer, messages, tools, prompt_ids, decision_ids, call, result
    ):
        """Compatibility wrapper for format-only CPU checks."""
        plan = self.prepare_continuation(
            tokenizer, messages, tools, prompt_ids, decision_ids, call
        )
        return plan.append(tokenizer, result)

    def prepare_continuation(
        self, tokenizer, messages, tools, prompt_ids, decision_ids, call
    ):
        """Pure pre-dispatch history/ending check; result does not exist yet."""
        if self.family == "mistral" and call.model_call_id is None:
            raise UnsupportedTemplate(
                "MISSING_HISTORY_ID: pinned HF template requires an ID"
            )
        assistant = call.message()
        tool = dict(role="tool", name=call.name, content="{}")
        if call.call_id is not None:
            tool["tool_call_id"] = call.call_id
        closed = self.render(tokenizer, messages + [assistant], tools, generate=False)
        next_messages = messages + [assistant, tool]
        full = self.render(tokenizer, next_messages, tools, generate=True)
        previous = self.render(tokenizer, messages, tools, generate=True)
        if not closed.startswith(previous) or not full.startswith(closed):
            raise UnsupportedTemplate(
                "Native template changes an earlier conversation span"
            )
        if (
            not prompt_ids
            or not decision_ids
            or any(
                type(token) is not int or token < 0
                for token in prompt_ids + decision_ids
            )
        ):
            raise ValueError("Supply actual nonnegative prompt and generated token IDs")
        ending = next(
            (
                marker + closed[len(closed.rstrip()) :]
                for marker in self.markers
                if closed.rstrip().endswith(marker)
            ),
            None,
        )
        if ending is None:
            raise UnsupportedTemplate(
                "Native assistant tool-call ending is unsupported"
            )
        raw = tokenizer.decode(decision_ids, skip_special_tokens=False)
        parsed = self.parse(raw, {call.name})
        if parsed != call:
            raise ValueError("Tool metadata differs from actual generated tokens")
        seen = next((m for m in self.markers if raw.rstrip().endswith(m)), None)
        if raw.endswith(ending):
            closing = ""
        elif seen is None:
            closing = ending
        elif raw.endswith(seen) and ending.startswith(seen):
            closing = ending[len(seen) :]
        else:
            raise UnsupportedTemplate("Generated ending differs from native template")
        return ContinuationPlan(
            self,
            tuple(prompt_ids) + tuple(decision_ids),
            json.dumps(next_messages),
            json.dumps(tools),
            closed,
            closing,
        )


@dataclass(frozen=True)
class ContinuationPlan:
    adapter: FamilyAdapter
    saved_ids: tuple[int, ...]
    messages_json: str
    tools_json: str
    closed: str
    closing: str

    def append(self, tokenizer, result, *, max_input_tokens=None):
        messages = json.loads(self.messages_json)
        messages[-1]["content"] = json.dumps(result, sort_keys=True, allow_nan=False)
        full = self.adapter.render(
            tokenizer, messages, json.loads(self.tools_json), generate=True
        )
        if not full.startswith(self.closed):
            raise UnsupportedTemplate("Actual tool result changes saved history")
        suffix_ids = tokenizer.encode(
            self.closing + full[len(self.closed) :], add_special_tokens=False
        )
        ids = list(self.saved_ids) + suffix_ids
        if max_input_tokens is not None and len(ids) > max_input_tokens:
            raise ValueError("Tool result exceeds continuation token budget")
        return ids, messages


def aligned_prefix(ids, page_size=16, threshold=64):
    if type(page_size) is not int or page_size < 1:
        raise ValueError("page_size must be positive")
    size = (len(ids) - 1) // page_size * page_size
    return list(ids[:size]) if size >= threshold else []
