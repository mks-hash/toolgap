"""Native-template suffixes appended to actual saved IDs; no model execution."""

import copy
import json
import re
from dataclasses import dataclass


class UnsupportedTemplate(ValueError):
    """Appending would change saved conversation or use an unverified boundary."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict
    call_id: str | None = None

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
        self.markers = {
            "qwen": ("<|im_end|>",),
            "mistral": ("</s>",),
            "llama": ("<|eom_id|>", "<|eot_id|>"),
        }[family]

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

    @staticmethod
    def render(tokenizer, messages, tools, *, generate):
        return tokenizer.apply_chat_template(
            messages,
            tools=tools,
            tokenize=False,
            add_generation_prompt=generate,
            date_string="04 Oct 2026",
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

    def parse(self, raw, allowed_tools):
        """None means final text; malformed/unsupported tool calls raise."""
        text = self.strip_end(raw)
        if self.family == "qwen":
            if "<tool_call>" not in text and "</tool_call>" not in text:
                return None
            match = re.fullmatch(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.S)
            if not match:
                raise ValueError("Expected one complete Qwen tool call")
            body = json.loads(match[1])
            argument_key = "arguments"
        elif self.family == "mistral":
            if "[TOOL_CALLS]" not in text:
                return None
            if not text.startswith("[TOOL_CALLS]"):
                raise ValueError("Unexpected text before Mistral tool call")
            calls = json.loads(text[len("[TOOL_CALLS]") :])
            if not isinstance(calls, list) or len(calls) != 1:
                raise ValueError("Only one tool call per turn is supported")
            body = calls[0]
            argument_key = "arguments"
        else:
            tagged = text.startswith("<|python_tag|>")
            if tagged:
                text = text[len("<|python_tag|>") :]
            try:
                body = json.loads(text)
            except json.JSONDecodeError:
                if tagged:
                    raise ValueError("Only JSON custom-tool Llama calls are supported")
                return None
            if not tagged and (not isinstance(body, dict) or "name" not in body):
                return None
            argument_key = "parameters"
        expected = {"name", argument_key} | (
            {"id"} if self.family == "mistral" else set()
        )
        if not isinstance(body, dict) or set(body) != expected:
            raise ValueError("Tool call has missing or unsupported fields")
        name, arguments = body["name"], body[argument_key]
        if (
            not isinstance(name, str)
            or name not in allowed_tools
            or not isinstance(arguments, dict)
        ):
            raise ValueError("Unknown tool or invalid arguments")
        call_id = body.get("id")
        if self.family == "mistral" and (
            not isinstance(call_id, str) or not re.fullmatch(r"[A-Za-z0-9]{9}", call_id)
        ):
            raise ValueError("Mistral needs the model's nine-character tool call ID")
        return ToolCall(name, arguments, call_id)

    def continuation(
        self, tokenizer, messages, tools, prompt_ids, decision_ids, call, result
    ):
        """Canonical history derives suffix only, never replaces generated IDs."""
        assistant = call.message()
        tool = dict(
            role="tool", name=call.name, content=json.dumps(result, sort_keys=True)
        )
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
        suffix = full[len(closed) :]
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
        saved = list(prompt_ids) + list(decision_ids)
        return saved + tokenizer.encode(
            closing + suffix, add_special_tokens=False
        ), next_messages


def aligned_prefix(ids, page_size=16, threshold=64):
    if type(page_size) is not int or page_size < 1:
        raise ValueError("page_size must be positive")
    size = (len(ids) - 1) // page_size * page_size
    return list(ids[:size]) if size >= threshold else []
