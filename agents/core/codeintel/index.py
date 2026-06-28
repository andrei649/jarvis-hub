"""index.py — 0.31 Code Intelligence: a read-only AST symbol index.

A pure, offline code-indexing backend over the project's **own** Python source:
walk ``*.py`` under a root, parse each with the stdlib :mod:`ast`, and extract the
symbols (module functions, classes, and methods) with their location and the
first line of their docstring. Then ``search_symbols`` does a transparent
substring match over the index.

It returns **structure, not contents** — symbol names, kinds, relative paths, line
numbers, and a one-line doc — so an agent can find *where* something is defined
without the indexer ever shipping file bodies. Pure and deterministic: the core
operates on a root you hand it (tests use a tmp dir); the HTTP layer indexes the
project root and caches the result.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Directories never worth indexing (vendored / generated / VCS / caches).
_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache", "build", "dist",
})


def _docline(node: ast.AST) -> str:
    """First non-empty line of a node's docstring, or '' (never the whole body)."""
    try:
        doc = ast.get_docstring(node)
    except Exception:
        doc = None
    if not doc:
        return ""
    for line in doc.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _symbols_in_source(source: str, rel_path: str) -> list[dict]:
    """Extract module-level functions/classes (+ their methods) from one file."""
    tree = ast.parse(source)
    out: list[dict] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
            out.append({"name": node.name, "qualname": node.name, "kind": kind,
                        "file": rel_path, "lineno": node.lineno, "doc": _docline(node)})
        elif isinstance(node, ast.ClassDef):
            out.append({"name": node.name, "qualname": node.name, "kind": "class",
                        "file": rel_path, "lineno": node.lineno, "doc": _docline(node)})
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append({"name": sub.name, "qualname": f"{node.name}.{sub.name}",
                                "kind": "method", "file": rel_path, "lineno": sub.lineno,
                                "doc": _docline(sub)})
    return out


def build_index(root: str | Path) -> dict:
    """Index every ``*.py`` under *root*. Returns symbols + roll-ups + honest errors.

    A file that can't be read or parsed (e.g. a syntax error) is recorded under
    ``errors`` rather than aborting the whole index.
    """
    root = Path(root)
    symbols: list[dict] = []
    errors: list[dict] = []
    files = 0
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        rel = str(path.relative_to(root))
        try:
            symbols.extend(_symbols_in_source(path.read_text(encoding="utf-8"), rel))
            files += 1
        except Exception as e:
            errors.append({"file": rel, "error": type(e).__name__})
    by_kind: dict[str, int] = {}
    for s in symbols:
        by_kind[s["kind"]] = by_kind.get(s["kind"], 0) + 1
    return {
        "symbols": symbols,
        "files_indexed": files,
        "symbol_count": len(symbols),
        "by_kind": by_kind,
        "errors": errors,
    }


def search_symbols(index: dict, query: str, *, kind: str | None = None, limit: int = 50) -> list[dict]:
    """Case-insensitive substring search over an index's symbols (name + qualname).

    Optional *kind* filter (function / async_function / class / method). Results are
    deterministic: ranked by an exact-name match first, then file then line.
    """
    q = (query or "").strip().lower()
    limit = max(1, min(int(limit or 50), 500))
    if not q:
        return []
    hits = [
        s for s in index.get("symbols", [])
        if (kind is None or s["kind"] == kind) and q in s["qualname"].lower()
    ]
    hits.sort(key=lambda s: (s["name"].lower() != q, s["file"], s["lineno"]))
    return hits[:limit]
