"""data_export.py — portable user-data export (roadmap 0.14 · H23.9, export half).

GDPR-style data portability: dump the user's *content* DBs to a single,
human-readable JSON document (``{db: {table: [rows…]}}``) plus a manifest. This
is deliberately distinct from ``backup.py``: backup produces a binary,
restore-oriented ``.tar.gz`` of the whole data root; export produces a readable,
inspectable, portable JSON of the data the user actually owns.

**Secret hygiene.** Only an allow-list of user-*content* DBs is exported
(notes, missions, autonomy tasks, analytics), plus the two canonical private
Howard roots (raw imports and the derived archive). ``settings.db`` (config +
secret references) and unrelated stores are **never** exported, so a
portability dump can't leak tokens.

Read-only — it never mutates or deletes. The delete/forget ("forget me") half of
H23.9 and the HTTP surface are deliberate follow-ups. CLI:
``python -m agents.core.data_export [--out DIR]``.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agents.core.ingestion.lifecycle import PRIVATE_INGESTION_ROOTS, legacy_import_status
from agents.core.paths import data_root

logger = logging.getLogger("jarvis.data_export")

EXPORT_VERSION = 2

# User-content DBs that belong to the owner and are safe to export. settings.db
# (config + secret references) and anything else are intentionally excluded.
EXPORT_DBS: tuple[str, ...] = ("notes.db", "missions.db", "autonomy.db", "analytics.db")

# Live JSON content stores. On main, notes are stored in notes.json (not the
# notes.db block-tree, which is test-only), and canvas.json holds saved replies —
# so a DB-only export silently omitted the user's actual notes. Mirrors
# data_purge.PURGE_JSON so export and forget cover the same owner content.
EXPORT_JSON: tuple[str, ...] = ("notes.json", "canvas.json")

# Raw Howard imports and every derived archive artifact. These are directories,
# not a file allowlist: a new artifact below either root is exported by default.
EXPORT_PRIVATE_DIRS: tuple[str, ...] = PRIVATE_INGESTION_ROOTS

_SQLITE_SIDECARS: tuple[str, ...] = ("-wal", "-shm", "-journal")


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
            # from caller input. Quote them defensively because an imported DB
            # can still contain spaces, quotes, or SQL-looking catalog names.
            quoted = '"' + table.replace('"', '""') + '"'
            rows = conn.execute(f"SELECT * FROM {quoted}").fetchall()
            out[table] = [dict(r) for r in rows]
    finally:
        conn.close()
    return out


def _dump_jsonl(path: Path) -> dict:
    """Decode JSONL while retaining malformed lines verbatim instead of omitting them."""
    records: list[object] = []
    raw_lines: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            raw_lines.append({"line": line_number, "raw": line})
    result: dict[str, object] = {"format": "jsonl", "records": records}
    if raw_lines:
        result["raw_lines"] = raw_lines
    return result


def _dump_private_file(path: Path) -> dict:
    """Return a JSON-safe, portable representation of one private ingestion file."""
    if path.suffix == ".db":
        return {"format": "sqlite", "tables": _dump_db(path)}
    if path.suffix == ".json":
        text = path.read_text(encoding="utf-8")
        try:
            return {"format": "json", "value": json.loads(text)}
        except ValueError:
            return {"format": "invalid_json_text", "text": text}
    if path.suffix == ".jsonl":
        return _dump_jsonl(path)

    payload = path.read_bytes()
    try:
        return {"format": "text", "text": payload.decode("utf-8")}
    except UnicodeDecodeError:
        return {
            "format": "base64",
            "data": base64.b64encode(payload).decode("ascii"),
        }


def _dump_private_dir(path: Path) -> dict:
    """Export one private root recursively without ever following symlinks."""
    result: dict[str, object] = {"exists": path.exists(), "files": {}, "skipped": []}
    files: dict[str, dict] = result["files"]  # type: ignore[assignment]
    skipped: list[dict[str, str]] = result["skipped"]  # type: ignore[assignment]
    if path.is_symlink():
        result["exists"] = False
        skipped.append({"path": ".", "reason": "symlink_refused"})
        return result
    if not path.exists():
        return result
    if not path.is_dir():
        skipped.append({"path": ".", "reason": "not_a_directory"})
        return result

    for item in sorted(path.rglob("*"), key=lambda candidate: candidate.as_posix()):
        relative = item.relative_to(path).as_posix()
        if item.is_symlink():
            skipped.append({"path": relative, "reason": "symlink_refused"})
            continue
        if not item.is_file():
            continue
        if item.name.endswith(_SQLITE_SIDECARS):
            base_name = item.name
            for suffix in _SQLITE_SIDECARS:
                if base_name.endswith(suffix):
                    base_name = base_name[: -len(suffix)]
                    break
            if (item.parent / base_name).is_file():
                files[relative] = {
                    "format": "sqlite_sidecar",
                    "covered_by": (item.parent / base_name).relative_to(path).as_posix(),
                }
            else:
                skipped.append({"path": relative, "reason": "orphan_sqlite_sidecar"})
            continue
        try:
            files[relative] = _dump_private_file(item)
        except (OSError, sqlite3.DatabaseError) as exc:
            logger.warning("could not export private ingestion file %s: %s", item, exc)
            skipped.append({"path": relative, "reason": "unreadable"})
    return result


def _dump_vault(src: Path) -> dict:
    """Decrypt and embed every vault item (T-0.20).

    The vault's on-disk `.blob` files are ciphertext by design — a raw copy of
    the directory into a "readable, portable" export would just be unreadable
    noise. This opens the SAME root the live app would (same key file) and
    embeds each item's plaintext as base64 alongside its metadata. Read-only:
    ``Vault.get``/``Vault.list`` never mutate the index or blobs.
    """
    vault_dir = src / "vault"
    if not vault_dir.is_dir():
        return {"available": False, "items": [], "skipped": []}
    try:
        from agents.core.vault import Vault, VaultError
        vault = Vault(root=vault_dir)
        entries = vault.list()
    except Exception as exc:
        logger.warning("could not open/list vault for export: %s", exc)
        return {"available": False, "items": [], "skipped": [{"reason": "vault_unavailable"}]}
    items: list[dict] = []
    skipped: list[dict] = []
    for entry in entries:
        try:
            data = vault.get(entry["id"])
        except VaultError as exc:
            logger.warning("could not decrypt vault item %s for export: %s", entry["id"], exc)
            skipped.append({"id": entry["id"], "reason": "decrypt_failed"})
            continue
        items.append({**entry, "data_base64": base64.b64encode(data).decode("ascii")})
    return {"available": True, "items": items, "skipped": skipped}


def export_data(source_root: Optional[str] = None, out_dir: Optional[str] = None) -> dict:
    """Write a portable JSON export of the user-content DBs; return a manifest.

    ``EXPORT_DBS`` and ``EXPORT_JSON`` are allow-listed; the canonical Howard
    roots are captured recursively so a newly-added archive artifact cannot be
    silently omitted. Returns a manifest including completeness for those roots.
    """
    src = Path(source_root) if source_root else data_root()
    out = Path(out_dir) if out_dir else (src / "exports")
    out.mkdir(parents=True, exist_ok=True)
    legacy_ingestion = legacy_import_status()

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

    private_ingestion = {
        name: _dump_private_dir(src / name)
        for name in EXPORT_PRIVATE_DIRS
    }
    private_complete = (
        all(not item["skipped"] for item in private_ingestion.values())
        and not legacy_ingestion["detected"]
    )

    vault_export = _dump_vault(src)

    doc = {
        "version": EXPORT_VERSION,
        "generated_at": _now_iso(),
        "source_root": str(src),
        "databases": databases,
        "json_stores": json_stores,
        "private_ingestion": private_ingestion,
        "legacy_private_ingestion": legacy_ingestion,
        "vault": vault_export,
    }
    # Filename is a server-generated timestamp only — no user value in the path.
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    export_path = out / f"jarvis-export-{ts}.json"
    # Owner-only from birth (0o600, no chmod-after-write window): the export
    # embeds decrypted vault plaintext and private message content, so a
    # umask-default world-readable file would silently downgrade the at-rest
    # protection the vault's own chmod-private discipline provides.
    fd = os.open(export_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(doc, indent=2, ensure_ascii=False, default=str))
    return {
        "export": str(export_path),
        "bytes": export_path.stat().st_size,
        "generated_at": doc["generated_at"],
        "databases": sorted(databases.keys()),
        "json_stores": sorted(json_stores.keys()),
        "private_ingestion_roots": list(EXPORT_PRIVATE_DIRS),
        "private_ingestion_complete": private_complete,
        "legacy_private_ingestion": legacy_ingestion,
        "row_counts": row_counts,
        "vault_items": len(vault_export["items"]),
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
