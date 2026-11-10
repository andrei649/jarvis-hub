"""H440 third review round.

- B1  a chat that was continued and then used again is listed again (``/sessions/continue``
      does not move the chat that is open, so its later turns are in no continuation): its
      own row, marked as an earlier part, in the route, the ``/sessions`` command, ``nerva
      sessions`` and the selectors; a name opens whichever of it and its continuations was
      used last. One with no later turn stays hidden.
- M1  the backups of one conversation are one set: every pruner keeps it whole or removes
      it whole, and counts it once.
- M2  only an answer that names the request field turns the JSON schema off; the note is
      kept per (model, address) and forgotten after an hour.
- m1  a conversation is walked by its parent links, whatever the clock said.
- m2  the sweep's lists cost per row, however large one conversation is.
- m3  a title write looks titles up in an index; it does not read every session.
- m4  a conversation's only row may take the conversation's own first name.
- m6  the status strip counts sessions as the lists show them.
- m7  parts numbered before the model's title arrived follow it.
- nits: suffixes respect the title bounds; the listings say "other sessions in this
      conversation"; a rename never tells whether an id exists; the ``/sessions`` command
      leaves imported chats out for a guest.
(m5, the HUD's part-way delete, is in frontend/src/test/sessions-lineage.test.tsx.)
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import session_archive as sa  # noqa: E402
from agents.core import session_selectors as sel  # noqa: E402
from agents.core import session_titles as st  # noqa: E402
from agents.core.checkpoint import CheckpointManager  # noqa: E402
from agents.core.session_continuation import ContinuationStore  # noqa: E402
from tests.h058_access_fixture import user_tier_allowed  # noqa: E402, F401 — a fixture (H058: /sessions allowed)

SEED = [{"role": "user", "content": "Remember the blue door", "agent_id": None,
         "timestamp": "2026-09-01T10:00:00+00:00", "token_count": 6}]
_COUNTER = iter(range(1, 1_000_000))


@pytest.fixture
def cp(tmp_path):
    manager = CheckpointManager(str(tmp_path / "checkpoints.db"))
    manager.initialize()
    yield manager
    manager.close()


def _request(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def _continue(cp, source: str) -> str:
    return ContinuationStore(cp).create(source, _request(next(_COUNTER)), SEED,
                                        cp.clock_snapshot(source))["session_id"]


def _titled(cp, sid: str, title: str, source: str = st.FIRST_WORDS) -> str:
    cp.create_session_record(sid)
    assert cp.set_session_title(sid, title, source)
    return sid


def _title(cp, sid: str) -> str:
    return cp.session_title(sid)["title"]


def _meta(cp, sid: str) -> dict:
    return json.loads(cp.session_row(sid)["metadata"] or "{}")


def _ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _age(cp, days: float, *ids: str) -> None:
    with cp._lock:
        for sid in ids:
            cp._conn.execute("UPDATE sessions SET started_at=?, ended_at=? WHERE id=?", (_ago(days), _ago(days), sid))
        cp._conn.commit()


def _turn(cp, sid: str, count: int = 9) -> None:
    """What every turn does to its session's row (``MemoryManager.add_turn``)."""
    time.sleep(0.002)                       # a later instant than the continuation's own
    cp.update_session(sid, turn_count=count)


def _client(monkeypatch, orch, *, owner: bool = False):
    """A guest's client; ``owner``: the owner's (a direct-localhost caller while no admin
    token is configured, as ``web._admin_guard`` decides)."""
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import sessions as route

    monkeypatch.setattr(route, "get_orch", lambda: orch)
    if not owner:
        return TestClient(web.app)
    monkeypatch.delenv("JARVIS_ADMIN_TOKEN", raising=False)
    return TestClient(web.app, client=("127.0.0.1", 4000))


def _rows(client, **params) -> dict:
    return {row["id"]: row for row in client.get("/sessions", params=params).json()["sessions"]}


@asynccontextmanager
async def _free_lease(session_key=None):
    yield True


# ── B1: turns written after a chat was continued ─────────────────────────────────

@pytest.fixture
def live(cp, tmp_path, monkeypatch):
    """The real memory manager, continuation store and routes around one checkpoint store."""
    from agents.core.memory import conversation, persistence
    from agents.core.memory.manager import MemoryManager

    mem = tmp_path / "mem"
    mem.mkdir()
    monkeypatch.setattr(persistence, "MEMORY_DIR", mem)
    monkeypatch.setattr(conversation, "MEMORY_DIR", mem)
    memory = MemoryManager()
    memory._checkpoint_mgr = cp
    sid = "session_" + "a" * 32
    orch = SimpleNamespace(checkpoints=cp, memory=memory, session_id=sid, turn_lease=_free_lease)
    return SimpleNamespace(cp=cp, memory=memory, orch=orch, sid=sid, client=_client(monkeypatch, orch, owner=True))


async def _open_and_continue(live) -> str:
    cp, memory, sid = live.cp, live.memory, live.sid
    cp.create_session_record(sid)
    memory.conversation.current_session_id = sid
    await memory.add_turn(sid, "user", "Plan the Brasov trip")
    assert cp.set_session_title(sid, "Plan the Brasov trip", "first_words")
    await memory.add_turn(sid, "assistant", "Day 1: Black Church")
    made = live.client.post("/sessions/continue", json={"source_session_id": sid, "request_id": _request(1)})
    assert made.status_code == 201
    assert live.orch.session_id == sid          # the route does not move the chat that is open
    return made.json()["session_id"]


def _resume(live, **body) -> dict:
    got = live.client.post("/sessions/resume", json=body)
    assert got.status_code == 200, got.text
    live.orch.session_id = "session_" + "b" * 32          # the owner looks at another chat again
    return got.json()


async def test_a_continued_chat_nobody_used_since_stays_hidden(live):
    child = await _open_and_continue(live)
    rows = _rows(live.client)
    assert set(rows) == {child}
    assert (rows[child]["title"], rows[child]["continuations"], rows[child]["earlier_part"]) == (
        "Plan the Brasov trip #2", 1, False)
    assert _resume(live, title="Plan the Brasov trip")["session"] == child
    assert live.cp.continued_sessions([live.sid, child, "nope"]) == {live.sid}


async def test_turns_written_to_a_chat_after_it_was_continued_are_listed_and_open_by_name(live):
    child = await _open_and_continue(live)
    # the owner keeps typing: the turns go to the hub's active session, the source
    await live.memory.add_turn(live.orch.session_id, "user", "Also book the Rasnov fortress for Saturday")
    await live.memory.add_turn(live.orch.session_id, "assistant", "Booked: Rasnov, Saturday 10:00")
    rows = _rows(live.client)
    assert set(rows) == {live.sid, child}
    source = rows[live.sid]
    assert (source["title"], source["earlier_part"], source["resume_id"], source["continuations"]) == (
        "Plan the Brasov trip", True, live.sid, 1)
    assert (rows[child]["title"], rows[child]["earlier_part"], rows[child]["continuations"]) == (
        "Plan the Brasov trip #2", False, 1)
    by_name = _resume(live, title="Plan the Brasov trip")
    assert by_name["session"] == live.sid
    assert any("Rasnov" in turn["content"] for turn in by_name["turns"])
    by_row = _resume(live, session_id=source["resume_id"])
    assert by_row["turns"][-1]["content"] == "Booked: Rasnov, Saturday 10:00"
    assert _resume(live, title="Plan the Brasov trip #2")["session"] == child     # its own name is its own
    assert sel.resolve(live.cp, "Plan the Brasov trip") == live.sid == sel.resolve(live.cp, "latest")


async def test_the_name_opens_whichever_of_the_part_and_its_continuation_was_used_last(live):
    child = await _open_and_continue(live)
    await live.memory.add_turn(live.sid, "user", "Also book the Rasnov fortress")
    assert sel.resolve_title(live.cp, "Plan the Brasov trip") == live.sid
    live.client.post("/sessions/resume", json={"session_id": child})
    await live.memory.add_turn(child, "user", "And a table at Sergiana")       # the continuation, later
    assert sel.resolve_title(live.cp, "Plan the Brasov trip") == child
    assert sel.resolve_title(live.cp, "Plan the Brasov trip #2") == child
    rows = _rows(live.client)
    assert set(rows) == {live.sid, child} and rows[live.sid]["earlier_part"] is True   # still a row: still reachable
    await live.memory.add_turn(live.sid, "user", "Saturday, not Sunday")       # and the first part again
    assert sel.resolve_title(live.cp, "Plan the Brasov trip") == live.sid
    assert sel.resolve(live.cp, "Plan the Brasov trip") == live.sid


def test_a_middle_part_and_a_branching_root_used_again_are_rows_and_answer_their_names(cp, monkeypatch):
    _titled(cp, "root", "Trip plan")
    two = _continue(cp, "root")
    three = _continue(cp, two)
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    assert set(_rows(client)) == {three}
    _turn(cp, two)
    rows = _rows(client)
    assert set(rows) == {two, three}
    assert [rows[s]["earlier_part"] for s in (two, three)] == [True, False]
    assert [rows[s]["continuations"] for s in (two, three)] == [2, 2]       # the other sessions, truthfully
    for name in ("Trip plan #2", "Trip plan", "trip  PLAN"):
        assert sel.resolve_title(cp, name) == two, name
    assert sel.resolve_title(cp, "Trip plan #3") == three
    assert {r["id"] for r in cp.get_sessions(hide_continuations=True)} == {two, three}

    _titled(cp, "fork", "Fork")
    a, b = _continue(cp, "fork"), _continue(cp, "fork")
    assert set(_rows(client)) == {two, three, a, b}
    assert sel.resolve_title(cp, "Fork") == b                              # nobody used either: the newest
    _turn(cp, "fork")
    assert {"fork", a, b} <= set(_rows(client)) and sel.resolve_title(cp, "Fork") == "fork"
    _turn(cp, a)
    assert sel.resolve_title(cp, "Fork") == a and sel.resolve_title(cp, "Fork #3") == b
    b2 = _continue(cp, b)                                                   # continuing a branch hides only it
    assert set(_rows(client)) == {two, three, "fork", a, b2}


def test_archive_pin_and_delete_from_an_earlier_part_row_are_the_conversations(cp, tmp_path, monkeypatch):
    from agents.core.memory import conversation, persistence
    from agents.core.memory.conversation import ConversationMemory

    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    _turn(cp, "root")
    mem = tmp_path / "mem"
    mem.mkdir()
    monkeypatch.setattr(persistence, "MEMORY_DIR", mem)
    monkeypatch.setattr(conversation, "MEMORY_DIR", mem)
    monkeypatch.setenv("JARVIS_FORGET_ARCHIVE_DIR", str(tmp_path / "backup"))
    conv = ConversationMemory(persist=False)
    for sid in ("root", tip):
        conv.sessions[sid], conv.instances[sid] = [], f"i-{sid}"
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp, memory=conv, session_id="live",
                                                  turn_lease=_free_lease), owner=True)
    assert client.post("/sessions/root/archive").status_code == 200
    assert _rows(client) == {} and set(_rows(client, archived="true")) == {"root", tip}
    assert client.post(f"/sessions/{tip}/unarchive").status_code == 200
    assert client.post("/sessions/root/pin").status_code == 200
    assert all("pinned_at" in _meta(cp, s) for s in ("root", tip))
    assert client.post(f"/sessions/{tip}/unpin").status_code == 200
    alone = client.delete("/sessions/root", params={"confirm": "DELETE"})
    assert alone.status_code == 409 and alone.json()["reason"] == "has_continuations"
    whole = client.delete("/sessions/root", params={"confirm": "DELETE", "lineage": "true"})
    assert whole.status_code == 200 and whole.json()["deleted"] == [tip, "root"]


async def test_the_sessions_command_and_the_cli_mark_an_earlier_part_still_in_use(cp, user_tier_allowed):
    from agents.cli.nerva import EXIT_OK, Context, main
    from agents.core.commands import Principal, build_default_registry

    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    orch = SimpleNamespace(checkpoints=cp)
    quiet = await build_default_registry().dispatch("/sessions", orch=orch, principal=Principal(channel="cli", admin=True))
    assert "root" not in quiet.reply.replace(tip, "") and "earlier part" not in quiet.reply
    _turn(cp, "root")
    out = await build_default_registry().dispatch("/sessions", orch=orch, principal=Principal(channel="cli", admin=True))
    lines = out.reply.splitlines()
    assert any(line.startswith("root ") and line.endswith("Trip plan  (earlier part, still in use)") for line in lines)
    assert any(line.startswith(tip) and line.endswith("Trip plan #2") for line in lines)

    class _Client:
        def get(self, path):
            return {"sessions": [
                {"id": "root", "started_at": "T1", "title": "Trip plan", "resume_id": "root", "continuations": 1,
                 "earlier_part": True},
                {"id": "tip", "started_at": "T2", "title": "Trip plan #2", "resume_id": "tip", "continuations": 1,
                 "earlier_part": False},
                {"id": "big", "started_at": "T3", "title": "Big", "resume_id": "big", "continuations": 4},
            ]}

    printed = io.StringIO()
    ctx = Context(environ={}, out=printed, err=io.StringIO(), inp=io.StringIO(""), client_factory=lambda env: _Client())
    assert main(["sessions"], context=ctx) == EXIT_OK
    assert printed.getvalue().splitlines() == [
        "root  T1  Trip plan  (+1 other session in this conversation)  (earlier part, still in use)",
        "tip  T2  Trip plan #2  (+1 other session in this conversation)",
        "big  T3  Big  (+4 other sessions in this conversation)",
    ]


async def test_the_sessions_command_leaves_imported_chats_out_for_a_guest(cp, user_tier_allowed):
    from agents.core.commands import Principal, build_default_registry
    from agents.core.session_import import import_turns

    _titled(cp, "native", "Native chat")
    imported = [import_turns(cp, source="claude", external_id=f"e{i}", request_id=_request(900 + i), source_sha256=None,
                             turns=[{"role": "user", "content": "hello", "timestamp": "2026-10-01T00:00:00+00:00"}]
                             )["session_id"] for i in range(6)]         # newer than the native chat, a full window
    orch = SimpleNamespace(checkpoints=cp)
    guest = await build_default_registry().dispatch("/sessions", orch=orch,
                                                    principal=Principal(channel="telegram", admin=False))
    assert "native" in guest.reply and not any(sid in guest.reply for sid in imported)
    owner = await build_default_registry().dispatch("/sessions", orch=orch,
                                                    principal=Principal(channel="cli", admin=True))
    assert sum(sid in owner.reply for sid in imported) == 5


# ── m6: the status strip counts what the lists show ──────────────────────────────

def test_the_active_session_count_leaves_hidden_parts_out(cp, monkeypatch):
    _titled(cp, "root", "Trip plan")
    two = _continue(cp, "root")
    _continue(cp, two)
    cp.create_session_record("solo")
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    assert len(_rows(client)) == 2 and cp.active_session_count(_ago(1)) == 2      # it said 4
    _turn(cp, "root")
    assert len(_rows(client)) == 3 and cp.active_session_count(_ago(1)) == 3


# ── M1: a conversation's backups are one set ─────────────────────────────────────

def _delete_orch(cp, tmp_path, monkeypatch, ids):
    from agents.core.memory import conversation, persistence
    from agents.core.memory.conversation import ConversationMemory
    from agents.core.routers import sessions as route

    mem = tmp_path / "mem"
    mem.mkdir(exist_ok=True)
    monkeypatch.setattr(persistence, "MEMORY_DIR", mem)
    monkeypatch.setattr(conversation, "MEMORY_DIR", mem)
    monkeypatch.setenv("JARVIS_FORGET_ARCHIVE_DIR", str(tmp_path / "backup"))
    conv = ConversationMemory(persist=False)
    for sid in ids:
        conv.sessions[sid], conv.instances[sid] = [], f"i-{sid}"
    orch = SimpleNamespace(checkpoints=cp, memory=conv, session_id="live", turn_lease=_free_lease)
    monkeypatch.setattr(route, "get_orch", lambda: orch)
    return orch, route


def _chain(cp, length: int, title: str = "Long chat", root: str = "root") -> list[str]:
    ids = [_titled(cp, root, title)]
    for _ in range(length - 1):
        ids.append(_continue(cp, ids[-1]))
    return ids


def _know(orch, cp, *ids):
    for sid in ids:
        orch.memory.sessions[sid], orch.memory.instances[sid] = [], f"i-{sid}"


async def _delete(route, sid, **kw) -> dict:
    done = await route.delete_session(sid, confirm="DELETE", **kw)
    assert done.status_code == 200, done.body
    return json.loads(done.body)


async def test_an_unrelated_delete_after_a_long_conversation_keeps_all_of_its_backups(cp, tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_SESSION_BACKUP_KEEP", raising=False)
    ids = _chain(cp, 13)
    orch, route = _delete_orch(cp, tmp_path, monkeypatch, ids)
    whole = await _delete(route, "root", lineage=True)
    assert len(whole["backups"]) == 13 and len(sa.backup_sets(sa.default_backup_dir())) == 1
    _titled(cp, "solo", "Solo")
    _know(orch, cp, "solo")
    one = await _delete(route, "solo")
    assert one["pruned"] == []                                         # it cut the conversation to nine parts
    assert all(Path(p).exists() for p in whole["backups"]) and Path(one["backup"]).exists()
    assert [len(files) for files in sa.backup_sets(sa.default_backup_dir())] == [1, 13]


async def test_with_keep_one_the_conversation_backups_go_together_never_in_part(cp, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_SESSION_BACKUP_KEEP", "1")
    ids = _chain(cp, 5)
    orch, route = _delete_orch(cp, tmp_path, monkeypatch, ids)
    whole = await _delete(route, "root", lineage=True)
    assert all(Path(p).exists() for p in whole["backups"])
    _titled(cp, "solo", "Solo")
    _know(orch, cp, "solo")
    one = await _delete(route, "solo")
    left = [Path(p).exists() for p in whole["backups"]]
    assert left == [False] * 5                                         # it left one headless part
    assert sorted(one["pruned"]) == sorted(Path(p).name for p in whole["backups"])
    assert Path(one["backup"]).exists()


async def test_ten_single_deletes_after_a_conversation_prune_it_whole(cp, tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_SESSION_BACKUP_KEEP", raising=False)
    ids = _chain(cp, 13)
    orch, route = _delete_orch(cp, tmp_path, monkeypatch, ids)
    whole = await _delete(route, "root", lineage=True)
    for i in range(10):
        _titled(cp, f"solo{i}", f"Solo {i}")
        _know(orch, cp, f"solo{i}")
        await _delete(route, f"solo{i}")
        left = sum(Path(p).exists() for p in whole["backups"])
        assert left == (13 if i < 9 else 0), (i, left)                  # all thirteen, then none


async def test_parts_deleted_one_by_one_and_a_run_that_stopped_are_the_same_set(cp, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_SESSION_BACKUP_KEEP", "1")
    ids = _chain(cp, 4)
    orch, route = _delete_orch(cp, tmp_path, monkeypatch, ids)
    tip = await _delete(route, ids[3])                                  # the row alone

    @asynccontextmanager
    async def busy(session_key=None):
        yield session_key != ids[1]

    orch.turn_lease = busy
    stopped = await route.delete_session("root", confirm="DELETE", lineage=True)
    assert stopped.status_code == 409 and json.loads(stopped.body)["deleted"] == [ids[2]]
    orch.turn_lease = _free_lease
    rest = await _delete(route, "root", lineage=True)
    assert rest["deleted"] == [ids[1], "root"]
    sets = sa.backup_sets(sa.default_backup_dir())
    assert [len(files) for files in sets] == [4]                        # one conversation, one set
    names = {path.name for path in sets[0]}
    assert Path(tip["backup"]).name in names and all(Path(p).name in names for p in rest["backups"])
    keys = {name.split(".c-")[1] for name in names}
    assert len(keys) == 1


def test_a_reused_id_and_an_old_style_backup_are_sets_of_their_own(tmp_path):
    first = {"session_id": "main", "session": {"id": "main", "instance_id": "i1"}, "continuation": None}
    again = {"session_id": "main", "session": {"id": "main", "instance_id": "i2"}, "continuation": None}
    part = {"session_id": "p", "session": {"id": "p", "instance_id": "i9"},
            "continuation": {"root_id": "main", "root_instance_id": "i1"}}
    assert sa.conversation_key(first) == sa.conversation_key(part) != sa.conversation_key(again)
    root = tmp_path / "sessions"
    root.mkdir()
    made = []
    for i, name in enumerate(["old-style-1.json.enc", "old-style-2.json.enc",
                              sa.backup_name("p", "S1", sa.conversation_key(part)),
                              sa.backup_name("main", "S2", sa.conversation_key(first)),
                              sa.backup_name("main", "S3", sa.conversation_key(again))]):
        path = root / name
        path.write_bytes(b"x")
        os.utime(path, (1_000_000 + i, 1_000_000 + i))
        made.append(path)
    assert [sorted(p.name for p in files) for files in sa.backup_sets(root)] == [
        [made[4].name], sorted([made[2].name, made[3].name]), [made[1].name], [made[0].name]]
    assert sorted(sa.prune_backups(root, 2)) == sorted([made[0].name, made[1].name])
    assert sorted(sa.prune_backups(root, 1)) == sorted([made[2].name, made[3].name])


# the lifecycle sweep's own prune

def _sweep_orch(cp, tmp_path, settings: dict):
    from agents.core.memory.conversation import ConversationMemory
    from agents.core.notes import NotesStore
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "live"
    orch.checkpoints, orch.memory = cp, ConversationMemory(persist=False)
    orch.notes = NotesStore(tmp_path / "notes.json")
    orch._channel_sessions = {}
    orch._turn_lease_max_wait = 0.05
    orch._runtime_settings = settings
    orch.audit, orch.ingestion_watcher = None, None
    return orch


@pytest.fixture
def swept(tmp_path, monkeypatch):
    from agents.core import retention
    from agents.core.memory import persistence

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.setenv("JARVIS_FORGET_ARCHIVE_DIR", str(tmp_path / "bk"))
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    monkeypatch.setattr(persistence, "MEMORY_DIR", None)
    manager = CheckpointManager(str(home / "checkpoints.db"))
    manager.initialize()
    settings = {"retention.enabled": True, "memory.auto_archive_days": 100, "retention.conversation_ttl_days": 60,
                "retention.audit_ttl_days": 0, "retention.ingestion_ttl_days": 0, "retention.artifact_ttl_days": 0}
    manager.put_state(retention.APPROVED_STATE, {"values": {k: settings.get(k) for k in retention.RETENTION_KEYS}})
    yield SimpleNamespace(cp=manager, root=home, tmp=tmp_path, settings=settings)
    manager.close()


def _expire(env, *ids):
    for sid in ids:
        (env.root / f"{sid}.json").write_text(json.dumps({"session_id": sid, "turns": [
            {"role": "user", "content": "old"}]}), encoding="utf-8")
    _age(env.cp, 200, *ids)
    for sid in ids:
        meta = _meta(env.cp, sid)
        meta["archived_at"] = _ago(150)
        with env.cp._lock:
            env.cp._conn.execute("UPDATE sessions SET metadata=? WHERE id=?", (json.dumps(meta), sid))
            env.cp._conn.commit()


@pytest.mark.parametrize("keep", [None, "1"])
async def test_a_sweep_after_a_long_conversation_never_leaves_part_of_its_backups(swept, monkeypatch, keep):
    from agents.core import lifecycle_sweep
    from agents.core.routers import sessions as route

    if keep is None:
        monkeypatch.delenv("JARVIS_SESSION_BACKUP_KEEP", raising=False)
    else:
        monkeypatch.setenv("JARVIS_SESSION_BACKUP_KEEP", keep)
    cp = swept.cp
    ids = _chain(cp, 13)
    for sid in ids:
        (swept.root / f"{sid}.json").write_text(json.dumps({"session_id": sid, "turns": []}), encoding="utf-8")
    orch = _sweep_orch(cp, swept.tmp, swept.settings)
    monkeypatch.setattr(route, "get_orch", lambda: orch)
    whole = await _delete(route, "root", lineage=True)
    assert len(whole["backups"]) == 13
    for i in range(3):                                                  # three old chats for retention
        _titled(cp, f"old{i}", f"Old {i}")
    _expire(swept, "old0", "old1", "old2")
    report = await lifecycle_sweep.run_sweep(orch, now=time.time(), root=swept.root)
    conv = report["retention"]["conversations"]
    assert sorted(conv["deleted"]) == ["old0", "old1", "old2"]
    left = sum(Path(p).exists() for p in whole["backups"])
    assert left in (0, 13)                                              # never a part
    if keep is None:
        assert left == 13 and conv["backups_pruned"] == []


async def test_a_conversation_retention_deletes_is_one_set_too(swept, monkeypatch):
    from agents.core import lifecycle_sweep

    monkeypatch.delenv("JARVIS_SESSION_BACKUP_KEEP", raising=False)
    cp = swept.cp
    ids = _chain(cp, 3, "Old trip")
    _titled(cp, "plain", "Plain old chat")
    _expire(swept, *ids, "plain")
    report = await lifecycle_sweep.run_sweep(_sweep_orch(cp, swept.tmp, swept.settings), now=time.time(),
                                             root=swept.root)
    assert sorted(report["retention"]["conversations"]["deleted"]) == sorted([*ids, "plain"])
    assert sorted(len(files) for files in sa.backup_sets(sa.default_backup_dir())) == [1, 3]


# ── M2: what counts as "this server refuses the schema" ──────────────────────────

GOOD = '{"title": "Brasov trip planning"}'
UNRELATED_400 = [
    "invalid format for field messages",
    "Error rendering prompt with jinja template: unsupported chat format",
    "model 'qwen' is in GGUF format v1 which is no longer supported",
    "Unsupported image format",
    "database schema migration in progress, retry",
    "Context length exceeded. Information about prompt formatting: see docs",
    "No models loaded. Please load a model.",
    "the schema of this server's config file changed; restart it",
    "str.format() failed while building the prompt",
]
REFUSALS = [
    "'response_format.type' must be 'json_object' or 'text'",
    "response_format is not supported",
    "Unrecognized request argument supplied: json_schema",
    "json: cannot unmarshal object into Go struct field GenerateRequest.format of type string",
    'invalid value for "format": expected "json"',
    "unknown field `format`",
    "invalid format: {...}; expected \"json\" or a valid JSON Schema object",
]


def _wired(backend_name, backend, handler):
    from agents.core.llm.egress import llm_async_client
    from agents.core.llm.router import LLMRouter
    from agents.core.orchestrator import Orchestrator

    backend.client = llm_async_client(backend_name, base_url=backend.base_url,
                                      transport=httpx.MockTransport(handler))
    router = LLMRouter()
    router._backend, router._backend_name = backend, backend_name
    router._detected_model = router._local_model = "selected-local"
    orch = Orchestrator.__new__(Orchestrator)
    orch.llm_router = router
    orch.get_setting = lambda _key, default=None: default
    return orch


def _server(kind, sent, decide):
    """``decide(has_schema, call_number, body) -> (status, text)``; errors in each server's own envelope."""
    def handler(request):
        if kind == "ollama" and request.url.path != "/api/generate":
            return httpx.Response(404, json={})
        body = json.loads(request.content)
        sent.append(body)
        status, text = decide(("response_format" if kind == "lm-studio" else "format") in body, len(sent), body)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": text}} if kind == "lm-studio" else {"error": text})
        if kind == "lm-studio":
            return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}]})
        return httpx.Response(200, json={"response": text, "done_reason": "stop"})
    return handler


def _backend(kind):
    from agents.core.llm.base import LMStudioBackend, OllamaBackend

    return (LMStudioBackend("http://127.0.0.1:1234") if kind == "lm-studio"
            else OllamaBackend("http://127.0.0.1:11434"))


async def _upgrade(cp, orch, sid):
    from agents.core.orchestrator import Orchestrator

    _titled(cp, sid, f"Plan my Brasov trip {sid}")
    return await Orchestrator._upgrade_session_title(cp, sid, "Plan my Brasov trip for August", orch._session_titler())


@pytest.mark.parametrize("kind", ["lm-studio", "ollama"])
@pytest.mark.parametrize("body", UNRELATED_400)
async def test_a_400_that_only_mentions_format_or_schema_leaves_the_schema_on(cp, monkeypatch, kind, body):
    """The first call fails for an unrelated reason; then the server is healthy and takes a
    schema. A model that answers the message must not get its answer taken for a title."""
    monkeypatch.delenv("JARVIS_AUX_SESSION_TITLE_MODEL", raising=False)
    sent: list = []
    backend = _backend(kind)
    orch = _wired(kind, backend, _server(kind, sent, lambda has, n, _b: (400, body) if n == 1 else (
        200, GOOD if has else "Paris is the capital of France")))
    key = "response_format" if kind == "lm-studio" else "format"
    assert not await _upgrade(cp, orch, "s1")                           # that one keeps its first words
    assert await _upgrade(cp, orch, "s2") and await _upgrade(cp, orch, "s3")
    assert [key in b for b in sent] == [True, True, True]               # it went [True, False, False, False]
    assert backend.json_schema_refused(sent[0]["model"]) is False
    assert cp.session_title("s3")["title"].startswith("Brasov trip planning")


@pytest.mark.parametrize("kind", ["lm-studio", "ollama"])
@pytest.mark.parametrize("body", REFUSALS)
async def test_an_answer_that_names_the_field_is_a_refusal_and_the_session_is_still_named(cp, monkeypatch, kind, body):
    monkeypatch.delenv("JARVIS_AUX_SESSION_TITLE_MODEL", raising=False)
    sent: list = []
    backend = _backend(kind)
    orch = _wired(kind, backend, _server(kind, sent, lambda has, n, _b: (400, body) if has else (
        200, "Brasov trip planning")))
    key = "response_format" if kind == "lm-studio" else "format"
    assert await _upgrade(cp, orch, "s1") and await _upgrade(cp, orch, "s2")
    assert [key in b for b in sent] == [True, False, False]
    assert backend.json_schema_refused(sent[0]["model"]) is True


async def test_two_models_that_both_refuse_are_each_asked_once(cp, monkeypatch):
    sent: list = []
    backend = _backend("lm-studio")
    orch = _wired("lm-studio", backend, _server("lm-studio", sent, lambda has, n, _b: (
        400, "response_format is not supported") if has else (200, "Brasov trip planning")))
    for i in range(6):
        monkeypatch.setenv("JARVIS_AUX_SESSION_TITLE_MODEL", "model-a" if i % 2 == 0 else "model-b")
        assert await _upgrade(cp, orch, f"s{i}")
    probes = [b["model"] for b in sent if "response_format" in b]
    assert probes == ["model-a", "model-b"]                             # it probed on all six
    assert backend.json_schema_refused("model-a") and backend.json_schema_refused("model-b")
    assert backend.json_schema_refused("model-c") is False


async def test_a_remembered_refusal_is_forgotten_after_an_hour(cp, monkeypatch):
    from agents.core.llm import base

    monkeypatch.delenv("JARVIS_AUX_SESSION_TITLE_MODEL", raising=False)
    now = {"t": 1000.0}
    monkeypatch.setattr(base, "_schema_clock", lambda: now["t"])
    sent: list = []
    backend = _backend("ollama")
    upgraded = {"yes": False}                                           # the server is updated in place
    orch = _wired("ollama", backend, _server("ollama", sent, lambda has, n, _b: (
        (400, 'invalid value for "format"') if has and not upgraded["yes"] else (200, GOOD if has else "Brasov trip planning"))))
    assert await _upgrade(cp, orch, "s1") and await _upgrade(cp, orch, "s2")
    assert ["format" in b for b in sent] == [True, False, False]
    upgraded["yes"] = True
    now["t"] += base.SCHEMA_REFUSAL_TTL_S - 1
    assert await _upgrade(cp, orch, "s3") and "format" not in sent[-1]  # still believed
    now["t"] += 2
    assert backend.json_schema_refused(sent[0]["model"]) is False
    assert await _upgrade(cp, orch, "s4") and "format" in sent[-1]      # offered again, and taken
    assert await _upgrade(cp, orch, "s5") and "format" in sent[-1]


def test_the_refusal_notes_are_per_instance_and_bounded():
    from agents.core.llm import base

    one, two = _backend("lm-studio"), _backend("lm-studio")
    one._note_schema_refusal("m")
    assert one.json_schema_refused("m") is True and two.json_schema_refused("m") is False
    for i in range(200):
        one._note_schema_refusal(f"model-{i}")
    assert len(one._schema_refusals) <= base._SCHEMA_REFUSALS_KEPT and one.json_schema_refused("model-199")


# ── m1: the order is the parent links' ───────────────────────────────────────────

async def test_a_clock_that_stepped_back_does_not_block_the_whole_conversation_delete(cp, tmp_path, monkeypatch):
    ids = _chain(cp, 3, "Clock")
    root, two, three = ids
    with cp._lock:                                                      # the child's stamp is older than its parent's
        cp._conn.execute("UPDATE session_continuations SET created_at='2020-01-01T00:00:00+00:00' WHERE session_id=?",
                         (three,))
        cp._conn.commit()
    assert cp.lineage_members("root") == [root, two, three] == cp.lineage_members(three)
    for sid in ids:
        assert cp.set_archived(sid, True, at=_ago(300))
    _age(cp, 400, *ids)
    assert cp.expired_sessions(_ago(30), archived_before=_ago(30)) == [three, two, root]
    _orch, route = _delete_orch(cp, tmp_path, monkeypatch, ids)
    body = await _delete(route, "root", lineage=True)                   # it answered 409 has_continuations
    assert body["deleted"] == [three, two, root]
    assert cp.lineage_members("root") == []


def test_the_lineage_order_puts_every_session_after_the_one_it_continues(cp):
    _titled(cp, "root", "Tree")
    a = _continue(cp, "root")
    b = _continue(cp, "root")
    a2 = _continue(cp, a)
    b2 = _continue(cp, b)
    a3 = _continue(cp, a2)
    with cp._lock:                                                      # every stamp reversed
        for i, sid in enumerate([a3, b2, a2, b, a]):
            cp._conn.execute("UPDATE session_continuations SET created_at=? WHERE session_id=?",
                             (f"2020-01-0{i + 1}T00:00:00+00:00", sid))
        cp._conn.commit()
    order = cp.lineage_members(a2)
    assert order[0] == "root" and set(order) == {"root", a, b, a2, b2, a3}
    for child, parent in ((a, "root"), (b, "root"), (a2, a), (b2, b), (a3, a2)):
        assert order.index(child) > order.index(parent), (child, parent)
    for sid in order:
        assert cp.set_archived(sid, True, at=_ago(300))
    _age(cp, 400, *order)
    expired = cp.expired_sessions(_ago(30), archived_before=_ago(30))
    for child, parent in ((a, "root"), (b, "root"), (a2, a), (b2, b), (a3, a2)):
        assert expired.index(child) < expired.index(parent), (child, parent)
    assert cp.expired_sessions(_ago(30), archived_before=_ago(30), limit=2) == expired[:2]


# ── m2: the sweep's lists cost per row ───────────────────────────────────────────

def _bulk(cp, plain: int, big: int) -> int:
    old = _ago(400)
    rows, links = [], []
    for i in range(plain):
        rows.append((f"plain{i}", old, old, json.dumps({"title": f"plain chat {i}", "title_source": "first_words"})))
    rows.append(("bigroot", old, old, json.dumps({"title": "big", "title_source": "first_words"})))
    members = ["bigroot"]
    for j in range(big):
        sid = f"bigm{j}"
        rows.append((sid, old, old, json.dumps({"title": f"big #{j + 2}", "title_source": "lineage"})))
        links.append((sid, "i", uuid.uuid4().hex, members[(j * 7919) % len(members)], "i", "bigroot", "i", old, "[]",
                      "x", f"2025-01-01T00:00:00.{j:06d}+00:00"))
        members.append(sid)
    with cp._lock:
        cp._conn.executemany("INSERT INTO sessions(id,started_at,ended_at,turn_count,metadata) VALUES(?,?,?,1,?)", rows)
        cp._conn.executemany("INSERT INTO session_continuations VALUES(?,?,?,?,?,?,?,?,?,?,?)", links)
        cp._conn.commit()
    return len(rows)


def test_one_very_large_conversation_does_not_make_the_sweep_lists_slow(cp):
    total = _bulk(cp, 2000, 3000)
    started = time.perf_counter()
    assert len(cp.stale_sessions(_ago(30), limit=100_000)) == total
    assert len(cp.stale_sessions(_ago(30))) == 500
    with cp._lock:
        cp._conn.execute("UPDATE sessions SET metadata=json_set(metadata,'$.archived_at',?)", (_ago(300),))
        cp._conn.commit()
    expired = cp.expired_sessions(_ago(30), limit=100_000)
    assert len(expired) == total and expired[-1].startswith(("plain", "bigroot"))
    assert cp.lineage_others(["bigm5", "bigm2999", "plain1"]) == {"bigm5": 3000, "bigm2999": 3000}
    spent = time.perf_counter() - started
    assert spent < 4, spent                       # each list alone took 7 to 9 s under the store lock
    # one pinned member, one member in use: the whole conversation is out of both lists
    assert cp.set_pinned("bigm17", True)
    assert not any(sid.startswith("big") for sid in cp.expired_sessions(_ago(30), limit=100_000))
    assert len(cp.expired_sessions(_ago(30), limit=100_000)) == 2000


def test_the_lists_decide_as_before_for_a_conversation(cp):
    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    cp.create_session_record("solo")
    _age(cp, 40, "root", tip, "solo")
    assert set(cp.stale_sessions(_ago(30))) == {"root", tip, "solo"}
    _age(cp, 1, tip)
    assert cp.stale_sessions(_ago(30)) == ["solo"]                      # an idle root whose tip is in use stays
    _age(cp, 40, tip)
    assert cp.set_pinned("root", True) and cp.stale_sessions(_ago(30)) == ["solo"]
    assert cp.set_pinned("root", False)
    for sid in ("root", tip, "solo"):
        assert cp.set_archived(sid, True, at=_ago(35))
    assert cp.expired_sessions(_ago(30), archived_before=_ago(30)) == [tip, "root", "solo"] or \
        cp.expired_sessions(_ago(30), archived_before=_ago(30))[0] == tip
    with cp._lock:                                                      # one member back in the list
        cp._conn.execute("UPDATE sessions SET metadata=json_remove(metadata,'$.archived_at') WHERE id='root'")
        cp._conn.commit()
    assert cp.expired_sessions(_ago(30), archived_before=_ago(30)) == ["solo"]


# ── m3: a title write looks titles up, it does not read every session ────────────

def _statements(cp, action):
    seen: list[str] = []
    cp._conn.set_trace_callback(seen.append)
    try:
        action()
    finally:
        cp._conn.set_trace_callback(None)
    return seen


def test_a_title_write_reads_no_other_sessions_metadata(cp):
    for i in range(300):
        _titled(cp, f"s{i}", f"chat number {i}")
    _titled(cp, "root", "Trip plan")
    cp.create_session_record("new")
    cp.create_session_record("other")

    def metadata_reads(statements):
        """How many rows' metadata the statements could read: a lookup by key or id reads few."""
        scans = [sql for sql in statements if "metadata" in sql and sql.lstrip().upper().startswith("SELECT")
                 and "WHERE" not in sql.upper()]
        return scans

    for action in (lambda: cp.set_session_title("new", "chat number 7", "first_words"),
                   lambda: cp.rename_session("other", "A brand new name"),
                   lambda: cp.set_session_title("new", "Model name", "model", replace=("first_words",)),
                   lambda: _continue(cp, "root")):
        statements = _statements(cp, action)
        assert metadata_reads(statements) == [], statements
    assert _title(cp, "new") == "Model name"

    def plan(sql, params):
        return " | ".join(row[3] for row in cp._conn.execute("EXPLAIN QUERY PLAN " + sql, params))  # noqa: S608

    for sql, params in (("SELECT id, metadata FROM sessions WHERE title_key = ?", ("x",)),
                        ("SELECT id, metadata FROM sessions WHERE title_key >= ? AND title_key < ?", ("x #", "x $")),
                        ("SELECT id, metadata FROM sessions WHERE title_key IS NULL", ())):
        assert "idx_sessions_title_key" in plan(sql, params) and "SCAN" not in plan(sql, params)


def test_a_title_changed_by_a_writer_that_does_not_know_the_key_is_still_seen(cp):
    _titled(cp, "a", "First name")
    cp.create_session_record("b")
    with cp._lock:                                                      # an older hub, a script, a test
        cp._conn.execute("UPDATE sessions SET metadata=json_set(metadata,'$.title','Second name') WHERE id='a'")
        cp._conn.execute("INSERT INTO sessions(id, started_at, metadata) VALUES('raw', ?, ?)",
                         (_ago(1), json.dumps({"title": "Raw title", "title_source": "first_words"})))
        cp._conn.commit()
    with pytest.raises(st.TitleRefused):
        cp.rename_session("b", "second NAME")
    with pytest.raises(st.TitleRefused):
        cp.rename_session("b", "Raw title")
    assert cp.rename_session("b", "First name") is True                 # nobody carries it any more
    assert _titled(cp, "c", "Raw title") and _title(cp, "c") == "Raw title (2)"
    with cp._lock:                                                      # a stamp is not a title change
        key = cp._conn.execute("SELECT title_key FROM sessions WHERE id='c'").fetchone()[0]
    assert cp.set_pinned("c", True)
    with cp._lock:
        assert cp._conn.execute("SELECT title_key FROM sessions WHERE id='c'").fetchone()[0] == key == "raw title (2)"


def test_a_store_made_before_the_key_gets_it_filled_in(tmp_path):
    path = str(tmp_path / "old.db")
    first = CheckpointManager(path)
    first.initialize()
    _titled(first, "a", "Old chat")
    first.create_session_record("untitled")
    with first._lock:
        first._conn.execute("DROP TRIGGER session_title_key_stale")
        first._conn.execute("DROP INDEX idx_sessions_title_key")
        first._conn.execute("ALTER TABLE sessions DROP COLUMN title_key")
        first._conn.commit()
    first.close()
    again = CheckpointManager(path)
    again.initialize()
    try:
        keys = dict(again._conn.execute("SELECT id, title_key FROM sessions"))
        assert keys == {"a": "old chat", "untitled": ""}
        assert _titled(again, "b", "Old chat") and _title(again, "b") == "Old chat (2)"
        assert "title_key" not in again.get_sessions()[0]               # never part of a row's shape
    finally:
        again.close()


def test_the_dedupe_and_the_part_numbers_are_what_they_were(cp):
    for sid in ("h1", "h2", "h3"):
        _titled(cp, sid, "hello")
    assert [_title(cp, s) for s in ("h1", "h2", "h3")] == ["hello", "hello (2)", "hello (3)"]
    _titled(cp, "lit", "hello #2")                                      # a title of its own
    child = _continue(cp, "h1")
    assert _title(cp, child) == "hello #3"                              # numbers are never shared
    assert _title(cp, _continue(cp, child)) == "hello #4"
    _titled(cp, "issue", "Fix issue #12")
    assert _title(cp, _continue(cp, "issue")) == "Fix issue #12 #2"


# ── m4: the conversation's own name ──────────────────────────────────────────────

def test_the_only_row_of_a_conversation_can_take_the_conversations_own_first_name(cp, monkeypatch):
    _titled(cp, "root", "Trip plan")
    tip = _continue(cp, "root")
    _titled(cp, "other", "Other chat")
    other_tip = _continue(cp, "other")
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    assert set(_rows(client)) == {tip, other_tip}
    got = client.patch(f"/sessions/{tip}/title", json={"title": "Trip plan"})
    assert (got.status_code, got.json().get("title")) == (200, "Trip plan")       # it answered 409 title_taken
    assert _rows(client)[tip]["title"] == "Trip plan"
    assert sel.resolve_title(cp, "Trip plan") == tip == sel.resolve(cp, "Trip plan")
    # another conversation's names are still taken — its first name, its part numbers
    for name in ("Other chat", "other chat #2", "Other chat #7"):
        refused = client.patch(f"/sessions/{tip}/title", json={"title": name})
        assert (refused.status_code, refused.json()["reason"]) == (409, "title_taken"), name
    _turn(cp, "root")                                                   # both parts listed, one name: still one answer
    assert sel.resolve_title(cp, "Trip plan") == "root"
    _turn(cp, tip)
    assert sel.resolve_title(cp, "Trip plan") == tip


# ── m7: parts numbered before the model's title follow it ────────────────────────

def test_a_continuation_made_before_the_model_title_lands_takes_the_new_base(cp, monkeypatch):
    _titled(cp, "root", "can you help me plan a trip to brasov for")
    two = _continue(cp, "root")
    three = _continue(cp, two)
    renamed = _continue(cp, "root")
    assert cp.rename_session(renamed, "My own name")
    assert _title(cp, two) == "can you help me plan a trip to brasov for #2"
    assert cp.set_session_title("root", "Brasov trip planning", "model", replace=("first_words",))
    assert [_title(cp, s) for s in ("root", two, three, renamed)] == [
        "Brasov trip planning", "Brasov trip planning #2", "Brasov trip planning #3", "My own name"]
    assert [_meta(cp, s)["title_source"] for s in (two, three, renamed)] == ["lineage", "lineage", "human"]
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    assert {row["title"] for row in _rows(client).values()} == {"Brasov trip planning #3", "My own name"}
    assert sel.resolve_title(cp, "Brasov trip planning") in (three, renamed)
    assert _title(cp, _continue(cp, three)) == "Brasov trip planning #4"        # the count goes on (#4 was renamed)
    with pytest.raises(sel.SessionSelectionError):
        sel.resolve_title(cp, "can you help me plan a trip to brasov for")       # nobody goes by it now


def test_a_part_whose_new_name_is_taken_keeps_the_one_it_has(cp):
    _titled(cp, "root", "first words here")
    two = _continue(cp, "root")
    _titled(cp, "squatter", "Model name #2")
    assert cp.set_session_title("root", "Model name", "model", replace=("first_words",))
    assert _title(cp, two) == "first words here #2" and _title(cp, "squatter") == "Model name #2"


# ── nits ─────────────────────────────────────────────────────────────────────────

def test_a_dedupe_suffix_never_takes_a_title_past_its_bound(cp):
    words = "z" * st.MAX_TITLE_CHARS
    for sid in ("l1", "l2", "l3"):
        _titled(cp, sid, words)
    titles = [_title(cp, s) for s in ("l1", "l2", "l3")]
    assert titles[0] == words and len(set(titles)) == 3
    assert all(len(t) <= st.MAX_TITLE_CHARS for t in titles), [len(t) for t in titles]   # it wrote 52
    assert titles[1].endswith("… (2)") and titles[2].endswith("… (3)")
    model = "m" * st.MAX_MODEL_TITLE_CHARS
    for sid in ("m1", "m2"):
        cp.create_session_record(sid)
        assert cp.set_session_title(sid, model, "model")
    assert len(_title(cp, "m2")) <= st.MAX_MODEL_TITLE_CHARS and _title(cp, "m2").endswith("(2)")
    assert st.distinct_title("abc", ["abc"]) == "abc (2)" and st.with_suffix("abcdef", " (2)", 8) == "abc… (2)"


def test_no_part_name_is_longer_than_a_rename_accepts(cp, monkeypatch):
    cp.create_session_record("root")
    assert cp.rename_session("root", "w" * st.MAX_HUMAN_TITLE_CHARS)
    parts = ["root"]
    for _ in range(11):
        parts.append(_continue(cp, parts[-1]))
    titles = [_title(cp, s) for s in parts[1:]]
    assert all(len(t) <= st.MAX_HUMAN_TITLE_CHARS for t in titles), [len(t) for t in titles]   # it wrote 103
    assert [t.rsplit("#", 1)[1] for t in titles] == [str(n) for n in range(2, 13)]
    assert len({t.rsplit(" #", 1)[0] for t in titles}) == 1             # one stem for the whole conversation
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))
    again = client.patch(f"/sessions/{parts[-1]}/title", json={"title": titles[-1]})
    assert again.status_code == 200                                     # the route takes the name it shows
    assert sel.resolve_title(cp, titles[3]) == parts[-1]


def test_a_rename_gives_the_same_answer_for_a_real_id_and_a_made_up_one(cp, monkeypatch):
    from agents.core.session_import import import_turns

    _titled(cp, "native", "Native chat")
    imported = import_turns(cp, source="claude", external_id="e1", request_id=_request(990), source_sha256=None,
                            turns=[{"role": "user", "content": "secret words", "timestamp": "2026-10-01T00:00:00+00:00"}]
                            )["session_id"]
    client = _client(monkeypatch, SimpleNamespace(checkpoints=cp))

    def rename(title):
        got = client.patch("/sessions/native/title", json={"title": title})
        return got.status_code, got.json().get("reason")

    made_up = "session_" + "0" * 32
    assert rename(imported) == rename(made_up) == (400, "title_reserved")         # the made-up one answered 200
    assert rename(f"  {made_up} ") == (400, "title_reserved")
    assert _title(cp, "native") == "Native chat"
    assert cp.set_session_title("fresh", made_up, "first_words") is False
    assert rename("session notes") == (200, None)
