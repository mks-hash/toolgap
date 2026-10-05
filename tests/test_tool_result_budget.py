"""Token-bound evidence pages; no model behavior or performance claims."""

import json
import unittest
from research.agent_resume.adapters import FamilyAdapter, ToolCall
from research.agent_resume.budget import (
    ToolResultBudget,
    InsufficientEvidence,
    MAX_TOOL_SUFFIX_TOKENS,
)
from research.agent_resume.workloads import RepositoryTools, SCHEMA
from test_research_harness import FormatFixture


class TestResultBudget(unittest.TestCase):
    def plan(self, tools, call):
        tokenizer = FormatFixture()
        adapter = FamilyAdapter("qwen")
        messages = [dict(role="user", content="Find evidence")]
        initial = adapter.prompt(tokenizer, messages, SCHEMA)
        raw = (
            "<tool_call>"
            + json.dumps(dict(name=call.name, arguments=call.arguments))
            + "</tool_call>"
        )
        return adapter.prepare_continuation(
            tokenizer, messages, SCHEMA, initial, tokenizer.encode(raw), call
        ), tokenizer

    def test_pages_preserve_rows_and_cursor_retrieves_rest(self):
        tools = RepositoryTools(
            dict(
                commit="fixture",
                files={
                    "src/data.py": dict(
                        text="\n".join("stock " + str(i) for i in range(30)),
                        sha256="fixture",
                    )
                },
            )
        )
        call = ToolCall("search_repository", dict(query="stock"))
        plan, tok = self.plan(tools, call)
        budget = ToolResultBudget(plan, tok, 10000)
        budget.preflight()
        raw = tools.search("stock")
        before = json.dumps(raw, sort_keys=True)
        delivered, measure = budget.deliver(tools, call, raw)
        count = len(delivered["matches"])
        self.assertGreater(count, 0)
        self.assertLess(count, 20)
        self.assertEqual(delivered["matches"], raw["matches"][:count])
        self.assertEqual(json.dumps(raw, sort_keys=True), before)
        self.assertEqual(delivered["result_status"], "PARTIAL")
        self.assertEqual(delivered["next_offset"], count)
        self.assertLessEqual(measure["suffix_tokens"], MAX_TOOL_SUFFIX_TOKENS)
        next_call = ToolCall(**delivered["next_cursor"])
        tools.validate_call(next_call)
        self.assertEqual(
            tools.search(**next_call.arguments)["matches"][0], raw["matches"][count]
        )
        ids, _ = plan.append(tok, delivered)
        self.assertEqual(ids[: len(plan.saved_ids)], list(plan.saved_ids))

    def test_no_row_is_not_fabricated_success(self):
        tools = RepositoryTools(
            dict(
                commit="fixture",
                files={"src/large.py": dict(text="x" * 10000, sha256="fixture")},
            )
        )
        call = ToolCall("read_source", dict(path="src/large.py", start=1, end=1))
        plan, tok = self.plan(tools, call)
        result, report = ToolResultBudget(plan, tok, 10000).deliver(
            tools, call, tools.read(**call.arguments)
        )
        self.assertEqual(result["result_status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["lines"], [])
        self.assertEqual(report["delivered_rows"], 0)
        self.assertNotIn("passed", result)

    def test_minimum_response_fails_before_tool_effects(self):
        call = ToolCall("read_source", dict(path="file", start=1, end=1))
        plan, tok = self.plan(None, call)
        with self.assertRaises(InsufficientEvidence):
            ToolResultBudget(plan, tok, len(plan.saved_ids)).preflight()

    def test_read_cursor_has_actual_next_line_and_end(self):
        tools = RepositoryTools(
            dict(
                commit="fixture",
                files={
                    "src/data.py": dict(
                        text="\n".join("A" * 80 for _ in range(20)), sha256="fixture"
                    )
                },
            )
        )
        call = ToolCall("read_source", dict(path="src/data.py", start=1, end=20))
        plan, tok = self.plan(tools, call)
        result, _ = ToolResultBudget(plan, tok, 10000).deliver(
            tools, call, tools.read(**call.arguments)
        )
        self.assertEqual(
            result["next_cursor"]["arguments"]["start"], len(result["lines"]) + 1
        )
        self.assertEqual(result["next_cursor"]["arguments"]["end"], 20)
        tools.validate_call(ToolCall(**result["next_cursor"]))

    def test_classified_minimum_fails_before_tool_or_prefetch(self):
        import asyncio
        from research.agent_resume.prepare import ScriptedModel, call_text
        from research.agent_resume.runner import initial_messages, run_task
        from research.agent_resume.workloads import TASKS

        class EffectTools(RepositoryTools):
            effects = 0

            async def __call__(self, call):
                self.effects += 1
                return await super().__call__(call)

        class EffectPolicy:
            active = None
            effects = 0

            async def submit(self, *args, **kwargs):
                self.effects += 1
                raise AssertionError("Prefetch should not run")

        tools = EffectTools(
            dict(
                commit="fixture",
                files={TASKS[0]["path"]: dict(text="actual line", sha256="fixture")},
            )
        )
        tok = FormatFixture()
        adapter = FamilyAdapter("qwen")
        messages = initial_messages(adapter, TASKS[0])
        call = ToolCall("read_source", dict(path=TASKS[0]["path"], start=1, end=1))
        raw = call_text("qwen", call)
        prompt = adapter.prompt(tok, messages, SCHEMA)
        plan = adapter.prepare_continuation(
            tok, messages, SCHEMA, prompt, tok.encode(raw), call
        )
        empty_ids, _ = plan.append(tok, {})
        model = ScriptedModel(tok, [raw])
        policy = EffectPolicy()
        row = asyncio.run(
            run_task(
                adapter,
                tok,
                model,
                tools,
                TASKS[0],
                policy=policy,
                context_limit=len(empty_ids) + model.max_new_tokens,
            )
        )
        self.assertEqual(row["status"], "INSUFFICIENT_EVIDENCE", row.get("error"))
        self.assertEqual(tools.effects, 0)
        self.assertEqual(policy.effects, 0)
        self.assertEqual(row["tools"], [])
