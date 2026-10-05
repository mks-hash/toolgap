"""Useful exhaustive lexical retrieval over a fixed JSONL document corpus.

No sleeps or injected latency. Workload size is an input, not selected by TTFT.
The default corpus is a deterministic synthetic fixture; external JSONL is allowed.
"""

import argparse
import collections
import hashlib
import json
import math
import re
from pathlib import Path


def create_corpus(path, count=10000):
    topics = [
        "attention kernel tiling",
        "host memory capacity accounting",
        "storage failure cleanup",
        "agent task scheduling",
        "model sampling",
    ]
    with Path(path).open("w") as f:
        for i in range(count):
            title = topics[i % len(topics)]
            text = (
                f"Report {i}: {title}. We record experimental procedures, "
                "resource budgets, reproducibility, results and correctness. "
            ) * 8
            if i == 173:
                text = (
                    "KV prefetch during tool execution hides storage restore latency. "
                    "An exact prefix is restored into resident host cache before "
                    "continuation arrival; normal H2D resumes generation. "
                ) * 8
            f.write(json.dumps(dict(id=f"DOC-{i:05d}", text=text)) + "\n")


def rank_documents(documents, query):
    """Shared exhaustive lexical scorer; no delay, answer lookup or persistent index."""
    query_terms = set(re.findall(r"[a-z0-9]+", query.lower()))
    if not query_terms:
        raise ValueError("No searchable query terms")
    records, frequency = [], collections.Counter()
    for doc in documents:
        terms = collections.Counter(re.findall(r"[a-z0-9]+", doc["text"].lower()))
        frequency.update(terms.keys())
        records.append((doc, terms))
    ranked = []
    for doc, terms in records:
        score = sum(
            (1 + math.log(terms[t])) * math.log((1 + len(records)) / (1 + frequency[t]))
            for t in sorted(query_terms)
            if terms[t]
        )
        ranked.append((score, doc["id"], doc["text"]))
    ranked.sort(key=lambda r: (-r[0], r[1]))
    return ranked


def search(path, query):
    if not re.findall(r"[a-z0-9]+", query.lower()):
        raise ValueError("No searchable query terms")
    documents, digest = [], hashlib.sha256()
    with Path(path).open("rb") as f:
        for line in f:
            digest.update(line)
            documents.append(json.loads(line))
    ranked = rank_documents(documents, query)
    if not ranked or ranked[0][0] <= 0:
        raise ValueError("No matching document")
    score, doc_id, text = ranked[0]
    return dict(
        document_id=doc_id,
        score=round(score, 6),
        excerpt=text[:180],
        records_scanned=len(documents),
        corpus_sha256=digest.hexdigest(),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("corpus", type=Path)
    p.add_argument("query")
    args = p.parse_args()
    print(json.dumps(search(args.corpus, args.query), sort_keys=True))
