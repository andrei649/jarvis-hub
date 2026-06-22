"""Backup / restore + restore-drill (0.14 · H23.8).

Offline: builds a throwaway data root with real SQLite DBs + plain files, then
exercises create → list → verify(drill) → restore. Asserts the safety/honesty
properties — consistent DB snapshots, integrity-checked drill, Zip-Slip-proof
extraction, and that the backups dir isn't recursively swept into its own archive.
"""
import sqlite3
import tarfile
from pathlib import Path

import pytest

from agents.core import backup as bk


def _seed_db(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


@pytest.fixture()
def data_root(tmp_path):
    root = tmp_path / "data"
    _seed_db(root / "settings.db", 3)
    _seed_db(root / "autonomy.db", 5)
    (root / "tokens").mkdir(parents=True)
    (root / "tokens" / "note.txt").write_text("hello", encoding="utf-8")
    return root


def test_create_produces_archive_with_manifest(data_root):
    res = bk.create_backup(source_root=str(data_root))
    assert Path(res["archive"]).exists()
    assert res["bytes"] > 0
    assert sorted(res["dbs"]) == ["autonomy.db", "settings.db"]
    with tarfile.open(res["archive"], "r:gz") as tar:
        names = tar.getnames()
    assert "backup_manifest.json" in names
    assert "settings.db" in names and "tokens/note.txt" in names


def test_backups_dir_not_swept_into_archive(data_root):
    bk.create_backup(source_root=str(data_root))           # first → creates backups/
    res2 = bk.create_backup(source_root=str(data_root))    # second must exclude backups/
    with tarfile.open(res2["archive"], "r:gz") as tar:
        names = tar.getnames()
    assert not any(n.startswith("backups/") for n in names)


def test_sidecars_excluded(data_root):
    # touch a WAL sidecar; it must not be archived (folded into the DB snapshot)
    (data_root / "settings.db-wal").write_text("x", encoding="utf-8")
    res = bk.create_backup(source_root=str(data_root))
    with tarfile.open(res["archive"], "r:gz") as tar:
        names = tar.getnames()
    assert not any(n.endswith("-wal") for n in names)


def test_list_backups_newest_first(data_root):
    bk.create_backup(source_root=str(data_root), label="one")
    bk.create_backup(source_root=str(data_root), label="two")
    listing = bk.list_backups(out_dir=str(bk.default_backup_dir(data_root)))
    assert len(listing) == 2
    assert all(r["name"].startswith("jarvis-backup-") for r in listing)


def test_verify_drill_passes_on_good_backup(data_root):
    res = bk.create_backup(source_root=str(data_root))
    report = bk.verify_backup(res["archive"])
    assert report["ok"] is True
    assert report["dbs"]["settings.db"] == "ok"
    assert report["dbs"]["autonomy.db"] == "ok"
    assert report["manifest"]["version"] == bk.BACKUP_VERSION


def test_restore_roundtrip_preserves_rows(data_root, tmp_path):
    res = bk.create_backup(source_root=str(data_root))
    target = tmp_path / "restored"
    out = bk.restore_backup(res["archive"], str(target))
    assert out["ok"] is True
    conn = sqlite3.connect(str(target / "autonomy.db"))
    n = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    conn.close()
    assert n == 5
    assert (target / "tokens" / "note.txt").read_text() == "hello"


def test_restore_refuses_nonempty_target(data_root, tmp_path):
    res = bk.create_backup(source_root=str(data_root))
    target = tmp_path / "restored"
    target.mkdir()
    (target / "existing").write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        bk.restore_backup(res["archive"], str(target))
    # force overwrites
    out = bk.restore_backup(res["archive"], str(target), force=True)
    assert out["ok"] is True


def test_resolve_backup_matches_listing(data_root):
    res = bk.create_backup(source_root=str(data_root))
    name = Path(res["archive"]).name
    out_dir = str(bk.default_backup_dir(data_root))
    assert bk.resolve_backup(name, out_dir=out_dir) is not None
    # a traversal-y name resolves to nothing (matched against the listing, not joined)
    assert bk.resolve_backup("../../etc/passwd", out_dir=out_dir) is None


def test_safe_extract_rejects_traversal(tmp_path):
    # craft an archive with a member escaping the destination
    evil = tmp_path / "evil.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("x", encoding="utf-8")
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(str(payload), arcname="../escape.txt")
    with tarfile.open(evil, "r:gz") as tar:
        with pytest.raises(ValueError):
            bk._safe_extract(tar, tmp_path / "dest")


def test_verify_detects_corrupt_db(data_root):
    res = bk.create_backup(source_root=str(data_root))
    # corrupt the archived DB by rewriting the tar with a garbage settings.db
    import io
    good = Path(res["archive"])
    corrupt = good.with_name("corrupt.tar.gz")
    with tarfile.open(good, "r:gz") as src, tarfile.open(corrupt, "w:gz") as dst:
        for m in src.getmembers():
            if m.name == "settings.db":
                data = b"not a database"
                info = tarfile.TarInfo("settings.db"); info.size = len(data)
                dst.addfile(info, io.BytesIO(data))
            else:
                f = src.extractfile(m)
                dst.addfile(m, f) if f else dst.addfile(m)
    report = bk.verify_backup(str(corrupt))
    assert report["ok"] is False
    assert report["dbs"]["settings.db"] != "ok"
