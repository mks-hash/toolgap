"""Pinned real-document retrieval using v0.2's lexical scorer; no live model."""

import argparse
import asyncio
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path

from examples.tool_loop.search_tool import rank_documents

SCHEMA = [
    dict(
        type="function",
        function=dict(
            name="search_documents",
            description="Search pinned documents by words. Return actual complete passages with document IDs. Use next_cursor arguments for the next page. Cite an exact quote from a returned passage.",
            parameters=dict(
                type="object",
                properties=dict(
                    query=dict(type="string", minLength=1, maxLength=128),
                    offset=dict(type="integer", minimum=0),
                ),
                required=["query"],
                additionalProperties=False,
            ),
        ),
    )
]

TASKS = [
    dict(
        id="host-sharing",
        workload="document-search",
        question="Can two SGLang instances on the same node pool resident HiCache host memory? Verify using document search; answer yes or no and cite a returned quote.",
        answer="no",
        needle="Host memory cannot be pooled across instances",
    ),
    dict(
        id="host-size",
        workload="document-search",
        question="Which HiCache flag overrides the host-memory ratio with an explicit size? Verify using document search and give the flag with a returned quote.",
        answer="--hicache-size",
        needle="will override the above ratio",
    ),
    dict(
        id="page-io",
        workload="document-search",
        question="Which I/O backend is compatible with HiCache page_first memory layout? Verify using document search; give the backend and a returned quote.",
        answer="kernel",
        needle="Only compatible with `kernel`",
    ),
]

DEFAULT_PATHS = [
    "docs/docs/advanced_features/hicache_best_practices.mdx",
    "docs/docs/advanced_features/hicache_design.mdx",
    "docs/docs/advanced_features/hicache_storage_runtime_attach_detach.mdx",
    "docs/docs/advanced_features/server_arguments.mdx",
    "docs/docs/advanced_features/tool_parser.mdx",
]


def corpus_hash(records):
    return hashlib.sha256(
        json.dumps(records, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def validate_corpus(corpus):
    if not isinstance(corpus, dict) or not isinstance(corpus.get("records"), list):
        raise ValueError("Invalid corpus envelope")
    records = corpus["records"]
    if (
        not records
        or len(json.dumps(records).encode()) > 2_000_000
        or corpus_hash(records) != corpus.get("sha256")
    ):
        raise ValueError("Empty, oversized or changed document corpus")
    ids = set()
    for doc in records:
        if (
            not isinstance(doc, dict)
            or not isinstance(doc.get("id"), str)
            or not doc["id"]
            or doc["id"] in ids
            or not isinstance(doc.get("text"), str)
            or not doc["text"].strip()
            or not isinstance(doc.get("source"), dict)
            or not isinstance(doc["source"].get("commit"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", doc["source"]["commit"])
            or doc["source"].get("repository") != "sgl-project/sglang"
            or not isinstance(doc["source"].get("path"), str)
            or not doc["source"]["path"]
            or Path(doc["source"]["path"]).is_absolute()
            or ".." in Path(doc["source"]["path"]).parts
            or type(doc["source"].get("start_line")) is not int
            or doc["source"]["start_line"] < 1
        ):
            raise ValueError("Invalid or duplicate pinned document")
        ids.add(doc["id"])
    return corpus


def extract(repo, revision, paths):
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", revision + "^{commit}"], cwd=repo, text=True
    ).strip()
    records = []
    for path in paths:
        if path.startswith("/") or ".." in Path(path).parts:
            raise ValueError("Use relative pinned source paths")
        text = subprocess.check_output(
            ["git", "show", f"{commit}:{path}"], cwd=repo
        ).decode()
        # Whole paragraphs and whole Markdown table rows are evidence units.
        # Never slice passage text to fit the downstream native-token budget.
        units = []
        for match in re.finditer(r"\S.*?(?=\n\s*\n|\Z)", text, re.S):
            start = text[: match.start()].count("\n") + 1
            paragraph = match.group()
            html_rows = list(re.finditer(r"<tr(?:\s[^>]*)?>.*?</tr>", paragraph, re.S))
            lines = paragraph.splitlines(keepends=True)
            if html_rows:
                units.extend(
                    (start + paragraph[: row.start()].count("\n"), row.group())
                    for row in html_rows
                )
            elif all(re.fullmatch(r"\s*\|.*\|\s*", line) for line in lines):
                units.extend(
                    (start + index, line.rstrip("\r\n"))
                    for index, line in enumerate(lines)
                )
            else:
                units.append((start, paragraph))
        for start, passage in units:
            records.append(
                dict(
                    id=f"{path}:{start}",
                    text=passage,
                    source=dict(
                        repository="sgl-project/sglang",
                        commit=commit,
                        path=path,
                        start_line=start,
                    ),
                )
            )
    return validate_corpus(
        dict(
            records=records,
            sha256=corpus_hash(records),
            kind="PINNED_PUBLIC_SOURCE_DOCUMENTS",
        )
    )


class DocumentTools:
    schema = SCHEMA
    bounded_results = True

    def __init__(self, corpus):
        self.corpus = validate_corpus(copy.deepcopy(corpus))
        self.artifacts = []

    def validate_call(self, call):
        args = call.arguments
        if (
            call.name != "search_documents"
            or not {"query"} <= set(args)
            or set(args) - {"query", "offset"}
            or not isinstance(args["query"], str)
            or not args["query"].strip()
            or not 1 <= len(args["query"]) <= 128
            or type(args.get("offset", 0)) is not int
            or args.get("offset", 0) < 0
        ):
            raise ValueError("Invalid document-search arguments")

    def search(self, query, offset=0):
        ranked = [r for r in rank_documents(self.corpus["records"], query) if r[0] > 0]
        return dict(
            matches=[
                dict(document_id=doc_id, text=text, score=round(score, 6))
                for score, doc_id, text in ranked[offset : offset + 5]
            ],
            total_matches=len(ranked),
            offset=offset,
            records_scanned=len(self.corpus["records"]),
            corpus_sha256=self.corpus["sha256"],
        )

    async def __call__(self, call):
        self.validate_call(call)
        return await asyncio.to_thread(self.search, **call.arguments)

    def resume_arguments(self, call, result, count):
        offset = call.arguments.get("offset", 0) + count
        if offset < result["total_matches"]:
            return dict(
                name=call.name,
                arguments=dict(query=call.arguments["query"], offset=offset),
            )
        return None

    def grade(self, task, text, tool_records):
        try:
            answer = json.loads(text)
            if (
                set(answer) != {"answer", "evidence"}
                or answer["answer"] != task["answer"]
                or not answer["evidence"]
            ):
                return False
            returned = {
                r["document_id"]: r["text"]
                for step in tool_records
                for r in step["result"].get("matches", [])
            }
            documents = {r["id"]: r["text"] for r in self.corpus["records"]}
            relevant = False
            for evidence in answer["evidence"]:
                doc, quote = evidence["document_id"], evidence["quote"]
                if (
                    not isinstance(quote, str)
                    or not quote.strip()
                    or quote not in returned.get(doc, "")
                    or quote not in documents.get(doc, "")
                ):
                    return False
                relevant |= task["needle"] in quote
            return relevant
        except (ValueError, TypeError, KeyError):
            return False


def context_task(adapter, tokenizer, task, corpus, target_tokens, variant):
    from .runner import initial_messages

    if (
        type(target_tokens) is not int
        or not 512 <= target_tokens <= 16384
        or type(variant) is not int
        or variant < 0
    ):
        raise ValueError("Use a 512..16384 context target and nonnegative variant")
    validate_corpus(corpus)
    result = copy.deepcopy(task)
    records = corpus["records"]
    offset = variant % len(records)
    chunks = [f"{r['id']}\n{r['text']}" for r in records[offset:] + records[:offset]]
    accepted = []
    for chunk in chunks:
        result["context_pack"] = "\n\n".join(accepted + [chunk])
        if (
            len(adapter.prompt(tokenizer, initial_messages(adapter, result), SCHEMA))
            > target_tokens
        ):
            break
        accepted.append(chunk)
    if not accepted:
        raise ValueError("No real document fits the initial context budget")
    result["context_pack"] = "\n\n".join(accepted)
    result["initial_input_ids"] = adapter.prompt(
        tokenizer, initial_messages(adapter, result), SCHEMA
    )
    result["initial_tokens"] = len(result["initial_input_ids"])
    result["context_sha256"] = hashlib.sha256(
        result["context_pack"].encode()
    ).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Never overwrite an existing corpus")
    corpus = extract(args.repository, args.revision, DEFAULT_PATHS)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(corpus, indent=2) + "\n")
    print(
        json.dumps(
            dict(
                documents=len(corpus["records"]),
                sha256=corpus["sha256"],
                synthetic=False,
                model_generation=False,
            )
        )
    )


if __name__ == "__main__":
    main()
