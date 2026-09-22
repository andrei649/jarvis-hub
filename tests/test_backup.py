"""Backup / restore + restore-drill (0.14 · H23.8).

Offline: builds a throwaway data root with real SQLite DBs + plain files, then
exercises create → list → verify(drill) → restore. Asserts the safety/honesty
properties — consistent DB snapshots, integrity-checked drill, Zip-Slip-proof
extraction, and that the backups dir isn't recursively swept into its own archive.
"""
import base64
import sqlite3
import tarfile
from pathlib import Path

import pytest

from agents.core import backup as bk
from agents.core.secrets import SecretStoreError

# Raw 32-byte urlsafe-base64 key → hermetic (no keyfile), works with/without cryptography.
_BK_KEY = base64.urlsafe_b64encode(b"backup-test-key-32bytes-padding!").decode()
_BK_OTHER = base64.urlsafe_b64encode(b"backup-OTHER-key-32byte-paddng!!").decode()


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


def test_verify_and_restore_reject_traversal(tmp_path):
    # craft an archive with a member escaping the destination; both entry points that
    # unpack a backup must refuse it (H503: through the shared archive_safe module)
    evil = tmp_path / "evil.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("x", encoding="utf-8")
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(str(payload), arcname="../escape.txt")
    with pytest.raises(ValueError):
        bk.verify_backup(str(evil))
    with pytest.raises(ValueError):
        bk.restore_backup(str(evil), str(tmp_path / "dest" / "inner"))
    assert not (tmp_path / "dest" / "escape.txt").exists()


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


# ── AUD-1 / F2: encrypted backups (carry no plaintext at rest) ─────
def test_encrypted_archive_is_opaque(data_root):
    res = bk.create_backup(source_root=str(data_root), key=_BK_KEY)
    assert res["encrypted"] is True
    assert res["archive"].endswith(".tar.gz.enc")
    # The encrypted archive is not a readable gzip tar (opaque at rest)...
    with pytest.raises(tarfile.TarError):
        with tarfile.open(res["archive"], "r:gz"):
            pass
    # ...while an unencrypted control of the same data opens fine.
    plain = bk.create_backup(source_root=str(data_root))
    assert plain["encrypted"] is False
    with tarfile.open(plain["archive"], "r:gz") as tar:
        assert "settings.db" in tar.getnames()


def test_encrypted_verify_drill_passes(data_root):
    res = bk.create_backup(source_root=str(data_root), key=_BK_KEY)
    report = bk.verify_backup(res["archive"], key=_BK_KEY)
    assert report["ok"] is True
    assert report["encrypted"] is True
    assert report["dbs"]["settings.db"] == "ok"


def test_encrypted_restore_roundtrip(data_root, tmp_path):
    res = bk.create_backup(source_root=str(data_root), key=_BK_KEY)
    target = tmp_path / "restored"
    out = bk.restore_backup(res["archive"], str(target), key=_BK_KEY)
    assert out["ok"] is True
    conn = sqlite3.connect(str(target / "autonomy.db"))
    n = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    conn.close()
    assert n == 5
    assert (target / "tokens" / "note.txt").read_text() == "hello"


def test_encrypt_via_env_key(data_root, monkeypatch):
    monkeypatch.setenv("JARVIS_BACKUP_KEY", _BK_KEY)
    res = bk.create_backup(source_root=str(data_root))   # no explicit key arg
    assert res["encrypted"] is True
    report = bk.verify_backup(res["archive"])            # env key picked up
    assert report["ok"] is True


def test_list_marks_encrypted(data_root):
    bk.create_backup(source_root=str(data_root), key=_BK_KEY)
    bk.create_backup(source_root=str(data_root))
    listing = bk.list_backups(out_dir=str(bk.default_backup_dir(data_root)))
    assert {r["encrypted"] for r in listing} == {True, False}
    enc = [r for r in listing if r["encrypted"]][0]
    assert bk.resolve_backup(enc["name"], out_dir=str(bk.default_backup_dir(data_root))) is not None


def test_wrong_key_cannot_decrypt(data_root):
    res = bk.create_backup(source_root=str(data_root), key=_BK_KEY)
    with pytest.raises(SecretStoreError):
        bk.verify_backup(res["archive"], key=_BK_OTHER)


# ── H503: one hardened extractor, atomic producer ──────────────────
def _tampered_archive(path: Path, extra) -> Path:
    """A real-looking backup (manifest + DB-less file) with one extra member appended."""
    import io
    with tarfile.open(path, "w:gz") as tar:
        data = b'{"version": 1}'
        info = tarfile.TarInfo("backup_manifest.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        note = b"hello"
        info = tarfile.TarInfo("tokens/note.txt")
        info.size = len(note)
        tar.addfile(info, io.BytesIO(note))
        tar.addfile(extra)
    return path


def _link(name, kind, target="/etc/passwd"):
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = target
    return info


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE])
def test_verify_raises_on_a_tampered_link_or_device_member(tmp_path, kind):
    # Used to be skipped, so verify reported ok on an archive that restores a quietly
    # incomplete tree. A tampered archive now fails the drill loudly.
    arc = _tampered_archive(tmp_path / "jarvis-backup-tampered.tar.gz", _link("tokens/key", kind))
    with pytest.raises(ValueError):
        bk.verify_backup(str(arc))


def test_restore_of_a_tampered_archive_writes_nothing(tmp_path):
    arc = _tampered_archive(tmp_path / "jarvis-backup-tampered.tar.gz",
                            _link("tokens/key", tarfile.SYMTYPE))
    target = tmp_path / "restored"
    with pytest.raises(ValueError):
        bk.restore_backup(str(arc), str(target))
    # validated before any write — not "everything up to the bad member"
    assert not (target / "tokens" / "note.txt").exists()


def test_cli_verify_and_restore_report_a_rejected_archive(tmp_path, monkeypatch, capsys):
    # The operator's entry point: a clear refusal and a non-zero exit, not a traceback.
    root = tmp_path / "live"
    (root / "backups").mkdir(parents=True)
    monkeypatch.setattr(bk, "data_root", lambda: root)
    arc = _tampered_archive(root / "backups" / "jarvis-backup-tampered.tar.gz",
                            _link("tokens/key", tarfile.SYMTYPE))
    assert bk._main(["verify", arc.name]) == 1
    assert "archive rejected" in capsys.readouterr().out
    target = tmp_path / "restored"
    assert bk._main(["restore", arc.name, str(target)]) == 1
    assert "nothing restored" in capsys.readouterr().out
    assert not (target / "tokens" / "note.txt").exists()


def test_create_skips_symlinks_so_a_planted_link_cannot_pull_a_file_in(data_root, tmp_path):
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("not part of the data root", encoding="utf-8")
    (data_root / "tokens" / "planted").symlink_to(outside)
    res = bk.create_backup(source_root=str(data_root))
    with tarfile.open(res["archive"], "r:gz") as tar:
        names = tar.getnames()
        assert all(m.isfile() or m.isdir() for m in tar.getmembers())
    assert "tokens/planted" not in names
    assert res["skipped_links"] == 1
    # and a root with a link in it still produces a backup that passes its own drill
    assert bk.verify_backup(res["archive"])["ok"] is True


def test_backup_member_cap_is_enforced_and_configurable(data_root, monkeypatch):
    res = bk.create_backup(source_root=str(data_root))   # 4 members: 2 DBs, note, manifest
    monkeypatch.setenv("JARVIS_BACKUP_MAX_MEMBERS", "3")
    with pytest.raises(ValueError, match="members"):
        bk.verify_backup(res["archive"])
    monkeypatch.setenv("JARVIS_BACKUP_MAX_MEMBERS", "10")
    assert bk.verify_backup(res["archive"])["ok"] is True


def test_backup_byte_cap_is_enforced_and_configurable(data_root, monkeypatch, tmp_path):
    res = bk.create_backup(source_root=str(data_root))
    monkeypatch.setenv("JARVIS_BACKUP_MAX_BYTES", "1024")      # the DBs alone are larger
    with pytest.raises(ValueError, match="bytes"):
        bk.verify_backup(res["archive"])
    target = tmp_path / "restored"
    with pytest.raises(ValueError, match="bytes"):
        bk.restore_backup(res["archive"], str(target))
    assert not target.exists() or not any(target.iterdir())


def test_archive_is_gnu_format(data_root):
    # Hermes picks GNU over PAX deliberately so macOS Archive Utility opens it.
    import gzip
    res = bk.create_backup(source_root=str(data_root))
    with gzip.open(res["archive"], "rb") as fh:
        header = fh.read(512)
    assert header[257:265] == tarfile.GNU_MAGIC


def _fsize_limit():
    try:
        import resource
    except ImportError:  # pragma: no cover - Windows
        return None
    return resource if hasattr(resource, "RLIMIT_FSIZE") else None


@pytest.mark.skipif(_fsize_limit() is None, reason="needs RLIMIT_FSIZE")
def test_encrypted_backup_interrupted_mid_write_leaves_no_archive(data_root, tmp_path):
    """A backup that dies mid-write must not leave a truncated archive under a final name.

    RLIMIT_FSIZE makes the write fail the way a full disk does: partway through. The
    staged plaintext fits under the limit; the (larger) ciphertext does not.
    """
    import os
    resource = _fsize_limit()
    (data_root / "blob.bin").write_bytes(os.urandom(256 * 1024))
    plain = bk.create_backup(source_root=str(data_root), out_dir=str(tmp_path / "probe-plain"),
                             encrypt=False)
    enc = bk.create_backup(source_root=str(data_root), out_dir=str(tmp_path / "probe-enc"),
                           key=_BK_KEY)
    if enc["bytes"] - plain["bytes"] < 4096:  # pragma: no cover - fallback cipher, no headroom
        pytest.skip("the cipher adds too little size to split the staged tar from the ciphertext")
    limit = (plain["bytes"] + enc["bytes"]) // 2
    out = tmp_path / "out"
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, hard))
    try:
        with pytest.raises(OSError):
            bk.create_backup(source_root=str(data_root), out_dir=str(out), key=_BK_KEY)
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))
    assert bk.list_backups(out_dir=str(out)) == []           # nothing listed, nothing pruned against
    assert sorted(p.name for p in out.iterdir()) == []       # and no temp debris either


@pytest.mark.skipif(_fsize_limit() is None, reason="needs RLIMIT_FSIZE")
def test_plain_backup_interrupted_mid_write_leaves_no_archive(data_root, tmp_path):
    import os
    resource = _fsize_limit()
    (data_root / "blob.bin").write_bytes(os.urandom(256 * 1024))
    out = tmp_path / "out"
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024, hard))
    try:
        with pytest.raises(OSError):
            bk.create_backup(source_root=str(data_root), out_dir=str(out), encrypt=False)
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))
    assert bk.list_backups(out_dir=str(out)) == []
    assert sorted(p.name for p in out.iterdir()) == []


def test_create_sweeps_abandoned_temp_files_but_not_fresh_ones(data_root, tmp_path):
    import os
    import time as _time
    out = tmp_path / "out"
    out.mkdir()
    stale = out / ".jarvis-backup-20260101T000000_000000Z_abcdef.tar.gz.tmp-deadbeef"
    stale.write_bytes(b"half an archive from a killed process")
    old = _time.time() - 2 * 3600
    os.utime(stale, (old, old))
    fresh = out / ".jarvis-backup-20260101T000001_000000Z_abcdef.tar.gz.tmp-cafef00d"
    fresh.write_bytes(b"a concurrent backup still writing")
    bk.create_backup(source_root=str(data_root), out_dir=str(out), encrypt=False)
    assert not stale.exists()
    assert fresh.exists()
    assert len(bk.list_backups(out_dir=str(out))) == 1


def test_restore_is_not_reachable_from_any_route_or_tool():
    """Restore overwrites live data; it stays an operator CLI action (governance note).

    If this ever fails, the new caller must make restore a file.write-class effect that
    crosses the Action Kernel — not just call it.
    """
    repo_root = Path(__file__).resolve().parent.parent
    callers = []
    for path in sorted((repo_root / "agents").rglob("*.py")):
        rel = path.relative_to(repo_root).as_posix()
        if rel == "agents/core/backup.py" or rel.startswith("agents/web/v2/"):
            continue
        if "restore_backup" in path.read_text(encoding="utf-8", errors="replace"):
            callers.append(rel)
    assert callers == []
