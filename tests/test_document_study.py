"""Bounded real-source retrieval and diagnostic/evidence separation, on CPU."""

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from examples.tool_loop.search_tool import rank_documents, search
from research.agent_resume.adapters import FamilyAdapter, ToolCall
from research.agent_resume.budget import ToolResultBudget
from research.agent_resume.documents import (
    DocumentTools,
    TASKS,
    corpus_hash,
    extract,
    validate_corpus,
)
from research.agent_resume import readiness, pressure, live
from research.agent_resume.runner import run_task
from research.agent_resume.prepare import ScriptedModel, call_text
from test_readiness_sampling import live_rows
from test_research_harness import FormatFixture


def fixture_corpus():
    records = [
        dict(
            id="doc:1",
            text="Host memory cannot be pooled across instances. Separate workers have separate pools.",
            source=dict(
                repository="sgl-project/sglang",
                commit="a" * 40,
                path="docs/example.mdx",
                start_line=1,
            ),
        ),
        dict(
            id="doc:3",
            text="The explicit --hicache-size will override the above ratio.",
            source=dict(
                repository="sgl-project/sglang",
                commit="a" * 40,
                path="docs/example.mdx",
                start_line=3,
            ),
        ),
    ]
    return dict(
        records=records,
        sha256=corpus_hash(records),
        kind="PINNED_PUBLIC_SOURCE_DOCUMENTS",
    )


class TestDocuments(unittest.TestCase):
    def test_pin_extracts_unmodified_whole_paragraphs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            text = "Header\n\nActual complete paragraph.\nSecond line.\n\nLast paragraph.\n"
            (root / "doc.mdx").write_text(text)
            subprocess.run(["git", "add", "doc.mdx"], cwd=root, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-qm",
                    "source",
                ],
                cwd=root,
                check=True,
            )
            corpus = extract(root, "HEAD", ["doc.mdx"])
            self.assertEqual(len(corpus["records"]), 3)
            for row in corpus["records"]:
                self.assertIn(row["text"], text)
                self.assertEqual(
                    row["source"]["commit"],
                    subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=root, text=True
                    ).strip(),
                )
            (root / "doc.mdx").write_text("uncommitted substitution")
            self.assertEqual(extract(root, "HEAD", ["doc.mdx"]), corpus)
            with self.assertRaises(ValueError):
                extract(root, "HEAD", ["../escape"])

    def test_html_table_rows_are_whole_source_units(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            text = "## Options\n<table>\n<tr><td>flag</td><td>description one</td></tr>\n<tr><td>other</td><td>description two</td></tr>\n</table>\n"
            (root / "doc.mdx").write_text(text)
            subprocess.run(["git", "add", "doc.mdx"], cwd=root, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-qm",
                    "source",
                ],
                cwd=root,
                check=True,
            )
            corpus = extract(root, "HEAD", ["doc.mdx"])
            self.assertEqual(
                [r["source"]["start_line"] for r in corpus["records"]], [3, 4]
            )
            for row in corpus["records"]:
                self.assertTrue(row["text"].startswith("<tr>"))
                self.assertTrue(row["text"].endswith("</tr>"))
                self.assertIn(row["text"], text)

    def test_corpus_validation_rejects_changed_or_ambiguous_identity(self):
        original = fixture_corpus()
        validate_corpus(original)
        for change in ("text", "duplicate", "path", "commit", "line"):
            corpus = copy.deepcopy(original)
            if change == "text":
                corpus["records"][0]["text"] = "changed"
            elif change == "duplicate":
                corpus["records"].append(corpus["records"][0])
            elif change == "path":
                corpus["records"][0]["source"]["path"] = "/private/doc"
            elif change == "commit":
                corpus["records"][0]["source"]["commit"] = 1
            elif change == "line":
                corpus["records"][0]["source"]["start_line"] = True
            if change != "text":
                corpus["sha256"] = corpus_hash(corpus["records"])
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_corpus(corpus)

    def test_quotes_must_have_been_returned_and_match_pinned_source(self):
        tools = DocumentTools(fixture_corpus())
        result = tools.search("host memory instances")
        quote = TASKS[0]["needle"]
        final = dict(answer="no", evidence=[dict(document_id="doc:1", quote=quote)])
        self.assertTrue(tools.grade(TASKS[0], json.dumps(final), [dict(result=result)]))
        self.assertFalse(tools.grade(TASKS[0], json.dumps(final), []))
        final["evidence"][0]["quote"] = "Invented exact quote"
        self.assertFalse(
            tools.grade(TASKS[0], json.dumps(final), [dict(result=result)])
        )

    def test_old_search_preserves_scoring_excerpt_and_raw_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.jsonl"
            records = fixture_corpus()["records"]
            data = "".join(json.dumps(r) + "\n" for r in records).encode()
            path.write_bytes(data)
            ranked = rank_documents(records, "host memory")
            result = search(path, "host memory")
            self.assertEqual(
                result,
                dict(
                    document_id=ranked[0][1],
                    score=round(ranked[0][0], 6),
                    excerpt=ranked[0][2][:180],
                    records_scanned=2,
                    corpus_sha256=hashlib.sha256(data).hexdigest(),
                ),
            )
            with self.assertRaisesRegex(ValueError, "No searchable"):
                search(path.parent / "absent", "?!")

    def test_document_page_cursor_and_full_text(self):
        corpus = fixture_corpus()
        for i in range(6):
            corpus["records"].append(
                dict(
                    id=f"doc:{i + 10}",
                    text="Host instance " + str(i) + " " + ("word " * 12),
                    source=copy.deepcopy(corpus["records"][0]["source"]),
                )
            )
        corpus["sha256"] = corpus_hash(corpus["records"])
        tools = DocumentTools(corpus)
        tok = FormatFixture()
        adapter = FamilyAdapter("qwen")
        messages = [dict(role="user", content="Find host")]
        call = ToolCall("search_documents", dict(query="host"))
        initial = adapter.prompt(tok, messages, tools.schema)
        plan = adapter.prepare_continuation(
            tok,
            messages,
            tools.schema,
            initial,
            tok.encode(call_text("qwen", call)),
            call,
        )
        raw = tools.search("host")
        delivered, _ = ToolResultBudget(plan, tok, 10000).deliver(tools, call, raw)
        self.assertGreater(len(delivered["matches"]), 0)
        self.assertEqual(
            delivered["matches"], raw["matches"][: len(delivered["matches"])]
        )
        cursor = ToolCall(**delivered["next_cursor"])
        tools.validate_call(cursor)
        next_result = tools.search(**cursor.arguments)
        self.assertNotIn(next_result["matches"][0], delivered["matches"])


class TestDiagnostic(unittest.IsolatedAsyncioTestCase):
    def test_wrong_answer_does_not_destroy_technical_diagnostic(self):
        rows = live_rows()
        rows[0]["task_success"] = False
        result = readiness.live_result(rows, [r["task_id"] for r in rows], False)
        self.assertFalse(result["study_success"])
        self.assertTrue(result["diagnostic_ready"])
        for kind in ("invalid", "ids", "cleanup", "lost", "duplicate"):
            changed = copy.deepcopy(rows)
            if kind == "invalid":
                changed[0]["failure_kind"] = "InvalidOutput"
            elif kind == "ids":
                changed[0]["generations"][1]["input_ids"] = [99]
            elif kind == "cleanup":
                changed[0]["prefetch"] = [dict(cleanup_confirmed=False)]
            elif kind == "lost":
                changed.pop()
            else:
                changed[1] = copy.deepcopy(changed[0])
            with self.subTest(kind=kind):
                self.assertFalse(
                    readiness.live_result(changed, [r["task_id"] for r in rows], False)[
                        "diagnostic_ready"
                    ]
                )

    def test_caller_without_tool_call_is_retained_in_diagnostics(self):
        rows = live_rows()
        expected = [r["task_id"] for r in rows]
        rows[0].update(task_success=False, tools=[])
        rows[0]["generations"] = rows[0]["generations"][:1]
        result = readiness.live_result(rows, expected, False)
        self.assertTrue(result["diagnostic_ready"])
        self.assertFalse(result["study_success"])
        self.assertEqual(result["tasks"], 3)
        for row in rows:
            row["tools"] = []
            row["generations"] = row["generations"][:1]
        self.assertFalse(
            readiness.live_result(rows, expected, False)["diagnostic_ready"]
        )
        rows = live_rows()
        rows[0]["tools"] = []
        rows[0]["generations"] = rows[0]["generations"][:1]
        rows[0]["generations"][0]["output_ids"] = []
        self.assertFalse(
            readiness.live_result(rows, expected, False)["diagnostic_ready"]
        )

    def test_document_native_proof_binds_document_schema_source(self):
        from test_readiness_sampling import native_record

        profile = json.loads(
            (readiness.ROOT / "research/agent_resume/profiles/qwen.json").read_text()
        )
        record = native_record(profile)
        record["workload_kind"] = "document-search"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.json"
            path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "documents.py"):
                readiness.require_native(path, profile, workload="document-search")
            record["source_sha256"]["documents.py"] = readiness.file_hash(
                readiness.ROOT / "research/agent_resume/documents.py"
            )
            path.write_text(json.dumps(record))
            self.assertTrue(
                readiness.require_native(path, profile, workload="document-search")
            )

    async def test_diagnostic_proactive_rejected_before_files_or_http(self):
        from types import SimpleNamespace

        with self.assertRaisesRegex(ValueError, "request-time"):
            await live.execute(SimpleNamespace(purpose="diagnostic", mode="proactive"))
        with self.assertRaisesRegex(ValueError, "request-time"):
            await pressure.execute(
                SimpleNamespace(purpose="diagnostic", mode="proactive", baseline=None)
            )

    async def test_document_runner_keeps_budget_and_actual_evidence(self):
        tok = FormatFixture()
        adapter = FamilyAdapter("qwen")
        tools = DocumentTools(fixture_corpus())
        call = ToolCall("search_documents", dict(query="host memory instances"))
        answer = json.dumps(
            dict(
                answer="no",
                evidence=[dict(document_id="doc:1", quote=TASKS[0]["needle"])],
            )
        )
        row = await run_task(
            adapter,
            tok,
            ScriptedModel(tok, [call_text("qwen", call), answer]),
            tools,
            TASKS[0],
        )
        self.assertTrue(row["task_success"], row.get("error"))
        self.assertEqual(row["tools"][0]["result_budget"]["result_status"], "COMPLETE")
        self.assertGreaterEqual(row["tools"][0]["result_serialization_ms"], 0)
        saved = row["generations"][0]["input_ids"] + row["generations"][0]["output_ids"]
        self.assertEqual(row["generations"][1]["input_ids"][: len(saved)], saved)

    def test_diagnostic_record_cannot_be_forged_or_promoted(self):
        profile = json.loads(
            (readiness.ROOT / "research/agent_resume/profiles/qwen.json").read_text()
        )
        rows = live_rows()
        rows[0]["task_success"] = False
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def save(rows, purpose):
                (root / "tasks.jsonl").write_text(
                    "\n".join(json.dumps(r) for r in rows)
                )
                (root / "manifest.json").write_text("{}")
                (root / "control-events.json").write_text("[]")
                record = readiness.live_result(
                    rows, [r["task_id"] for r in live_rows()], False
                )
                record.update(
                    provenance=readiness.provenance(profile),
                    purpose=purpose,
                    cleanup_unresolved=False,
                    artifacts_sha256={
                        name: readiness.file_hash(root / name)
                        for name in (
                            "tasks.jsonl",
                            "manifest.json",
                            "control-events.json",
                        )
                    },
                )
                (root / "readiness.json").write_text(json.dumps(record))
                return record

            record = save(rows, "diagnostic")
            self.assertTrue(readiness.require_live(root, profile, purpose="diagnostic"))
            with self.assertRaises(ValueError):
                readiness.require_live(root, profile)
            changed = copy.deepcopy(rows)
            changed[0]["generations"][1]["input_ids"] = [999]
            record = save(changed, "diagnostic")
            record["diagnostic_ready"] = True
            (root / "readiness.json").write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                readiness.require_live(root, profile, purpose="diagnostic")
            save(live_rows(), "diagnostic")
            with self.assertRaises(ValueError):
                readiness.require_live(root, profile, purpose="evidence")
