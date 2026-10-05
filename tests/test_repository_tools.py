"""Repository discovery/retrieval fixtures; no live model-support claims."""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.agent_resume.adapters import ToolCall
from research.agent_resume.readiness import measurement_contract
from research.agent_resume.workloads import RepositoryTools, TASKS, snapshot


def fixture(files):
    return dict(
        commit="fixture",
        files={path: dict(text=text, sha256="fixture") for path, text in files.items()},
    )


class TestRepositoryRetrieval(unittest.IsolatedAsyncioTestCase):
    async def test_words_find_code_identifiers_without_task_vocabulary(self):
        tools = RepositoryTools(
            fixture(
                {
                    "src/inventory.py": "def warehouseStockCount():\n    stock_count = 3\n",
                    "docs/inventory.md": "warehouse stock\n",
                }
            )
        )
        result = await tools(
            ToolCall(
                "search_repository",
                {
                    "query": "warehouse stock count",
                },
            )
        )
        self.assertEqual(result["matches"][0]["path"], "src/inventory.py")
        self.assertEqual(result["matches"][0]["line"], 1)
        self.assertEqual(
            result["matches"][0]["matched_terms"], ["count", "stock", "warehouse"]
        )
        self.assertFalse(result["matches"][0]["literal_match"])
        self.assertEqual(tools.search("stock_count")["matches"][0]["line"], 2)

    async def test_literal_priority_limits_ties_and_unknown_queries(self):
        files = {f"src/item-{i:02}.py": "color\nred\nred color\n" for i in range(25)}
        tools = RepositoryTools(fixture(files))
        result = tools.search("red color")
        self.assertEqual(len(result["matches"]), 20)
        self.assertTrue(result["truncated"])
        self.assertTrue(all(h["literal_match"] for h in result["matches"]))
        self.assertEqual(
            result,
            RepositoryTools(fixture(dict(reversed(list(files.items()))))).search(
                "red color"
            ),
        )
        self.assertEqual(tools.search("quuxnotpresent")["matches"], [])
        # No model-specific synonyms: these unrelated words do not match.
        self.assertEqual(tools.search("scarlet pigment")["matches"], [])
        for query in ("", "   ", None, "x" * 129):
            with self.subTest(query=query), self.assertRaises(ValueError):
                tools.search(query)

    async def test_discovery_pages_are_complete_and_do_not_grant_citations(self):
        task = TASKS[0]
        files = {f"src/file-{i:02}.py": "x\n" for i in range(45)}
        files[task["path"]] = task["needle"] + "\n"
        tools = RepositoryTools(fixture(files))
        first = await tools(ToolCall("list_repository", dict(prefix="src/", offset=0)))
        second = tools.listing("src/", first["next_offset"])
        self.assertEqual(len(first["files"]), 40)
        paths = [r["path"] for r in first["files"] + second["files"]]
        self.assertEqual(paths, sorted(files))
        self.assertIsNone(second["next_offset"])
        answer = json.dumps(
            dict(answer=task["answer"], evidence=[dict(path=task["path"], line=1)])
        )
        self.assertFalse(tools.grade(task, answer, [dict(result=first)]))
        read = tools.read(task["path"], 1, 1)
        self.assertTrue(tools.grade(task, answer, [dict(result=read)]))
        for prefix, offset in [
            ("../", 0),
            ("/etc/", 0),
            ("\x00", 0),
            ("", -1),
            ("", True),
        ]:
            with (
                self.subTest(prefix=prefix, offset=offset),
                self.assertRaises(ValueError),
            ):
                tools.listing(prefix, offset)
        with self.assertRaises(ValueError):
            await tools(
                ToolCall("list_repository", dict(prefix="", offset=0, command="ls"))
            )

    async def test_failed_live_search_phrases_now_return_real_evidence_paths(self):
        # Retained public queries against a committed repository snapshot.
        # Historical-corpus replay is retained separately; these fixtures need
        # no old Git history (e.g. a shallow CI checkout).
        # This checks retrieval only, not whether a model can finish a task.
        root = Path(__file__).resolve().parents[1]
        record = json.loads(
            (
                root / "research/agent_resume/qwen7-live-pilot-2026-10-05.json"
            ).read_text()
        )
        corpus = snapshot(root, "HEAD")
        tools = RepositoryTools(corpus)
        queries = [
            "physical prefetch cleanup pending",
            "physical prefetch cleanup pending boolean field",
            "physical prefetch cleanup pending boolean field source",
            "estimated hidden restore milliseconds",
            "estimated hidden restore calculation",
            "hidden restore time function",
            "calculate hidden restore time",
        ]
        self.assertEqual(record["execution"]["successful"], 0)
        for query in queries:
            with self.subTest(query=query):
                matches = tools.search(query)["matches"]
                self.assertTrue(matches)
                for hit in matches:
                    line = corpus["files"][hit["path"]]["text"].splitlines()[
                        hit["line"] - 1
                    ]
                    self.assertEqual(hit["text"], line[:500])
        # A second identifier query reaches actual source, without task lookup
        # inside the search implementation.
        for task in TASKS[:2]:
            matches = tools.search(task["answer"])["matches"]
            self.assertTrue(
                any(
                    h["path"] == task["path"] and task["needle"] in h["text"]
                    for h in matches
                )
            )

    async def test_regression_returns_actual_test_class_evidence_and_rejects_fake_path(
        self,
    ):
        root = Path(__file__).resolve().parents[1]
        # Current committed source is used only for this CPU execution fixture.
        tools = RepositoryTools(snapshot(root, "HEAD"), root)
        call = ToolCall("run_regression", dict(suite="admission_hints"))
        result = await tools(call)
        self.assertTrue(result["passed"])
        self.assertEqual(result["tests"], 9)
        task = TASKS[2]
        evidence = next(h for h in result["matches"] if "class TestHints" in h["text"])
        records = [dict(call=dict(name=call.name), result=result)]
        answer = dict(
            answer="PASS", evidence=[dict(path=evidence["path"], line=evidence["line"])]
        )
        self.assertTrue(tools.grade(task, json.dumps(answer), records))
        self.assertFalse(
            tools.grade(
                task,
                json.dumps(answer),
                [dict(call=dict(name=call.name), result=dict(result, passed=False))],
            )
        )
        answer["evidence"] = [dict(path="admission_hints/test_class.py", line=1)]
        self.assertFalse(tools.grade(task, json.dumps(answer), records))

    def test_frozen_study_binds_tool_schema_executor_and_prompt(self):
        contract = measurement_contract()["repository_tools"]
        self.assertEqual(contract["version"], 2)
        for key in ("schema_sha256", "executor_sha256", "runner_sha256"):
            self.assertEqual(len(contract[key]), 64)
        self.assertNotEqual(
            measurement_contract(),
            {
                k: v
                for k, v in measurement_contract().items()
                if k != "repository_tools"
            },
        )

    async def test_stale_tool_contract_stops_before_live_http_or_tools(self):
        from research.agent_resume.pressure import digest, execute

        old = measurement_contract()
        old.pop("repository_tools")
        packet = dict(profile={}, measurement_contract=old)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "packet.json"
            path.write_text(json.dumps(dict(packet=packet, sha256=digest(packet))))
            # No other live arguments exist: a stale but checksum-valid packet
            # must stop before accessing native/live proofs or constructing HTTP.
            with self.assertRaisesRegex(ValueError, "current measurement contract"):
                await execute(types.SimpleNamespace(packet=path))


if __name__ == "__main__":
    unittest.main()
