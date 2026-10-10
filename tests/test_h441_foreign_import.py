"""H441 immutable import receipt, replay, and strict hydration."""

import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from agents.cli.foreign_sessions import ForeignSourceError, discover, read_file
from agents.core.checkpoint import CheckpointManager
from agents.core.foreign_history import ForeignHistoryRefused, status, validate_turn_lineage
from agents.core.memory import persistence
from agents.core.memory.manager import MemoryManager
from agents.core.session_continuation import (
    ContinuationRefused,
    ContinuationStore,
    create_continuation,
    prepare_session,
)
from agents.core.session_import import import_turns


@pytest.fixture
def store(tmp_path):
    cp = CheckpointManager(str(tmp_path / "history.db"))
    cp.initialize()
    yield cp
    cp.close()


def turns():
    return [
        {"role": "user", "content": "old user text", "timestamp": "2026-10-01T00:00:00+00:00"},
        {"role": "assistant", "content": "old answer", "timestamp": "2026-10-01T00:01:00+00:00",
         "tools": ["Read"]},
    ]


def test_import_is_atomic_replayable_and_private_without_metadata(store):
    request = str(uuid.uuid4())
    first = import_turns(store, source="claude", external_id="foreign-1", turns=turns(), request_id=request)
    second = import_turns(store, source="claude", external_id="foreign-1", turns=turns(), request_id=request)
    assert first == second
    assert status(store, first["session_id"]).kind == "imported"
    with store._lock, store._conn:
        store._conn.execute("UPDATE sessions SET metadata='{}' WHERE id=?", (first["session_id"],))
    with pytest.raises(ForeignHistoryRefused):
        status(store, first["session_id"])
    with store._lock, store._conn:
        store._conn.execute("DELETE FROM session_imports WHERE session_id=?", (first["session_id"],))
    with pytest.raises(ForeignHistoryRefused):
        status(store, first["session_id"])


def test_orphan_foreign_binding_cannot_become_native(store):
    imported = import_turns(store, source="claude", external_id="orphan", turns=turns(),
                            request_id=str(uuid.uuid4()))
    sid = imported["session_id"]
    with store._lock, store._conn:
        store._conn.execute("DELETE FROM session_imports WHERE session_id=?", (sid,))
        store._conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
    with pytest.raises(ForeignHistoryRefused):
        status(store, sid)


def test_same_source_changed_content_is_a_new_import(store):
    first = import_turns(store, source="codex", external_id="foreign-1", turns=turns(),
                         request_id=str(uuid.uuid4()))
    changed = turns()
    changed[0]["content"] = "new content"
    second = import_turns(store, source="codex", external_id="foreign-1", turns=changed,
                          request_id=str(uuid.uuid4()))
    assert first["session_id"] != second["session_id"]


def test_invalid_import_rolls_back_all_rows(store):
    invalid = turns()
    invalid[0]["role"] = "system"
    with pytest.raises(ForeignHistoryRefused):
        import_turns(store, source="claude", external_id="foreign-2", turns=invalid,
                     request_id=str(uuid.uuid4()))
    assert store._conn.execute("SELECT COUNT(*) FROM session_imports").fetchone()[0] == 0
    assert store._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_pre_h441_three_column_binding_migrates_before_foreign_receipt_probe(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE session_history_instances("
                     "session_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL, "
                     "allow_legacy INTEGER NOT NULL DEFAULT 0)")
    cp = CheckpointManager(str(path))
    cp.initialize()
    try:
        columns = {row[1] for row in cp._conn.execute("PRAGMA table_info(session_history_instances)")}
        assert "foreign_lineage" in columns
        assert cp._conn.execute("SELECT 1 FROM session_imports").fetchone() is None
    finally:
        cp.close()


def test_equal_source_timestamps_preserve_each_turn_origin(store):
    shared = turns()
    shared[1]["timestamp"] = shared[0]["timestamp"]
    imported = import_turns(store, source="claude", external_id="same-clock", turns=shared,
                            request_id=str(uuid.uuid4()))
    from agents.core.foreign_history import seed
    rows = seed(store, imported["session_id"])
    validate_turn_lineage(store, imported["session_id"], rows)
    rows[0].pop("foreign_origin")
    with pytest.raises(ForeignHistoryRefused):
        validate_turn_lineage(store, imported["session_id"], rows)


@pytest.mark.asyncio
async def test_seed_hydrates_after_restart_and_corrupt_present_snapshot_refuses(store, tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path / "memory")
    imported = import_turns(store, source="claude", external_id="foreign-3", turns=turns(),
                            request_id=str(uuid.uuid4()))
    sid = imported["session_id"]
    memory = MemoryManager(graph_backend="memory")
    memory.set_checkpoint_manager(store)
    orch = SimpleNamespace(memory=memory, checkpoints=store)
    await prepare_session(orch, sid)
    history = await memory.get_history(sid)
    assert [item["foreign_origin"] for item in history] == ["claude", "claude"]
    await memory.add_turn(sid, "assistant", "new local reply")
    assert persistence.load_memory_snapshot(sid)["foreign_history"]["kind"] == "imported"
    restarted = MemoryManager(graph_backend="memory")
    restarted.set_checkpoint_manager(store)
    await prepare_session(SimpleNamespace(memory=restarted, checkpoints=store), sid)
    assert (await restarted.get_history(sid))[-1]["content"] == "new local reply"
    (tmp_path / "memory" / f"{sid}.json").write_text("{ broken", encoding="utf-8")
    fresh = MemoryManager(graph_backend="memory")
    fresh.set_checkpoint_manager(store)
    with pytest.raises(ContinuationRefused) as caught:
        await prepare_session(SimpleNamespace(memory=fresh, checkpoints=store), sid)
    assert caught.value.reason == "invalid_history"


@pytest.mark.asyncio
async def test_continuation_is_derived_and_stays_private_after_foreign_turns_age_out(store, tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path / "memory")
    imported = import_turns(store, source="codex", external_id="foreign-4", turns=turns(),
                            request_id=str(uuid.uuid4()))
    source = imported["session_id"]
    memory = MemoryManager(graph_backend="memory")
    memory.set_checkpoint_manager(store)
    await prepare_session(SimpleNamespace(memory=memory, checkpoints=store), source)
    carried = await memory.get_history(source)
    continued = ContinuationStore(store).create(source, str(uuid.uuid4()), carried,
                                               store.clock_snapshot(source))
    child = continued["session_id"]
    assert status(store, child).kind == "derived"
    await prepare_session(SimpleNamespace(memory=memory, checkpoints=store), child)
    memory.conversation.max_turns = 1
    await memory.add_turn(child, "user", "new local question")
    await memory.add_turn(child, "assistant", "new local reply")
    assert status(store, child).kind == "derived"
    history = await memory.get_history(child)
    assert all("foreign_origin" not in turn for turn in history)
    assert history[-1]["content"] == "new local reply"
    assert child in memory.conversation.foreign_origins


@pytest.mark.asyncio
async def test_corrupt_foreign_parent_refuses_continuation_with_route_error(store, tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path / "memory")
    imported = import_turns(store, source="codex", external_id="corrupt-parent", turns=turns(),
                            request_id=str(uuid.uuid4()))
    sid = imported["session_id"]
    with store._lock, store._conn:
        store._conn.execute("UPDATE sessions SET metadata='{}' WHERE id=?", (sid,))

    @asynccontextmanager
    async def turn_lease(_sid):
        yield True

    memory = MemoryManager(graph_backend="memory")
    memory.set_checkpoint_manager(store)
    orch = SimpleNamespace(memory=memory, checkpoints=store, turn_lease=turn_lease)
    with pytest.raises(ContinuationRefused) as caught:
        await create_continuation(orch, sid, str(uuid.uuid4()))
    assert caught.value.reason == "foreign_history_unavailable"


@pytest.mark.asyncio
async def test_seed_only_import_rewind_keeps_durable_private_lineage(store, tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path / "memory")
    imported = import_turns(store, source="claude", external_id="rewind-seed", turns=turns(),
                            request_id=str(uuid.uuid4()))
    sid = imported["session_id"]
    memory = MemoryManager(graph_backend="memory")
    memory.set_checkpoint_manager(store)
    await prepare_session(SimpleNamespace(memory=memory, checkpoints=store), sid)
    clock = store.clock_snapshot(sid)
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    result = await memory.commit_rollback_rewind(ticket)
    assert result.removed_turns == 2
    document = persistence.load_memory_snapshot(sid)
    assert document["foreign_history"]["kind"] == "imported"
    assert document["rewound"] is True and document["turns"] == []
    persistence.save_memory("newer_native", [{"role": "user", "content": "other"}])
    fresh = MemoryManager(graph_backend="memory")
    fresh.set_checkpoint_manager(store)
    assert sid not in fresh.conversation.foreign_origins
    assert await fresh.resume_session(sid)
    assert sid in fresh.conversation.foreign_origins
    await prepare_session(SimpleNamespace(memory=fresh, checkpoints=store), sid)
    assert status(store, sid).kind == "imported"


def test_source_specific_synthetic_jsonl_excludes_system_reasoning_and_tool_payload(tmp_path):
    claude = tmp_path / "claude.jsonl"
    claude.write_text("\n".join([
        '{"type":"system","message":{"role":"system","content":"private"}}',
        '{"type":"user","sessionId":"foreign-1","timestamp":"2026-10-01T00:00:00Z","message":{"role":"user","content":"hi"}}',
        '{"type":"assistant","sessionId":"foreign-1","timestamp":"2026-10-01T00:01:00Z","message":{"role":"assistant","content":[{"type":"thinking","thinking":"hidden"},{"type":"text","text":"hello"},{"type":"tool_use","name":"Read","input":{"secret":"no"}}]}}',
    ]), encoding="utf-8")
    parsed = read_file("claude", claude)
    assert parsed["external_id"] == "foreign-1"
    assert [row["content"] for row in parsed["turns"]] == ["hi", "hello"]
    assert parsed["turns"][1]["tools"] == ["Read"]
    assert "hidden" not in repr(parsed) and "secret" not in repr(parsed)
    codex = tmp_path / "codex.jsonl"
    codex.write_text("\n".join([
        '{"type":"event_msg","timestamp":"2026-10-01T00:00:00Z","payload":{"type":"user_message","message":"question"}}',
        '{"type":"event_msg","timestamp":"2026-10-01T00:01:00Z","payload":{"type":"agent_message","message":"answer"}}',
    ]), encoding="utf-8")
    assert [row["content"] for row in read_file("codex", codex)["turns"]] == ["question", "answer"]
    link = tmp_path / "link.jsonl"
    link.symlink_to(claude)
    with pytest.raises(ForeignSourceError):
        read_file("claude", link)


def test_codex_rollout_metadata_id_text_blocks_and_duplicate_events(tmp_path):
    root = tmp_path / ".codex" / "sessions" / "2026" / "10"
    root.mkdir(parents=True)
    uid = "39d28bc2-a3e2-4ff0-ad62-ff5849af646a"
    path = root / f"rollout-2026-10-10T00-00-00-{uid}.jsonl"
    path.write_text("\n".join([
        json.dumps({"type": "session_meta", "payload": {"id": uid}}),
        json.dumps({"type": "event_msg", "timestamp": "2026-10-01T00:00:00Z",
                    "payload": {"type": "user_message", "message": "question"}}),
        json.dumps({"type": "response_item", "timestamp": "2026-10-01T00:00:01Z",
                    "payload": {"type": "message", "role": "user",
                                "content": [{"type": "input_text", "text": "question"}]}}),
        json.dumps({"type": "response_item", "timestamp": "2026-10-01T00:01:00Z",
                    "payload": {"type": "message", "role": "assistant",
                                "content": [{"type": "output_text", "text": "answer"}]}}),
        json.dumps({"type": "response_item", "timestamp": "2026-10-01T00:01:01Z",
                    "payload": {"type": "function_call", "name": "shell_command",
                                "arguments": "private arguments"}}),
    ]), encoding="utf-8")
    parsed = read_file("codex", path)
    assert parsed["external_id"] == uid
    assert [row["content"] for row in parsed["turns"]][:2] == ["question", "answer"]
    assert parsed["turns"][2]["tools"] == ["shell_command"]
    assert "private arguments" not in repr(parsed)
    assert discover("codex", uid, home=tmp_path) == path


def test_codex_selector_uses_session_metadata_even_when_filename_lacks_id(tmp_path):
    root = tmp_path / ".codex" / "sessions"
    root.mkdir(parents=True)
    uid = "8ff6a74f-bc31-4908-9c67-2b4075531995"
    path = root / "rollout.jsonl"
    path.write_text("\n".join([
        json.dumps({"type": "session_meta", "payload": {"id": uid}}),
        json.dumps({"type": "event_msg", "timestamp": "2026-10-01T00:00:00Z",
                    "payload": {"type": "user_message", "message": "question"}}),
    ]), encoding="utf-8")
    assert discover("codex", uid, home=tmp_path) == path


def test_claude_selector_rejects_filename_with_different_session_id(tmp_path):
    root = tmp_path / ".claude" / "projects" / "project"
    root.mkdir(parents=True)
    path = root / "claimed.jsonl"
    path.write_text(json.dumps({"type": "user", "sessionId": "actual",
                                "timestamp": "2026-10-01T00:00:00Z",
                                "message": {"role": "user", "content": "hello"}}), encoding="utf-8")
    with pytest.raises(ForeignSourceError):
        discover("claude", "claimed", home=tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="FIFO nonblocking opening is POSIX-specific")
def test_foreign_fifo_named_jsonl_is_refused_without_waiting(tmp_path):
    path = tmp_path / "stall.jsonl"
    os.mkfifo(path)
    with pytest.raises(ForeignSourceError):
        read_file("claude", path)
