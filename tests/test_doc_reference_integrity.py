"""Live instructional docs may only point at paths that exist (DRA-26).

The #981 de-gate deleted `.github/ai-development-policy.json` and
`scripts/check_ai_workflow_policy.py`, but PARALLEL_WORKFLOW.md, docs/AGENT_WORKFLOW.md,
docs/DEVELOPMENT_ROADMAP.md and AI_SYSTEM_PROMPT.md kept naming them as the source of truth and
telling readers to run the checker. Those are the docs a new agent reads first, so a dangling
pointer there is worse than link rot — it is an instruction that cannot be followed.

Scope note: only *live instructional* docs are checked. Dated snapshots (docs/superpowers/plans,
docs/decisions, docs/meetings, .opencode/) correctly describe their own moment and are left alone.
A backticked path on a line that says the file was removed/deleted/archived is a factual statement
about a deletion, not a pointer, so those lines are exempt — the point is that no doc *directs*
you at something absent.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

LIVE_INSTRUCTIONAL_DOCS = (
    "AGENTS.md",
    "PARALLEL_WORKFLOW.md",
    "docs/AGENT_WORKFLOW.md",
    "docs/DEVELOPMENT_ROADMAP.md",
    "AI_SYSTEM_PROMPT.md",
    "CLAUDE.md",
)

_REPO_PATH = re.compile(r"^(\.github|scripts|agents|frontend|mobile|tests|docs)/[\w./-]+$")
_LINK = re.compile(r"\]\(([^)\s]+)\)")
_BACKTICK = re.compile(r"`([^`\n]+)`")
_DELETION_NOTE = re.compile(r"\b(removed|deleted|archived|restore)\b", re.I)

# gitignored runtime state; never present in a clean checkout
_SKIP_PREFIXES = ("memory_logs/",)


def _blocks(text: str) -> list[tuple[int, str]]:
    """(first line number, block text) for each blank-line-separated block.

    Prose wraps, so a sentence saying "X was removed" can put the filename on one line and the
    word "removed" on the next. Judging exemption per *block* keeps the check on meaning rather
    than on where the author happened to wrap.
    """
    blocks: list[tuple[int, str]] = []
    start, buf = 1, []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            if not buf:
                start = number
            buf.append(line)
        elif buf:
            blocks.append((start, "\n".join(buf)))
            buf = []
    if buf:
        blocks.append((start, "\n".join(buf)))
    return blocks


def _candidate_paths(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, block in _blocks(text):
        exempt = bool(_DELETION_NOTE.search(block))
        for target in _LINK.findall(block):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if exempt and not (REPO / target.split("#", 1)[0]).exists():
                continue
            found.append((number, target.split("#", 1)[0]))
        if exempt:
            continue  # a block documenting a deletion may name the deleted file
        for token in _BACKTICK.findall(block):
            if _REPO_PATH.match(token):
                found.append((number, token))
    return found


def test_live_instructional_docs_reference_only_existing_paths() -> None:
    missing: list[str] = []
    for rel in LIVE_INSTRUCTIONAL_DOCS:
        doc = REPO / rel
        assert doc.is_file(), rel
        base = doc.parent
        for number, target in _candidate_paths(doc.read_text(encoding="utf-8")):
            if "*" in target or target.startswith(_SKIP_PREFIXES) or not target:
                continue
            resolved = (base / target) if not (REPO / target).exists() else (REPO / target)
            if not resolved.exists():
                missing.append(f"{rel}:{number} → {target}")
    assert not missing, "docs point at paths that do not exist:\n  " + "\n  ".join(missing)


def test_parallel_workflow_lease_section_names_its_backlog_row() -> None:
    """The unbuilt lease service must name where it is tracked, so 'planned' is not a dead end."""
    text = (REPO / "PARALLEL_WORKFLOW.md").read_text(encoding="utf-8")
    section = text.split("## 3. Planned GitHub-backed path leases", 1)
    assert len(section) == 2, "lease section heading moved"
    body = section[1].split("\n## ", 1)[0]
    assert "DRA-26" in body
    assert "BACKLOG.md" in body


def test_no_live_doc_tells_the_reader_to_run_the_deleted_policy_checker() -> None:
    assert not (REPO / "scripts/check_ai_workflow_policy.py").exists()
    for rel in LIVE_INSTRUCTIONAL_DOCS:
        text = (REPO / rel).read_text(encoding="utf-8")
        for number, block in _blocks(text):
            if "check_ai_workflow_policy" not in block:
                continue
            assert _DELETION_NOTE.search(block), (
                f"{rel}:{number} still instructs running the deleted checker:\n{block}"
            )
