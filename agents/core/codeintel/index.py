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
    """Extract every function/class in one file, at any nesting depth.

    This used to walk `tree.body` plus one pass over each module-level class body, which
    silently dropped anything deeper: nested functions and closures, defs inside a
    module-level ``if``/``try``/``with``, and classes nested in classes (skipped whole,
    methods and all). Measured on this repo, that hid 267 of 6,007 function defs under
    ``agents/`` — and a search miss reads to an operator as "not in the repo" rather than
    "not indexed at this depth", which is the reason this is a correctness bug and not a
    coverage preference.

    Descends through every statement body rather than only the two it used to know about,
    so a symbol's presence no longer depends on which block it happens to sit in. Each
    symbol carries a dotted ``qualname`` built from its enclosing scopes
    (``Outer.method.method_local``), so two same-named nested defs in one file stay
    distinguishable. Non-scoping blocks (``if``/``try``/``with``/loops) do not contribute
    a segment — the qualname names the SCOPE chain, which is what a reader can look up.
    """
    tree = ast.parse(source)
    out: list[dict] = []

    def walk(body: list, scope: str, in_class: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # "method" means: written directly in a class body. That is a property of
                # the enclosing scope, so it is carried down the recursion rather than
                # guessed from the name.
                if in_class:
                    kind = "method"
                else:
                    kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
                qual = f"{scope}.{node.name}" if scope else node.name
                out.append({"name": node.name, "qualname": qual, "kind": kind,
                            "file": rel_path, "lineno": node.lineno, "doc": _docline(node)})
                walk(node.body, qual, False)
            elif isinstance(node, ast.ClassDef):
                qual = f"{scope}.{node.name}" if scope else node.name
                out.append({"name": node.name, "qualname": qual, "kind": "class",
                            "file": rel_path, "lineno": node.lineno, "doc": _docline(node)})
                walk(node.body, qual, True)
            else:
                # if / try / with / for / while: not a scope, so recurse WITHOUT extending
                # the qualname and WITHOUT changing class-ness. A def here is as real as
                # any other, and used to be invisible.
                for attr in ("body", "orelse", "finalbody"):
                    inner = getattr(node, attr, None)
                    if isinstance(inner, list):
                        walk(inner, scope, in_class)
                for handler in getattr(node, "handlers", []) or []:
                    walk(getattr(handler, "body", []) or [], scope, in_class)

    walk(tree.body, "", False)
    return out


def _in_virtualenv(path: Path, root: Path, cache: list[Path]) -> bool:
    """True when *path* lives inside a virtualenv, detected by its ``pyvenv.cfg`` marker.

    _SKIP_DIRS lists venv directories BY NAME (".venv", "venv", "env"), which misses any
    other name — including ``.venv312``, this repo's actual interpreter. The effect was
    not cosmetic: 37,220 of 53,641 indexed symbols were third-party site-packages, so
    `symbol_count` was meaningless as a project measure and a search for a common name
    drowned in vendored hits. A marker check is name-independent and cannot go stale the
    next time someone picks a different directory name.

    Discovered venv roots are cached in *cache* so the walk stays O(depth) per file
    instead of re-statting the same ancestors for every file inside a large venv.
    """
    for known in cache:
        if known in path.parents:
            return True
    for parent in path.parents:
        if parent == root.parent:
            break
        if (parent / "pyvenv.cfg").exists():
            cache.append(parent)
            return True
        if parent == root:
            break
    return False


def build_index(root: str | Path) -> dict:
    """Index every ``*.py`` under *root*. Returns symbols + roll-ups + honest errors.

    A file that can't be read or parsed (e.g. a syntax error) is recorded under
    ``errors`` rather than aborting the whole index.
    """
    root = Path(root)
    symbols: list[dict] = []
    errors: list[dict] = []
    files = 0
    venv_roots: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if _in_virtualenv(path, root, venv_roots):
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
