"""'Forget me' data purge (roadmap 0.14 · H23.9) — erase user content at rest.

Final piece of the data-rights trilogy (backup #302 → export #303 → **delete**). The
user can snapshot and export their content; this lets them *forget* it. The purge is
intentionally **backup-first**: it snapshots the data root and verifies the snapshot
restores before deleting anything, so a forget is always recoverable from the archive it
just made (``PurgeError`` aborts the purge if that snapshot fails verification).

Scope is the user's **structured content** at rest:

  * ``missions.db`` / ``autonomy.db`` / ``analytics.db`` — rows deleted, schema kept
  * ``notes.json`` / ``canvas.json``                     — reset to an empty object
  * the **memory subsystem** (when ``memory=True``, the CLI + ``/api/admin/forget`` default,
    AUD-2) — the fixed graph/entity/decay/cognition stores, the embedding cache, and
    conversation transcripts for confirmed sessions (see ``_purge_memory_at_rest``)

Rows are ``DELETE``\\ d (not the files dropped) and JSON is rewritten to ``{}`` so live
stores holding open handles read back empty rather than hitting a missing file — WAL keeps
the deletes visible across connections.

Excluded by design: ``settings.db`` (config + OAuth secrets — same boundary the export
draws), ``security/audit.db`` (append-only compliance chain), and system stores
(``checkpoints.db``/``marketplace.db``). Note: the **backup-first** safety net snapshots the
data root *before* deleting; that archive is encrypted only when a backup key is configured
(AUD-1) — until then it holds full plaintext PII, so secure or remove it after a forget, or
pass ``--no-backup``.

This list mirrors the export's content set; when the export module lands on main its
``EXPORT_DBS`` and these allow-lists should be reconciled (the export branch migrated notes
to a SQLite ``notes.db``; on main notes is still ``notes.json``, hence ``PURGE_JSON``).
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Iterable, Optional

from agents.core import backup as _backup
from agents.core.automation_contracts import ContractTemplate, contract_denial, predicate
from agents.core.paths import data_root
from agents.core.validation import is_valid_session_id

logger = logging.getLogger("jarvis.purge")

# User-content SQLite DBs — every row in every (non-internal) table is deleted, schema kept.
PURGE_DBS: tuple[str, ...] = ("missions.db", "autonomy.db", "analytics.db")
# User-content JSON stores — reset to an empty object (their top-level shape is a dict).
# canvas.json holds explicitly saved assistant replies (Canvas artifacts) — user content;
# CanvasStore._deserialize({}) loads the reset file as an empty store.
PURGE_JSON: tuple[str, ...] = ("notes.json", "canvas.json")

# AUD-2 — the memory subsystem at rest. These FIXED-name stores hold extracted
# user content (the knowledge graph, named entities, decay activations); deleting
# them by exact name is unambiguous. Conversation transcripts are session-keyed
# (`<sid>.json` / `<sid>.jsonl`) and share the data root with config JSON, so they
# are removed only for *confirmed* sessions (see _purge_memory_at_rest), never by
# a blanket glob. The live in-memory stores are cleared first (clear_live_memory)
# so a running orchestrator doesn't re-persist what we delete.
PURGE_MEMORY_FILES: tuple[str, ...] = (
    "bitemporal_kg.json",
    "entities.json",
    "decay.json",
    "cognition/core_memory.json",
    "cognition/living_tiers.json",
    "house/private_graph.enc",
    "house/private_graph.cipher.salt",
)
# Directories removed wholesale (embedded recall cache derived from user content).
PURGE_MEMORY_DIRS: tuple[str, ...] = ("embedding_cache",)
# Top-level *.jsonl that are NOT conversation transcripts — never treated as sessions.
_NON_SESSION_JSONL: frozenset[str] = frozenset({"autonomy_journal", "problems"})


class PurgeError(RuntimeError):
    """Raised when a purge cannot proceed safely (e.g. the pre-forget backup won't verify)."""


DATA_PURGE_CONTRACT_KIND = "data.purge"


def _data_purge_contract_template() -> ContractTemplate:
    """Contract form of the destructive user-content purge gate."""

    def data_purge_kind(view, now):
        return view.get("kind") == DATA_PURGE_CONTRACT_KIND

    def action_matches(view, now):
        return view.get("action") == "purge_data"

    def source_known(view, now):
        return view.get("source") in {"function", "api.admin.forget"}

    def flags_are_bool(view, now):
        return isinstance(view.get("backup_first"), bool) and isinstance(view.get("memory"), bool)

    def session_count_valid(view, now):
        value = view.get("session_count")
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    return ContractTemplate(kind=DATA_PURGE_CONTRACT_KIND, constraints=(
        predicate("data_purge_kind", data_purge_kind, reason="invalid_kind"),
        predicate("action_matches", action_matches, reason="invalid_action"),
        predicate("source_known", source_known, reason="unknown_source"),
        predicate("flags_are_bool", flags_are_bool, reason="invalid_flags"),
        predicate("session_count_valid", session_count_valid, reason="invalid_session_count"),
    ), requires_approval=False, description="Admissibility for destructive user-content purge.")


DATA_PURGE_CONTRACT = _data_purge_contract_template()


def purge_contract_denial(*, source: str = "function", backup_first: bool = True,
                          memory: bool = False, session_count: int = 0,
                          source_root: Optional[str] = None) -> str | None:
    """Return a stable contract denial for a purge request, or None."""
    payload = {
        "kind": DATA_PURGE_CONTRACT_KIND,
        "action": "purge_data",
        "source": source,
        "backup_first": bool(backup_first),
        "memory": bool(memory),
        "session_count": int(session_count),
        "source_root": "custom" if source_root else "default",
    }
    try:
        decision = DATA_PURGE_CONTRACT.evaluate(payload, now=time.time())
    except Exception:
        logger.warning("data purge contract evaluation failed", exc_info=True)
        return "contract_error"
    return contract_denial(decision)


def _purge_db(path: Path) -> dict:
    """Delete every row from each non-internal table in *path*; keep the schema.

    Table names come from the SQLite catalog (never caller input), so no external value
    reaches the SQL text. Returns ``{table: rows_deleted}``.
    """
    deleted: dict[str, int] = {}
    conn = sqlite3.connect(str(path))
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
        for table in tables:
            before = conn.total_changes
            conn.execute(_delete_all_rows_sql(table))
            deleted[table] = conn.total_changes - before
        conn.commit()
    finally:
        conn.close()
    return deleted


def _delete_all_rows_sql(table: str) -> str:
    # Table names come from sqlite_master. Quote defensively anyway.
    quoted = '"' + table.replace('"', '""') + '"'
    return " ".join(("DELETE", "FROM", quoted))


def _purge_memory_at_rest(root: Path, live_session_ids: Iterable[str] = ()) -> dict:
    """Erase the memory subsystem's at-rest content under *root*.

    Removes the fixed-name graph/entity/decay stores and the embedding cache, then
    deletes conversation transcripts for *confirmed* sessions only: ids passed in
    from the live manager, plus the stems of any top-level ``*.jsonl`` that look
    like a session (validated id, not on the non-session denylist). Files like
    ``notes.json`` / ``canvas.json`` — which have no ``.jsonl`` and aren't live
    sessions — are never touched *here*; the ``PURGE_JSON`` pass resets them.
    """
    report: dict = {"files": [], "dirs": [], "sessions": []}

    for name in PURGE_MEMORY_FILES:
        p = root / name
        if p.exists():
            p.unlink()
            report["files"].append(name)

    for name in PURGE_MEMORY_DIRS:
        d = root / name
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            report["dirs"].append(name)

    sessions = {s for s in live_session_ids if is_valid_session_id(s)}
    for jl in root.glob("*.jsonl"):
        stem = jl.stem
        if stem not in _NON_SESSION_JSONL and is_valid_session_id(stem):
            sessions.add(stem)
    for sid in sorted(sessions):
        removed = False
        for suffix in (".json", ".jsonl"):
            p = root / f"{sid}{suffix}"
            if p.exists():
                p.unlink()
                removed = True
        if removed:
            report["sessions"].append(sid)
    return report


async def clear_live_memory(orch) -> list[str]:
    """Best-effort clear of the orchestrator's in-memory stores before a purge, so a
    running process doesn't re-persist what the file purge removes. Never raises."""
    cleared: list[str] = []
    mem = getattr(orch, "memory", None)
    if mem is not None and hasattr(mem, "clear"):
        try:
            await mem.clear()
            cleared.append("conversation")
        except Exception:  # pragma: no cover - defensive
            logger.warning("clear_live_memory: conversation clear failed", exc_info=True)
        for attr in ("graph", "vectors"):
            store = getattr(mem, attr, None)
            if store is not None and hasattr(store, "clear"):
                try:
                    store.clear()
                    cleared.append(attr)
                except Exception:  # pragma: no cover - defensive
                    logger.warning("clear_live_memory: %s clear failed", attr, exc_info=True)
    for attr in ("entities", "decay"):
        store = getattr(orch, attr, None)
        if store is not None and hasattr(store, "clear"):
            try:
                store.clear()
                cleared.append(attr)
            except Exception:  # pragma: no cover - defensive
                logger.warning("clear_live_memory: %s clear failed", attr, exc_info=True)
    # Canvas artifacts are explicitly saved user replies: clear the LIVE store
    # too, so a running orchestrator can't re-persist forgotten elements over the
    # PURGE_JSON reset on its next save. Use the in-memory-only clear so this does
    # NOT rewrite canvas.json before purge_data's pre-forget backup snapshots it
    # (a persisting clear here would drop the artifacts from the recovery archive).
    canvas = getattr(orch, "canvas", None)
    if canvas is not None:
        try:
            if hasattr(canvas, "clear_memory"):
                canvas.clear_memory()
                cleared.append("canvas")
            elif hasattr(canvas, "clear"):
                canvas.clear(keep_pinned=False)
                cleared.append("canvas")
        except Exception:  # pragma: no cover - defensive
            logger.warning("clear_live_memory: canvas clear failed", exc_info=True)
    cognition = getattr(orch, "cognition", None)
    living = None
    if cognition is not None and hasattr(cognition, "module"):
        try:
            living = cognition.module("memory")
        except Exception:  # pragma: no cover - defensive
            logger.warning("clear_live_memory: cognition memory lookup failed", exc_info=True)
    if living is not None and hasattr(living, "clear"):
        try:
            living.clear()
            cleared.append("cognition_memory")
        except Exception:  # pragma: no cover - defensive
            logger.warning("clear_live_memory: cognition memory clear failed", exc_info=True)
    # H20: drop the frozen core-block prompt snapshot — a purge is exactly the
    # case where snapshot staleness is unacceptable (forgotten facts must not
    # keep being injected until the session/day cache key rolls).
    if getattr(orch, "_core_block_cache", None) is not None:
        orch._core_block_cache = None
        cleared.append("core_block_cache")
    return cleared


def _json_entries(path: Path) -> int:
    """Best-effort count of top-level entries in a JSON store (for the report)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return len(data) if isinstance(data, (dict, list)) else 0
    except (ValueError, OSError):
        return 0


def purge_data(source_root: Optional[str] = None, *, backup_first: bool = True,
               memory: bool = False, session_ids: Optional[Iterable[str]] = None) -> dict:
    """Erase the user's content under the data root. Irreversible.

    When ``backup_first`` (default), a snapshot is created **and verified** before any
    deletion; if it fails verification, ``PurgeError`` is raised and nothing is purged.
    (The snapshot is encrypted at rest when a backup key is configured — see AUD-1.)

    When ``memory`` (AUD-2), the memory subsystem at rest is also erased: the fixed
    graph/entity/decay/cognition stores, the embedding cache, and conversation
    transcripts for ``session_ids`` (plus any session-shaped ``*.jsonl``). Callers
    that have a live orchestrator should ``await clear_live_memory(orch)`` first
    so nothing is re-persisted, and pass its known ``session_ids``.

    Returns ``{ok, backup, purged, total_rows}``.
    """
    sessions = tuple(session_ids or ())
    denial = purge_contract_denial(
        source="function",
        backup_first=backup_first,
        memory=memory,
        session_count=len(sessions),
        source_root=source_root,
    )
    if denial is not None:
        raise PurgeError(f"contract denied: {denial}")

    root = Path(source_root) if source_root else data_root()
    report: dict = {"ok": True, "backup": None, "purged": {}, "total_rows": 0}

    if backup_first:
        snap = _backup.create_backup(source_root=str(root), label="pre-forget")
        verdict = _backup.verify_backup(snap["archive"])
        if not verdict.get("ok"):
            raise PurgeError(
                f"pre-forget backup failed verification ({snap['archive']}); aborting purge"
            )
        report["backup"] = {"archive": snap["archive"], "verified": True}

    for name in PURGE_DBS:
        p = root / name
        if not p.exists():
            continue
        deleted = _purge_db(p)
        report["purged"][name] = deleted
        report["total_rows"] += sum(deleted.values())

    for name in PURGE_JSON:
        p = root / name
        if not p.exists():
            continue
        before = _json_entries(p)
        p.write_text("{}", encoding="utf-8")
        report["purged"][name] = {"reset": before}

    if memory:
        report["purged"]["memory"] = _purge_memory_at_rest(root, sessions)

    logger.info("forget purge complete: %s rows across %s targets (memory=%s, backup=%s)",
                report["total_rows"], len(report["purged"]), memory,
                report["backup"]["archive"] if report["backup"] else "none")
    return report


# ── CLI ───────────────────────────────────────────────────────────
def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agents.core.data_purge",
                                 description="Jarvis 'forget me' — erase user content at rest")
    ap.add_argument("--confirm", action="store_true",
                    help="required: acknowledge that this irreversibly erases user content")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip the (default) backup-first safety net — NOT recommended")
    ap.add_argument("--no-memory", action="store_true",
                    help="leave the memory subsystem at rest (KG/entities/decay/embedding cache + "
                         "session transcripts) intact; by default a forget erases it too (AUD-2)")
    ap.add_argument("--source-root", default=None,
                    help="data root to purge (defaults to $JARVIS_HOME / memory_logs)")
    args = ap.parse_args(argv)

    if not args.confirm:
        print("refusing to purge without --confirm (this irreversibly erases user content)")
        return 2
    try:
        # memory on by default so an offline CLI forget is as complete as the endpoint's
        # (which also clears the *live* stores first — the CLI can only reach what's at rest).
        report = purge_data(source_root=args.source_root, backup_first=not args.no_backup,
                            memory=not args.no_memory)
    except PurgeError as e:
        print(f"purge aborted: {e}")
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
