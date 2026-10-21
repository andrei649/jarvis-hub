"""H652 — the developer docs for adding a tool and for the agent loop stay true, and the
decision not to offer CLI extension hooks is pinned by the code it describes.

Every ``path::Symbol`` the docs cite must name a file that exists and a symbol defined in
it, and every repo path in backticks must exist, so a rename that leaves the docs behind
fails here instead of misleading the next reader.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOCS = [
    REPO / "docs/developer/adding-a-tool.md",
    REPO / "docs/developer/agent-loop.md",
    REPO / "docs/decisions/2026-10-21-no-cli-extension-hooks.md",
]
_SYMBOL_REF = re.compile(r"`([\w./-]+\.py)::([\w.]+)`")
_PATH_REF = re.compile(r"`((?:agents|tests|docs|skills|frontend|training|scripts)/[\w./<>*-]+)`")


def _defined(path: Path, dotted: str) -> bool:
    """``Class.method``, ``function`` or ``CONSTANT`` defined at that nesting in *path*."""
    scope: list[ast.stmt] = ast.parse(path.read_text(encoding="utf-8")).body
    for part in dotted.split("."):
        found = None
        for node in scope:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == part:
                found = node
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id == part for t in targets):
                    found = node
        if found is None:
            return False
        scope = getattr(found, "body", [])
    return True


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_cited_symbol_exists(doc):
    text = doc.read_text(encoding="utf-8")
    refs = _SYMBOL_REF.findall(text)
    assert refs, f"{doc.name} cites no path::Symbol"
    missing = [f"{path}::{name}" for path, name in refs
               if not (REPO / path).is_file() or not _defined(REPO / path, name)]
    assert missing == []


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_cited_repo_path_exists(doc):
    text = doc.read_text(encoding="utf-8")
    paths = {p for p in _PATH_REF.findall(text) if "<" not in p and "*" not in p}
    assert paths
    assert sorted(p for p in paths if not (REPO / p).exists()) == []


def test_the_tool_doc_carries_the_skill_vs_tool_rule_and_the_two_files():
    text = (REPO / "docs/developer/adding-a-tool.md").read_text(encoding="utf-8")
    assert "## Skill or tool?" in text
    assert "**Make it a skill when**" in text and "**Make it a tool when**" in text
    assert "## The two places you touch" in text and "## Checklist" in text
    assert "agent-loop.md" in text


def test_the_loop_doc_names_every_exit_reason():
    from agents.core.tool_loop_result import ToolLoopExitReason

    text = (REPO / "docs/developer/agent-loop.md").read_text(encoding="utf-8")
    assert [reason.name for reason in ToolLoopExitReason if f"`{reason.name}`" not in text] == []


def test_architecture_points_at_the_developer_docs():
    text = (REPO / "docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "docs/developer/adding-a-tool.md" in text and "docs/developer/agent-loop.md" in text
    assert "agents/core/trajectory.py" in text


# ── the CLI extension-hook decision ──────────────────────────────────────────


def test_nerva_dispatches_only_to_its_own_functions():
    from agents.cli import nerva

    assert {fn.__module__ for fn in nerva._VERBS.values()} == {"agents.cli.nerva"}
    assert all(callable(fn) for fn in nerva._VERBS.values())


def test_nothing_in_the_cli_loads_code_dynamically():
    banned = re.compile(r"\bimportlib\b|\bentry_points\b|__import__\s*\(|\bexec\s*\(|\beval\s*\(")
    offenders = []
    for path in sorted((REPO / "agents/cli").glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if banned.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    assert offenders == [], (
        "nerva loads code at run time; docs/decisions/2026-10-21-no-cli-extension-hooks.md "
        "says it does not. Revisit the decision first.")


def test_the_decision_says_not_offered_and_why():
    text = (REPO / "docs/decisions/2026-10-21-no-cli-extension-hooks.md").read_text(encoding="utf-8")
    assert "**Status:** decided — not offered" in text
    assert "Revisit when" in text and "docs/EXTENSIONS.md" in text
