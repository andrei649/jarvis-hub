"""Dashboard API contract against the Nerva-scoped Hermes SQLite port."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from agents.core.kanban import dashboard_api
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.kanban.upstream import projects_db as pdb


def _client(home: Path, *, board: str = "default", mutate: bool = True):
    app = FastAPI()

    async def scope():
        with kanban_scope(KanbanContext(home=home, profile="owner", board=board, can_mutate=mutate)):
            yield

    app.include_router(dashboard_api.router, prefix="/api/kanban", dependencies=[Depends(scope)])
    return TestClient(app)


def test_metadata_lifecycle_and_board_isolation(tmp_path):
    client = _client(tmp_path)
    made = client.post("/api/kanban/tasks", json={"title": "First", "triage": True})
    assert made.status_code == 200, made.text
    task = made.json()["task"]
    assert task["created_by"] == "owner"
    task_id = task["id"]
    assert client.post(f"/api/kanban/tasks/{task_id}/comments", json={"body": "hello", "author": "forged"}).status_code == 422
    assert client.post(f"/api/kanban/tasks/{task_id}/comments", json={"body": "hello"}).status_code == 200
    assert client.get(f"/api/kanban/tasks/{task_id}").json()["comments"][0]["author"] == "owner"
    board = client.post("/api/kanban/boards", json={"slug": "second", "name": "Second"})
    assert board.status_code == 200, board.text
    assert client.get(f"/api/kanban/tasks/{task_id}?board=second").status_code == 404
    second = client.post("/api/kanban/tasks?board=second", json={"title": "Other", "triage": True})
    assert second.status_code == 200, second.text
    assert second.json()["task"]["id"] != task_id
    assert client.get("/api/kanban/board").json()["columns"][0]["tasks"][0]["id"] == task_id


def test_upload_cap_and_forged_path_refused(tmp_path):
    client = _client(tmp_path)
    task_id = client.post("/api/kanban/tasks", json={"title": "file", "triage": True}).json()["task"]["id"]
    sent = client.post(f"/api/kanban/tasks/{task_id}/attachments", files={"file": ("note.txt", b"abc")})
    assert sent.status_code == 200, sent.text
    attachment_id = sent.json()["attachment"]["id"]
    assert client.get(f"/api/kanban/attachments/{attachment_id}").content == b"abc"
    external = tmp_path.parent / (tmp_path.name + "-private")
    external.write_text("secret")
    with kanban_scope(KanbanContext(home=tmp_path, profile="owner", can_mutate=True)), kb.connect_closing() as conn:
        conn.execute("UPDATE task_attachments SET stored_path = ? WHERE id = ?", (str(external), attachment_id))
        conn.commit()
    assert client.get(f"/api/kanban/attachments/{attachment_id}").status_code == 404
    assert client.delete(f"/api/kanban/attachments/{attachment_id}").status_code == 404
    assert external.read_text() == "secret"
    too_big = client.post(f"/api/kanban/tasks/{task_id}/attachments", files={"file": ("large", b"x" * (25 * 1024 * 1024 + 1))})
    assert too_big.status_code == 413
    forged = client.post(f"/api/kanban/tasks/{task_id}/attachments",
                         files={"file": ("note.txt", b"hi")}, data={"uploaded_by": "forged"})
    assert forged.status_code == 400


def test_unbound_effects_and_scope(tmp_path):
    client = _client(tmp_path)
    task_id = client.post("/api/kanban/tasks", json={"title": "safe", "triage": True}).json()["task"]["id"]
    assert client.post("/api/kanban/tasks", json={"title": "unsafe", "workspace_kind": "worktree"}).status_code == 400
    assert client.post("/api/kanban/tasks", json={"title": "goal", "goal_mode": True}).status_code == 503
    assert client.post(f"/api/kanban/tasks/{task_id}/specify", json={}).status_code == 503
    assert client.post(f"/api/kanban/tasks/{task_id}/reclaim", json={}).status_code == 503
    assert client.post("/api/kanban/boards/import", json={"archive": "/tmp/archive.tar.gz"}).status_code == 503
    assert client.get("/api/kanban/model-options").status_code == 503
    assert _client(tmp_path, mutate=False).post("/api/kanban/tasks", json={"title": "denied"}).status_code == 403
    app = FastAPI()
    app.include_router(dashboard_api.router, prefix="/api/kanban")
    assert TestClient(app).get("/api/kanban/board").status_code == 403


def test_links_review_runs_bulk_and_signed_dispatch(tmp_path, monkeypatch):
    client = _client(tmp_path)
    parent = client.post("/api/kanban/tasks", json={"title": "Parent", "triage": True}).json()["task"]["id"]
    child = client.post("/api/kanban/tasks", json={"title": "Child", "triage": True}).json()["task"]["id"]
    linked = client.post("/api/kanban/links", json={"parent_id": parent, "child_id": child})
    assert linked.status_code == 200, linked.text
    assert client.get(f"/api/kanban/tasks/{child}").json()["links"]["parents"] == [parent]
    blocked = client.patch(f"/api/kanban/tasks/{child}", json={"status": "ready"})
    assert blocked.status_code == 409
    assert client.patch(f"/api/kanban/tasks/{parent}", json={"status": "ready"}).status_code == 200
    reviewed = client.patch(f"/api/kanban/tasks/{parent}", json={"status": "review", "summary": "Please check"})
    assert reviewed.status_code == 200, reviewed.text
    done = client.patch(f"/api/kanban/tasks/{parent}", json={"status": "done"})
    assert done.status_code == 200, done.text
    assert client.get(f"/api/kanban/tasks/{parent}").json()["runs"]
    assert client.patch(f"/api/kanban/tasks/{child}", json={"status": "ready"}).status_code == 200
    bulk = client.post("/api/kanban/tasks/bulk", json={"ids": [child], "priority": 5})
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["results"] == [{"id": child, "ok": True}]

    calls = []

    class Adapter:
        async def request(self, principal, *, board, limit):
            calls.append((principal.channel, principal.admin, board, limit))
            return {"ok": True, "status": "queued", "queued": [{"queue_id": "q1"}]}

    class Autonomy:
        def kanban_dispatcher(self):
            return Adapter()

    class Orch:
        _autonomy = Autonomy()

    monkeypatch.setattr(dashboard_api, "get_orch", lambda: Orch())
    response = client.post("/api/kanban/dispatch?max=2")
    assert response.status_code == 200, response.text
    assert calls == [("web", True, "default", 2)]
    assert client.post("/api/kanban/dispatch?dry_run=true").status_code == 503
    assert client.post("/api/kanban/dispatch?max=17").status_code == 422


def test_event_tail_copies_scope_into_reader_thread(tmp_path):
    import asyncio

    client = _client(tmp_path)
    task_id = client.post("/api/kanban/tasks", json={"title": "Event", "triage": True}).json()["task"]["id"]

    async def read():
        with kanban_scope(KanbanContext(home=tmp_path, profile="owner", can_mutate=True)):
            tail = dashboard_api._EventTail("default")
            try:
                cursor = await tail.latest()
                assert cursor > 0
                new_cursor, rows = await tail.poll(0)
                assert new_cursor >= cursor
                assert any(row["task_id"] == task_id for row in rows)
            finally:
                await tail.shutdown()

    asyncio.run(read())


def test_worker_scope_cannot_use_dashboard(tmp_path):
    app = FastAPI()

    async def worker_scope():
        with kanban_scope(KanbanContext(home=tmp_path, profile="worker", task_id="t_owned",
                                        run_id=7, board="default", can_mutate=True)):
            yield

    app.include_router(dashboard_api.router, prefix="/api/kanban", dependencies=[Depends(worker_scope)])
    client = TestClient(app)
    assert client.get("/api/kanban/board").status_code == 403
    assert client.post("/api/kanban/tasks", json={"title": "unauthorized"}).status_code == 403
    assert client.get("/api/kanban/projects").status_code == 403


def test_dashboard_projects_uses_live_store_and_keeps_homes_separate(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir()
    folder = root / "alpha"
    folder.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    home = tmp_path / "home"
    with kanban_scope(KanbanContext(home=home, profile="owner", can_mutate=True)), pdb.connect_closing() as conn:
        pid = pdb.create_project(conn, name="Alpha", folders=[str(folder)])
        archived = pdb.create_project(conn, name="Archived")
        pdb.archive_project(conn, archived)

    client = _client(home, mutate=False)
    response = client.get("/api/kanban/projects")
    assert response.status_code == 200, response.text
    rows = response.json()["projects"]
    assert [row["id"] for row in rows] == [pid]
    assert rows[0]["primary_path"] == str(folder)
    assert rows[0]["folders"][0]["is_primary"] is True
    with kanban_scope(KanbanContext(home=home, profile="owner", can_mutate=True)), pdb.connect_closing() as conn:
        pdb.update_project(conn, pid, name="Renamed")
    assert client.get("/api/kanban/projects").json()["projects"][0]["name"] == "Renamed"

    other = tmp_path / "other-home"
    response = _client(other, mutate=False).get("/api/kanban/projects")
    assert response.status_code == 200, response.text
    assert response.json() == {"projects": []}
    assert not (other / "projects.db").exists()


def test_dashboard_projects_rejects_revoked_roots_and_symlink_drift(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir()
    folder = root / "alpha"
    folder.mkdir()
    replacement = root / "replacement"
    replacement.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(root))
    home = tmp_path / "home"
    with kanban_scope(KanbanContext(home=home, profile="owner", can_mutate=True)), pdb.connect_closing() as conn:
        pdb.create_project(conn, name="Alpha", primary_path=str(folder))
    client = _client(home)
    folder.rmdir()
    folder.symlink_to(replacement, target_is_directory=True)
    response = client.get("/api/kanban/projects")
    assert response.status_code == 403, response.text
    folder.unlink()
    folder.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path / "revoked"))
    response = client.get("/api/kanban/projects")
    assert response.status_code == 403, response.text


def test_dashboard_projects_requires_owner_request_scope(tmp_path):
    app = FastAPI()
    app.include_router(dashboard_api.router, prefix="/api/kanban")
    assert TestClient(app).get("/api/kanban/projects").status_code == 403
