"""codeintel — 0.31 Code Intelligence: a read-only AST symbol index over the project source.

Pure core (:mod:`.index`: ``build_index`` / ``search_symbols``) plus a lazily-built,
cached index of the project root for the HTTP layer (the source doesn't change at
runtime, so one build is reused).
"""

from __future__ import annotations

from pathlib import Path

from .index import build_index, search_symbols

__all__ = ["build_index", "search_symbols", "project_index", "reindex", "PROJECT_ROOT"]

# agents/core/codeintel/index.py → parents[3] == the repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

_CACHE: dict | None = None


def project_index() -> dict:
    """The cached index of the project root (built on first use)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = build_index(PROJECT_ROOT)
    return _CACHE


def reindex() -> dict:
    """Rebuild the cached project index and return it."""
    global _CACHE
    _CACHE = build_index(PROJECT_ROOT)
    return _CACHE
