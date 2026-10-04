"""Thin exact-prefix control client. No implicit session or tokenization."""

from .client import PrefetchClient, PrefetchRejected

__all__ = ["PrefetchClient", "PrefetchRejected"]
