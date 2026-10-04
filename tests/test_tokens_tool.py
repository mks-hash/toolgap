import tempfile
import unittest
from pathlib import Path

from search_tool import create_corpus, search
from tokens import aligned_saved_prefix, continuation_ids, parse_tool_call


class TokenizerStub:
    def decode(self, ids, **kwargs):
        return "raw noncanonical tool call"

    def encode(self, text, **kwargs):
        self.appended = text
        return [99, 100]


class TestExactTokensAndTool(unittest.TestCase):
    def test_saved_tokens_are_not_retokenized(self):
        tokenizer = TokenizerStub()
        prompt = list(range(80))
        decision = [999, 1000]
        result = continuation_ids(
            tokenizer, prompt, decision, dict(document_id="DOC-1")
        )
        self.assertEqual(result[:82], prompt + decision)
        self.assertEqual(result[82:], [99, 100])
        self.assertNotIn("raw noncanonical", tokenizer.appended)
        self.assertEqual(aligned_saved_prefix(prompt, decision), list(range(80)))

    def test_missing_model_tool_call_is_not_synthesized(self):
        with self.assertRaises(ValueError):
            parse_tool_call("I think you should search")
        with self.assertRaises(ValueError):
            parse_tool_call('<tool_call>{"name":"unknown","arguments":{}}</tool_call>')

    def test_multiple_tools_and_extra_arguments_are_rejected(self):
        call = '<tool_call>{"name":"search_documents","arguments":{"query":"KV"}}</tool_call>'
        with self.assertRaises(ValueError):
            parse_tool_call(call + call)
        with self.assertRaises(ValueError):
            parse_tool_call(call.replace('"query":"KV"', '"query":"KV","other":1'))

    def test_actual_tool_result_is_reproducible_and_query_dependent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.jsonl"
            create_corpus(path, 200)
            result = search(path, "KV prefetch tool latency")
            self.assertEqual(result["document_id"], "DOC-00173")
            self.assertEqual(result, search(path, "KV prefetch tool latency"))
            self.assertEqual(result["records_scanned"], 200)
            self.assertNotEqual(
                result["document_id"],
                search(path, "attention kernel tiling")["document_id"],
            )


if __name__ == "__main__":
    unittest.main()
