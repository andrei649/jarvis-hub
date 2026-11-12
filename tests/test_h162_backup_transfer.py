"""H162 — a backup can be downloaded, an archive from elsewhere uploaded, and checkpoints listed.

What the owner can do: download a listed archive byte for byte; upload an off-site copy
encrypted with this box's backup key, which is restore-drilled and then listed under a
server-made name, so the existing restore route (an irreversible-tier card that says the
archive was uploaded) can restore it; choose on the card whether the credentials and hooks
are replaced too; see file checkpoints read-only in the backup section.

What an attacker cannot do (review M1/M2 and minors included): download or upload without
the admin credential; download from a cross-site page or through a planted link; upload a
plaintext archive (it could carry anyone's admin token, approvals and hooks) or one the
box's key does not open; get anything written under backups/ (the restore trace and the
archives) by an upload or a restore; have a restore replace the live credential store or
hooks unless the owner asked for that on the card; fill the disk.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from agents.core import archive_safe
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
    # This box's backup key (a Fernet key: no salt needed).
    monkeypatch.setenv("JARVIS_BACKUP_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.delenv("JARVIS_TASK_MEDIATION", raising=False)
    queue = TaskQueue(db_path=str(tmp_path / "q.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200),
                            budget=InterruptBudget(per_day=4))
    yield SimpleNamespace(root=root, queue=queue, orch=SimpleNamespace(autonomy=worker),
                          tmp=tmp_path)
    queue.close()


@pytest.fixture
def client(env, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import backup as backup_router

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h162")
    monkeypatch.setattr(backup_router, "get_orch", lambda: env.orch)
    return TestClient(web.app)


def _encrypt(data: bytes) -> bytes:
    """Encrypt with this box's backup key, as create_backup does."""
    return bk._backup_cipher(None).encrypt_bytes(data)


def _crafted(members: dict[str, bytes]) -> bytes:
    """A plaintext tar.gz that passes the drill: the given files + a manifest counting them."""
    buf = io.BytesIO()
    manifest = json.dumps({"created_at": "2026-11-01T00:00:00+00:00", "version": 1,
                           "mode": "full", "file_count": len(members)}).encode()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in [*members.items(), (bk._MANIFEST_NAME, manifest)]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _offsite(env, *, admin_token: bool = False) -> tuple[bytes, str | None]:
    """An encrypted backup made of another data root with this box's key (an off-site copy)."""
    from agents.core.security.token_store import TokenStore

    other = env.tmp / "offsite" / "data"
    _seed(other / "settings.db")
    token = None
    if admin_token:
        ts = TokenStore(db_path=str(other / "security" / "tokens.db"))
        token = ts.issue("admin", ttl_days=3650)
        ts.close()
    (other / "hooks").mkdir(parents=True, exist_ok=True)
    (other / "hooks" / "hooks.json").write_text('{"format":1,"hooks":["archived"]}', encoding="utf-8")
    made = bk.create_backup(source_root=str(other), out_dir=str(env.tmp / "offsite" / "out"),
                            encrypt=True)
    return Path(made["archive"]).read_bytes(), token


def _listed(env) -> list[str]:
    return [r["name"] for r in bk.list_backups()]


def _no_partials() -> bool:
    out = bk.default_backup_dir()
    return not out.exists() or [p.name for p in out.iterdir() if p.name.startswith(".")] == []


# ── download ──────────────────────────────────────────────────────────────────

def test_download_returns_the_listed_archive_byte_for_byte(env, client):
    made = bk.create_backup()
    name = Path(made["archive"]).name
    resp = client.get("/api/admin/backup/download", params={"name": name}, headers=ADMIN)
    assert resp.status_code == 200, resp.text
    assert resp.content == Path(made["archive"]).read_bytes()
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["cache-control"] == "no-store"


def test_download_needs_admin_refuses_cross_site_unlisted_names_and_paths(env, client):
    made = bk.create_backup()
    name = Path(made["archive"]).name
    assert client.get("/api/admin/backup/download", params={"name": name}).status_code in (401, 403)
    cross = client.get("/api/admin/backup/download", params={"name": name},
                       headers={**ADMIN, "Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    for bad in ("../settings.db", "settings.db", str(env.root / "settings.db"),
                "jarvis-backup-x.tar.gz", made["archive"]):
        assert client.get("/api/admin/backup/download", params={"name": bad},
                          headers=ADMIN).status_code == 404


def test_download_does_not_follow_a_planted_link_out_of_the_backups_dir(env, client):
    secret = env.tmp / "outside-secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    out = bk.default_backup_dir()
    out.mkdir(parents=True, exist_ok=True)
    os.symlink(secret, out / "jarvis-backup-planted.tar.gz")
    resp = client.get("/api/admin/backup/download",
                      params={"name": "jarvis-backup-planted.tar.gz"}, headers=ADMIN)
    assert resp.status_code == 404 and b"TOP-SECRET" not in resp.content


# ── upload ────────────────────────────────────────────────────────────────────

def test_an_encrypted_offsite_copy_is_drilled_listed_marked_and_restorable_only_through_a_card(env, client):
    archive, _ = _offsite(env)
    resp = client.put("/api/admin/backup/upload", content=archive, headers=OCTET)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ok"] is True and body["encrypted"] is True and body["origin"] == "upload"
    assert body["name"].startswith("jarvis-backup-upload-") and body["name"].endswith(".tar.gz.enc")
    row = next(r for r in bk.list_backups() if r["name"] == body["name"])
    assert row["uploaded"] is True
    assert (bk.default_backup_dir() / (body["name"] + ".origin.json")).exists()
    assert bk.pending_restore(env.root) is None            # an upload restores nothing
    assert _no_partials()
    queued = client.post("/api/admin/backup/restore", headers=ADMIN, json={"name": body["name"]})
    assert queued.status_code == 202, queued.text
    task = env.queue.get(queued.json()["pending"])
    assert task.kind == "backup.restore" and task.risk_tier == 3 and task.status == "blocked"
    assert task.payload["origin"] == "upload" and task.payload["replace_credentials"] is False
    preview = task.payload["preview"]
    assert preview["origin"] == "upload" and "uploaded archive" in preview["origin_note"]
    assert "security/" in preview["kept"] and "hooks/" in preview["kept"]


def test_a_plaintext_upload_is_refused_and_not_kept(env, client):
    for archive in (_crafted({"notes.json": b"{}"}), b"\x1f\x8b" + b"\0" * 64):
        resp = client.put("/api/admin/backup/upload", content=archive, headers=OCTET)
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"] == "plaintext_refused"
        assert "encrypted" in resp.json()["verify"]["problem"]
    assert _listed(env) == [] and _no_partials()


def test_an_archive_the_boxs_key_does_not_open_is_refused(env, client):
    foreign = Fernet(Fernet.generate_key()).encrypt(_crafted({"notes.json": b"{}"}))
    resp = client.put("/api/admin/backup/upload", content=foreign, headers=OCTET)
    assert resp.status_code == 422 and resp.json()["error"] in {"wrong_key", "unreadable"}
    assert client.put("/api/admin/backup/upload", content=b"not an archive at all",
                      headers=OCTET).status_code == 422
    assert client.put("/api/admin/backup/upload", content=b"", headers=OCTET).status_code == 400
    assert _listed(env) == [] and _no_partials()


def test_an_encrypted_archive_that_fails_the_drill_is_refused(env, client):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:   # no manifest
        info = tarfile.TarInfo("notes.txt")
        info.size = 5
        tar.addfile(info, io.BytesIO(b"hello"))
    resp = client.put("/api/admin/backup/upload", content=_encrypt(buf.getvalue()), headers=OCTET)
    assert resp.status_code == 422 and resp.json()["error"] == "failed_drill"
    assert resp.json()["verify"]["ok"] is False
    assert _listed(env) == [] and _no_partials()


def test_an_archive_that_writes_into_backups_is_refused_by_the_drill(env, client):
    out = bk.default_backup_dir()
    out.mkdir(parents=True, exist_ok=True)
    history = out / "restore-history.jsonl"
    history.write_text('{"event": "staged", "name": "real"}\n', encoding="utf-8")
    archive = _encrypt(_crafted({"backups/restore-history.jsonl": b'{"event":"forged"}\n',
                                 "notes.json": b"{}"}))
    resp = client.put("/api/admin/backup/upload", content=archive, headers=OCTET)
    assert resp.status_code == 422 and resp.json()["error"] == "failed_drill"
    assert "backups/" in resp.json()["verify"]["problem"]
    assert history.read_text(encoding="utf-8") == '{"event": "staged", "name": "real"}\n'


def test_upload_needs_admin_same_origin_a_key_and_room(env, client, monkeypatch):
    archive, _ = _offsite(env)
    assert client.put("/api/admin/backup/upload", content=archive,
                      headers={"Content-Type": "application/octet-stream"}).status_code in (401, 403)
    cross = client.put("/api/admin/backup/upload", content=archive,
                       headers={**OCTET, "Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    real_free = bk._free_bytes
    monkeypatch.setattr(bk, "_free_bytes", lambda path: 10)
    assert client.put("/api/admin/backup/upload", content=archive, headers=OCTET).status_code == 507
    monkeypatch.setattr(bk, "_free_bytes", real_free)
    monkeypatch.setenv("JARVIS_KEY_DIR", str(env.tmp / "empty-keys"))
    monkeypatch.delenv("JARVIS_BACKUP_KEY", raising=False)
    monkeypatch.delenv("JARVIS_SECRET_KEY", raising=False)
    missing = client.put("/api/admin/backup/upload", content=archive, headers=OCTET)
    assert missing.status_code == 422 and missing.json()["error"] == "key_missing"
    assert _listed(env) == []


def test_the_size_cap_holds_on_the_declared_length_and_while_streaming(env, client, monkeypatch):
    archive, _ = _offsite(env)
    monkeypatch.setattr(bk, "UPLOAD_MAX_BYTES", 64)
    assert client.put("/api/admin/backup/upload", content=archive, headers=OCTET).status_code == 413
    upload = bk.BackupUpload(max_bytes=8)
    try:
        upload.write(b"gAAAA")
        with pytest.raises(bk.BackupUploadError) as err:
            upload.write(b"456789")
        assert err.value.reason == "too_large"
    finally:
        upload.close()
    assert _no_partials()


def test_the_disk_floor_stops_a_stream(env, monkeypatch):
    upload = bk.BackupUpload()
    try:
        monkeypatch.setattr(bk, "_FREE_CHECK_EVERY", 4)
        monkeypatch.setattr(bk, "_free_bytes", lambda path: 1)
        with pytest.raises(bk.BackupUploadError) as err:
            upload.write(b"gAAAAAAA")
        assert err.value.reason == "no_space"
    finally:
        upload.close()


def test_the_partial_file_is_never_an_archive_temp_the_backup_sweep_removes(env):
    upload = bk.BackupUpload()
    try:
        assert not archive_safe.is_temp_name(upload.tmp.name, bk._ARCHIVE_PREFIX)
        old = 1.0
        os.utime(upload.tmp, (old, old))
        bk._sweep_abandoned_temps(upload.tmp.parent)
        assert upload.tmp.exists()
    finally:
        upload.close()


# ── restore: backups/ never written, credentials and hooks kept unless asked ─────

def test_a_restore_never_rewrites_the_backups_dir(env):
    out = bk.default_backup_dir()
    out.mkdir(parents=True, exist_ok=True)
    history = out / "restore-history.jsonl"
    history.write_text('{"event": "staged", "name": "real"}\n', encoding="utf-8")
    arc = env.tmp / "jarvis-backup-crafted.tar.gz"
    arc.write_bytes(_crafted({"backups/restore-history.jsonl": b'{"event":"forged"}\n'}))
    result = bk.restore_backup(str(arc), str(env.root), force=True)
    assert history.read_text(encoding="utf-8") == '{"event": "staged", "name": "real"}\n'
    assert result["not_restored"] == ["backups"] and result["problem"] is None


def test_restoring_an_uploaded_archive_keeps_the_live_admin_tokens_and_hooks(env, client):
    from agents.core.security.token_store import TokenStore

    (env.root / "hooks").mkdir(parents=True, exist_ok=True)
    (env.root / "hooks" / "hooks.json").write_text('{"format":1,"hooks":["live"]}', encoding="utf-8")
    archive, archived_token = _offsite(env, admin_token=True)
    resp = client.put("/api/admin/backup/upload", content=archive, headers=OCTET)
    assert resp.status_code == 201, resp.text
    path = bk.resolve_backup(resp.json()["name"])
    result = bk.restore_backup(str(path), str(env.root), force=True)   # what the accepted card applies
    assert "security" in result["kept_live"] and "hooks" in result["kept_live"]
    live = TokenStore(db_path=str(env.root / "security" / "tokens.db"))
    try:
        assert live.verify(archived_token) != "admin"
    finally:
        live.close()
    assert "live" in (env.root / "hooks" / "hooks.json").read_text(encoding="utf-8")


def test_the_owner_can_choose_to_replace_credentials_and_the_card_says_so(env, client):
    from agents.core.security.token_store import TokenStore

    archive, archived_token = _offsite(env, admin_token=True)
    name = client.put("/api/admin/backup/upload", content=archive, headers=OCTET).json()["name"]
    assert client.post("/api/admin/backup/restore", headers=ADMIN,
                       json={"name": name, "replace_credentials": "yes"}).status_code == 400
    keep = client.post("/api/admin/backup/restore", headers=ADMIN, json={"name": name}).json()
    replace = client.post("/api/admin/backup/restore", headers=ADMIN,
                          json={"name": name, "replace_credentials": True}).json()
    assert replace["pending"] != keep["pending"]            # a different card, not the waiting one
    task = env.queue.get(replace["pending"])
    assert task.payload["replace_credentials"] is True
    assert "ALSO replaces the credentials" in task.payload["preview"]["origin_note"]
    assert "including credentials" in task.title
    staged = bk.stage_restore(name, replace_credentials=True)
    assert staged["ok"] and staged["replace_credentials"] is True and staged["origin"] == "upload"
    bk.restore_backup(str(bk.resolve_backup(name)), str(env.root), force=True, replace_credentials=True)
    live = TokenStore(db_path=str(env.root / "security" / "tokens.db"))
    try:
        assert live.verify(archived_token) == "admin"
    finally:
        live.close()


def test_a_local_in_place_restore_also_keeps_credentials_unless_asked(env):
    (env.root / "security").mkdir(parents=True, exist_ok=True)
    (env.root / "security" / "credential_shares.json").write_text('{"v":"old"}', encoding="utf-8")
    made = bk.create_backup()
    (env.root / "security" / "credential_shares.json").write_text('{"v":"new"}', encoding="utf-8")
    bk.restore_backup(made["archive"], str(env.root), force=True)
    assert (env.root / "security" / "credential_shares.json").read_text(encoding="utf-8") == '{"v":"new"}'
    card = bk.restore_request(Path(made["archive"]).name)
    assert card["payload"]["origin"] == "local" and "UPLOADED" not in card["title"]
    bk.restore_backup(made["archive"], str(env.root), force=True, replace_credentials=True)
    assert (env.root / "security" / "credential_shares.json").read_text(encoding="utf-8") == '{"v":"old"}'


def test_pruning_an_uploaded_archive_drops_its_origin_sidecar(env, client):
    archive, _ = _offsite(env)
    name = client.put("/api/admin/backup/upload", content=archive, headers=OCTET).json()["name"]
    sidecar = bk.default_backup_dir() / (name + ".origin.json")
    assert sidecar.exists()
    assert name in bk.prune_backups(keep=0)
    assert not sidecar.exists()


# ── checkpoints ───────────────────────────────────────────────────────────────

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
    assert client.get("/api/admin/backup/checkpoints", headers=ADMIN).status_code == 503
