"""Rewind verification follows actual cold-binding lifecycle without global outage."""

import pytest

from agents.core.checkpoint import CheckpointManager
from agents.core.memory import conversation, persistence
from agents.core.memory.manager import MemoryManager, RewindRefused


@pytest.fixture
def context(tmp_path, monkeypatch):
    root = tmp_path / "memory"
    monkeypatch.setattr(persistence, "MEMORY_DIR", root)
    monkeypatch.setattr(conversation, "MEMORY_DIR", root)
    checkpoints = CheckpointManager(str(tmp_path / "checkpoints.db"))
    checkpoints.initialize()
    memory = MemoryManager()
    memory.set_checkpoint_manager(checkpoints)
    yield memory, checkpoints, root
    checkpoints.close()


async def rewind(memory, checkpoints, sid):
    await memory.new_session(sid)
    await memory.add_turn(sid, "user", "keep")
    await memory.add_turn(sid, "assistant", "kept answer")
    await memory.add_turn(sid, "user", "removed request")
    clock = checkpoints.clock_snapshot(sid)
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.commit_rollback_rewind(ticket)


@pytest.mark.asyncio
async def test_cold_binding_defers_valid_head_until_real_initialize(context):
    memory, checkpoints, _ = context
    sid = "valid_rewind"
    await rewind(memory, checkpoints, sid)
    cold = CheckpointManager(checkpoints.db_path)
    restarted = MemoryManager()
    # Orchestrator constructs and binds the manager before it initializes SQLite.
    restarted.set_checkpoint_manager(cold)
    try:
        with pytest.raises(RewindRefused):
            await restarted.get_history(sid)
        cold.initialize()
        assert [row["content"] for row in await restarted.get_history(sid)] == ["keep", "kept answer"]
        await restarted.add_turn(sid, "user", "next request")
        assert [row["content"] for row in await restarted.get_history(sid)] == [
            "keep", "kept answer", "next request"
        ]
    finally:
        cold.close()


@pytest.mark.asyncio
async def test_corrupt_inactive_rewind_blocks_only_its_session(context):
    memory, checkpoints, root = context
    bad = "corrupt_rewind"
    await rewind(memory, checkpoints, bad)
    healthy = await memory.new_session("healthy_session")
    await memory.add_turn(healthy, "user", "healthy history")
    (root / f"{bad}.json").write_text("{broken", encoding="utf-8")
    restarted = MemoryManager()
    restarted.set_checkpoint_manager(checkpoints)
    assert await restarted.resume_session(healthy)
    assert [row["content"] for row in await restarted.get_history(healthy)] == ["healthy history"]
    await restarted.add_turn(healthy, "assistant", "healthy answer")
    assert (await restarted.new_session("new_healthy_session")) == "new_healthy_session"
    with pytest.raises(RewindRefused):
        await restarted.get_history(bad)
    with pytest.raises(RewindRefused):
        await restarted.resume_session(bad)
    with pytest.raises(RewindRefused):
        await restarted.add_turn(bad, "user", "must not replace corrupt snapshot")
    assert (root / f"{bad}.json").read_text(encoding="utf-8") == "{broken"


@pytest.mark.asyncio
async def test_existing_sync_snapshot_save_is_exact_head_noop_after_rewind(context):
    memory, checkpoints, root = context
    sid = "sync_save_after_rewind"
    await rewind(memory, checkpoints, sid)
    for appended in (False, True):
        if appended:
            await memory.add_turn(sid, "user", "next request")
        path = root / f"{sid}.json"
        before = path.read_bytes()
        head = checkpoints._conn.execute(
            "SELECT revision,snapshot_sha256 FROM session_history_rewinds WHERE session_id=?", (sid,)
        ).fetchone()
        memory.conversation._save_snapshot(sid)
        assert path.read_bytes() == before
        assert checkpoints._conn.execute(
            "SELECT revision,snapshot_sha256 FROM session_history_rewinds WHERE session_id=?", (sid,)
        ).fetchone() == head


@pytest.mark.asyncio
async def test_same_revision_changed_history_cannot_replace_rewind_head(context):
    memory, checkpoints, root = context
    sid = "changed_sync_save_after_rewind"
    await rewind(memory, checkpoints, sid)
    path = root / f"{sid}.json"
    before = path.read_bytes()
    head = checkpoints._conn.execute(
        "SELECT revision,snapshot_sha256 FROM session_history_rewinds WHERE session_id=?", (sid,)
    ).fetchone()
    altered = [turn.to_dict() for turn in memory.conversation.sessions[sid]]
    altered[-1]["content"] = "erased tail resurrected without a new revision"
    with pytest.raises(persistence.SnapshotRevisionConflict):
        persistence.save_memory(
            sid, altered, instance_id=memory.conversation.instances[sid],
            revision=memory.conversation.revisions[sid], checkpoint_mgr=checkpoints,
            require_rewind=True,
        )
    assert path.read_bytes() == before
    assert checkpoints._conn.execute(
        "SELECT revision,snapshot_sha256 FROM session_history_rewinds WHERE session_id=?", (sid,)
    ).fetchone() == head
