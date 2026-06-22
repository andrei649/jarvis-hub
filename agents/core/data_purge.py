"""'Forget me' data purge (roadmap 0.14 · H23.9) — erase user content at rest.

Final piece of the data-rights trilogy (backup #302 → export #303 → **delete**). The
user can snapshot and export their content; this lets them *forget* it. The purge is
intentionally **backup-first**: it snapshots the data root and verifies the snapshot
restores before deleting anything, so a forget is always recoverable from the archive it
just made (``PurgeError`` aborts the purge if that snapshot fails verification).

Scope is the user's **structured content** at rest:

  * ``missions.db`` / ``autonomy.db`` / ``analytics.db`` — rows deleted, schema kept
  * ``notes.json``                                       — reset to an empty object

Rows are ``DELETE``\\ d (not the files dropped) and JSON is rewritten to ``{}`` so live
stores holding open handles read back empty rather than hitting a missing file — WAL keeps
the deletes visible across connections.

Excluded by design: ``settings.db`` (config + OAuth secrets — same boundary the export
draws), ``memory.db`` + conversation session files (their own surfaces: ``/memory/clear``,
``/api/admin/memory/clear``, ``/api/memory/decay/forget``), ``security/audit.db``
(append-only compliance chain), and system stores (``checkpoints.db``/``marketplace.db``).

This list mirrors the export's content set; when the export module lands on main its
``EXPORT_DBS`` and these allow-lists should be reconciled (the export branch migrated notes
to a SQLite ``notes.db``; on main notes is still ``notes.json``, hence ``PURGE_JSON``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from agents.core import backup as _backup
from agents.core.paths import data_root

logger = logging.getLogger("jarvis.purge")

# User-content SQLite DBs — every row in every (non-internal) table is deleted, schema kept.
PURGE_DBS: tuple[str, ...] = ("missions.db", "autonomy.db", "analytics.db")
# User-content JSON stores — reset to an empty object (their top-level shape is a dict).
PURGE_JSON: tuple[str, ...] = ("notes.json",)


class PurgeError(RuntimeError):
    """Raised when a purge cannot proceed safely (e.g. the pre-forget backup won't verify)."""


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
            # Identifier quoted from the catalog name — not a request value.
            conn.execute(f'DELETE FROM "{table}"')
            deleted[table] = conn.total_changes - before
        conn.commit()
    finally:
        conn.close()
    return deleted


def _json_entries(path: Path) -> int:
    """Best-effort count of top-level entries in a JSON store (for the report)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return len(data) if isinstance(data, (dict, list)) else 0
    except (ValueError, OSError):
        return 0


def purge_data(source_root: Optional[str] = None, *, backup_first: bool = True) -> dict:
    """Erase the user's structured content under the data root. Irreversible.

    When ``backup_first`` (default), a snapshot is created **and verified** before any
    deletion; if it fails verification, ``PurgeError`` is raised and nothing is purged.

    Returns ``{ok, backup, purged, total_rows}`` where ``backup`` is
    ``{archive, verified}`` or ``None``, and ``purged`` maps each target to what it cleared.
    """
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

    logger.info("forget purge complete: %s rows across %s targets (backup=%s)",
                report["total_rows"], len(report["purged"]),
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
    ap.add_argument("--source-root", default=None,
                    help="data root to purge (defaults to $JARVIS_HOME / memory_logs)")
    args = ap.parse_args(argv)

    if not args.confirm:
        print("refusing to purge without --confirm (this irreversibly erases user content)")
        return 2
    try:
        report = purge_data(source_root=args.source_root, backup_first=not args.no_backup)
    except PurgeError as e:
        print(f"purge aborted: {e}")
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
