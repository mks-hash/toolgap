"""Two declared study workloads; not an extensible agent framework."""

from .workloads import RepositoryTools, snapshot
from .documents import DocumentTools, validate_corpus


def tools_factory(packet, root):
    kind = packet.get("workload_kind", "repository-audit")
    if kind == "document-search":
        corpus = validate_corpus(packet["document_corpus"])
        return lambda: DocumentTools(corpus)
    if kind == "repository-audit":
        corpus = snapshot(root, packet["profile"]["source_commit"])
        return lambda: RepositoryTools(corpus, root)
    raise ValueError("Unsupported study workload")
