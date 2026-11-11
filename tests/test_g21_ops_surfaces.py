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
