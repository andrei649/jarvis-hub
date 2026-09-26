"""H218 — archived chats: put a conversation away, bring it back, delete it for good.

An archive stamp in the session's metadata takes it out of ``GET /sessions`` and into
``GET /sessions?archived=true``; resuming it brings it back. ``memory.auto_archive_days``
archives idle chats daily. A permanent delete (admin, ``?confirm=DELETE``) writes a
backup of every trace of the session first — fsynced and read back — and deletes nothing
when that backup did not land; the session in use cannot be deleted.
``llm.project_dir`` sets the directory H594 reads a project's convention files from.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import session_archive as sa
from agents.core.checkpoint import CheckpointManager
from agents.core.todo_tool import TodoStore

T0 = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


@pytest.fixture
def cp(tmp_path):
    manager = CheckpointManager(str(tmp_path / "checkpoints.db"))
    manager.initialize()
    yield manager
    manager.close() if hasattr(manager, "close") else None


def _session(cp, sid, *, started, ended=None, meta=None):
    cp.create_session_record(sid, "jarvis", meta or {})
    with cp._lock:
        cp._conn.execute("UPDATE sessions SET started_at=?, ended_at=? WHERE id=?", (started, ended, sid))
        cp._conn.commit()


def _meta(cp, sid):
    return json.loads(cp.session_row(sid)["metadata"] or "{}")


# ── the archive flag ─────────────────────────────────────────────────────────────

def test_archiving_takes_a_session_out_of_the_list_and_back(cp):
    _session(cp, "s-old", started="2026-09-01T00:00:00+00:00")
    _session(cp, "s-new", started="2026-09-20T00:00:00+00:00", meta={"title": "Brasov"})
    assert [r["id"] for r in cp.get_sessions()] == ["s-new", "s-old"]
    assert cp.set_archived("s-new", True, at="2026-09-26T00:00:00+00:00") is True
    assert _meta(cp, "s-new") == {"title": "Brasov", "archived_at": "2026-09-26T00:00:00+00:00"}
    assert [r["id"] for r in cp.get_sessions(archived=False)] == ["s-old"]
    assert [r["id"] for r in cp.get_sessions(archived=True)] == ["s-new"]
    assert [r["id"] for r in cp.get_sessions()] == ["s-new", "s-old"]          # existing callers see all
    assert cp.set_archived("s-new", False) is True
    assert _meta(cp, "s-new") == {"title": "Brasov"}
    assert cp.get_sessions(archived=True) == []


def test_archiving_stamps_now_by_default_and_never_creates_a_session(cp):
    _session(cp, "s", started="2026-09-01T00:00:00+00:00")
    cp.set_archived("s", True)
    stamp = datetime.fromisoformat(_meta(cp, "s")["archived_at"])
    assert abs((datetime.now(UTC) - stamp).total_seconds()) < 60
    assert cp.set_archived("nope", True) is False and cp.session_row("nope") is None


@pytest.mark.parametrize("raw", ["not json", "[1]", None, ""])
def test_a_broken_metadata_row_is_listed_as_unarchived_and_can_be_archived(cp, raw):
    _session(cp, "s", started="2026-09-01T00:00:00+00:00")
    with cp._lock:
        cp._conn.execute("UPDATE sessions SET metadata=? WHERE id='s'", (raw,))
        cp._conn.commit()
    assert [r["id"] for r in cp.get_sessions(archived=False)] == ["s"]
    assert cp.set_archived("s", True, at="x") is True and _meta(cp, "s") == {"archived_at": "x"}
    assert [r["id"] for r in cp.get_sessions(archived=True)] == ["s"]


def test_the_limit_counts_only_the_view_asked_for(cp):
    for i in range(5):
        _session(cp, f"a{i}", started=f"2026-09-2{i}T00:00:00+00:00")
        cp.set_archived(f"a{i}", True)
    _session(cp, "live", started="2026-09-01T00:00:00+00:00")
    assert [r["id"] for r in cp.get_sessions(limit=2, archived=False)] == ["live"]
    assert [r["id"] for r in cp.get_sessions(limit=2, archived=True)] == ["a4", "a3"]


def test_no_connection_answers_empty(tmp_path):
    cold = CheckpointManager(str(tmp_path / "x.db"))
    assert cold.get_sessions(archived=True) == [] and cold.set_archived("s", True) is False
    assert cold.stale_sessions("2030") == [] and cold.session_row("s") is None
    assert cold.session_rows_for_backup("s") == {"session": None, "checkpoints": [], "clock": None}
    assert cold.delete_session_rows("s") == {"checkpoints": 0, "session_clock": 0, "sessions": 0}


# ── auto-archive ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,days", [
    (0, 0), (7, 7), ("30", 30), (-1, 0), (3650, 3650), (3651, 0), (True, 0), ("x", 0), (None, 0), (2.9, 2),
])
def test_the_setting_is_a_whole_number_of_days_or_off(value, days):
    assert sa.auto_archive_days(value) == days


def test_idle_sessions_are_archived_and_the_active_one_never(cp):
    _session(cp, "idle", started=(T0 - timedelta(days=40)).isoformat(), ended=(T0 - timedelta(days=31)).isoformat())
    _session(cp, "active", started=(T0 - timedelta(days=60)).isoformat())
    _session(cp, "recent", started=(T0 - timedelta(days=40)).isoformat(), ended=(T0 - timedelta(days=29)).isoformat())
    _session(cp, "never", started=None)
    _session(cp, "done", started=(T0 - timedelta(days=90)).isoformat())
    cp.set_archived("done", True, at="earlier")
    got = sa.run_auto_archive(cp, 30, active="active", now=T0)
    assert got == ["idle"]
    assert _meta(cp, "idle")["archived_at"] == T0.isoformat()
    assert _meta(cp, "done")["archived_at"] == "earlier"                         # left as it was
    assert sa.run_auto_archive(cp, 0, now=T0) == [] and sa.run_auto_archive(None, 30, now=T0) == []
    assert cp.stale_sessions((T0 - timedelta(days=30)).isoformat()) == ["active"]


def test_the_stale_list_is_oldest_first_and_bounded(cp):
    for i in range(4):
        _session(cp, f"s{i}", started=(T0 - timedelta(days=100 - i)).isoformat())
    assert cp.stale_sessions(T0.isoformat(), limit=2) == ["s0", "s1"]


async def test_the_scheduler_runs_it_only_when_set(cp, monkeypatch):
    from agents.core.scheduler_service import SchedulerService

    _session(cp, "idle", started=(datetime.now(UTC) - timedelta(days=40)).isoformat())
    settings = {"memory.auto_archive_days": 0}
    orch = SimpleNamespace(checkpoints=cp, session_id="other",
                           get_setting=lambda key, default=None: settings.get(key, default))
    svc = SchedulerService.__new__(SchedulerService)
    svc._orch = orch
    assert await svc.run_auto_archive() == {"_scheduler_status": "skipped"}
    settings["memory.auto_archive_days"] = 30
    assert await svc.run_auto_archive() == {"archived": 1}
    orch.checkpoints = SimpleNamespace(stale_sessions=lambda before: 1 / 0)
    assert await svc.run_auto_archive() == {"_scheduler_status": "failed"}


def test_the_job_is_scheduled_daily():
    from agents.core import scheduler_service

    src = inspect.getsource(scheduler_service.SchedulerService)
    assert 'sched.add_job(self.run_auto_archive, "cron", hour=3, minute=40,' in src
    assert 'id="session-auto-archive"' in src
    assert "self.schedule_auto_archive()" in inspect.getsource(scheduler_service.SchedulerService.__init__) or \
        "self.schedule_auto_archive()" in src


# ── delete for good ──────────────────────────────────────────────────────────────

@pytest.fixture
def stores(cp, tmp_path, monkeypatch):
    from agents.core.memory import persistence

    mem = tmp_path / "mem"
    mem.mkdir()
    monkeypatch.setattr(persistence, "MEMORY_DIR", mem)
    _session(cp, "gone", started="2026-09-01T00:00:00+00:00", meta={"title": "Old chat"})
    with cp._lock:
        cp._conn.execute("INSERT INTO checkpoints (agent_id, session_id, state, data, created_at)"
                         " VALUES ('jarvis', 'gone', '{}', '{}', 'now')")
        cp._conn.commit()
    (mem / "gone.json").write_text(json.dumps({"session_id": "gone", "turns": [{"role": "user", "content": "hi"}]}),
                                   encoding="utf-8")
    (mem / "gone.jsonl").write_text('{"role": "user", "content": "hi"}\n\nnot json\n', encoding="utf-8")
    archive_root = tmp_path / "arch"
    from agents.core.memory.precompress import TranscriptArchive

    arch = TranscriptArchive(archive_root).path_for("gone")
    arch.parent.mkdir(parents=True, exist_ok=True)
    arch.write_text('{"role": "assistant", "text": "old"}\n', encoding="utf-8")
    todos = TodoStore()
    todos.write("gone", [{"id": "1", "content": "x", "status": "pending"}]) if hasattr(todos, "write") else None
    return SimpleNamespace(mem=mem, arch=arch, archive_root=archive_root, todos=todos, backup=tmp_path / "bk")


class _Conv:
    def __init__(self):
        self.cleared = []

    async def clear(self, sid=None):
        self.cleared.append(sid)


async def test_a_delete_backs_up_every_trace_first_then_removes_them(cp, stores):
    conv = _Conv()
    got = await sa.delete_session("gone", checkpoints=cp, memory=conv, todos=stores.todos, active="other",
                                  backup_root=stores.backup, archive_root=stores.archive_root)
    backup = Path(got["backup"])
    assert got["ok"] is True and got["session"] == "gone" and backup.parent == stores.backup
    assert backup.name.startswith("gone-") and backup.suffix == ".json"
    record = json.loads(backup.read_text(encoding="utf-8"))
    assert record["session"]["id"] == "gone" and json.loads(record["session"]["metadata"])["title"] == "Old chat"
    assert len(record["checkpoints"]) == 1
    assert record["snapshot"]["turns"] == [{"role": "user", "content": "hi"}]
    assert record["log"] == [{"role": "user", "content": "hi"}, "not json"]
    assert record["compaction_archive"] == [{"role": "assistant", "text": "old"}]
    assert (backup.stat().st_mode & 0o777) == 0o600
    assert got["removed"]["rows"] == {"checkpoints": 1, "session_clock": 0, "sessions": 1}
    assert got["removed"]["snapshot"] is True and got["removed"]["log"] is True and got["removed"]["compaction_archive"] is True
    assert cp.session_row("gone") is None
    assert not (stores.mem / "gone.json").exists() and not (stores.mem / "gone.jsonl").exists()
    assert not stores.arch.exists() and conv.cleared == ["gone"]
    assert list(stores.backup.glob(".session-*")) == []


async def test_the_session_in_use_cannot_be_deleted(cp, stores):
    with pytest.raises(sa.SessionDeleteError) as err:
        await sa.delete_session("gone", checkpoints=cp, active="gone", backup_root=stores.backup,
                                archive_root=stores.archive_root)
    assert err.value.reason == "active_session" and cp.session_row("gone") is not None
    assert not stores.backup.exists()


async def test_an_unknown_session_is_not_found(cp, stores):
    with pytest.raises(sa.SessionDeleteError) as err:
        await sa.delete_session("nobody", checkpoints=cp, backup_root=stores.backup, archive_root=stores.archive_root)
    assert err.value.reason == "not_found"


async def test_a_session_known_only_from_its_transcript_is_found(cp, stores):
    (stores.mem / "orphan.jsonl").write_text('{"role": "user", "content": "x"}\n', encoding="utf-8")
    got = await sa.delete_session("orphan", checkpoints=cp, backup_root=stores.backup, archive_root=stores.archive_root)
    assert got["removed"]["log"] is True and got["removed"]["snapshot"] is False


async def test_a_backup_that_does_not_land_deletes_nothing(cp, stores, monkeypatch):
    monkeypatch.setattr(sa.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(sa.SessionDeleteError) as err:
        await sa.delete_session("gone", checkpoints=cp, backup_root=stores.backup, archive_root=stores.archive_root)
    assert err.value.reason == "backup_failed"
    assert cp.session_row("gone") is not None and (stores.mem / "gone.json").exists() and stores.arch.exists()
    assert list(stores.backup.glob("*")) == []                       # the half-written temp is gone


async def test_a_backup_that_does_not_read_back_deletes_nothing(cp, stores, monkeypatch):
    real = Path.read_text

    def lying(self, *a, **kw):
        text = real(self, *a, **kw)
        return text.replace('"session_id": "gone"', '"session_id": "other"') if self.parent == stores.backup else text
    monkeypatch.setattr(Path, "read_text", lying)
    with pytest.raises(sa.SessionDeleteError) as err:
        await sa.delete_session("gone", checkpoints=cp, backup_root=stores.backup, archive_root=stores.archive_root)
    assert err.value.reason == "backup_failed" and cp.session_row("gone") is not None


def test_the_backup_lands_in_the_data_home_by_default():
    assert sa.BACKUP_DIR == ("backups", "sessions") and sa.CONFIRM == "DELETE"
    src = inspect.getsource(sa.delete_session)
    assert "data_path(*BACKUP_DIR)" in src


def test_todo_forget_drops_one_plan():
    store = TodoStore()
    store.apply("a", [{"id": "1", "content": "x", "status": "pending"}], False)
    store.apply("b", [{"id": "1", "content": "y", "status": "pending"}], False)
    assert store.forget("a") is True and store.forget("a") is False
    assert [p["session_id"] for p in store.recent()] == ["b"]


# ── routes ───────────────────────────────────────────────────────────────────────

def _client(monkeypatch, orch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import sessions as route

    monkeypatch.setattr(route, "get_orch", lambda: orch)
    return TestClient(web.app)


def test_the_list_route_hides_archived_chats_unless_asked(cp, monkeypatch):
    _session(cp, "kept", started="2026-09-01T00:00:00+00:00")
    _session(cp, "away", started="2026-09-02T00:00:00+00:00")
    cp.set_archived("away", True, at="2026-09-03T00:00:00+00:00")
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    main = client.get("/sessions").json()["sessions"]
    assert [s["id"] for s in main] == ["kept"] and main[0]["archived_at"] is None
    away = client.get("/sessions", params={"archived": "true"}).json()["sessions"]
    assert [(s["id"], s["archived_at"]) for s in away] == [("away", "2026-09-03T00:00:00+00:00")]


def test_the_archive_routes(cp, monkeypatch):
    _session(cp, "s", started="2026-09-01T00:00:00+00:00")
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    got = client.post("/sessions/s/archive")
    assert got.status_code == 200 and got.json() == {"ok": True, "session": "s", "archived": True}
    assert "no-store" in got.headers["Cache-Control"]
    assert _meta(cp, "s").get("archived_at")
    assert client.post("/sessions/s/unarchive").json()["archived"] is False and "archived_at" not in _meta(cp, "s")
    assert client.post("/sessions/nope/archive").status_code == 404
    assert client.post("/sessions/bad%20id/archive").status_code == 400
    assert _client(monkeypatch, None).post("/sessions/s/archive").status_code == 503


async def test_the_delete_route(cp, stores, monkeypatch):
    from agents.core import todo_tool
    from agents.core.routers import sessions as route

    orch = SimpleNamespace(checkpoints=cp, memory=SimpleNamespace(conversation=_Conv()), session_id="live")
    monkeypatch.setattr(route, "get_orch", lambda: orch)
    monkeypatch.setattr(sa, "BACKUP_DIR", (str(stores.backup),))
    unconfirmed = await route.delete_session("gone", confirm="")
    assert unconfirmed.status_code == 400 and json.loads(unconfirmed.body)["reason"] == "confirm_required"
    assert (await route.delete_session("bad id", confirm="DELETE")).status_code == 400
    live = await route.delete_session("live", confirm="DELETE")
    assert live.status_code == 409 and json.loads(live.body)["reason"] == "active_session"
    assert (await route.delete_session("nobody", confirm="DELETE")).status_code == 404
    todo_tool.TODOS.apply("gone", [{"id": "1", "content": "x", "status": "pending"}], False)
    done = await route.delete_session("gone", confirm="DELETE")
    body = json.loads(done.body)
    assert done.status_code == 200 and body["ok"] is True and body["removed"]["todo"] is True
    assert cp.session_row("gone") is None and orch.memory.conversation.cleared == ["gone"]
    monkeypatch.setattr(route, "get_orch", lambda: None)
    assert (await route.delete_session("gone", confirm="DELETE")).status_code == 503


async def test_a_failed_backup_answers_500(cp, stores, monkeypatch):
    from agents.core.routers import sessions as route

    orch = SimpleNamespace(checkpoints=cp, memory=SimpleNamespace(conversation=_Conv()), session_id="live")
    monkeypatch.setattr(route, "get_orch", lambda: orch)
    monkeypatch.setattr(sa, "BACKUP_DIR", (str(stores.backup),))
    monkeypatch.setattr(sa.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk full")))
    got = await route.delete_session("gone", confirm="DELETE")
    assert got.status_code == 500 and json.loads(got.body)["reason"] == "backup_failed"


def test_the_delete_route_is_admin_only_and_archive_is_the_owners():
    from agents.core.routers import sessions as route

    routes = {(r.path, tuple(sorted(r.methods))): r for r in route.router.routes}
    names = lambda r: [d.call.__name__ for d in r.dependant.dependencies]  # noqa: E731
    assert names(routes[("/sessions/{session_id}", ("DELETE",))]) == ["admin_guard"]
    assert names(routes[("/sessions/{session_id}/archive", ("POST",))]) == ["user_guard"]
    assert names(routes[("/sessions/{session_id}/unarchive", ("POST",))]) == ["user_guard"]


async def test_resuming_an_archived_chat_brings_it_back(cp, monkeypatch):
    from agents.core.routers import sessions as route

    _session(cp, "s", started="2026-09-01T00:00:00+00:00")
    cp.set_archived("s", True)

    async def resume(sid):
        return True

    async def history(sid):
        return []
    orch = SimpleNamespace(checkpoints=cp, memory=SimpleNamespace(resume_session=resume, get_history=history))
    client = _client(monkeypatch, orch)
    assert client.post("/sessions/resume", json={"session_id": "s"}).status_code == 200
    assert "archived_at" not in _meta(cp, "s")


# ── settings and the default project directory ──────────────────────────────────

def test_the_settings_are_declared():
    from agents.core.settings_db import DEFAULTS

    rows = {(r["category"], r["key"]): r for r in DEFAULTS}
    assert rows[("memory", "auto_archive_days")]["value"] == 0 and rows[("memory", "auto_archive_days")]["kind"] == "number"
    assert rows[("llm", "project_dir")]["value"] == "" and rows[("llm", "project_dir")]["kind"] == "text"
    assert sa.SETTING_AUTO_DAYS == "memory.auto_archive_days"


def test_the_default_project_directory_is_where_convention_files_are_read(tmp_path, monkeypatch):
    from agents.core import project_context as pc
    from agents.core.file_tools import FileScope

    root = tmp_path / "work"
    proj = root / "proj"
    (proj / ".git").mkdir(parents=True)
    (proj / "AGENTS.md").write_text("proj rules\n", encoding="utf-8")
    scope = FileScope([root])
    monkeypatch.delenv("JARVIS_SAFE_MODE", raising=False)
    assert pc.start_dir(scope, str(proj)) == proj
    assert pc.start_dir(scope, "proj") == proj                         # relative to the first root
    assert pc.start_dir(scope, "") == root and pc.start_dir(scope, None) == root
    assert pc.start_dir(scope, str(tmp_path)) == root                  # outside the roots: the root
    assert pc.start_dir(scope, str(proj / "AGENTS.md")) == root        # not a folder
    assert pc.start_dir(scope, "  ") == root
    assert "proj rules" in pc.build_turn("s", scope=scope, workdir=str(proj)).block
    assert pc.build_turn("s", scope=scope).block == ""


async def test_the_orchestrator_passes_the_setting(tmp_path, monkeypatch):
    from agents.core import project_context as pc
    from agents.core.orchestrator import _begin_project_context

    seen = {}

    def fake(session, *, setting=None, workdir=None):
        seen.update(session=session, workdir=workdir, on=setting("k", None))
        return None
    monkeypatch.setattr(pc, "build_turn", fake)
    settings = {"llm.project_dir": "proj"}
    owner = SimpleNamespace(session_id="s1", get_setting=lambda key, default=None: settings.get(key, default))
    await _begin_project_context(owner)
    assert seen == {"session": "s1", "workdir": "proj", "on": True}
    settings["llm.project_context_files"] = False
    await _begin_project_context(owner)
    assert seen["workdir"] == "" and seen["on"] is False
    token = pc.bind()
    pc.reset(token)
    assert asyncio.iscoroutinefunction(_begin_project_context)
