"""G21 — ops surfaces in the HUD: the owner's file browser (H142).

Owner side: the owner lists the approved folders, previews and downloads a file, uploads a
new one and makes a folder; a rename or a delete is an approval card at the irreversible
tier and happens only on a human's accept, after the target is found unchanged.
Attacker side: a non-admin is refused on every route; credentials, keys, data stores and
hidden files are never listed, read or written; ``..``, absolute paths, symlinks (file or
folder, also swapped mid-walk) and hard links never lead out of an approved folder; an
upload never replaces a file and stops at the size cap; a folder that is or contains a
protected place is never an approved folder; a machine decider cannot apply a card.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import file_browser as fb

ADMIN = {"X-Admin-Token": "adm-g21"}
USER = {"X-User-Token": "usr-g21"}


class FakeAudit:
    def __init__(self):
        self.rows = []

    def log(self, event):
        self.rows.append((event.action_taken, event.content_preview))


@pytest.fixture
def env(tmp_path, monkeypatch):
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(data))
    monkeypatch.delenv("JARVIS_TASK_MEDIATION", raising=False)
    monkeypatch.delenv("NERVA_FILE_BROWSER_MAX_BYTES", raising=False)
    monkeypatch.delenv("JARVIS_FILE_BROWSER_MAX_BYTES", raising=False)
    approved = tmp_path / "share"
    approved.mkdir()
    monkeypatch.delenv("NERVA_FILE_BROWSER_DIRS", raising=False)
    monkeypatch.setenv("JARVIS_FILE_BROWSER_DIRS", str(approved))
    (approved / "notes.txt").write_text("hello owner\n", encoding="utf-8")
    (approved / "docs").mkdir()
    (approved / "docs" / "plan.md").write_text("# plan\n", encoding="utf-8")
    for secret in (".env", "id_rsa", "api_key.txt", "credentials.json", "hub.db", "server.pem",
                   "telegram_token.txt", "store.sqlite3", "secrets.enc"):
        (approved / secret).write_text("SECRET=1\n", encoding="utf-8")
    for folder in ("security", "tokens", "vault", ".ssh", ".gnupg"):
        (approved / folder).mkdir()
        (approved / folder / "inside.txt").write_text("x", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("not for the browser", encoding="utf-8")
    queue = TaskQueue(db_path=str(tmp_path / "autonomy-q.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200),
                            budget=InterruptBudget(per_day=4))
    orch = SimpleNamespace(autonomy=worker, audit=FakeAudit())
    root = fb.roots()[0]
    yield SimpleNamespace(data=data, approved=approved.resolve(), outside=outside, queue=queue,
                          worker=worker, orch=orch, root=root.id)
    queue.close()


@pytest.fixture
def client(env, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import files as files_router

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-g21")
    monkeypatch.setattr(web, "USER_TOKEN", "usr-g21")
    monkeypatch.setattr(web.app, "dependency_overrides", {})
    monkeypatch.setattr(files_router, "get_orch", lambda: env.orch)
    return TestClient(web.app)


def _names(client, env, path=""):
    response = client.get("/api/files/list", headers=ADMIN, params={"root": env.root, "path": path})
    assert response.status_code == 200, response.text
    return response.json()


# ── who may use it ───────────────────────────────────────────────────────────────

def test_every_files_route_refuses_a_non_admin(env, client):
    calls = [("get", "/api/files/roots", {}), ("get", "/api/files/list", {"params": {"root": env.root}}),
             ("get", "/api/files/read", {"params": {"root": env.root, "path": "notes.txt"}}),
             ("get", "/api/files/download", {"params": {"root": env.root, "path": "notes.txt"}}),
             ("put", "/api/files/upload", {"params": {"root": env.root, "name": "x.txt"}, "content": b"x"}),
             ("post", "/api/files/mkdir", {"json": {"root": env.root, "name": "new"}}),
             ("post", "/api/files/rename", {"json": {"root": env.root, "path": "notes.txt", "new_name": "n.txt"}}),
             ("post", "/api/files/delete", {"json": {"root": env.root, "path": "notes.txt"}})]
    for headers in ({}, USER):
        for method, path, kwargs in calls:
            response = client.request(method.upper(), path, headers=headers, **kwargs)
            assert response.status_code in (401, 403), (method, path, headers, response.status_code)
    assert not (env.approved / "x.txt").exists() and not (env.approved / "new").exists()
    assert (env.approved / "notes.txt").exists()
    assert env.queue.pending_decisions() == []


def test_a_cross_site_write_is_refused(env, client):
    response = client.post("/api/files/mkdir", headers={**ADMIN, "Sec-Fetch-Site": "cross-site"},
                           json={"root": env.root, "name": "csrf"})
    assert response.status_code == 403
    assert not (env.approved / "csrf").exists()


# ── the denylist ─────────────────────────────────────────────────────────────────

def test_a_listing_never_names_credentials_keys_data_stores_or_hidden_files(env, client):
    body = _names(client, env)
    names = {row["name"] for row in body["entries"]}
    assert names == {"docs", "notes.txt"}
    assert body["hidden"] == 14
    assert body["entries"][0] == {**body["entries"][0], "name": "docs", "kind": "dir"}
    for leaked in ("id_rsa", ".env", "SECRET", "token", "vault"):
        assert leaked not in str(body["entries"])


@pytest.mark.parametrize("path", [".env", "id_rsa", "api_key.txt", "credentials.json", "hub.db",
                                  "server.pem", "telegram_token.txt", "store.sqlite3", "secrets.enc",
                                  "security/inside.txt", "tokens/inside.txt", "vault/inside.txt",
                                  ".ssh/inside.txt", ".gnupg/inside.txt"])
def test_a_denied_name_is_never_read_or_downloaded(env, client, path):
    for route in ("read", "download"):
        response = client.get(f"/api/files/{route}", headers=ADMIN, params={"root": env.root, "path": path})
        assert response.status_code == 403, (route, path, response.text)
        assert response.json()["error"] == "denied_name"
        assert "SECRET" not in response.text and "inside" not in response.text


@pytest.mark.parametrize("name", [".env", "id_ed25519", "aws_secret.txt", "my.key", "settings.db",
                                  "x.sqlite", "auth.json"])
def test_a_denied_name_is_never_created(env, client, name):
    up = client.put("/api/files/upload", headers=ADMIN, params={"root": env.root, "name": name}, content=b"k=v")
    assert up.status_code == 403 and up.json()["error"] == "denied_name"
    mk = client.post("/api/files/mkdir", headers=ADMIN, json={"root": env.root, "name": name})
    assert mk.status_code == 403
    rn = client.post("/api/files/rename", headers=ADMIN,
                     json={"root": env.root, "path": "notes.txt", "new_name": name})
    assert rn.status_code == 403
    assert env.queue.pending_decisions() == []


def test_the_denylist_keeps_ordinary_names(env):
    for ok in ("notes.txt", "keyboard.md", "authors.txt", "budget.xlsx", "photo.jpg"):
        assert not fb.denied_name(ok), ok


# ── no escape ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["../outside/private.txt", "docs/../../outside/private.txt", "/etc/passwd",
                                  "docs//plan.md", "./notes.txt", "docs\\plan.md", "notes.txt\x00",
                                  "docs/./plan.md"])
def test_traversal_and_absolute_paths_are_refused(env, client, path):
    response = client.get("/api/files/read", headers=ADMIN, params={"root": env.root, "path": path})
    assert response.status_code in (400, 422), (path, response.text)
    assert "not for the browser" not in response.text


def test_an_unknown_root_is_refused(env, client):
    response = client.get("/api/files/list", headers=ADMIN, params={"root": "r000000000000"})
    assert response.status_code == 404 and response.json()["error"] == "unknown_root"


def test_a_symlinked_file_or_folder_is_never_followed(env, client):
    (env.approved / "link.txt").symlink_to(env.outside / "private.txt")
    (env.approved / "linkdir").symlink_to(env.outside, target_is_directory=True)
    rows = {row["name"]: row for row in _names(client, env)["entries"]}
    assert rows["link.txt"]["kind"] == "link" and "size" not in rows["link.txt"]
    for route in ("read", "download"):
        response = client.get(f"/api/files/{route}", headers=ADMIN, params={"root": env.root, "path": "link.txt"})
        assert response.status_code == 403 and response.json()["error"] == "symlink"
        response = client.get(f"/api/files/{route}", headers=ADMIN,
                              params={"root": env.root, "path": "linkdir/private.txt"})
        assert response.status_code == 403 and response.json()["error"] == "symlink"
    listed = client.get("/api/files/list", headers=ADMIN, params={"root": env.root, "path": "linkdir"})
    assert listed.status_code == 403 and "private.txt" not in listed.text
    up = client.put("/api/files/upload", headers=ADMIN, params={"root": env.root, "path": "linkdir", "name": "a.txt"},
                    content=b"x")
    assert up.status_code == 403 and not (env.outside / "a.txt").exists()


def test_a_folder_swapped_for_a_link_mid_walk_fails_the_walk(env, monkeypatch):
    real_open = os.open
    swapped = []

    def swap_then_open(path, flags, *args, **kwargs):
        if path == "docs" and not swapped:
            (env.approved / "docs").rename(env.approved / "docs-real")
            (env.approved / "docs").symlink_to(env.outside, target_is_directory=True)
            swapped.append(True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(fb.os, "open", swap_then_open)
    with pytest.raises(fb.FileBrowserError) as caught:
        fb.read_preview(env.root, "docs/private.txt")
    assert caught.value.reason == "symlink" and swapped


def test_a_hard_link_is_never_read_or_downloaded(env, client):
    os.link(env.outside / "private.txt", env.approved / "innocent.txt")
    for route in ("read", "download"):
        response = client.get(f"/api/files/{route}", headers=ADMIN, params={"root": env.root, "path": "innocent.txt"})
        assert response.status_code == 403 and response.json()["error"] == "hard_link"
        assert "not for the browser" not in response.text


def test_a_fifo_is_not_a_file(env, client):
    os.mkfifo(env.approved / "pipe")
    response = client.get("/api/files/read", headers=ADMIN, params={"root": env.root, "path": "pipe"})
    assert response.status_code == 400 and response.json()["error"] == "not_a_file"


def test_a_protected_or_containing_folder_is_never_approved(env, monkeypatch):
    home = Path.home()
    for bad in (Path(os.sep), home, env.data, env.data / "security", Path(__file__).resolve().parents[1]):
        bad.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("JARVIS_FILE_BROWSER_DIRS", str(bad))
        assert fb.roots() == [], bad
    monkeypatch.setenv("JARVIS_FILE_BROWSER_DIRS", "relative/dir")
    assert fb.roots() == []


def test_default_roots_are_the_hubs_own_work_folders(env, monkeypatch):
    monkeypatch.delenv("JARVIS_FILE_BROWSER_DIRS")
    assert fb.roots() == []
    (env.data / "outputs").mkdir()
    (env.data / "workspace").mkdir()
    assert [r.label for r in fb.roots()] == ["workspace", "outputs"]


# ── reads ────────────────────────────────────────────────────────────────────────

def test_the_owner_lists_previews_and_downloads(env, client):
    roots = client.get("/api/files/roots", headers=ADMIN).json()
    assert roots["roots"] == [{"id": env.root, "label": "share", "path": str(env.approved)}]
    docs = _names(client, env, "docs")
    assert [r["name"] for r in docs["entries"]] == ["plan.md"] and docs["path"] == "docs"
    preview = client.get("/api/files/read", headers=ADMIN, params={"root": env.root, "path": "notes.txt"}).json()
    assert preview["text"] == "hello owner\n" and preview["binary"] is False and preview["truncated"] is False
    response = client.get("/api/files/download", headers=ADMIN, params={"root": env.root, "path": "notes.txt"})
    assert response.status_code == 200 and response.content == b"hello owner\n"
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert ("file_browser_download", "downloaded 12 bytes from share") in env.orch.audit.rows


def test_a_binary_file_previews_as_binary_and_a_large_one_is_capped(env, client, monkeypatch):
    (env.approved / "blob.bin").write_bytes(b"\x00\x01\x02" * 10)
    body = client.get("/api/files/read", headers=ADMIN, params={"root": env.root, "path": "blob.bin"}).json()
    assert body["binary"] is True and body["text"] is None
    monkeypatch.setenv("JARVIS_FILE_BROWSER_MAX_BYTES", "10")
    response = client.get("/api/files/download", headers=ADMIN, params={"root": env.root, "path": "blob.bin"})
    assert response.status_code == 413 and response.json()["error"] == "too_large"


# ── writes that replace nothing ──────────────────────────────────────────────────

def test_upload_creates_a_new_file_and_never_replaces_one(env, client):
    response = client.put("/api/files/upload", headers=ADMIN,
                          params={"root": env.root, "path": "docs", "name": "report.txt"}, content=b"new bytes")
    assert response.status_code == 201, response.text
    assert response.json()["path"] == "docs/report.txt" and response.json()["size"] == 9
    assert (env.approved / "docs" / "report.txt").read_bytes() == b"new bytes"
    again = client.put("/api/files/upload", headers=ADMIN, params={"root": env.root, "name": "notes.txt"},
                       content=b"overwrite")
    assert again.status_code == 409 and again.json()["error"] == "exists"
    assert (env.approved / "notes.txt").read_text(encoding="utf-8") == "hello owner\n"
    assert not list(env.approved.rglob(".nerva-upload-*"))


def test_upload_stops_at_the_size_cap_and_leaves_nothing(env, client, monkeypatch):
    monkeypatch.setenv("JARVIS_FILE_BROWSER_MAX_BYTES", "8")
    response = client.put("/api/files/upload", headers=ADMIN, params={"root": env.root, "name": "big.txt"},
                          content=b"0123456789")
    assert response.status_code == 413
    upload = fb.Upload(env.root, "", "big.txt", limit=4)
    try:
        upload.write(b"abc")
        with pytest.raises(fb.FileBrowserError):
            upload.write(b"de")
    finally:
        upload.close()
    assert not (env.approved / "big.txt").exists()
    assert not [p for p in env.approved.iterdir() if p.name.startswith(".nerva-upload-")]


def test_mkdir_makes_a_new_folder_only(env, client):
    response = client.post("/api/files/mkdir", headers=ADMIN, json={"root": env.root, "path": "docs", "name": "drafts"})
    assert response.status_code == 201 and (env.approved / "docs" / "drafts").is_dir()
    again = client.post("/api/files/mkdir", headers=ADMIN, json={"root": env.root, "name": "docs"})
    assert again.status_code == 409


# ── rename / delete: approval cards ──────────────────────────────────────────────

def _accept(env, task_id, decided_by="admin"):
    from agents.core.autonomy import irreversible

    task = asyncio.run(env.worker.apply_decision(task_id, "accept", decided_by=decided_by))
    return asyncio.run(irreversible.execute(task, orch=env.orch))


def test_delete_is_a_tier_three_card_and_happens_only_on_a_human_accept(env, client):
    from agents.core.autonomy import irreversible

    response = client.post("/api/files/delete", headers=ADMIN, json={"root": env.root, "path": "notes.txt"})
    assert response.status_code == 202, response.text
    task_id = response.json()["pending"]
    task = env.queue.get(task_id)
    assert task.kind == "files.delete" and task.risk_tier == 3 and task.status == "blocked"
    assert task.payload["preview"]["path"] == "notes.txt" and task.payload["reversible"] is False
    assert (env.approved / "notes.txt").exists()
    again = client.post("/api/files/delete", headers=ADMIN, json={"root": env.root, "path": "notes.txt"})
    assert again.json() == {"pending": task_id, "existing": True}
    machine = SimpleNamespace(id=task_id, kind="files.delete", payload=task.payload, decided_by="policy",
                              decision="accept")
    assert asyncio.run(irreversible.execute(machine, orch=env.orch))["reason"] == "human_decision_required"
    assert (env.approved / "notes.txt").exists()
    assert _accept(env, task_id) == {"status": "ok", "kind": "files.delete", "deleted": "notes.txt"}
    assert not (env.approved / "notes.txt").exists()
    assert any(action == "file_browser_delete" for action, _ in env.orch.audit.rows)


def test_a_file_changed_since_the_card_is_not_deleted(env, client):
    task_id = client.post("/api/files/delete", headers=ADMIN,
                          json={"root": env.root, "path": "notes.txt"}).json()["pending"]
    (env.approved / "notes.txt").unlink()
    (env.approved / "notes.txt").write_text("a different file, same name\n", encoding="utf-8")
    assert _accept(env, task_id) == {"status": "refused", "reason": "changed_since_request"}
    assert (env.approved / "notes.txt").read_text(encoding="utf-8").startswith("a different")


def test_a_card_whose_folder_is_no_longer_approved_is_refused(env, client, monkeypatch, tmp_path):
    task_id = client.post("/api/files/delete", headers=ADMIN,
                          json={"root": env.root, "path": "notes.txt"}).json()["pending"]
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("JARVIS_FILE_BROWSER_DIRS", str(other))
    assert _accept(env, task_id) == {"status": "refused", "reason": "root_changed"}
    assert (env.approved / "notes.txt").exists()


def test_a_folder_is_deleted_only_when_empty(env, client):
    response = client.post("/api/files/delete", headers=ADMIN, json={"root": env.root, "path": "docs"})
    assert response.status_code == 409 and response.json()["error"] == "not_empty"
    (env.approved / "empty").mkdir()
    task_id = client.post("/api/files/delete", headers=ADMIN, json={"root": env.root, "path": "empty"}).json()["pending"]
    (env.approved / "empty" / "late.txt").write_text("arrived after the card", encoding="utf-8")
    assert _accept(env, task_id)["status"] == "refused"
    assert (env.approved / "empty" / "late.txt").exists()


def test_deleting_a_symlink_removes_the_link_not_its_target(env, client):
    (env.approved / "link.txt").symlink_to(env.outside / "private.txt")
    task_id = client.post("/api/files/delete", headers=ADMIN,
                          json={"root": env.root, "path": "link.txt"}).json()["pending"]
    assert _accept(env, task_id)["status"] == "ok"
    assert not (env.approved / "link.txt").is_symlink()
    assert (env.outside / "private.txt").read_text(encoding="utf-8") == "not for the browser"


def test_rename_is_a_card_and_never_replaces_a_file(env, client):
    response = client.post("/api/files/rename", headers=ADMIN,
                           json={"root": env.root, "path": "notes.txt", "new_name": "renamed.txt"})
    assert response.status_code == 202, response.text
    task_id = response.json()["pending"]
    assert env.queue.get(task_id).kind == "files.rename"
    assert (env.approved / "notes.txt").exists() and not (env.approved / "renamed.txt").exists()
    clash = client.post("/api/files/rename", headers=ADMIN,
                        json={"root": env.root, "path": "notes.txt", "new_name": "docs"})
    assert clash.status_code == 409
    assert _accept(env, task_id) == {"status": "ok", "kind": "files.rename", "renamed": "notes.txt",
                                     "to": "renamed.txt"}
    assert (env.approved / "renamed.txt").read_text(encoding="utf-8") == "hello owner\n"


def test_a_rename_target_created_after_the_card_is_not_overwritten(env, client):
    task_id = client.post("/api/files/rename", headers=ADMIN,
                          json={"root": env.root, "path": "notes.txt", "new_name": "taken.txt"}).json()["pending"]
    (env.approved / "taken.txt").write_text("keep me", encoding="utf-8")
    assert _accept(env, task_id) == {"status": "refused", "reason": "exists"}
    assert (env.approved / "taken.txt").read_text(encoding="utf-8") == "keep me"


def test_a_tampered_payload_is_refused(env):
    for payload in (None, {"op": "delete"}, {"op": "rename", "target": {}},
                    {"op": "delete", "root_id": env.root, "root_path": str(env.approved), "path": "../outside",
                     "target": {}}):
        assert fb.apply_payload(payload, kind=fb.KIND_DELETE)["status"] == "refused"
    assert fb.apply_payload({"op": "rename", "target": {}}, kind=fb.KIND_DELETE)["reason"] == "payload_invalid"


def test_no_approval_queue_means_nothing_changes(env, client):
    env.orch.autonomy = None
    response = client.post("/api/files/delete", headers=ADMIN, json={"root": env.root, "path": "notes.txt"})
    assert response.status_code == 503 and (env.approved / "notes.txt").exists()


# ══ slice 2 — channel settings (H151 / H160) ═════════════════════════════════════

CHANNEL_NAMES = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USER_IDS", "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN",
                 "SLACK_APP_TOKEN", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "IMAP_HOST", "IMAP_PORT",
                 "IMAP_USER", "IMAP_PASS", "NTFY_URL", "NTFY_TOPIC", "NTFY_TOKEN", "NTFY_TITLE", "NTFY_INBOUND",
                 "NTFY_PUBLISH_TOPIC", "NTFY_MARKDOWN", "JARVIS_SMS_ENABLED", "NERVA_SMS_ENABLED",
                 "JARVIS_SMS_ACCOUNT_SID", "NERVA_SMS_ACCOUNT_SID", "JARVIS_SMS_AUTH_TOKEN", "NERVA_SMS_AUTH_TOKEN",
                 "JARVIS_SMS_FROM_NUMBER", "NERVA_SMS_FROM_NUMBER", "JARVIS_SMS_ALLOWED_NUMBERS",
                 "NERVA_SMS_ALLOWED_NUMBERS", "JARVIS_SMS_WEBHOOK_URL", "NERVA_SMS_WEBHOOK_URL")
TG_TOKEN = "123456789:synthetic-telegram-bot-token-AAAA-ZZZZ"
CBASE = "/api/admin/channels"


@pytest.fixture
def chub(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core import channel_config, integration_keys, managed_scope, settings_db
    from agents.core.routers import channel_config as channel_router

    for name in CHANNEL_NAMES:
        monkeypatch.delenv(name, raising=False)
    integration_keys._PLACED.clear()
    channel_config.reset_for_tests()
    store = tmp_path / "security" / "secrets.enc"
    monkeypatch.setattr(integration_keys, "_store_path", lambda: store)
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.delenv("JARVIS_MANAGED_DIR", raising=False)
    monkeypatch.delenv("NERVA_MANAGED_DIR", raising=False)
    managed_scope.invalidate()
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-g21")
    monkeypatch.setattr(web, "USER_TOKEN", "usr-g21")
    monkeypatch.setattr(web.app, "dependency_overrides", {})
    orch = SimpleNamespace(audit=FakeAudit(), channels={"web": object(), "telegram": object()})
    monkeypatch.setattr(channel_router, "get_orch", lambda: orch)
    yield SimpleNamespace(client=TestClient(web.app), orch=orch, store=store, tmp=tmp_path)
    integration_keys.reset_for_tests()
    channel_config.reset_for_tests()
    managed_scope.invalidate()
    for name in CHANNEL_NAMES:
        os.environ.pop(name, None)


def _channel(chub, cid):
    body = chub.client.get(f"{CBASE}/config", headers=ADMIN).json()
    return next(c for c in body["channels"] if c["id"] == cid)


def _field(row, name):
    return next(f for f in row["fields"] if f["name"] == name)


def test_every_channel_route_refuses_a_non_admin(chub):
    calls = [("get", f"{CBASE}/config", None),
             ("put", f"{CBASE}/telegram/config", {"values": {"TELEGRAM_ALLOWED_USER_IDS": "1"}}),
             ("put", f"{CBASE}/telegram/secret", {"name": "TELEGRAM_BOT_TOKEN", "value": TG_TOKEN}),
             ("delete", f"{CBASE}/telegram/secret/TELEGRAM_BOT_TOKEN", None)]
    for headers in ({}, USER):
        for method, path, body in calls:
            kwargs = {"headers": headers}
            if body is not None:
                kwargs["json"] = body
            assert chub.client.request(method.upper(), path, **kwargs).status_code in (401, 403), (method, path)
    assert "TELEGRAM_BOT_TOKEN" not in os.environ and not chub.store.exists()


def test_the_listing_shows_every_channel_and_whether_it_runs(chub):
    body = chub.client.get(f"{CBASE}/config", headers=ADMIN).json()
    ids = [c["id"] for c in body["channels"]]
    assert ids == ["telegram", "discord", "slack", "email", "ntfy", "sms"]
    assert _channel(chub, "telegram")["running"] is True and _channel(chub, "email")["running"] is False
    token = _field(_channel(chub, "telegram"), "TELEGRAM_BOT_TOKEN")
    assert token == {**token, "secret": True, "set": False, "source": None, "editable": True}
    assert "value" not in token


def test_a_secret_is_stored_encrypted_and_never_echoed(chub):
    response = chub.client.put(f"{CBASE}/telegram/secret", headers=ADMIN,
                               json={"name": "TELEGRAM_BOT_TOKEN", "value": TG_TOKEN})
    assert response.status_code == 200, response.text
    assert TG_TOKEN not in response.text and TG_TOKEN[-4:] not in response.text
    assert response.json()["secret"] == {"name": "TELEGRAM_BOT_TOKEN", "set": True, "source": "hub"}
    assert os.environ["TELEGRAM_BOT_TOKEN"] == TG_TOKEN
    listing = chub.client.get(f"{CBASE}/config", headers=ADMIN)
    assert TG_TOKEN not in listing.text and TG_TOKEN[-4:] not in listing.text
    assert _channel(chub, "telegram")["restart_required"] is True
    assert chub.store.exists() and TG_TOKEN not in chub.store.read_text(encoding="utf-8", errors="replace")
    assert all(TG_TOKEN not in preview for _, preview in chub.orch.audit.rows)
    # the start applies it from the store, after .env, before the channels are wired
    from agents.core import integration_keys

    integration_keys._PLACED.clear()
    os.environ.pop("TELEGRAM_BOT_TOKEN")
    assert "TELEGRAM_BOT_TOKEN" in integration_keys.apply_stored()
    assert os.environ["TELEGRAM_BOT_TOKEN"] == TG_TOKEN
    removed = chub.client.delete(f"{CBASE}/telegram/secret/TELEGRAM_BOT_TOKEN", headers=ADMIN)
    assert removed.status_code == 200 and removed.json()["secret"]["set"] is False
    assert "TELEGRAM_BOT_TOKEN" not in os.environ


def test_a_malformed_secret_body_never_echoes_the_value(chub):
    for body in ({"name": "TELEGRAM_BOT_TOKEN", "value": TG_TOKEN, "extra": TG_TOKEN},
                 {"name": "telegram bot", "value": TG_TOKEN}, {"name": "TELEGRAM_BOT_TOKEN", "value": 5},
                 {"name": "TELEGRAM_BOT_TOKEN", "value": TG_TOKEN + "\nX"}):
        response = chub.client.put(f"{CBASE}/telegram/secret", headers=ADMIN, json=body)
        assert response.status_code in (404, 422), (body, response.status_code)
        assert TG_TOKEN not in response.text
    assert "TELEGRAM_BOT_TOKEN" not in os.environ


def test_a_secret_cannot_be_written_as_a_plain_setting_or_to_another_channel(chub):
    plain = chub.client.put(f"{CBASE}/telegram/config", headers=ADMIN,
                            json={"values": {"TELEGRAM_BOT_TOKEN": TG_TOKEN}})
    assert plain.status_code == 404 and TG_TOKEN not in plain.text
    other = chub.client.put(f"{CBASE}/discord/secret", headers=ADMIN,
                            json={"name": "TELEGRAM_BOT_TOKEN", "value": TG_TOKEN})
    assert other.status_code == 404
    arbitrary = chub.client.put(f"{CBASE}/telegram/secret", headers=ADMIN,
                                json={"name": "OPENAI_API_KEY", "value": TG_TOKEN})
    assert arbitrary.status_code == 404
    assert "OPENAI_API_KEY" not in os.environ and "TELEGRAM_BOT_TOKEN" not in os.environ


def test_plain_settings_go_to_the_settings_database_validated(chub):
    from agents.core import channel_config, settings_db

    response = chub.client.put(f"{CBASE}/email/config", headers=ADMIN, json={"values": {
        "SMTP_HOST": "smtp.example.org", "SMTP_PORT": 587, "SMTP_USER": "owner@example.org",
        "IMAP_HOST": "imap.example.org", "IMAP_PORT": "993"}})
    assert response.status_code == 200, response.text
    assert settings_db.get_value("channels", "config", {})["SMTP_HOST"] == "smtp.example.org"
    assert os.environ["SMTP_PORT"] == "587"
    row = _channel(chub, "email")
    assert _field(row, "SMTP_HOST") == {**_field(row, "SMTP_HOST"), "value": "smtp.example.org", "source": "hub"}
    assert row["restart_required"] is True
    for cid, bad in (("email", {"SMTP_PORT": 70000}), ("email", {"SMTP_HOST": "bad host;rm"}),
                     ("email", {"SMTP_USER": "a\nb"}), ("ntfy", {"NTFY_URL": "file:///etc/passwd"})):
        refused = chub.client.put(f"{CBASE}/{cid}/config", headers=ADMIN, json={"values": bad})
        assert refused.status_code == 422, bad
    assert os.environ["SMTP_PORT"] == "587"
    cleared = chub.client.put(f"{CBASE}/email/config", headers=ADMIN, json={"values": {"SMTP_USER": None}})
    assert cleared.status_code == 200 and "SMTP_USER" not in os.environ
    # at the next start the stored values are placed again, before the channels are wired
    channel_config.reset_for_tests()
    assert "SMTP_HOST" not in os.environ
    assert set(channel_config.apply_stored()) == {"SMTP_HOST", "SMTP_PORT", "IMAP_HOST", "IMAP_PORT"}
    assert os.environ["IMAP_PORT"] == "993"


def test_sms_settings_apply_now(chub):
    response = chub.client.put(f"{CBASE}/sms/config", headers=ADMIN, json={"values": {
        "JARVIS_SMS_ACCOUNT_SID": "AC00000000000000000000000000000000",
        "JARVIS_SMS_FROM_NUMBER": "+15550001111", "JARVIS_SMS_ALLOWED_NUMBERS": "+15550002222, +15550003333"}})
    assert response.status_code == 200, response.text
    from agents.core.channels import sms

    assert sms.allowed_numbers() == frozenset({"+15550002222", "+15550003333"})
    assert _channel(chub, "sms")["restart_required"] is False
    bad = chub.client.put(f"{CBASE}/sms/config", headers=ADMIN, json={"values": {"JARVIS_SMS_FROM_NUMBER": "555"}})
    assert bad.status_code == 422


def test_env_wins_over_the_hud(chub, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "from-dot-env-token-0000000000")
    monkeypatch.setenv("SMTP_HOST", "env.example.org")
    secret = chub.client.put(f"{CBASE}/telegram/secret", headers=ADMIN,
                             json={"name": "TELEGRAM_BOT_TOKEN", "value": TG_TOKEN})
    assert secret.status_code == 409 and secret.json()["error"] == "env_managed"
    plain = chub.client.put(f"{CBASE}/email/config", headers=ADMIN, json={"values": {"SMTP_HOST": "x.example.org"}})
    assert plain.status_code == 409
    assert os.environ["TELEGRAM_BOT_TOKEN"] == "from-dot-env-token-0000000000"
    row = _channel(chub, "telegram")
    token = _field(row, "TELEGRAM_BOT_TOKEN")
    assert token["source"] == "env" and token["editable"] is False
    assert "from-dot-env" not in chub.client.get(f"{CBASE}/config", headers=ADMIN).text


def test_a_managed_pin_or_managed_mode_refuses_the_write(chub, monkeypatch):
    from agents.core import managed_scope

    directory = chub.tmp / "etc-nerva"
    directory.mkdir()
    monkeypatch.setenv("NERVA_MANAGED_DIR", str(directory))
    monkeypatch.setattr(managed_scope, "_TRUST_ANY_OWNER_FOR_TESTS", True)
    monkeypatch.setattr("agents.core.settings_db._LAST_VALID_PIN", {})
    (directory / ".env").write_text("SMTP_HOST=pinned.example.org\nTELEGRAM_BOT_TOKEN=admin-token-000000000000\n",
                                    encoding="utf-8")
    managed_scope.invalidate()
    refused = chub.client.put(f"{CBASE}/email/config", headers=ADMIN, json={"values": {"SMTP_HOST": "x.example.org"}})
    assert refused.status_code == 409 and refused.json()["error"] == "managed"
    secret = chub.client.put(f"{CBASE}/telegram/secret", headers=ADMIN,
                             json={"name": "TELEGRAM_BOT_TOKEN", "value": TG_TOKEN})
    assert secret.status_code == 409 and secret.json()["error"] == "managed"
    assert TG_TOKEN not in secret.text
    assert any(action == "settings_managed_refused" for action, _ in chub.orch.audit.rows)
    (directory / ".env").unlink()
    (directory / ".managed").write_text("ask your administrator\n", encoding="utf-8")
    managed_scope.invalidate()
    locked = chub.client.put(f"{CBASE}/email/config", headers=ADMIN, json={"values": {"IMAP_HOST": "i.example.org"}})
    assert locked.status_code == 409 and "IMAP_HOST" not in os.environ


def test_a_cross_site_channel_write_is_refused(chub):
    response = chub.client.put(f"{CBASE}/email/config", headers={**ADMIN, "Sec-Fetch-Site": "cross-site"},
                               json={"values": {"SMTP_HOST": "x.example.org"}})
    assert response.status_code == 403 and "SMTP_HOST" not in os.environ


def test_channel_secrets_never_reach_a_sandboxed_child(chub):
    from agents.core import channel_config, code_env

    assert channel_config.secret_names() <= code_env._MANAGED_NAMES


# ══ slice 3 — restart and update check (H160 / H173 / H624) ══════════════════════

def _run(cwd, *args):
    import subprocess

    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org", "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture
def ops(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core import hub_restart, hub_update
    from agents.core.routers import ops as ops_router

    origin = tmp_path / "origin.git"
    _run(tmp_path, "init", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _run(tmp_path, "clone", str(origin), str(work))
    (work / "README.md").write_text("one\n", encoding="utf-8")
    _run(work, "add", "README.md")
    _run(work, "commit", "-m", "one")
    _run(work, "push", "-u", "origin", "HEAD:main")
    _run(work, "branch", "--set-upstream-to=origin/main")
    other = tmp_path / "other"
    _run(tmp_path, "clone", str(origin), str(other))
    (other / "CHANGES.md").write_text("two\n", encoding="utf-8")
    _run(other, "add", "CHANGES.md")
    _run(other, "commit", "-m", "two")
    _run(other, "push", "origin", "HEAD:main")
    monkeypatch.setattr(hub_update, "repo_root", lambda: work)
    monkeypatch.setattr(hub_update, "_install_kind", lambda: "git")
    hub_update.reset_for_tests()
    hub_restart.reset()
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-g21")
    monkeypatch.setattr(web, "USER_TOKEN", "usr-g21")
    monkeypatch.setattr(web.app, "dependency_overrides", {})
    orch = SimpleNamespace(audit=FakeAudit())
    monkeypatch.setattr(ops_router, "get_orch", lambda: orch)
    yield SimpleNamespace(client=TestClient(web.app), work=work, orch=orch)
    hub_restart.reset()
    hub_update.reset_for_tests()


def _wait_action(client, action_id):
    import time

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        body = client.get(f"/api/admin/ops/actions/{action_id}", headers=ADMIN).json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("the action did not finish")


def test_every_ops_route_refuses_a_non_admin(ops):
    calls = [("get", "/api/admin/ops/update", None), ("post", "/api/admin/ops/update/fetch", None),
             ("get", "/api/admin/ops/actions/0123456789abcdef", None),
             ("post", "/api/admin/ops/restart", {"confirm": "restart"})]
    stopped = []
    from agents.core import hub_restart

    hub_restart.install(lambda: stopped.append(True))
    for headers in ({}, USER):
        for method, path, body in calls:
            kwargs = {"headers": headers}
            if body is not None:
                kwargs["json"] = body
            assert ops.client.request(method.upper(), path, **kwargs).status_code in (401, 403), (method, path)
    import time

    time.sleep(0.8)
    assert stopped == []


def test_the_update_check_is_honest_about_behind_count_dirty_tree_and_apply(ops):
    body = ops.client.get("/api/admin/ops/update", headers=ADMIN).json()
    assert body["install"] == "git" and body["branch"] == "main" and body["upstream"] == "origin/main"
    assert body["behind"] == 0 and body["ahead"] == 0 and body["dirty"] is False
    assert body["can_apply"] is False and any("signature" in r for r in body["apply_refused"])
    started = ops.client.post("/api/admin/ops/update/fetch", headers=ADMIN, json={})
    assert started.status_code == 202, started.text
    done = _wait_action(ops.client, started.json()["id"])
    assert done["status"] == "ok" and done["result"]["behind"] == 1
    assert done["lines"][0] == "$ git fetch --prune origin"
    after = ops.client.get("/api/admin/ops/update", headers=ADMIN).json()
    assert after["behind"] == 1 and after["fetched_seconds_ago"] is not None
    (ops.work / "README.md").write_text("edited\n", encoding="utf-8")
    dirty = ops.client.get("/api/admin/ops/update", headers=ADMIN).json()
    assert dirty["dirty"] is True and any("uncommitted" in r for r in dirty["apply_refused"])
    assert dirty["can_apply"] is False
    # nothing was pulled: the checkout still has its one commit
    assert not (ops.work / "CHANGES.md").exists()


def test_a_container_or_a_non_git_install_never_offers_an_apply(ops, monkeypatch):
    from agents.core import hub_update

    monkeypatch.setattr(hub_update, "_install_kind", lambda: "container")
    body = ops.client.get("/api/admin/ops/update", headers=ADMIN).json()
    assert body["can_apply"] is False and any("image" in r for r in body["apply_refused"])
    refused = ops.client.post("/api/admin/ops/update/fetch", headers=ADMIN, json={})
    assert refused.status_code == 409 and refused.json()["error"] == "not_a_git_checkout"


def test_a_fetch_log_never_carries_url_credentials():
    from agents.core import hub_update

    line = hub_update.clean_line("From https://owner:ghp_secret0123@github.example.org/o/r\x1b[31m")
    assert line == "From https://github.example.org/o/r[31m"
    assert "ghp_secret" not in line


def test_restart_needs_the_confirm_word_and_says_when_it_cannot_restart_itself(ops):
    from agents.core import hub_restart

    manual = ops.client.post("/api/admin/ops/restart", headers=ADMIN, json={"confirm": "restart"})
    assert manual.status_code == 409 and manual.json()["error"] == "manual" and manual.json()["restart"] == "manual"
    stopped = []
    hub_restart.install(lambda: stopped.append(True))
    wrong = ops.client.post("/api/admin/ops/restart", headers=ADMIN, json={"confirm": "yes"})
    assert wrong.status_code == 400
    cross = ops.client.post("/api/admin/ops/restart", headers={**ADMIN, "Sec-Fetch-Site": "cross-site"},
                            json={"confirm": "restart"})
    assert cross.status_code == 403
    import time

    time.sleep(0.8)
    assert stopped == []
    ok = ops.client.post("/api/admin/ops/restart", headers=ADMIN, json={"confirm": "restart"})
    assert ok.status_code == 202 and ok.json()["restart"] == "requested"
    deadline = time.monotonic() + 5
    while not stopped and time.monotonic() < deadline:
        time.sleep(0.05)
    assert stopped == [True] and hub_restart.requested() == "owner restart from the HUD"
    assert ("ops_restart", "hub restart requested from the HUD") in ops.orch.audit.rows


def test_an_unknown_action_is_404(ops):
    assert ops.client.get("/api/admin/ops/actions/0123456789abcdef", headers=ADMIN).status_code == 404
    assert ops.client.get("/api/admin/ops/actions/../x", headers=ADMIN).status_code in (404, 422)


# ══ security review fixes ════════════════════════════════════════════════════════

NTFY_TOKEN = "tk_synthetic_ntfy_token_0123456789"
IMAP_PASSWORD = "synthetic-imap-app-password-XYZ"


def test_m1_ntfy_url_must_be_https_unless_loopback(chub):
    for bad in ("http://ntfy.example.org", "ftp://ntfy.example.org", "https://u:p@ntfy.example.org"):
        assert chub.client.put(f"{CBASE}/ntfy/config", headers=ADMIN,
                               json={"values": {"NTFY_URL": bad}}).status_code == 422, bad
    for ok in ("https://ntfy.example.org", "http://127.0.0.1:8090", "http://localhost:8090"):
        assert chub.client.put(f"{CBASE}/ntfy/config", headers=ADMIN,
                               json={"values": {"NTFY_URL": ok}}).status_code == 200, ok


def test_m1_moving_an_endpoint_clears_its_bound_secret(chub):
    c = chub.client
    assert c.put(f"{CBASE}/ntfy/config", headers=ADMIN,
                 json={"values": {"NTFY_URL": "https://ntfy.owner.example"}}).status_code == 200
    assert c.put(f"{CBASE}/ntfy/secret", headers=ADMIN, json={"name": "NTFY_TOKEN", "value": NTFY_TOKEN}).status_code == 200
    assert c.put(f"{CBASE}/ntfy/secret", headers=ADMIN, json={"name": "NTFY_TOPIC", "value": "owner-topic"}).status_code == 200
    # an unrelated field keeps the secret
    assert c.put(f"{CBASE}/ntfy/config", headers=ADMIN, json={"values": {"NTFY_TITLE": "Nerva"}}).json()["cleared_secrets"] == []
    assert os.environ["NTFY_TOKEN"] == NTFY_TOKEN
    moved = c.put(f"{CBASE}/ntfy/config", headers=ADMIN, json={"values": {"NTFY_URL": "https://other.example"}})
    assert moved.status_code == 200
    assert moved.json()["cleared_secrets"] == ["NTFY_TOKEN", "NTFY_TOPIC"]
    assert "NTFY_TOKEN" not in os.environ and "NTFY_TOPIC" not in os.environ
    assert any("secrets cleared for the new server" in preview for _, preview in chub.orch.audit.rows)
    # the email password the same way, port included
    assert c.put(f"{CBASE}/email/config", headers=ADMIN, json={"values": {"IMAP_HOST": "imap.owner.example"}}).status_code == 200
    assert c.put(f"{CBASE}/email/secret", headers=ADMIN, json={"name": "IMAP_PASS", "value": IMAP_PASSWORD}).status_code == 200
    assert c.put(f"{CBASE}/email/config", headers=ADMIN, json={"values": {"IMAP_PORT": 1993}}).json()["cleared_secrets"] == ["IMAP_PASS"]
    assert "IMAP_PASS" not in os.environ


def test_m1_an_endpoint_cannot_move_away_from_a_secret_in_env(chub, monkeypatch):
    monkeypatch.setenv("SMTP_PASS", "dot-env-smtp-password")
    c = chub.client
    response = c.put(f"{CBASE}/email/config", headers=ADMIN, json={"values": {"SMTP_HOST": "smtp.elsewhere.example"}})
    assert response.status_code == 409 and response.json()["error"] == "bound_secret_in_env"
    assert "SMTP_HOST" not in os.environ and "dot-env-smtp-password" not in response.text


def test_m1_a_secret_whose_server_changed_out_of_band_is_withheld_at_start(chub):
    from agents.core import channel_config, integration_keys, settings_db

    c = chub.client
    c.put(f"{CBASE}/email/config", headers=ADMIN, json={"values": {"IMAP_HOST": "imap.owner.example"}})
    c.put(f"{CBASE}/email/secret", headers=ADMIN, json={"name": "IMAP_PASS", "value": IMAP_PASSWORD})
    # the generic settings route (or a hand edit) repoints the server, bypassing the panel
    settings_db.put_category("channels", {"config": {"IMAP_HOST": "attacker.example.net"}})
    # the next start
    integration_keys._PLACED.clear()
    channel_config.reset_for_tests()
    for name in ("IMAP_PASS", "IMAP_HOST"):
        os.environ.pop(name, None)
    integration_keys.apply_stored()
    channel_config.apply_stored()
    assert os.environ.get("IMAP_HOST") == "attacker.example.net"
    assert "IMAP_PASS" not in os.environ
    field = next(f for f in _channel(chub, "email")["fields"] if f["name"] == "IMAP_PASS")
    assert field["needs_reentry"] is True
    # an unchanged server keeps its secret across a start
    settings_db.put_category("channels", {"config": {"IMAP_HOST": "imap.owner.example"}})
    integration_keys._PLACED.clear()
    channel_config.reset_for_tests()
    for name in ("IMAP_PASS", "IMAP_HOST"):
        os.environ.pop(name, None)
    integration_keys.apply_stored()
    channel_config.apply_stored()
    assert os.environ.get("IMAP_PASS") == IMAP_PASSWORD


def test_m1_the_email_channel_verifies_the_mail_servers_certificates(monkeypatch):
    import ssl

    from agents.core.channels import email as email_channel

    monkeypatch.delenv("JARVIS_TLS_INSECURE_TARGETS", raising=False)
    monkeypatch.delenv("NERVA_TLS_INSECURE_TARGETS", raising=False)
    context = email_channel._tls_context("imap.example.org")
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True
    monkeypatch.setenv("JARVIS_TLS_INSECURE_TARGETS", "mail.local")
    assert email_channel._tls_context("imap.example.org").verify_mode == ssl.CERT_REQUIRED
    assert email_channel._tls_context("mail.local").verify_mode == ssl.CERT_NONE


def test_m1_roots_refuse_links_code_and_hidden_folders(env, monkeypatch, tmp_path):
    import sys

    link = tmp_path / "share-link"
    link.symlink_to(env.approved, target_is_directory=True)
    hidden = tmp_path / ".hidden" / "box"
    hidden.mkdir(parents=True)
    skills = env.data / "skills"
    skills.mkdir()
    for bad in (link, hidden, skills, Path(sys.prefix), Path(fb.__file__).resolve().parents[2] / "docs"):
        monkeypatch.setenv("JARVIS_FILE_BROWSER_DIRS", str(bad))
        assert fb.roots() == [], bad


@pytest.mark.parametrize("name", ["evil.pth", "sitecustomize.py", "usercustomize.py", "lib.so", "lib.dylib",
                                  "x.dll", "y.pyd"])
def test_m1_code_loading_names_are_never_written(env, client, name):
    up = client.put("/api/files/upload", headers=ADMIN, params={"root": env.root, "name": name}, content=b"x")
    assert up.status_code == 403 and up.json()["error"] == "denied_name"
    rn = client.post("/api/files/rename", headers=ADMIN, json={"root": env.root, "path": "notes.txt", "new_name": name})
    assert rn.status_code == 403
    assert not (env.approved / name).exists()


def test_m2_a_log_line_keeps_no_password_with_at_signs_and_no_query_string():
    from agents.core import hub_update

    line = hub_update.clean_line("From https://owner:p@ss@w0rd@github.example.org/o/r?token=abc&x=1 done")
    assert line == "From https://github.example.org/o/r?[redacted] done"
    assert "w0rd" not in line and "abc" not in line


def test_nit_git_gets_no_hub_secret(monkeypatch):
    from agents.core import hub_update

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "hub-secret-token")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.sshCommand=evil'")
    env = hub_update._git_env()
    assert "TELEGRAM_BOT_TOKEN" not in env and "GIT_CONFIG_PARAMETERS" not in env
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "protocol.ext.allow=never" in hub_update._git_argv("fetch")


def test_m3_an_overlong_name_is_a_400(env, client):
    name = "é" * 200        # 200 characters, 400 bytes
    up = client.put("/api/files/upload", headers=ADMIN, params={"root": env.root, "name": name}, content=b"x")
    assert up.status_code == 400 and up.json()["error"] == "bad_name"
    read = client.get("/api/files/read", headers=ADMIN, params={"root": env.root, "path": name})
    assert read.status_code == 400


def test_nit_rename_card_is_marked_irreversible_and_listing_is_bounded(env, client, monkeypatch):
    task_id = client.post("/api/files/rename", headers=ADMIN,
                          json={"root": env.root, "path": "notes.txt", "new_name": "n2.txt"}).json()["pending"]
    assert env.queue.get(task_id).payload["preview"]["irreversible"] is True
    monkeypatch.setattr(fb, "MAX_SCAN_ENTRIES", 3)
    body = client.get("/api/files/list", headers=ADMIN, params={"root": env.root}).json()
    assert body["truncated"] is True and len(body["entries"]) + body["hidden"] <= 3


def test_nit_a_stale_upload_part_is_swept_when_listed(env, client):
    import time

    stale = env.approved / ".nerva-upload-0123.part"
    stale.write_bytes(b"half")
    old = time.time() - 2 * 86400
    os.utime(stale, (old, old))
    fresh = env.approved / ".nerva-upload-4567.part"
    fresh.write_bytes(b"in flight")
    client.get("/api/files/list", headers=ADMIN, params={"root": env.root})
    assert not stale.exists() and fresh.exists()


def test_nit_a_download_that_shrinks_aborts_and_one_that_grows_stops_at_its_size(env):
    target = env.approved / "grow.txt"
    target.write_bytes(b"a" * 100)
    download = fb.prepare_download(env.root, "grow.txt")
    with open(target, "ab") as fh:
        fh.write(b"b" * 100)
    assert b"".join(download.chunks()) == b"a" * 100
    shrink = fb.prepare_download(env.root, "grow.txt")
    os.truncate(target, 10)
    with pytest.raises(fb.DownloadChanged):
        b"".join(shrink.chunks())
    swap = fb.prepare_download(env.root, "notes.txt")
    (env.approved / "notes.txt").unlink()
    (env.approved / "notes.txt").write_text("a new file under the old name", encoding="utf-8")
    assert b"".join(swap.chunks()) == b"hello owner\n"    # the checked descriptor, not the new file
