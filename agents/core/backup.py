"""backup.py — one-command local backup / restore + restore-drill (roadmap 0.14 · H23.8).

All persistent runtime state lives under a single root (``paths.data_root()``):
SQLite DBs (settings, autonomy, missions, analytics, marketplace, notes …),
JSON stores, tokens, audio, eval corpora. This module snapshots that root into a
single ``.tar.gz`` and restores it, with three honesty/safety properties a real
backup needs:

* **Consistent DB snapshots.** A live SQLite DB in WAL mode must not be copied
  byte-for-byte mid-write. Each ``*.db`` is snapshotted through the SQLite online
  backup API (``Connection.backup``), which takes a transactionally-consistent
  copy even while the app is running; the transient ``-wal`` / ``-shm`` sidecars
  are skipped (their content is already folded into the snapshot).
* **A real restore drill.** ``verify_backup`` extracts the archive into a temp
  dir and runs ``PRAGMA integrity_check`` on every DB — so "we have backups" is
  provable, not assumed, without touching live data.
* **No archive path-traversal.** Extraction validates every member resolves
  *inside* the destination (Zip-Slip guard) and writes only regular files/dirs.

CLI: ``python -m agents.core.backup create|list|verify|restore`` (the
one-command story). Restore refuses to overwrite a non-empty target unless
``--force``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agents.core.paths import data_root

logger = logging.getLogger("jarvis.backup")

BACKUP_VERSION = 1
_ARCHIVE_PREFIX = "jarvis-backup-"
_SQLITE_SIDECARS = ("-wal", "-shm", "-journal")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_within(path: Path, root: Path) -> bool:
    root = root.resolve()
    p = path.resolve()
    return p == root or root in p.parents


def _sqlite_consistent_copy(src: Path, dst: Path) -> None:
    """Transactionally-consistent copy of a (possibly live, WAL-mode) SQLite DB."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(src))
    dest = sqlite3.connect(str(dst))
    try:
        with dest:
            source.backup(dest)
    finally:
        dest.close()
        source.close()


def _integrity_check(db: Path) -> str:
    """Run PRAGMA integrity_check; return 'ok' or the first problem reported."""
    try:
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
        return row[0] if row else "empty"
    except sqlite3.DatabaseError as e:
        return f"error: {e}"


def default_backup_dir(source_root: Optional[Path] = None) -> Path:
    return (source_root or data_root()) / "backups"


# ── create ────────────────────────────────────────────────────────
def create_backup(source_root: Optional[str] = None, out_dir: Optional[str] = None,
                  label: str = "") -> dict:
    """Snapshot the data root into a single ``.tar.gz``; return a manifest dict.

    DBs are copied through the SQLite backup API (consistent); everything else is
    archived as-is. The output ``backups/`` dir and SQLite sidecars are excluded.
    """
    src = Path(source_root) if source_root else data_root()
    if not src.exists():
        raise FileNotFoundError(f"data root does not exist: {src}")
    out = Path(out_dir) if out_dir else default_backup_dir(src)
    out.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = "".join(c for c in label if c.isalnum() or c in "-_")
    archive = out / f"{_ARCHIVE_PREFIX}{ts}{('-' + safe_label) if safe_label else ''}.tar.gz"
    manifest = {"created_at": _now_iso(), "source_root": str(src),
                "version": BACKUP_VERSION, "dbs": [], "file_count": 0}

    # Materialise the file list BEFORE opening the archive so the growing archive
    # (written into out/) is never itself swept in.
    files = sorted(p for p in src.rglob("*") if p.is_file())
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(archive, "w:gz") as tar:
        tmp = Path(tmp)
        for path in files:
            if _is_within(path, out):
                continue  # never back up the backups dir
            if path.name.endswith(_SQLITE_SIDECARS):
                continue  # WAL/shm/journal — folded into the DB snapshot
            rel = path.relative_to(src)
            if path.suffix == ".db":
                snap = tmp / rel
                _sqlite_consistent_copy(path, snap)
                tar.add(snap, arcname=str(rel))
                manifest["dbs"].append(str(rel))
            else:
                tar.add(path, arcname=str(rel))
            manifest["file_count"] += 1
        mpath = tmp / "backup_manifest.json"
        mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        tar.add(mpath, arcname="backup_manifest.json")

    return {"archive": str(archive), "bytes": archive.stat().st_size, **manifest}


# ── list ──────────────────────────────────────────────────────────
def list_backups(out_dir: Optional[str] = None) -> list[dict]:
    """List backup archives (newest first) with size + mtime."""
    out = Path(out_dir) if out_dir else default_backup_dir()
    if not out.exists():
        return []
    rows = []
    for p in out.glob(f"{_ARCHIVE_PREFIX}*.tar.gz"):
        try:
            st = p.stat()
        except OSError:
            continue
        rows.append({
            "name": p.name,
            "bytes": st.st_size,
            "modified_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
        })
    rows.sort(key=lambda r: r["modified_at"], reverse=True)
    return rows


def resolve_backup(name: str, out_dir: Optional[str] = None) -> Optional[Path]:
    """Resolve a backup *name* to a path by matching the trusted listing.

    The caller-supplied ``name`` is matched against the actual directory listing
    rather than joined into a path, so no request value reaches a path expression
    (path-injection defeated at the source)."""
    out = Path(out_dir) if out_dir else default_backup_dir()
    if not out.exists():
        return None
    for p in out.glob(f"{_ARCHIVE_PREFIX}*.tar.gz"):
        if p.name == name:
            return p
    return None


# ── safe extraction ───────────────────────────────────────────────
def _safe_extract(tar: tarfile.TarFile, dest: Path) -> int:
    """Extract regular files/dirs only, each validated to resolve inside dest.

    Defeats Zip-Slip: a member whose resolved path escapes ``dest`` raises. Symlinks
    and special files are skipped entirely (never written)."""
    dest = dest.resolve()
    count = 0
    for m in tar.getmembers():
        target = (dest / m.name).resolve()
        if target != dest and dest not in target.parents:
            raise ValueError(f"unsafe path in archive: {m.name!r}")
        if m.isdir():
            target.mkdir(parents=True, exist_ok=True)
        elif m.isfile():
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = tar.extractfile(m)
            if extracted is None:
                continue
            with extracted as srcf, open(target, "wb") as outf:
                shutil.copyfileobj(srcf, outf)
            count += 1
        # symlinks/devices/etc → skipped by design
    return count


# ── verify (the restore drill) ────────────────────────────────────
def verify_backup(archive: str) -> dict:
    """Restore-drill: extract into a temp dir and integrity-check every DB.

    Proves the archive is restorable without touching live data. Returns
    ``{ok, dbs:{rel: 'ok'|problem}, file_count, manifest}``.
    """
    arc = Path(archive)
    if not arc.exists():
        raise FileNotFoundError(f"backup not found: {arc}")
    report = {"archive": str(arc), "ok": True, "dbs": {}, "file_count": 0, "manifest": None}
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(arc, "r:gz") as tar:
        tmpp = Path(tmp)
        report["file_count"] = _safe_extract(tar, tmpp)
        mf = tmpp / "backup_manifest.json"
        if mf.exists():
            try:
                report["manifest"] = json.loads(mf.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                report["manifest"] = None
        for db in sorted(tmpp.rglob("*.db")):
            res = _integrity_check(db)
            report["dbs"][str(db.relative_to(tmpp))] = res
            if res != "ok":
                report["ok"] = False
    return report


# ── restore ───────────────────────────────────────────────────────
def restore_backup(archive: str, target_root: str, force: bool = False) -> dict:
    """Extract a backup into ``target_root``. Refuses a non-empty target unless force.

    Deliberately requires an *explicit* target (never silently overwrites the live
    data root). Hot in-place restore is an operator action: pass the live root +
    ``force=True`` with the server stopped.
    """
    arc = Path(archive)
    if not arc.exists():
        raise FileNotFoundError(f"backup not found: {arc}")
    target = Path(target_root)
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(
            f"target {target} is not empty — pass force=True to overwrite")
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(arc, "r:gz") as tar:
        count = _safe_extract(tar, target)
    # Post-restore drill on the live target so a corrupt restore is caught now.
    dbs = {str(p.relative_to(target)): _integrity_check(p) for p in sorted(target.rglob("*.db"))}
    return {"restored_to": str(target), "file_count": count, "dbs": dbs,
            "ok": all(v == "ok" for v in dbs.values())}


# ── CLI (one-command) ─────────────────────────────────────────────
def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agents.core.backup",
                                 description="Jarvis local backup / restore")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create", help="snapshot the data root to a .tar.gz")
    sub.add_parser("list", help="list existing backups")
    pv = sub.add_parser("verify", help="restore-drill a backup (integrity-check its DBs)")
    pv.add_argument("name", help="backup file name (see `list`)")
    pr = sub.add_parser("restore", help="restore a backup into a target dir")
    pr.add_argument("name", help="backup file name (see `list`)")
    pr.add_argument("target", help="destination directory")
    pr.add_argument("--force", action="store_true", help="overwrite a non-empty target")
    args = ap.parse_args(argv)

    if args.cmd == "create":
        print(json.dumps(create_backup(), indent=2))
    elif args.cmd == "list":
        print(json.dumps(list_backups(), indent=2))
    elif args.cmd == "verify":
        path = resolve_backup(args.name)
        if not path:
            print(f"no such backup: {args.name}"); return 2
        rep = verify_backup(str(path))
        print(json.dumps(rep, indent=2))
        return 0 if rep["ok"] else 1
    elif args.cmd == "restore":
        path = resolve_backup(args.name)
        if not path:
            print(f"no such backup: {args.name}"); return 2
        print(json.dumps(restore_backup(str(path), args.target, force=args.force), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
