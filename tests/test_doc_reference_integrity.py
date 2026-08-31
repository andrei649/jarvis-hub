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

import ast
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


# --- The roadmap may not schedule work the tree already contains -------------
#
# `docs/DEVELOPMENT_ROADMAP.md` Part II is a *plan*: every entry is an instruction to go
# build something. A partial post-merge sweep is therefore the same defect class as a
# dangling path above — it sends the next agent to rebuild a feature that already shipped.
# Each probe below is a fact about the tree, never about a doc, so the pair stays honest in
# both directions: when a probe flips, the assertion flips with it.

ROADMAP = "docs/DEVELOPMENT_ROADMAP.md"

# A closed entry is struck through or ticked. Deliberately NOT the word "shipped": the
# roadmap uses it in ordinary prose ("the shipped AI Step Builder"), and a marker that
# ambient prose satisfies is the shape-not-substance gate AGENTS.md warns about.
_ENTRY_CLOSED = re.compile(r"~~|✅|\*\*done")
_ENTRY_START = re.compile(r"^(?:[-*]|\d+\.)\s")


def _roadmap_entries() -> list[tuple[int, str]]:
    """(first line number, entry text) per top-level bullet / numbered item."""
    entries: list[tuple[int, str]] = []
    current: list[str] | None = None
    start = 0
    for number, line in enumerate((REPO / ROADMAP).read_text(encoding="utf-8").splitlines(), 1):
        if _ENTRY_START.match(line):
            if current is not None:
                entries.append((start, "\n".join(current)))
            current, start = [line], number
        elif current is not None and line.startswith((" ", "\t")):
            current.append(line)          # wrapped continuation of the same entry
        elif current is not None:
            entries.append((start, "\n".join(current)))
            current = None
    if current is not None:
        entries.append((start, "\n".join(current)))
    return entries


def _clause(entry: str, dra: str) -> str:
    """The one `;`-separated clause of an entry that talks about `dra`.

    Several roadmap entries carry two or three findings, so whole-entry matching would
    let a struck neighbour vouch for an item nobody swept.
    """
    flat = " ".join(part.strip() for part in entry.splitlines())
    return next((c for c in flat.split(";") if dra in c), flat)


def _reads(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# DRA id → the artifact in the tree that proves the item shipped.
SHIPPED_PROBES = {
    "DRA-05": lambda: (REPO / "agents/core/plugins/osint_enrich.py").is_file(),
    "DRA-06": lambda: "/api/screen/reflex" in _reads("agents/core/routers/multimodal.py"),
    "DRA-21": lambda: "stock-quotes" in _reads("agents/core/routers/market.py"),
    "DRA-23": lambda: "def llm_async_client" in _reads("agents/core/llm/egress.py"),
    "DRA-24": lambda: '"cached"' in _reads("agents/core/llm/cost_estimator.py"),
    "DRA-25": lambda: 'one_of("transport", {"stdio"})' in _reads("agents/core/mcp/client.py"),
    "DRA-28": lambda: "WorkflowBuilderPanel" in _reads("frontend/src/gap.tsx"),
    "DRA-38": lambda: "/drive" in _reads("agents/core/routers/acquisition.py"),
    "DRA-39": lambda: "subflow=spec.get" in _reads("agents/core/workflows/flow_api.py"),
    "DRA-41": lambda: "/api/learning/evolve" in _reads("agents/core/routers/learning.py"),
    "DRA-47": lambda: "def blocked_requests" in _reads("agents/core/security/ssrf.py"),
    "DRA-51": lambda: "def atomic_write_json" in _reads("agents/core/persistence/json_store.py"),
    "DRA-53": lambda: "from agents.core.notes_store import" in _reads("agents/core/routers/notes.py"),
}


def test_roadmap_does_not_schedule_dra_work_the_tree_already_shipped() -> None:
    entries = _roadmap_entries()
    unswept: list[str] = []
    for dra, probe in SHIPPED_PROBES.items():
        assert probe(), f"{dra}'s shipped artifact vanished — re-check the probe, not the doc"
        for number, entry in entries:
            if dra not in entry:
                continue
            clause = _clause(entry, dra)
            if not _ENTRY_CLOSED.search(clause):
                unswept.append(f"{ROADMAP}:{number} still schedules {dra} as unbuilt:\n  {clause}")
    assert not unswept, "roadmap entries contradict the tree:\n\n" + "\n\n".join(unswept)


def test_roadmap_still_names_the_halves_that_did_not_ship() -> None:
    """The opposite failure: a sweep that closes an item whose second half is open."""
    text = _reads(ROADMAP)
    overlays = ("agents.public.yaml", "agents/_system/agents.public.yaml")
    if not any((REPO / rel).exists() for rel in overlays):
        assert "agents.public.yaml" in text, "the public-demo roster overlay is unbuilt but unlisted"
    callers = [
        path for path in (REPO / "frontend/src").rglob("*.ts*")
        if path.name != "schema.gen.ts" and "/api/media/generate" in path.read_text(encoding="utf-8")
    ]
    if not callers:
        assert "/api/media/generate" in text, "media generate still has no caller but is unlisted"


def test_roadmap_uncalled_route_count_matches_the_punch_list() -> None:
    """The Phase 3 headline is a measurement — wiring routes has to move it."""
    tree = ast.parse(_reads("tests/test_hud_v2_parity.py"))
    sizes = [
        len(node.value.args[0].elts)
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and getattr(node.target, "id", "") == "UNCALLED_BACKLOG"
        and isinstance(node.value, ast.Call)
    ]
    assert len(sizes) == 1, "UNCALLED_BACKLOG moved or changed shape"
    claimed = re.search(r"(\d+)\s+shipped, user-facing routes have", _reads(ROADMAP))
    assert claimed, "the Phase 3 punch-list headline lost its number"
    assert int(claimed.group(1)) == sizes[0], (
        f"roadmap claims {claimed.group(1)} uncalled routes; the punch list holds {sizes[0]}"
    )
