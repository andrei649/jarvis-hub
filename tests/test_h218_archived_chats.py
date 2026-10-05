"""H218 — archived chats: put a conversation away, bring it back, delete it for good.

An archive stamp in the session's metadata takes it out of ``GET /sessions`` and into
``GET /sessions?archived=true``; resuming it brings it back. ``memory.auto_archive_days``
archives idle chats daily. A permanent delete (admin, ``?confirm=DELETE``) holds the
session's turn lease and the memory locks, writes an encrypted backup of what the hub keeps
under the session's id outside the data root first — fsynced and read back — and deletes
nothing when that backup did not land; the session in use, a busy one and one another chat
continues cannot be deleted. ``llm.project_dir`` sets the directory H594 reads a project's
convention files from.
"""
from __future__ import annotations

import asyncio
import base64
import json
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import session_archive as sa
from agents.core.checkpoint import CheckpointManager
from agents.core.session_files import NON_SESSION_STEMS
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
    assert cold.get_sessions(archived=True) == [] and cold.set_archived("s", True) is None
    assert cold.stale_sessions("2030") == [] and cold.session_row("s") is None
    assert cold.session_rows_for_backup("s") == {"session": None, "checkpoints": [], "clock": None,
                                                 "continuation": None, "history_instance": None,
                                                 "rewind": None,
                                                 "continued_by": []}
    assert cold.delete_session_rows("s") == {"checkpoints": 0, "session_clock": 0, "session_continuations": 0,
                                             "session_history_instances": 0, "session_history_rewinds": 0,
                                             "sessions": 0}


def test_a_store_error_while_archiving_is_not_a_missing_session(cp):
    _session(cp, "s", started="2026-09-01T00:00:00+00:00")
    cp._conn.close()
    assert cp.set_archived("s", True) is None


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


async def test_the_sweep_runs_the_archiver_only_when_set(cp, monkeypatch):
    """H262 — the lifecycle sweep's archive phase replaced the 03:40 job."""
    from agents.core.scheduler_service import SchedulerService

    _session(cp, "idle", started=(datetime.now(UTC) - timedelta(days=40)).isoformat())
    settings = {"memory.auto_archive_days": 0}
    orch = SimpleNamespace(checkpoints=cp, session_id="other",
                           get_setting=lambda key, default=None: settings.get(key, default))
    svc = SchedulerService.__new__(SchedulerService)
    svc._orch = orch
    assert await svc.run_retention_purge() == {"_scheduler_status": "skipped"}
    settings["memory.auto_archive_days"] = 30
    assert (await svc.run_retention_purge())["archived"] == ["idle"]
    settings["retention.min_interval_hours"] = 1
    orch.checkpoints = SimpleNamespace(claim_sweep=lambda *a: True, get_state=lambda name: None,
                                       stale_sessions=lambda before: 1 / 0)
    assert await svc.run_retention_purge() == {"_scheduler_status": "failed"}


def test_no_separate_archive_job_is_scheduled():
    """H262 — one hourly lifecycle job; the 03:40 ``session-auto-archive`` is retired."""
    from agents.core.scheduler_service import SchedulerService

    jobs = []
    sched = SimpleNamespace(add_job=lambda func, trigger, **kw: jobs.append((func, trigger, kw)))
    svc = SchedulerService(SimpleNamespace(heartbeat_scheduler=SimpleNamespace(scheduler=sched)))
    for name in dir(SchedulerService):                   # every other job stays off the fake scheduler
        if name.startswith("schedule_") and name not in {"schedule_all", "schedule_retention"}:
            setattr(svc, name, lambda: None)
    svc.schedule_all()
    assert [kw["id"] for _func, _trigger, kw in jobs] == ["data-retention-sweep"]


# ── delete for good ──────────────────────────────────────────────────────────────

@pytest.fixture
def stores(cp, tmp_path, monkeypatch):
    from agents.core.memory import conversation, persistence

    mem = tmp_path / "mem"
    mem.mkdir()
    monkeypatch.setattr(persistence, "MEMORY_DIR", mem)
    monkeypatch.setattr(conversation, "MEMORY_DIR", mem)             # where a live turn appends its log
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
    todos.write("gone", [{"id": "1", "content": "x", "status": "pending"}])
    return SimpleNamespace(mem=mem, arch=arch, archive_root=archive_root, todos=todos, backup=tmp_path / "bk")


def _conversation(*sids):
    from agents.core.memory.conversation import ConversationMemory

    conv = ConversationMemory(persist=False)
    for sid in sids:
        conv.sessions[sid], conv.instances[sid] = [], f"i-{sid}"
    return conv


async def _delete(cp, stores, sid="gone", **kw):
    return await sa.delete_session(sid, checkpoints=cp, backup_root=stores.backup, archive_root=stores.archive_root, **kw)


async def test_a_delete_backs_up_every_trace_first_then_removes_them(cp, stores, tmp_path):
    from agents.core.notes import NotesStore

    conv = _conversation("gone", "kept")
    notes = NotesStore(tmp_path / "notes.json")
    notes.set("gone", "call the bank")
    got = await _delete(cp, stores, memory=conv, todos=stores.todos, notes=notes, active="other")
    backup = Path(got["backup"])
    assert got["ok"] is True and got["session"] == "gone" and backup.parent == stores.backup
    assert backup.name.startswith("gone-") and backup.name.endswith(".json.enc")
    assert b"Old chat" not in backup.read_bytes() and b"call the bank" not in backup.read_bytes()
    record = sa.read_backup(backup)
    assert record["session"]["id"] == "gone" and json.loads(record["session"]["metadata"])["title"] == "Old chat"
    assert len(record["checkpoints"]) == 1 and record["history_instance"]["session_id"] == "gone"
    assert record["snapshot"]["turns"] == [{"role": "user", "content": "hi"}]
    assert record["log"] == [{"role": "user", "content": "hi"}, "not json"]
    assert record["compaction_archive"] == [{"role": "assistant", "text": "old"}]
    assert [item["content"] for item in record["todo"]["todos"]] == ["x"] and record["note"] == "call the bank"
    assert (backup.stat().st_mode & 0o777) == 0o600
    assert got["removed"]["rows"] == {"checkpoints": 1, "session_clock": 0, "session_continuations": 0,
                                      "session_history_instances": 1, "session_history_rewinds": 0,
                                      "sessions": 1}
    assert got["removed"]["snapshot"] is True and got["removed"]["log"] is True and got["removed"]["compaction_archive"] is True
    assert got["removed"]["todo"] is True and stores.todos.read("gone")["todos"] == []
    assert got["removed"]["note"] is True and notes.get("gone") == ""
    assert cp.session_row("gone") is None
    assert not (stores.mem / "gone.json").exists() and not (stores.mem / "gone.jsonl").exists()
    assert not stores.arch.exists()
    assert "gone" not in conv.sessions and "gone" not in conv.instances and "kept" in conv.sessions
    assert list(stores.backup.glob(".session-*")) == []


async def test_the_session_in_use_cannot_be_deleted(cp, stores):
    with pytest.raises(sa.SessionDeleteError) as err:
        await _delete(cp, stores, active="gone")
    assert err.value.reason == "active_session" and cp.session_row("gone") is not None
    assert not stores.backup.exists()


async def test_an_unknown_session_is_not_found(cp, stores):
    with pytest.raises(sa.SessionDeleteError) as err:
        await _delete(cp, stores, "nobody")
    assert err.value.reason == "not_found"


async def test_a_session_known_only_from_its_transcript_is_found(cp, stores):
    (stores.mem / "orphan.jsonl").write_text('{"role": "user", "content": "x"}\n', encoding="utf-8")
    got = await _delete(cp, stores, "orphan")
    assert got["removed"]["log"] is True and got["removed"]["snapshot"] is False


@pytest.mark.parametrize("name,body", [
    ("notes.json", '{"s1": {"content": "my notes"}}'),
    ("kill_switch.json", '{"engaged": true, "reason": "owner"}'),
    ("autonomy_journal.jsonl", '{"event": "x"}\n'),
    ("stray.json", '{"session_id": "other", "turns": []}'),
    *[(f"{stem}.json", '{"k": 1}') for stem in sorted(NON_SESSION_STEMS)],
])
async def test_another_store_in_the_data_root_is_never_deleted(cp, stores, name, body):
    (stores.mem / name).write_text(body, encoding="utf-8")
    with pytest.raises(sa.SessionDeleteError) as err:
        await _delete(cp, stores, name.split(".")[0])
    assert err.value.reason == "not_found" and (stores.mem / name).read_text(encoding="utf-8") == body
    assert not stores.backup.exists()


@pytest.mark.parametrize("name,part,raw", [
    ("gone.json", "snapshot", b'{"session_id": "gone", "tur'),
    ("gone.jsonl", "log", b'{"role": "user", "content": "hi"}\n{"content": "\xc3'),
])
async def test_a_torn_transcript_is_backed_up_byte_for_byte_and_deleted(cp, stores, name, part, raw):
    (stores.mem / name).write_bytes(raw)
    got = await _delete(cp, stores)
    record = sa.read_backup(Path(got["backup"]))
    assert base64.b64decode(record[part]) == raw and record["unreadable"] == [part]
    assert not (stores.mem / name).exists() and cp.session_row("gone") is None


async def test_a_transcript_that_cannot_be_read_refuses_with_a_reason(cp, stores, monkeypatch):
    real = Path.read_bytes

    def denied(self):
        if self.name == "gone.jsonl":
            raise PermissionError("denied")
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(sa.SessionDeleteError) as err:
        await _delete(cp, stores)
    assert err.value.reason == "backup_failed" and cp.session_row("gone") is not None
    assert (stores.mem / "gone.jsonl").exists()


async def test_a_backup_that_does_not_land_deletes_nothing(cp, stores, monkeypatch):
    monkeypatch.setattr(sa.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(sa.SessionDeleteError) as err:
        await _delete(cp, stores)
    assert err.value.reason == "backup_failed"
    assert cp.session_row("gone") is not None and (stores.mem / "gone.json").exists() and stores.arch.exists()
    assert list(stores.backup.glob("*")) == []                       # the half-written temp is gone


async def test_a_backup_that_does_not_read_back_deletes_nothing(cp, stores, monkeypatch):
    real = Path.read_bytes

    def flipped(self):
        data = real(self)
        return data[:-1] + bytes([data[-1] ^ 1]) if self.parent == stores.backup else data
    monkeypatch.setattr(Path, "read_bytes", flipped)
    with pytest.raises(sa.SessionDeleteError) as err:
        await _delete(cp, stores)
    assert err.value.reason == "backup_failed" and cp.session_row("gone") is not None


async def test_the_backup_lives_outside_the_data_root_by_default(cp, stores, tmp_path, monkeypatch):
    from agents.core.paths import data_root

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("JARVIS_FORGET_ARCHIVE_DIR", raising=False)
    got = await sa.delete_session("gone", checkpoints=cp, archive_root=stores.archive_root)
    root, backup = data_root().resolve(), Path(got["backup"]).resolve()
    assert backup.parent == sa.default_backup_dir().resolve() and backup.is_file()
    assert root not in backup.parents and backup.parent.name == "sessions"


async def test_old_backups_are_pruned_to_the_newest_few(cp, stores, monkeypatch):
    monkeypatch.setenv("JARVIS_SESSION_BACKUP_KEEP", "2")
    first = None
    for sid in ("a1", "a2", "a3"):
        _session(cp, sid, started="2026-09-01T00:00:00+00:00")
        got = await _delete(cp, stores, sid)
        first = first or Path(got["backup"]).name
    assert sorted(p.name.split("-")[0] for p in stores.backup.glob("*.json.enc")) == ["a2", "a3"]
    assert got["pruned"] == [first]


async def test_the_backup_and_the_deletes_run_off_the_event_loop(cp, stores, monkeypatch):
    loop_thread, seen = threading.current_thread(), []

    def spy(name, real):
        def call(*args, **kwargs):
            seen.append((name, threading.current_thread() is loop_thread))
            return real(*args, **kwargs)
        return call
    monkeypatch.setattr(sa, "collect", spy("collect", sa.collect))
    monkeypatch.setattr(sa, "_write_backup", spy("backup", sa._write_backup))
    monkeypatch.setattr(cp, "delete_session_rows", spy("rows", cp.delete_session_rows))
    await _delete(cp, stores)
    assert seen == [("collect", False), ("backup", False), ("rows", False)]


async def test_the_deleted_rows_are_not_left_in_the_database_files(cp, stores):
    marker = "ZZTITLEMARKERZZ"
    for i in range(60):
        _session(cp, f"s{i}", started="2026-09-01T00:00:00+00:00", meta={"title": f"chat {i}"})
    _session(cp, "victim", started="2026-09-01T00:00:00+00:00", meta={"title": marker * 4})
    await _delete(cp, stores, "victim")
    db = Path(cp.db_path)
    for path in (db, db.with_name(db.name + "-wal")):
        assert marker.encode() not in (path.read_bytes() if path.exists() else b""), path.name


# ── what a continued chat leaves behind ──────────────────────────────────────────

_SEED = [{"role": "user", "content": "my bank PIN is 4242", "agent_id": None,
          "timestamp": "2026-09-01T10:00:00+00:00", "token_count": 6}]


def _continue(cp, source="gone", request="00000000-0000-4000-8000-000000000001"):
    from agents.core.session_continuation import ContinuationStore

    return ContinuationStore(cp).create(source, request, _SEED, cp.clock_snapshot(source))["session_id"]


async def test_a_continued_chat_takes_its_seed_and_history_binding_with_it(cp, stores):
    child = _continue(cp)
    got = await _delete(cp, stores, child)
    record = sa.read_backup(Path(got["backup"]))
    assert "my bank PIN is 4242" in record["continuation"]["seed_json"]
    assert record["history_instance"]["session_id"] == child
    assert got["removed"]["rows"]["session_continuations"] == 1
    assert got["removed"]["rows"]["session_history_instances"] == 1
    for table in ("session_continuations", "session_history_instances", "session_clock"):
        count = cp._conn.execute(f"SELECT count(*) FROM {table} WHERE session_id=?", (child,)).fetchone()[0]  # nosec B608
        assert count == 0, table


async def test_a_chat_another_one_continues_is_kept_until_that_one_is_deleted(cp, stores):
    child = _continue(cp)
    with pytest.raises(sa.SessionDeleteError) as err:
        await _delete(cp, stores)
    assert err.value.reason == "has_continuations" and cp.session_row("gone") is not None
    assert not stores.backup.exists()
    await _delete(cp, stores, child)
    assert (await _delete(cp, stores))["ok"] is True


async def test_a_deleted_id_can_be_used_again(cp, stores):
    from agents.core.session_continuation import history_identity

    await _delete(cp, stores)
    cp.create_session_record("gone")
    with cp._lock:
        instance, _legacy = history_identity(cp._conn, "gone")
    assert instance == cp.session_row("gone")["instance_id"]


# ── what long-term recall keeps ──────────────────────────────────────────────────

def _recall_memory(embed):
    from agents.core.memory.manager import MemoryManager

    memory = MemoryManager()
    memory.embed_turns = True
    memory._embedder = SimpleNamespace(embed=embed)
    return memory


async def test_a_delete_takes_the_chats_turn_embeddings_out_of_recall(cp, stores):
    memory = _recall_memory(lambda text: [0.1] * 768)
    await memory.add_turn("gone", "user", "my bank PIN is 4242")
    await memory.add_turn("kept", "user", "the weather in Brasov")
    await memory.flush_embeddings()
    got = await _delete(cp, stores, memory=memory)
    assert got["removed"]["embeddings"] == 1
    assert [r.metadata["session"] for r in memory.vectors.records] == ["kept"]
    assert "gone" not in memory.conversation.sessions


async def test_a_turn_embedding_still_queued_for_a_deleted_chat_is_never_stored(cp, stores):
    gate = threading.Event()
    memory = _recall_memory(lambda text: gate.wait(5) and [0.1] * 768)
    await memory.add_turn("gone", "user", "my bank PIN is 4242")     # queued: the embedder is still working
    await _delete(cp, stores, memory=memory)
    gate.set()
    await memory.flush_embeddings()
    assert len(memory.vectors) == 0


async def test_embeddings_that_cannot_be_removed_stop_the_delete(cp, stores):
    memory = _recall_memory(lambda text: [0.1] * 768)
    memory.vectors.remove_where = lambda key, value: (_ for _ in ()).throw(RuntimeError("qdrant down"))
    with pytest.raises(sa.SessionDeleteError) as err:
        await _delete(cp, stores, memory=memory)
    assert err.value.reason == "recall_unavailable" and cp.session_row("gone") is not None
    assert (stores.mem / "gone.json").exists()


def test_the_vector_stores_remove_one_sessions_records():
    from unittest.mock import MagicMock

    from agents.core.memory.qdrant_store import QdrantVectorStore
    from agents.core.memory.store import InMemoryVectorStore

    local = InMemoryVectorStore(dimension=2)
    for rid, sid in (("a", "gone"), ("b", "kept"), ("c", "gone")):
        local.add(rid, [1.0, 0.0], {"session": sid})
    assert local.remove_where("session", "gone") == 2 and local.get("b").id == "b" and local.get("a") is None
    remote = QdrantVectorStore(url="http://q:6333")
    remote._client = MagicMock()
    remote._client.post.side_effect = [SimpleNamespace(status_code=200, json=lambda: {"result": {"count": 3}}),
                                       SimpleNamespace(status_code=200, json=lambda: {"result": {}})]
    assert remote.remove_where("session", "gone") == 3
    count, delete = remote._client.post.call_args_list
    only = {"must": [{"key": "session", "match": {"value": "gone"}}]}
    assert count.args[0] == "http://q:6333/collections/jarvis_memory/points/count" and count.kwargs["json"]["filter"] == only
    assert delete.args[0].startswith("http://q:6333/collections/jarvis_memory/points/delete")
    assert delete.kwargs["json"] == {"filter": only}
    remote._client.post.side_effect = [SimpleNamespace(status_code=500, text="boom", json=lambda: {})]
    with pytest.raises(RuntimeError):
        remote.remove_where("session", "gone")
    remote._client.post.side_effect = ConnectionError("down")
    with pytest.raises(RuntimeError):
        remote.remove_where("session", "gone")


# ── a turn in flight ─────────────────────────────────────────────────────────────

async def test_a_turn_written_while_the_delete_waits_is_in_the_backup_and_never_comes_back(cp, stores, monkeypatch):
    from agents.core.memory.conversation import ConversationMemory
    from agents.core.memory.manager import MemoryManager

    memory = MemoryManager()
    assert await memory.resume_session("gone")                       # the chat is live in memory
    writing, release = threading.Event(), threading.Event()
    real = ConversationMemory._persist_turn

    def slow_persist(self, *args, **kwargs):
        writing.set()
        release.wait(5)
        return real(self, *args, **kwargs)
    monkeypatch.setattr(ConversationMemory, "_persist_turn", slow_persist)
    turn = asyncio.create_task(memory.add_turn("gone", "user", "late news"))
    await asyncio.to_thread(writing.wait, 5)
    delete = asyncio.create_task(_delete(cp, stores, memory=memory))
    await asyncio.sleep(0.05)
    release.set()
    await turn
    record = sa.read_backup(Path((await delete)["backup"]))
    assert [t["content"] for t in record["snapshot"]["turns"]] == ["hi", "late news"]
    assert not (stores.mem / "gone.json").exists() and not (stores.mem / "gone.jsonl").exists()
    assert "gone" not in memory.conversation.sessions


@asynccontextmanager
async def _free_lease(session_key=None):
    yield True


async def test_a_turn_running_on_the_chat_is_waited_for_and_a_long_one_answers_busy(cp, stores, monkeypatch):
    from agents.core.orchestrator import Orchestrator
    from agents.core.routers import sessions as route

    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id, orch.checkpoints, orch.memory = "live", cp, _conversation("gone")
    orch._channel_sessions = {"telegram:1": "gone", "telegram:2": "kept"}
    orch._turn_lease_max_wait = 0.05
    monkeypatch.setattr(route, "get_orch", lambda: orch)
    monkeypatch.setenv("JARVIS_FORGET_ARCHIVE_DIR", str(stores.backup))
    held, done = asyncio.Event(), asyncio.Event()

    async def turn():
        async with orch.turn_lease("gone"):
            held.set()
            await done.wait()
    running = asyncio.create_task(turn())
    await held.wait()
    busy = await route.delete_session("gone", confirm="DELETE")
    assert busy.status_code == 409 and json.loads(busy.body)["reason"] == "session_busy"
    assert cp.session_row("gone") is not None and (stores.mem / "gone.json").exists()
    done.set()
    await running
    deleted = await route.delete_session("gone", confirm="DELETE")
    assert deleted.status_code == 200 and orch._channel_sessions == {"telegram:2": "kept"}


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

    orch = SimpleNamespace(checkpoints=cp, memory=_conversation("gone"), session_id="live", turn_lease=_free_lease)
    monkeypatch.setattr(route, "get_orch", lambda: orch)
    monkeypatch.setenv("JARVIS_FORGET_ARCHIVE_DIR", str(stores.backup))
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
    assert Path(body["backup"]).parent == stores.backup / "sessions"
    assert cp.session_row("gone") is None and "gone" not in orch.memory.sessions
    monkeypatch.setattr(route, "get_orch", lambda: None)
    assert (await route.delete_session("gone", confirm="DELETE")).status_code == 503


async def test_a_failed_backup_answers_500(cp, stores, monkeypatch):
    from agents.core.routers import sessions as route

    orch = SimpleNamespace(checkpoints=cp, memory=_conversation("gone"), session_id="live", turn_lease=_free_lease)
    monkeypatch.setattr(route, "get_orch", lambda: orch)
    monkeypatch.setenv("JARVIS_FORGET_ARCHIVE_DIR", str(stores.backup))
    monkeypatch.setattr(sa.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk full")))
    got = await route.delete_session("gone", confirm="DELETE")
    assert got.status_code == 500 and json.loads(got.body)["reason"] == "backup_failed"


@pytest.mark.parametrize("reason,status", [
    ("session_busy", 409), ("has_continuations", 409), ("not_found", 404), ("recall_unavailable", 503),
    ("backup_failed", 500),
])
async def test_each_refusal_answers_its_own_status(monkeypatch, reason, status):
    from agents.core.routers import sessions as route

    async def refuse(*args, **kwargs):
        raise sa.SessionDeleteError(reason)
    monkeypatch.setattr(sa, "delete_session", refuse)
    orch = SimpleNamespace(checkpoints=None, memory=None, session_id="live", turn_lease=_free_lease)
    monkeypatch.setattr(route, "get_orch", lambda: orch)
    got = await route.delete_session("gone", confirm="DELETE")
    assert got.status_code == status and json.loads(got.body)["reason"] == reason


def test_archiving_while_the_store_fails_is_not_a_missing_session(cp, monkeypatch):
    _session(cp, "s", started="2026-09-01T00:00:00+00:00")
    cp._conn.close()
    got = _client(monkeypatch, SimpleNamespace(checkpoints=cp)).post("/sessions/s/archive")
    assert got.status_code == 503 and got.json()["reason"] == "store_unavailable"


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


def test_resuming_a_chat_whose_history_cannot_be_restored_is_refused_not_a_crash(cp, monkeypatch):
    from agents.core.session_continuation import ContinuationRefused

    async def resume(sid):
        raise ContinuationRefused("continuation_identity_changed")
    got = _client(monkeypatch, SimpleNamespace(checkpoints=cp, memory=SimpleNamespace(resume_session=resume))).post(
        "/sessions/resume", json={"session_id": "s"})
    assert got.status_code == 409 and got.json()["error"] == "continuation_identity_changed"


# ── settings and the default project directory ──────────────────────────────────

def test_the_settings_are_declared():
    from agents.core.settings_db import DEFAULTS

    rows = {(r["category"], r["key"]): r for r in DEFAULTS}
    assert rows[("memory", "auto_archive_days")]["value"] == 0 and rows[("memory", "auto_archive_days")]["kind"] == "number"
    assert rows[("llm", "project_dir")]["value"] == "" and rows[("llm", "project_dir")]["kind"] == "text"
    assert "convention files" in rows[("llm", "project_dir")]["label"]          # what it moves, and only that
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

    def fake(session, *, setting=None, workdir=None, scope=None):
        assert scope is None, "an ordinary owner turn has no worker workspace scope"
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
