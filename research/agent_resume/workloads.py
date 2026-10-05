"""Useful tools over a bounded, immutable Git source snapshot."""

import asyncio
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

SCHEMA = [
    dict(
        type="function",
        function=dict(
            name=name,
            description=description,
            parameters=dict(
                type="object",
                properties=properties,
                required=list(properties),
                additionalProperties=False,
            ),
        ),
    )
    for name, description, properties in (
        (
            "search_repository",
            "Find source/documentation evidence by literal text.",
            {"query": {"type": "string", "minLength": 1, "maxLength": 128}},
        ),
        (
            "read_source",
            "Read 1..80 numbered lines from a known pinned repository file; start <= end <= start + 79 and end must exist.",
            {
                "path": {"type": "string", "minLength": 1},
                "start": {"type": "integer", "minimum": 1},
                "end": {"type": "integer", "minimum": 1},
            },
        ),
        (
            "run_regression",
            "Run the allowed admission-hints CPU regression suite.",
            {"suite": {"type": "string", "enum": ["admission_hints"]}},
        ),
    )
]

TASKS = [
    dict(
        id="physical-cleanup",
        question="Which boolean field confirms whether physical prefetch cleanup is still pending? Give the field name and source evidence.",
        answer="cleanup_pending",
        path="src/toolgap/admission.py",
        needle='response.get("cleanup_pending")',
    ),
    dict(
        id="overlap-estimate",
        question="Which function calculates the estimated hidden restore milliseconds? Give its name and source evidence.",
        answer="estimated_hidden_ms",
        path="src/toolgap/admission.py",
        needle="def estimated_hidden_ms",
    ),
    dict(
        id="run-regression",
        question="Run the admission_hints regression suite. Answer PASS only if it exits successfully; otherwise FAIL. Cite the test class as evidence.",
        answer="PASS",
        path="tests/test_admission_hints.py",
        needle="class TestHints",
        required_tool="run_regression",
    ),
]


def snapshot(repo, revision):
    repo = Path(repo).resolve()
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", revision + "^{commit}"], cwd=repo, text=True
    ).strip()
    paths = subprocess.check_output(
        [
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            commit,
            "--",
            "src",
            "docs",
            "tests",
            "examples/tool_loop",
        ],
        cwd=repo,
        text=True,
    ).splitlines()
    files, total = {}, 0
    for path in paths:
        if not path.endswith((".py", ".md")) or path.startswith("docs/report/"):
            continue
        data = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=repo)
        if len(data) > 150_000:
            continue
        total += len(data)
        if total > 2_000_000:
            raise ValueError("Source snapshot exceeds 2 MB")
        files[path] = dict(text=data.decode(), sha256=hashlib.sha256(data).hexdigest())
    return dict(commit=commit, files=files)


class RepositoryTools:
    def __init__(self, corpus, repo=None):
        self.corpus = corpus
        self.repo = Path(repo).resolve() if repo is not None else None
        self.artifacts = []

    def search(self, query):
        self._validate_search(query)
        hits = []
        for path, data in sorted(self.corpus["files"].items()):
            for index, text in enumerate(data["text"].splitlines(), 1):
                if query.casefold() in text.casefold():
                    hits.append(dict(path=path, line=index, text=text[:500]))
        return dict(
            matches=hits[:20], total_matches=len(hits), commit=self.corpus["commit"]
        )

    @staticmethod
    def _validate_search(query):
        if not isinstance(query, str) or not 1 <= len(query) <= 128:
            raise ValueError("query must contain 1..128 characters")

    def read(self, path, start, end):
        self._validate_read(path, start, end)
        lines = self.corpus["files"][path]["text"].splitlines()
        return dict(
            path=path,
            lines=[dict(line=i, text=lines[i - 1]) for i in range(start, end + 1)],
            sha256=self.corpus["files"][path]["sha256"],
            commit=self.corpus["commit"],
        )

    def _validate_read(self, path, start, end):
        if not isinstance(path, str) or path not in self.corpus["files"]:
            raise ValueError("Path is not in the pinned source snapshot")
        if (
            type(start) is not int
            or type(end) is not int
            or not 1 <= start <= end <= start + 79
        ):
            raise ValueError("Read 1..80 numbered lines")
        lines = self.corpus["files"][path]["text"].splitlines()
        if end > len(lines):
            raise ValueError("Source range exceeds file")

    async def regression(self, suite):
        if suite != "admission_hints" or self.repo is None:
            raise ValueError("Unknown/unavailable regression suite")
        # Execute only this fixed CPU command, never model-provided shell text.
        for path in [
            p for p in self.corpus["files"] if p.startswith(("src/", "tests/"))
        ]:
            if (
                hashlib.sha256((self.repo / path).read_bytes()).hexdigest()
                != self.corpus["files"][path]["sha256"]
            ):
                raise ValueError(
                    "Live regression source differs from the pinned snapshot"
                )
        import os

        env = dict(
            os.environ, PYTHONPATH=str(self.repo / "src"), CUDA_VISIBLE_DEVICES="99"
        )
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(self.repo / "tests"),
            "-p",
            "test_admission_hints.py",
            "-q",
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=self.repo,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(process.communicate(), 30)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.communicate()
            raise
        text = (out + err).decode(errors="replace")
        ran = re.search(r"Ran (\d+) tests?", text)
        self.artifacts.append(
            dict(
                command=command,
                stdout=out.decode(errors="replace")[:64000],
                stderr=err.decode(errors="replace")[:64000],
                exit_code=process.returncode,
            )
        )
        return dict(
            suite=suite,
            exit_code=process.returncode,
            tests=int(ran[1]) if ran else None,
            passed=process.returncode == 0 and ran is not None,
        )

    def validate_call(self, call):
        """Pure argument/corpus validation shared by admission and execution."""
        args = call.arguments
        expected = {
            "search_repository": {"query"},
            "read_source": {"path", "start", "end"},
            "run_regression": {"suite"},
        }
        if call.name not in expected or set(args) != expected[call.name]:
            raise ValueError("Tool arguments differ from the declared schema")
        if call.name == "search_repository":
            self._validate_search(**args)
        elif call.name == "read_source":
            self._validate_read(**args)
        elif args["suite"] != "admission_hints" or self.repo is None:
            raise ValueError("Unknown/unavailable regression suite")

    async def __call__(self, call):
        self.validate_call(call)
        args = call.arguments
        if call.name == "search_repository":
            return await asyncio.to_thread(self.search, **args)
        if call.name == "read_source":
            return await asyncio.to_thread(self.read, **args)
        return await self.regression(**args)

    def grade(self, task, text, tool_records):
        try:
            answer = json.loads(text)
            if (
                set(answer) != {"answer", "evidence"}
                or answer["answer"] != task["answer"]
            ):
                return False
            if task.get("required_tool") and not any(
                r["call"]["name"] == task["required_tool"] and r["result"].get("passed")
                for r in tool_records
            ):
                return False
            # At least one actual tool call must have returned the cited evidence.
            retrieved = {
                (hit["path"], hit["line"])
                for r in tool_records
                for hit in r["result"].get("matches", [])
            }
            retrieved |= {
                (r["result"]["path"], hit["line"])
                for r in tool_records
                if "lines" in r["result"]
                for hit in r["result"]["lines"]
            }
            requirements = task.get(
                "evidence_requirements",
                [dict(path=task["path"], needle=task["needle"])],
            )
            found = set()
            if not isinstance(answer["evidence"], list) or not answer["evidence"]:
                return False
            for item in answer["evidence"]:
                path, line = item["path"], item["line"]
                if type(line) is not int or (path, line) not in retrieved:
                    return False
                text = self.corpus["files"][path]["text"].splitlines()[line - 1]
                for index, requirement in enumerate(requirements):
                    if path == requirement["path"] and requirement["needle"] in text:
                        found.add(index)
            return len(found) == len(requirements)
        except (ValueError, TypeError, KeyError, IndexError):
            pass
        return False
