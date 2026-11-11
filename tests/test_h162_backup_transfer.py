"""H162 — a backup can be downloaded, an archive from elsewhere uploaded, and checkpoints listed.

What the owner can do: download a listed archive byte for byte; upload an archive from
another box, which is restore-drilled and then listed under a server-made name, so the
existing restore route (an irreversible-tier card) can restore it; see file checkpoints
read-only in the backup section.

What an attacker cannot do: download or upload without the admin credential; download
from a cross-site page; upload with a cross-site write; slip an archive that fails the
drill (or is not an archive) into the listing; name a path outside the listing.
"""
from __future__ import annotations

import io
import sqlite3
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import backup as bk

ADMIN = {"X-Admin-Token": "adm-h162"}
OCTET = {**ADMIN, "Content-Type": "application/octet-stream"}


def _seed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO t DEFAULT VALUES")
    conn.commit()
    conn.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget

    root = tmp_path / "data"
    _seed(root / "settings.db")
    (root / "notes.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(root))
    monkeypatch.delenv("JARVIS_BACKUP_KEY", raising=False)
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.delenv("JARVIS_TASK_MEDIATION", raising=False)
    queue = TaskQueue(db_path=str(tmp_path / "q.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200),
                            budget=InterruptBudget(per_day=4))
    yield SimpleNamespace(root=root, queue=queue, orch=SimpleNamespace(autonomy=worker),
                          other=tmp_path / "other")
    queue.close()


@pytest.fixture
def client(env, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import backup as backup_router

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h162")
    monkeypatch.setattr(backup_router, "get_orch", lambda: env.orch)
    return TestClient(web.app)


def _foreign_archive(env) -> bytes:
    """A good archive made on 'another box' (a different data root)."""
    other = env.other / "data"
    _seed(other / "settings.db")
    made = bk.create_backup(source_root=str(other), out_dir=str(env.other / "out"))
    return Path(made["archive"]).read_bytes()


def _listed(env) -> list[str]:
    return [r["name"] for r in bk.list_backups()]


def test_download_returns_the_listed_archive_byte_for_byte(env, client):
    made = bk.create_backup()
    name = Path(made["archive"]).name
    resp = client.get("/api/admin/backup/download", params={"name": name}, headers=ADMIN)
    assert resp.status_code == 200, resp.text
    assert resp.content == Path(made["archive"]).read_bytes()
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["cache-control"] == "no-store"


def test_download_needs_admin_refuses_cross_site_and_unlisted_names(env, client):
    name = Path(bk.create_backup()["archive"]).name
    assert client.get("/api/admin/backup/download", params={"name": name}).status_code in (401, 403)
    cross = client.get("/api/admin/backup/download", params={"name": name},
                       headers={**ADMIN, "Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    for bad in ("../settings.db", "settings.db", str(env.root / "settings.db"), "jarvis-backup-x.tar.gz"):
        assert client.get("/api/admin/backup/download", params={"name": bad},
                          headers=ADMIN).status_code == 404


def test_an_uploaded_archive_is_drilled_listed_and_restorable_only_through_a_card(env, client):
    resp = client.put("/api/admin/backup/upload", content=_foreign_archive(env), headers=OCTET)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ok"] is True and body["encrypted"] is False and body["verify"]["ok"] is True
    assert body["name"].startswith("jarvis-backup-upload-") and body["name"].endswith(".tar.gz")
    assert body["name"] in _listed(env)
    assert bk.pending_restore(env.root) is None  # an upload restores nothing
    queued = client.post("/api/admin/backup/restore", headers=ADMIN, json={"name": body["name"]})
    assert queued.status_code == 202, queued.text
    task = env.queue.get(queued.json()["pending"])
    assert task.kind == "backup.restore" and task.risk_tier == 3 and task.status == "blocked"
    # No temp is left beside the archives.
    assert [p.name for p in bk.default_backup_dir().iterdir() if p.name.startswith(".")] == []


def test_an_upload_that_is_not_a_good_archive_is_refused_and_not_kept(env, client):
    for junk in (b"not an archive at all", b"\x1f\x8b" + b"\0" * 64):
        resp = client.put("/api/admin/backup/upload", content=junk, headers=OCTET)
        assert resp.status_code == 422, resp.text
    # A real tar.gz without a backup manifest fails the drill.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"hello"
        info = tarfile.TarInfo("notes.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    resp = client.put("/api/admin/backup/upload", content=buf.getvalue(), headers=OCTET)
    assert resp.status_code == 422 and resp.json()["error"] == "failed_drill"
    assert resp.json()["verify"]["ok"] is False
    assert client.put("/api/admin/backup/upload", content=b"", headers=OCTET).status_code == 400
    assert _listed(env) == []
    out = bk.default_backup_dir()
    assert not out.exists() or [p.name for p in out.iterdir() if p.name.startswith(".")] == []


def test_upload_needs_admin_and_same_origin_and_has_a_size_cap(env, client, monkeypatch):
    archive = _foreign_archive(env)
    assert client.put("/api/admin/backup/upload", content=archive,
                      headers={"Content-Type": "application/octet-stream"}).status_code in (401, 403)
    cross = client.put("/api/admin/backup/upload", content=archive,
                       headers={**OCTET, "Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    monkeypatch.setattr(bk, "UPLOAD_MAX_BYTES", 64)
    big = client.put("/api/admin/backup/upload", content=archive, headers=OCTET)
    assert big.status_code == 413
    assert _listed(env) == []


def test_an_encrypted_upload_without_this_boxs_key_is_refused(env, client):
    resp = client.put("/api/admin/backup/upload", content=b"gAAAAAB" + b"x" * 200, headers=OCTET)
    assert resp.status_code == 422
    assert resp.json()["error"] in {"key_missing", "unreadable"}
    assert _listed(env) == []


def test_checkpoints_are_listed_read_only_for_the_owner(env, client, monkeypatch):
    from agents.core import checkpoint_commands

    seen = {}

    def fake_query(principal, query):
        seen.update(principal=principal, query=query)
        return {"ok": True, "items": [], "omitted": 0, "truncated": False, "index_state": "complete"}

    monkeypatch.setattr(checkpoint_commands, "_query", fake_query)
    resp = client.get("/api/admin/backup/checkpoints", params={"limit": 5}, headers=ADMIN)
    assert resp.status_code == 200 and resp.json()["items"] == []
    assert seen["query"]["action"] == "list" and seen["query"]["limit"] == 5
    assert seen["principal"].admin is True
    assert client.get("/api/admin/backup/checkpoints").status_code in (401, 403)
    assert client.get("/api/admin/backup/checkpoints", params={"limit": 0},
                      headers=ADMIN).status_code == 422


def test_the_checkpoint_listing_reports_an_unreadable_inventory(env, client, monkeypatch):
    from agents.core import checkpoint_commands

    def broken(principal, query):
        raise OSError("snapshot store unreadable")

    monkeypatch.setattr(checkpoint_commands, "_query", broken)
    resp = client.get("/api/admin/backup/checkpoints", headers=ADMIN)
    assert resp.status_code == 503


def test_the_streamed_size_cap_holds_without_a_declared_length(env):
    upload = bk.BackupUpload(max_bytes=8)
    try:
        upload.write(b"\x1f\x8b123")
        with pytest.raises(bk.BackupUploadError) as err:
            upload.write(b"456789")
        assert err.value.reason == "too_large"
    finally:
        upload.close()
    assert [p.name for p in bk.default_backup_dir().iterdir()] == []


def test_an_encrypted_archive_made_with_this_boxs_key_uploads(env, client, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setenv("JARVIS_BACKUP_KEY", "an owner passphrase for H162 tests")
    made = bk.create_backup(source_root=str(env.root), out_dir=str(tmp_path / "offsite"))
    assert made["encrypted"] is True
    resp = client.put("/api/admin/backup/upload", content=Path(made["archive"]).read_bytes(),
                      headers=OCTET)
    assert resp.status_code == 201, resp.text
    assert resp.json()["encrypted"] is True and resp.json()["name"].endswith(".tar.gz.enc")
    assert resp.json()["name"] in _listed(env)
