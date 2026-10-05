"""Useful tools over a bounded, immutable Git source snapshot."""

import asyncio
import ast
import hashlib
import json
import math
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
            "Search pinned source by words or code identifiers; literal matches rank first. Returns at most 20 numbered source lines. Read nearby lines with read_source when needed.",
            {"query": {"type": "string", "minLength": 1, "maxLength": 128}},
        ),
        (
            "list_repository",
            "Discover pinned file paths and line counts, 40 per page. Start with prefix='' and offset=0; use next_offset for later pages. File metadata alone is not citation evidence.",
            {
                "prefix": {"type": "string", "maxLength": 128},
                "offset": {"type": "integer", "minimum": 0},
            },
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
            "Run the allowed admission-hints CPU regression suite. Returns actual exit status/test count and numbered test-class source lines that can be cited; never invent test paths.",
            {"suite": {"type": "string", "enum": ["admission_hints"]}},
        ),
    )
]

# Optional search pagination. Existing query-only calls remain supported.
SCHEMA[0]["function"]["parameters"]["properties"]["offset"] = dict(
    type="integer", minimum=0
)
SCHEMA[0]["function"]["description"] += " Use next_cursor arguments for another page."

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


def tool_contract():
    """Bind prepared work to the schema, executor and initial prompt actually used."""
    return dict(
        version=3,
        search="LITERAL_FIRST_IDF_WORD_OVERLAP; NO_SEMANTIC_OR_SYNONYM_EXPANSION",
        search_limit=20,
        listing_limit=40,
        read_limit=80,
        schema_sha256=hashlib.sha256(
            json.dumps(SCHEMA, sort_keys=True).encode()
        ).hexdigest(),
        executor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        runner_sha256=hashlib.sha256(
            Path(__file__).with_name("runner.py").read_bytes()
        ).hexdigest(),
    )


def search_terms(text):
    # Split snake_case/camelCase without model/task-specific vocabulary or aliases.
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return set(re.findall(r"[^\W_]+", text.casefold())) - {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "which",
        "with",
    }


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
    schema = SCHEMA
    bounded_results = True

    def __init__(self, corpus, repo=None):
        self.corpus = corpus
        self.repo = Path(repo).resolve() if repo is not None else None
        self.artifacts = []
        self._search_lines = None

    def search(self, query, offset=0):
        self._validate_search(query, offset)
        if self._search_lines is None:
            # Build inside the first measured search, not in an unreported warmup.
            self._search_lines = [
                (path, index, text, search_terms(text))
                for path, data in sorted(self.corpus["files"].items())
                for index, text in enumerate(data["text"].splitlines(), 1)
            ]
        terms = search_terms(query)
        counts = {
            term: sum(term in row[3] for row in self._search_lines) for term in terms
        }
        weights = {
            term: math.log(1 + len(self._search_lines) / (1 + count))
            for term, count in counts.items()
        }
        hits = []
        for path, index, text, line_terms in self._search_lines:
            literal = query.casefold() in text.casefold()
            matched = sorted(terms & line_terms)
            if literal or matched:
                score = sum(weights[term] for term in matched)
                hits.append(
                    (
                        (-int(literal), -score, path, index),
                        dict(
                            path=path,
                            line=index,
                            text=text[:500],
                            literal_match=literal,
                            matched_terms=matched,
                        ),
                    )
                )
        hits.sort(key=lambda row: row[0])
        return dict(
            matches=[row[1] for row in hits[offset : offset + 20]],
            offset=offset,
            next_offset=offset + 20 if offset + 20 < len(hits) else None,
            total_matches=len(hits),
            truncated=len(hits) > offset + 20,
            query_terms=sorted(terms),
            method="literal-first-word-overlap-v2",
            commit=self.corpus["commit"],
        )

    @staticmethod
    def _validate_search(query, offset=0):
        if (
            not isinstance(query, str)
            or not query.strip()
            or not 1 <= len(query) <= 128
        ):
            raise ValueError("query must contain 1..128 nonblank characters")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a nonnegative integer")

    @staticmethod
    def _validate_listing(prefix, offset):
        if (
            not isinstance(prefix, str)
            or len(prefix) > 128
            or prefix.startswith("/")
            or ".." in prefix.split("/")
            or any(ord(c) < 32 for c in prefix)
        ):
            raise ValueError("prefix must be a relative pinned-file prefix")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a nonnegative integer")

    def listing(self, prefix, offset):
        self._validate_listing(prefix, offset)
        paths = sorted(p for p in self.corpus["files"] if p.startswith(prefix))
        page = paths[offset : offset + 40]
        return dict(
            files=[
                dict(
                    path=p,
                    lines=len(self.corpus["files"][p]["text"].splitlines()),
                    sha256=self.corpus["files"][p]["sha256"],
                )
                for p in page
            ],
            total_files=len(paths),
            next_offset=offset + len(page) if offset + len(page) < len(paths) else None,
            commit=self.corpus["commit"],
        )

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
        test_path = "tests/test_admission_hints.py"
        source = self.corpus["files"][test_path]
        lines = source["text"].splitlines()
        classes = [
            node
            for node in ast.parse(source["text"]).body
            if isinstance(node, ast.ClassDef)
        ]
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
            matches=[
                dict(
                    path=test_path, line=node.lineno, text=lines[node.lineno - 1][:500]
                )
                for node in classes[:20]
            ],
            source_sha256=source["sha256"],
            commit=self.corpus["commit"],
            source_truncated=len(classes) > 20,
        )

    def validate_call(self, call):
        """Pure argument/corpus validation shared by admission and execution."""
        args = call.arguments
        expected = {
            "search_repository": {"query"},
            "list_repository": {"prefix", "offset"},
            "read_source": {"path", "start", "end"},
            "run_regression": {"suite"},
        }
        optional = {"offset"} if call.name == "search_repository" else set()
        if (
            call.name not in expected
            or not expected[call.name] <= set(args)
            or set(args) - expected[call.name] - optional
        ):
            raise ValueError("Tool arguments differ from the declared schema")
        if call.name == "search_repository":
            self._validate_search(**args)
        elif call.name == "list_repository":
            self._validate_listing(**args)
        elif call.name == "read_source":
            self._validate_read(**args)
        elif args["suite"] != "admission_hints" or self.repo is None:
            raise ValueError("Unknown/unavailable regression suite")

    def resume_arguments(self, call, result, count):
        args = dict(call.arguments)
        if call.name in ("search_repository", "list_repository"):
            key = "matches" if call.name == "search_repository" else "files"
            total = result["total_matches" if key == "matches" else "total_files"]
            offset = args.get("offset", 0) + count
            if offset < total:
                args["offset"] = offset
                return dict(name=call.name, arguments=args)
        elif call.name == "read_source":
            start = args["start"] + count
            if start <= args["end"]:
                args["start"] = start
                return dict(name=call.name, arguments=args)
        elif count < len(result.get("matches", [])):
            # Regression executes once; a repeat cursor must not invent a cached run.
            return None
        return None

    async def __call__(self, call):
        self.validate_call(call)
        args = call.arguments
        if call.name == "search_repository":
            return await asyncio.to_thread(self.search, **args)
        if call.name == "list_repository":
            return await asyncio.to_thread(self.listing, **args)
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
