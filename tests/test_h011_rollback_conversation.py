"""H011 rollback conversation dependency: durable, current-tail-only rewind."""
from __future__ import annotations

import json

import pytest

from agents.core.checkpoint import CheckpointManager
from agents.core.llm.vision_history import ActiveImageUnavailable
from agents.core.memory import conversation, persistence
from agents.core.memory.conversation import ConversationMemory
from agents.core.memory.manager import MemoryManager, RewindRefused
from agents.core.session_continuation import ContinuationStore


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path / "memory")
    cp = CheckpointManager(str(tmp_path / "checkpoints.db"))
    cp.initialize()
    memory = MemoryManager()
    memory.set_checkpoint_manager(cp)
    yield memory, cp, tmp_path / "memory"
    cp.close()


async def begin(memory, cp, sid="session_rollback"):
    await memory.new_session(sid)
    clock = cp.clock_snapshot(sid)
    assert clock and clock.instance_id
    return sid, clock


@pytest.mark.asyncio
async def test_rewind_current_last_user_and_suffix_persists_without_rewriting_audit(context):
    memory, cp, root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "older request")
    await memory.add_turn(sid, "assistant", "older answer", tools=["read_file"])
    await memory.add_turn(sid, "user", "edit the file")
    await memory.add_turn(sid, "assistant", "tool output", tools=["write_file"])
    await memory.add_turn(sid, "assistant", "done")
    audit = (root / f"{sid}.jsonl").read_bytes()
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    result = await memory.commit_rollback_rewind(ticket)
    assert result.removed_turns == 3
    assert [row["content"] for row in await memory.get_history(sid)] == ["older request", "older answer"]
    assert (root / f"{sid}.jsonl").read_bytes() == audit
    restarted = MemoryManager()
    restarted.set_checkpoint_manager(cp)
    assert [row["content"] for row in await restarted.get_history(sid)] == ["older request", "older answer"]
    assert cp._conn.execute("SELECT turn_count FROM sessions WHERE id=?", (sid,)).fetchone()[0] == 2


@pytest.mark.asyncio
async def test_prepared_tail_refuses_concurrent_append_and_keeps_active_images(context):
    memory, cp, root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "edit")
    instance = memory.conversation.active_image_instance(sid)
    handle = memory.conversation.active_images.remember(sid, instance, "jarvis", "image", "answer", [b"private"])
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.add_turn(sid, "assistant", "late unrelated append")
    with pytest.raises(RewindRefused):
        await memory.commit_rollback_rewind(ticket)
    assert [row["content"] for row in await memory.get_history(sid)] == ["edit", "late unrelated append"]
    assert memory.conversation.active_images.resolve(sid, instance, "jarvis", [handle]) == (b"private",)
    assert len(persistence.load_memory(sid)) == 2


@pytest.mark.asyncio
async def test_empty_continuation_rewind_survives_restart_and_never_replays_seed(context):
    memory, cp, root = context
    source, _ = await begin(memory, cp, "source_session")
    await memory.add_turn(source, "user", "seed ask")
    seed = await memory.get_history(source)
    child = ContinuationStore(cp).create(
        source, "00000000-0000-4000-8000-000000000011", seed, cp.clock_snapshot(source)
    )["session_id"]
    assert await memory.resume_session(child)
    clock = cp.clock_snapshot(child)
    ticket = await memory.prepare_rollback_rewind(child, clock.instance_id, clock)
    assert (await memory.commit_rollback_rewind(ticket)).removed_turns == 1
    assert await memory.get_history(child) == []
    memory.conversation.sessions.pop(child)
    assert await memory.resume_session(child)
    assert await memory.get_history(child) == []
    await memory.add_turn(child, "user", "new post-undo ask")
    assert [r["content"] for r in await memory.get_history(child)] == ["new post-undo ask"]
    memory.conversation.sessions.pop(child)
    (root / f"{child}.json").unlink()
    with pytest.raises(RewindRefused):
        await memory.resume_session(child)
    assert ContinuationStore(cp).seed(child) == seed  # immutable audit lineage, never visible fallback


@pytest.mark.asyncio
async def test_rewind_snapshot_failure_does_not_publish_or_clear_images(context, monkeypatch):
    memory, cp, root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "edit")
    before = (root / f"{sid}.json").read_bytes()
    instance = memory.conversation.active_image_instance(sid)
    handle = memory.conversation.active_images.remember(sid, instance, "jarvis", "image", "answer", [b"private"])
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    monkeypatch.setattr(persistence, "atomic_write_json", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(RewindRefused):
        await memory.commit_rollback_rewind(ticket)
    assert [r["content"] for r in await memory.get_history(sid)] == ["edit"]
    assert (root / f"{sid}.json").read_bytes() == before
    assert memory.conversation.active_images.resolve(sid, instance, "jarvis", [handle]) == (b"private",)


@pytest.mark.asyncio
async def test_clock_or_instance_change_refuses_stale_ticket(context):
    memory, cp, root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "edit")
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    assert cp.commit_clock(clock, "new compaction") is not None
    with pytest.raises(RewindRefused):
        await memory.commit_rollback_rewind(ticket)
    assert [r["content"] for r in await memory.get_history(sid)] == ["edit"]


@pytest.mark.asyncio
async def test_stale_second_process_cannot_resurrect_rewound_exchange(context):
    memory, cp, root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "edit")
    # Model a second process which read the same snapshot before the rewind.
    stale_cp = CheckpointManager(str(root.parent / "checkpoints.db"))
    stale_cp.initialize()
    stale = MemoryManager()
    stale.set_checkpoint_manager(stale_cp)
    assert [r["content"] for r in await stale.get_history(sid)] == ["edit"]
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.commit_rollback_rewind(ticket)
    try:
        with pytest.raises(RewindRefused):
            await stale.add_turn(sid, "assistant", "stale completion")
        with pytest.raises(RewindRefused):
            await stale.get_history(sid)
        with pytest.raises(RuntimeError):
            await stale.conversation.get_history(sid)
        assert persistence.load_memory(sid) == []
    finally:
        stale_cp.close()


@pytest.mark.asyncio
async def test_continuation_refuses_uncommitted_or_missing_rewind_head(context):
    memory, cp, root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "seed")
    child = ContinuationStore(cp).create(
        sid, "00000000-0000-4000-8000-000000000012", await memory.get_history(sid), clock
    )["session_id"]
    assert await memory.resume_session(child)
    child_clock = cp.clock_snapshot(child)
    ticket = await memory.prepare_rollback_rewind(child, child_clock.instance_id, child_clock)
    await memory.commit_rollback_rewind(ticket)
    path = root / f"{child}.json"
    memory.conversation.sessions.pop(child)
    cp._conn.execute("DELETE FROM session_history_rewinds WHERE session_id=?", (child,))
    cp._conn.commit()
    with pytest.raises(RewindRefused):
        await memory.resume_session(child)
    cp._conn.execute(
        "INSERT INTO session_history_rewinds VALUES(?,?,?,?)",
        (child, ticket.instance_id, ticket.revision + 1,
         persistence.snapshot_digest(json.loads(path.read_text()))),
    )
    cp._conn.commit()
    path.write_text("{broken")
    with pytest.raises(RewindRefused):
        await memory.resume_session(child)


@pytest.mark.asyncio
async def test_changed_disk_snapshot_refuses_prepared_rewind(context):
    memory, cp, root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "edit")
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    path = root / f"{sid}.json"
    document = json.loads(path.read_text())
    document["unexpected"] = True
    path.write_text(json.dumps(document))
    with pytest.raises(RewindRefused):
        await memory.commit_rollback_rewind(ticket)
    assert [r["content"] for r in await memory.get_history(sid)] == ["edit"]


@pytest.mark.asyncio
async def test_sqlite_marker_failure_compensates_snapshot(context):
    memory, cp, root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "edit")
    path = root / f"{sid}.json"
    original = path.read_bytes()
    cp._conn.execute("""CREATE TRIGGER reject_rewind BEFORE INSERT ON session_history_rewinds
        BEGIN SELECT RAISE(ABORT, 'injected marker failure'); END""")
    cp._conn.commit()
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    with pytest.raises(RewindRefused):
        await memory.commit_rollback_rewind(ticket)
    assert path.read_bytes() == original
    assert [r["content"] for r in await memory.get_history(sid)] == ["edit"]
    assert cp._conn.execute(
        "SELECT 1 FROM session_history_rewinds WHERE session_id=?", (sid,)
    ).fetchone() is None


@pytest.mark.asyncio
async def test_success_invalidates_images_and_queued_embeddings(context):
    memory, cp, _root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "edit")
    instance = memory.conversation.active_image_instance(sid)
    handle = memory.conversation.active_images.remember(
        sid, instance, "jarvis", "image", "answer", [b"private"]
    )
    before_epoch = memory._session_epochs.get(sid, 0)
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.commit_rollback_rewind(ticket)
    with pytest.raises(ActiveImageUnavailable):
        memory.conversation.active_images.resolve(sid, instance, "jarvis", [handle])
    assert memory._session_epochs[sid] == before_epoch + 1


@pytest.mark.asyncio
async def test_ordinary_restart_quarantines_json_without_committed_marker(context):
    memory, cp, _root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "edit")
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.commit_rollback_rewind(ticket)
    cp._conn.execute("DELETE FROM session_history_rewinds WHERE session_id=?", (sid,))
    cp._conn.commit()
    restarted = MemoryManager()
    restarted.set_checkpoint_manager(cp)
    with pytest.raises(RewindRefused):
        await restarted.get_history(sid)
    assert sid in restarted._rewind_inconsistent


@pytest.mark.asyncio
async def test_standalone_conversation_never_publishes_unverified_rewind(context):
    memory, cp, _root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "edit")
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.commit_rollback_rewind(ticket)
    standalone = ConversationMemory()
    with pytest.raises(RuntimeError):
        await standalone.get_history(sid)
    with pytest.raises(RuntimeError):
        await standalone.resume_session(sid)


@pytest.mark.asyncio
async def test_ordinary_boot_quarantines_corrupt_committed_rewind_snapshot(context):
    memory, cp, root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "edit")
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.commit_rollback_rewind(ticket)
    (root / f"{sid}.json").write_text("{broken")
    restarted = MemoryManager()
    restarted.set_checkpoint_manager(cp)
    with pytest.raises(RewindRefused):
        await restarted.get_history(sid)
    assert sid in restarted._rewind_inconsistent


@pytest.mark.asyncio
async def test_reused_session_identity_refuses_prepared_ticket(context):
    memory, cp, _root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "edit")
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    newer = "11111111111111111111111111111111"
    cp._conn.execute("UPDATE sessions SET instance_id=? WHERE id=?", (newer, sid))
    cp._conn.execute("UPDATE session_history_instances SET instance_id=? WHERE session_id=?", (newer, sid))
    cp._conn.execute("UPDATE session_clock SET instance_id=? WHERE session_id=?", (newer, sid))
    cp._conn.commit()
    with pytest.raises(RewindRefused):
        await memory.commit_rollback_rewind(ticket)
    assert [r["content"] for r in await memory.get_history(sid)] == ["edit"]


@pytest.mark.asyncio
async def test_post_rewind_append_advances_exact_durable_head_and_loads(context):
    memory, cp, root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "old edit")
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.commit_rollback_rewind(ticket)
    old_head = cp._conn.execute(
        "SELECT revision,snapshot_sha256 FROM session_history_rewinds WHERE session_id=?", (sid,)
    ).fetchone()
    await memory.add_turn(sid, "user", "new request")
    snapshot = json.loads((root / f"{sid}.json").read_text())
    head = cp._conn.execute(
        "SELECT revision,snapshot_sha256 FROM session_history_rewinds WHERE session_id=?", (sid,)
    ).fetchone()
    assert head == (old_head[0] + 1, persistence.snapshot_digest(snapshot))
    await memory.add_turn(sid, "assistant", "new answer")
    snapshot = json.loads((root / f"{sid}.json").read_text())
    head = cp._conn.execute(
        "SELECT revision,snapshot_sha256 FROM session_history_rewinds WHERE session_id=?", (sid,)
    ).fetchone()
    assert head == (old_head[0] + 2, persistence.snapshot_digest(snapshot))
    restarted = MemoryManager()
    restarted.set_checkpoint_manager(cp)
    assert [r["content"] for r in await restarted.get_history(sid)] == ["new request", "new answer"]


@pytest.mark.asyncio
async def test_ordinary_boot_rejects_forged_higher_revision_removed_tail(context):
    memory, cp, root = context
    sid, clock = await begin(memory, cp)
    for role, content in [("user", "keep"), ("assistant", "kept"),
                          ("user", "removed edit"), ("assistant", "removed answer")]:
        await memory.add_turn(sid, role, content)
    original = await memory.get_history(sid)
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.commit_rollback_rewind(ticket)
    await memory.add_turn(sid, "user", "legitimate new request")
    path = root / f"{sid}.json"
    forged = json.loads(path.read_text())
    forged["turns"] = original + forged["turns"][-1:]
    forged["revision"] += 1
    path.write_text(json.dumps(forged))
    restarted = MemoryManager()
    restarted.set_checkpoint_manager(cp)
    with pytest.raises(RewindRefused):
        await restarted.get_history(sid)


@pytest.mark.asyncio
async def test_continuation_refuses_forged_higher_revision_seed_replay(context):
    memory, cp, root = context
    source, clock = await begin(memory, cp, "rewind_source")
    await memory.add_turn(source, "user", "removed carried seed")
    seed = await memory.get_history(source)
    child = ContinuationStore(cp).create(
        source, "00000000-0000-4000-8000-000000000013", seed, clock
    )["session_id"]
    assert await memory.resume_session(child)
    child_clock = cp.clock_snapshot(child)
    ticket = await memory.prepare_rollback_rewind(child, child_clock.instance_id, child_clock)
    await memory.commit_rollback_rewind(ticket)
    await memory.add_turn(child, "user", "legitimate new request")
    path = root / f"{child}.json"
    forged = json.loads(path.read_text())
    forged["turns"] = seed + forged["turns"]
    forged["revision"] += 1
    path.write_text(json.dumps(forged))
    memory.conversation.sessions.pop(child)
    with pytest.raises(RewindRefused):
        await memory.resume_session(child)


@pytest.mark.asyncio
async def test_failed_post_rewind_head_update_restores_snapshot_and_memory(context):
    memory, cp, root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "removed")
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.commit_rollback_rewind(ticket)
    before = (root / f"{sid}.json").read_bytes()
    cp._conn.execute("""CREATE TRIGGER reject_rewind_advance BEFORE UPDATE ON session_history_rewinds
        BEGIN SELECT RAISE(ABORT, 'injected head failure'); END""")
    cp._conn.commit()
    with pytest.raises(RewindRefused):
        await memory.add_turn(sid, "user", "not persisted")
    assert (root / f"{sid}.json").read_bytes() == before
    assert await memory.get_history(sid) == []


@pytest.mark.asyncio
async def test_failed_post_rewind_compensation_blocks_later_appends(context, monkeypatch):
    memory, cp, _root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "removed")
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.commit_rollback_rewind(ticket)
    cp._conn.execute("""CREATE TRIGGER reject_rewind_advance BEFORE UPDATE ON session_history_rewinds
        BEGIN SELECT RAISE(ABORT, 'injected head failure'); END""")
    cp._conn.commit()
    monkeypatch.setattr(persistence, "restore_memory_if_current", lambda *a, **k: False)
    with pytest.raises(RewindRefused):
        await memory.add_turn(sid, "user", "not persisted")
    assert sid in memory._rewind_inconsistent
    with pytest.raises(RewindRefused):
        await memory.add_turn(sid, "user", "still refused")


@pytest.mark.asyncio
async def test_cold_checkpoint_binding_defers_valid_rewind_until_initialize(context):
    memory, cp, root = context
    sid, clock = await begin(memory, cp)
    await memory.add_turn(sid, "user", "kept")
    await memory.add_turn(sid, "assistant", "answer")
    await memory.add_turn(sid, "user", "removed")
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.commit_rollback_rewind(ticket)
    cold = CheckpointManager(str(root.parent / "checkpoints.db"))
    restarted = MemoryManager()
    restarted.set_checkpoint_manager(cold)
    with pytest.raises(RewindRefused):
        await restarted.get_history(sid)
    cold.initialize()
    try:
        assert [r["content"] for r in await restarted.get_history(sid)] == ["kept", "answer"]
        assert await restarted.resume_session(sid)
    finally:
        cold.close()


@pytest.mark.asyncio
async def test_lazy_read_of_valid_inactive_rewind_keeps_current_healthy_session(context):
    memory, cp, _root = context
    sid, clock = await begin(memory, cp, "inactive_valid_rewind")
    await memory.add_turn(sid, "user", "kept")
    await memory.add_turn(sid, "assistant", "answer")
    await memory.add_turn(sid, "user", "removed")
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.commit_rollback_rewind(ticket)
    await memory.new_session("current_healthy")
    await memory.add_turn("current_healthy", "user", "still current")
    restarted = MemoryManager()
    restarted.set_checkpoint_manager(cp)
    assert restarted.conversation.current_session_id == "current_healthy"
    assert [r["content"] for r in await restarted.get_history(sid)] == ["kept", "answer"]
    assert restarted.conversation.current_session_id == "current_healthy"
    assert await restarted.resume_session(sid)
    assert restarted.conversation.current_session_id == sid


@pytest.mark.asyncio
async def test_corrupt_inactive_rewind_is_quarantined_without_blocking_healthy_session(context):
    memory, cp, root = context
    sid, clock = await begin(memory, cp, "corrupt_rewind")
    await memory.add_turn(sid, "user", "removed")
    ticket = await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)
    await memory.commit_rollback_rewind(ticket)
    await memory.new_session("healthy_rewind_neighbor")
    await memory.add_turn("healthy_rewind_neighbor", "user", "healthy")
    (root / f"{sid}.json").write_text("{broken")
    restarted = MemoryManager()
    restarted.set_checkpoint_manager(cp)
    assert [r["content"] for r in await restarted.get_history("healthy_rewind_neighbor")] == ["healthy"]
    for operation in (
        restarted.get_history(sid), restarted.get_context(sid), restarted.resume_session(sid),
        restarted.add_turn(sid, "user", "must not overwrite"),
        restarted.prepare_rollback_rewind(sid, clock.instance_id, clock),
    ):
        with pytest.raises(RewindRefused):
            await operation
    assert sid in restarted._rewind_inconsistent
    assert cp._conn.execute(
        "SELECT 1 FROM session_history_rewinds WHERE session_id=?", (sid,)
    ).fetchone() is not None
    assert await restarted.new_session("fresh_after_corruption") == "fresh_after_corruption"
    await restarted.add_turn("fresh_after_corruption", "user", "usable")
    assert [r["content"] for r in await restarted.get_history("fresh_after_corruption")] == ["usable"]


@pytest.mark.asyncio
async def test_corrupt_continuation_is_isolated_without_seed_replay(context):
    memory, cp, root = context
    source, source_clock = await begin(memory, cp, "quarantine_source")
    await memory.add_turn(source, "user", "immutable seed")
    seed = await memory.get_history(source)
    child = ContinuationStore(cp).create(
        source, "00000000-0000-4000-8000-000000000014", seed, source_clock
    )["session_id"]
    assert await memory.resume_session(child)
    child_clock = cp.clock_snapshot(child)
    ticket = await memory.prepare_rollback_rewind(child, child_clock.instance_id, child_clock)
    await memory.commit_rollback_rewind(ticket)
    await memory.new_session("healthy_after_child")
    await memory.add_turn("healthy_after_child", "user", "fine")
    (root / f"{child}.json").write_text("{broken")
    restarted = MemoryManager()
    restarted.set_checkpoint_manager(cp)
    assert [r["content"] for r in await restarted.get_history("healthy_after_child")] == ["fine"]
    for operation in (restarted.get_history(child), restarted.resume_session(child),
                      restarted.add_turn(child, "user", "cannot replay")):
        with pytest.raises(RewindRefused):
            await operation
    assert child in restarted._rewind_inconsistent
    assert ContinuationStore(cp).seed(child) == seed
