"""data_export.py — portable user-data export (roadmap 0.14 · H23.9, export half).

GDPR-style data portability: dump the user's *content* DBs to a single,
human-readable JSON document (``{db: {table: [rows…]}}``) plus a manifest. This
is deliberately distinct from ``backup.py``: backup produces a binary,
restore-oriented ``.tar.gz`` of the whole data root; export produces a readable,
inspectable, portable JSON of the data the user actually owns.

**Secret hygiene.** Only an allow-list of user-*content* DBs is exported
(notes, missions, autonomy tasks, analytics). ``settings.db`` (config + secret
references) and any non-listed store are **never** exported, so a portability
dump can't leak tokens.

Read-only — it never mutates or deletes. The delete/forget ("forget me") half of
H23.9 and the HTTP surface are deliberate follow-ups. CLI:
``python -m agents.core.data_export [--out DIR]``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agents.core.paths import data_root

logger = logging.getLogger("jarvis.data_export")

EXPORT_VERSION = 1

# User-content DBs that belong to the owner and are safe to export. settings.db
# (config + secret references) and anything else are intentionally excluded.
EXPORT_DBS: tuple[str, ...] = ("notes.db", "missions.db", "autonomy.db", "analytics.db")

# Live JSON content stores. On main, notes are stored in notes.json (not the
# notes.db block-tree, which is test-only), and canvas.json holds saved replies —
# so a DB-only export silently omitted the user's actual notes. Mirrors
# data_purge.PURGE_JSON so export and forget cover the same owner content.
EXPORT_JSON: tuple[str, ...] = ("notes.json", "canvas.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _dump_db(path: Path) -> dict:
    """Dump every (non-internal) table of a SQLite DB to ``{table: [row-dicts]}``."""
    out: dict[str, list[dict]] = {}
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        for table in _table_names(conn):
            # Table names come from sqlite_master (the DB's own catalog), never
            # from user input, so this identifier is trusted.
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            out[table] = [dict(r) for r in rows]
    finally:
        conn.close()
    return out


def export_data(source_root: Optional[str] = None, out_dir: Optional[str] = None) -> dict:
    """Write a portable JSON export of the user-content DBs; return a manifest.

    Only ``EXPORT_DBS`` present under the data root are included. Returns
    ``{export, bytes, generated_at, databases:[…], row_counts:{…}}``.
    """
    src = Path(source_root) if source_root else data_root()
    out = Path(out_dir) if out_dir else (src / "exports")
    out.mkdir(parents=True, exist_ok=True)

    databases: dict[str, dict] = {}
    row_counts: dict[str, int] = {}
    for name in EXPORT_DBS:
        db_path = src / name
        if not db_path.exists():
            continue
        dumped = _dump_db(db_path)
        databases[name] = dumped
        row_counts[name] = sum(len(rows) for rows in dumped.values())

    json_stores: dict[str, object] = {}
    for name in EXPORT_JSON:
        json_path = src / name
        if not json_path.exists():
            continue
        try:
            json_stores[name] = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("skipping unreadable JSON store %s: %s", name, e)

    doc = {
        "version": EXPORT_VERSION,
        "generated_at": _now_iso(),
        "source_root": str(src),
        "databases": databases,
        "json_stores": json_stores,
    }
    # Filename is a server-generated timestamp only — no user value in the path.
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    export_path = out / f"jarvis-export-{ts}.json"
    export_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str),
                           encoding="utf-8")
    return {
        "export": str(export_path),
        "bytes": export_path.stat().st_size,
        "generated_at": doc["generated_at"],
        "databases": sorted(databases.keys()),
        "json_stores": sorted(json_stores.keys()),
        "row_counts": row_counts,
    }


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m agents.core.data_export",
        description="Export user-content DBs to a portable JSON document.")
    ap.add_argument("--out", help="output directory (default: <data root>/exports)")
    args = ap.parse_args(argv)
    result = export_data(out_dir=args.out)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
