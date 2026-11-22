"""Dashboard API contract against the Nerva-scoped Hermes SQLite port."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from agents.core.kanban import dashboard_api, dispatch_store, dispatcher
from agents.core.kanban.context import KanbanContext, kanban_scope
from agents.core.kanban.dispatcher import KanbanDispatcher
from agents.core.kanban.upstream import kanban_db as kb
from agents.core.kanban.upstream import projects_db as pdb


def _client(home: Path, *, board: str = "default", mutate: bool = True):
    app = FastAPI()

    async def scope():
        with kanban_scope(KanbanContext(home=home, profile="owner", board=board, can_mutate=mutate)):
            yield

    app.include_router(dashboard_api.router, prefix="/api/kanban", dependencies=[Depends(scope)])
    return TestClient(app)


def test_active_workers_includes_two_current_native_runs_and_excludes_stale_runs(tmp_path, monkeypatch):
    client = _client(tmp_path)
    controller = KanbanDispatcher(SimpleNamespace(), home=tmp_path)

    def claimed(title, locks: ExitStack, *, release=False):
        task_id = client.post("/api/kanban/tasks", json={"title": title, "assignee": title,
                                                           "triage": True}).json()["task"]["id"]
        assert client.patch(f"/api/kanban/tasks/{task_id}", json={"status": "ready"}).status_code == 200
        with kanban_scope(KanbanContext(tmp_path, "dispatcher", can_mutate=True)), kb.connect_closing() as conn:
            dispatch_store.initialize(conn)
            record = dispatch_store.prepare(conn, kb.get_task(conn, task_id))
            identity = controller._attempt_lock(record["id"])
            proof = locks.enter_context(identity) if not release else None
            if release:
                with identity as proof:
                    pass
            with kb.write_txn(conn):
                run_id = kb._claim_and_open_run(conn, task_id, "ready", "nerva:" + record["id"],
                                                int(time.time()) + 3600, int(time.time()))
                conn.execute("UPDATE nerva_dispatches SET state='running', run_id=?, recovery_dev=?, "
                             "recovery_ino=?, recovery_pid=? WHERE id=?", (run_id, *proof, record["id"]))
        return task_id, run_id

    with ExitStack() as locks:
        one, first_run = claimed("Frigga", locks)
        two, second_run = claimed("Ultron", locks)
        stale, _ = claimed("stopped", locks, release=True)
        orphan, _ = claimed("orphan", locks)
        ended, ended_run = claimed("ended", locks)
        with (kanban_scope(KanbanContext(tmp_path, "dispatcher", can_mutate=True)),
              kb.connect_closing() as conn, kb.write_txn(conn)):
            conn.execute("UPDATE tasks SET current_run_id=NULL WHERE id=?", (orphan,))
            conn.execute("UPDATE task_runs SET ended_at=? WHERE id=?", (int(time.time()), ended_run))
        workers = client.get("/api/kanban/workers/active")
        assert workers.status_code == 200, workers.text
        rows = workers.json()["workers"]
        assert {row["task_id"] for row in rows} == {one, two}
        assert {row["run_id"] for row in rows} == {first_run, second_run}
        assert workers.json()["count"] == 2
        assert all(row["worker_pid"] is None for row in rows)
        with kanban_scope(KanbanContext(tmp_path, "owner")), kb.connect_closing() as conn:
            current = dict(conn.execute("SELECT * FROM nerva_dispatches WHERE run_id=?", (first_run,)).fetchone())
            stopped = dict(conn.execute("SELECT * FROM nerva_dispatches WHERE task_id=?", (stale,)).fetchone())
        with (dispatcher._probe_attempt_receipt(tmp_path, current, observer=True) as first,
              dispatcher._probe_attempt_receipt(tmp_path, current, observer=True) as second):
            assert (first, second) == ("held", "held")
        with (dispatcher._probe_attempt_receipt(tmp_path, stopped, observer=True) as first,
              dispatcher._probe_attempt_receipt(tmp_path, stopped, observer=True) as second):
            assert (first, second) == ("released", "released")

        original_probe = dispatcher._probe_attempt_receipt

        @contextmanager
        def unreadable(*_args, **_kwargs):
            yield "unverifiable"

        monkeypatch.setattr(dispatcher, "_probe_attempt_receipt", unreadable)
        assert client.get("/api/kanban/workers/active").status_code == 503

        @contextmanager
        def finishes_during_probe(home, record, *, observer=False):
            if record["task_id"] == one:
                with (kanban_scope(KanbanContext(tmp_path, "dispatcher", can_mutate=True)),
                      kb.connect_closing() as conn, kb.write_txn(conn)):
                    conn.execute("UPDATE task_runs SET ended_at=?, status='done' WHERE id=?",
                                 (int(time.time()), first_run))
                    conn.execute("UPDATE tasks SET status='done', current_run_id=NULL WHERE id=?", (one,))
                yield "unverifiable"
            else:
                with original_probe(home, record, observer=observer) as status:
                    yield status

        monkeypatch.setattr(dispatcher, "_probe_attempt_receipt", finishes_during_probe)
        after_finish = client.get("/api/kanban/workers/active")
        assert after_finish.status_code == 200, after_finish.text
        assert {row["task_id"] for row in after_finish.json()["workers"]} == {two}


def test_active_workers_keeps_current_legacy_pid_run_with_old_or_missing_native_table(tmp_path):
    client = _client(tmp_path)
    task_id = client.post("/api/kanban/tasks", json={"title": "legacy", "assignee": "legacy",
                                                       "triage": True}).json()["task"]["id"]
    assert client.patch(f"/api/kanban/tasks/{task_id}", json={"status": "ready"}).status_code == 200
    with (kanban_scope(KanbanContext(tmp_path, "owner", can_mutate=True)),
          kb.connect_closing() as conn, kb.write_txn(conn)):
        run_id = kb._claim_and_open_run(conn, task_id, "ready", "legacy-claim",
                                        int(time.time()) + 3600, int(time.time()))
        conn.execute("UPDATE task_runs SET worker_pid=? WHERE id=?", (os.getpid(), run_id))
    with kanban_scope(KanbanContext(tmp_path, "owner", can_mutate=True)), kb.connect_closing() as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='nerva_dispatches'").fetchone() is None
    workers = client.get("/api/kanban/workers/active")
    assert workers.status_code == 200, workers.text
    assert workers.json()["count"] == 1
    assert workers.json()["workers"][0]["task_id"] == task_id
    assert workers.json()["workers"][0]["worker_pid"] == os.getpid()
    with kanban_scope(KanbanContext(tmp_path, "owner", can_mutate=True)), kb.connect_closing() as conn:
        conn.execute("CREATE TABLE nerva_dispatches (id TEXT PRIMARY KEY, task_id TEXT, "
                     "run_id INTEGER, state TEXT)")
        conn.commit()
    historical = client.get("/api/kanban/workers/active")
    assert historical.status_code == 200, historical.text
    assert historical.json()["workers"] == workers.json()["workers"]


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
    assert client.post(f"/api/kanban/tasks/{task_id}/reclaim", json={}).status_code == 422
    assert client.post("/api/kanban/boards/import", json={"archive": "/tmp/archive.tar.gz"}).status_code == 503
    assert client.get("/api/kanban/model-options").status_code == 503
    assert _client(tmp_path, mutate=False).post("/api/kanban/tasks", json={"title": "denied"}).status_code == 403
    app = FastAPI()
    app.include_router(dashboard_api.router, prefix="/api/kanban")
    assert TestClient(app).get("/api/kanban/board").status_code == 403


def test_links_review_runs_bulk_and_signed_dispatch(tmp_path, monkeypatch):
    client = _client(tmp_path)
    parent = client.post("/api/kanban/tasks", json={"title": "Parent", "triage": True}).json()["task"]["id"]
    child = client.post("/api/kanban/tasks", json={"title": "Child", "assignee": "frigga",
                                                       "triage": True}).json()["task"]["id"]
    linked = client.post("/api/kanban/links", json={"parent_id": parent, "child_id": child})
    assert linked.status_code == 200, linked.text
    assert client.get(f"/api/kanban/tasks/{child}").json()["links"]["parents"] == [parent]
    assert client.get(f"/api/kanban/tasks/{parent}").json()["child_results"][0]["assignee"] == "frigga"
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


def test_recover_uses_the_reviewed_run_and_board(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agents.core.kanban.context import require_mutation

    client = _client(tmp_path)
    assert client.post("/api/kanban/boards", json={"slug": "studio", "name": "Studio"}).is_success
    task_id = client.post("/api/kanban/tasks?board=studio", json={"title": "Render", "triage": True}).json()["task"]["id"]
    url = f"/api/kanban/tasks/{task_id}/reclaim?board=studio"
    calls = []
    result = {"ok": False, "reason": "active_attempt"}

    async def recover(task_id, *, board, expected_run_id, reason):
        scope = require_mutation()
        calls.append((task_id, board, expected_run_id, reason, scope.board, scope.profile))
        return result

    adapter = SimpleNamespace(recover_interrupted=recover)
    orch = SimpleNamespace(_autonomy=SimpleNamespace(kanban_dispatcher=lambda: adapter))
    monkeypatch.setattr(dashboard_api, "get_orch", lambda: orch)
    for invalid_id in (True, "2", 0, -1):
        assert client.post(url, json={"expected_run_id": invalid_id}).status_code == 422
    assert not calls
    refused = client.post(url, json={"expected_run_id": 2, "reason": "Hub restarted"})
    assert refused.status_code == 409
    assert "active" in refused.json()["detail"].lower()
    assert calls == [(task_id, "studio", 2, "Hub restarted", "studio", "owner")]
    assert _client(tmp_path, mutate=False).post(url, json={"expected_run_id": 2}).status_code == 403
    assert len(calls) == 1
    for why, code, message in (("owner_required", 403, "owner"),
                               ("recovery_busy", 409, "in progress"),
                               ("replaced_attempt", 409, "newer")):
        result["reason"] = why
        response = client.post(url, json={"expected_run_id": 2})
        assert response.status_code == code
        assert message in response.json()["detail"].lower()
    result = {"ok": True, "status": "already_recovered", "task_id": task_id, "run_id": 2}
    assert client.post(url, json={"expected_run_id": 2}).json() == result


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
    assert client.post("/api/kanban/tasks/t_owned/reclaim", json={"expected_run_id": 7}).status_code == 403
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
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(folder), str(replacement)],
                       check=True, capture_output=True)
    else:
        folder.symlink_to(replacement, target_is_directory=True)
    try:
        response = client.get("/api/kanban/projects")
        assert response.status_code == 403, response.text
    finally:
        assert root.resolve().is_relative_to(tmp_path.resolve())
        assert folder.parent.resolve() == root.resolve()
        if sys.platform == "win32":
            assert folder.is_junction()
            folder.rmdir()
        else:
            assert folder.is_symlink()
            folder.unlink()
    folder.mkdir()
    monkeypatch.setenv("JARVIS_FILE_ROOTS", str(tmp_path / "revoked"))
    response = client.get("/api/kanban/projects")
    assert response.status_code == 403, response.text


def test_dashboard_projects_requires_owner_request_scope(tmp_path):
    app = FastAPI()
    app.include_router(dashboard_api.router, prefix="/api/kanban")
    assert TestClient(app).get("/api/kanban/projects").status_code == 403
