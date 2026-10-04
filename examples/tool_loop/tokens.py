"""Qwen2.5 chat continuation preserving the actual generated token sequence."""

import json
import re


def parse_tool_call(text):
    # Qwen's actual generated tool-call envelope, never a fabricated fallback.
    matches = re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, re.S)
    if len(matches) != 1 or text.count("<tool_call>") != 1:
        raise ValueError("Model did not emit a complete tool_call")
    call = json.loads(matches[0])
    if call.get("name") != "search_documents":
        raise ValueError("Unsupported model-selected tool")
    arguments = call.get("arguments")
    if not isinstance(arguments, dict) or set(arguments) != {"query"}:
        raise ValueError("Only a single query argument is supported")
    query = arguments["query"]
    if not isinstance(query, str) or not query.strip() or len(query) > 256:
        raise ValueError("Invalid tool query")
    return call


def continuation_ids(tokenizer, prompt_ids, decision_ids, result):
    saved = list(prompt_ids) + list(decision_ids)
    # Do not decode/re-encode saved tokens: BPE boundaries/JSON spacing may differ.
    raw = tokenizer.decode(decision_ids, skip_special_tokens=False)
    ending = "" if raw.rstrip().endswith("<|im_end|>") else "<|im_end|>"
    suffix = (
        ending
        + "\n<|im_start|>user\n<tool_response>\n"
        + json.dumps(result, sort_keys=True, separators=(",", ":"))
        + ("\n</tool_response><|im_end|>\n<|im_start|>assistant\n")
    )
    return saved + tokenizer.encode(suffix, add_special_tokens=False)


def aligned_saved_prefix(prompt_ids, decision_ids, page_size=16):
    saved = list(prompt_ids) + list(decision_ids)
    # Ordinary matching excludes the last saved token; no speculative result KV.
    size = ((len(saved) - 1) // page_size) * page_size
    if size < 64:
        raise ValueError("Saved prefix is below the configured storage threshold")
    return saved[:size]
