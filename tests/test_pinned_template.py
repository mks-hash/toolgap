"""Optional offline check against the exact Qwen tokenizer used by the demo."""

import json
import os
import unittest

from tokens import continuation_ids, parse_tool_call


@unittest.skipUnless(
    os.environ.get("TOOLGAP_TOKENIZER_PATH"), "Set offline pinned tokenizer path"
)
class TestPinnedTemplate(unittest.TestCase):
    def test_appended_tool_envelope_matches_qwen_chat_template(self):
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            os.environ["TOOLGAP_TOKENIZER_PATH"], local_files_only=True
        )
        call = dict(
            name="search_documents", arguments=dict(query="KV prefetch tool latency")
        )
        result = dict(document_id="DOC-00173")
        messages = [dict(role="user", content="Find evidence")]
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=True, return_dict=False, add_generation_prompt=True
        )
        # Keep deliberately noncanonical generated JSON spacing.
        raw = "<tool_call>\n" + json.dumps(call) + "\n</tool_call>"
        self.assertEqual(parse_tool_call(raw), call)
        expected_suffix = tokenizer.apply_chat_template(
            [
                dict(
                    role="tool",
                    content=json.dumps(result, sort_keys=True, separators=(",", ":")),
                )
            ],
            tokenize=False,
            add_generation_prompt=True,
        )
        expected_suffix = expected_suffix[expected_suffix.index("<|im_start|>user") :]
        for ending in ["", "<|im_end|>"]:
            decision = tokenizer.encode(raw + ending, add_special_tokens=False)
            ids = continuation_ids(tokenizer, prompt, decision, result)
            actual_suffix = tokenizer.decode(
                ids[len(prompt) + len(decision) :], skip_special_tokens=False
            )
            expected = ("" if ending else "<|im_end|>") + "\n" + expected_suffix
            self.assertEqual(actual_suffix, expected)
            self.assertEqual(ids[: len(prompt) + len(decision)], prompt + decision)
