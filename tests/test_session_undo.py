"""Conversation-only undo uses the durable, clock-fenced rewind."""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import replace

import pytest

from agents.core.memory.manager import MemoryManager, RewindRefused, RollbackRewindResult
from tests.test_h011_rewind_boot_lifecycle import context


def _undo():
    return importlib.import_module("agents.core.memory.session_undo").undo_last_exchange


@pytest.mark.asyncio
async def test_undo_rechecks_authority_after_waiting_for_commit_lock(context, monkeypatch):
    memory, checkpoints, root = context
    sid = await memory.new_session("undo_authority_race")
    await memory.add_turn(sid, "user", "retain request")
    await memory.add_turn(sid, "assistant", "retain reply")
    clock = checkpoints.clock_snapshot(sid)
    before = (root / f"{sid}.json").read_bytes()
    authority = {"allowed": True}
    entered = asyncio.Event()
    prepare = memory.prepare_rollback_rewind
    commit = memory.commit_rollback_rewind

    async def prepare_then_hold(*args):
        ticket = await prepare(*args)
        await memory._lock.acquire()
        return ticket

    async def observe_commit(ticket, **kwargs):
        entered.set()
        return await commit(ticket, **kwargs)

    monkeypatch.setattr(memory, "prepare_rollback_rewind", prepare_then_hold)
    monkeypatch.setattr(memory, "commit_rollback_rewind", observe_commit)
    task = asyncio.create_task(_undo()(memory, sid, clock, authorize=lambda: authority["allowed"]))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert not task.done() and memory._lock.locked()
        authority["allowed"] = False
        memory._lock.release()
        with pytest.raises(RewindRefused, match="authority"):
            await asyncio.wait_for(task, 1)
        assert [turn["content"] for turn in await memory.get_history(sid)] == [
            "retain request", "retain reply"]
        assert (root / f"{sid}.json").read_bytes() == before
        assert checkpoints.clock_snapshot(sid) == clock
        assert not memory._rollback_tickets
    finally:
        if memory._lock.locked():
            memory._lock.release()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_undo_removes_only_last_user_exchange_and_survives_restart(context):
    memory, checkpoints, root = context
    sid = await memory.new_session("undo_durable")
    for role, content in (
        ("user", "keep request"),
        ("assistant", "keep answer"),
        ("user", "remove request"),
        ("assistant", "remove answer"),
    ):
        await memory.add_turn(sid, role, content)
    clock = checkpoints.clock_snapshot(sid)

    result = await _undo()(memory, sid, clock)

    assert isinstance(result, RollbackRewindResult)
    assert result.removed_turns == 2
    assert [row["content"] for row in await memory.get_history(sid)] == [
        "keep request",
        "keep answer",
    ]
    assert memory._rollback_tickets == {}
    assert (root / f"{sid}.json").is_file()

    restarted = MemoryManager()
    restarted.set_checkpoint_manager(checkpoints)
    assert await restarted.resume_session(sid)
    assert [row["content"] for row in await restarted.get_history(sid)] == [
        "keep request",
        "keep answer",
    ]
    await restarted.add_turn(sid, "user", "new request")
    assert [row["content"] for row in await restarted.get_history(sid)] == [
        "keep request",
        "keep answer",
        "new request",
    ]


@pytest.mark.asyncio
async def test_undo_refuses_stale_clock_without_changing_history(context):
    memory, checkpoints, root = context
    sid = await memory.new_session("undo_stale_clock")
    await memory.add_turn(sid, "user", "retain")
    clock = checkpoints.clock_snapshot(sid)
    before = (root / f"{sid}.json").read_bytes()

    with pytest.raises(RewindRefused, match="clock changed"):
        await _undo()(memory, sid, replace(clock, revision=clock.revision + 1))

    assert [row["content"] for row in await memory.get_history(sid)] == ["retain"]
    assert (root / f"{sid}.json").read_bytes() == before
    assert memory._rollback_tickets == {}


@pytest.mark.asyncio
async def test_undo_refuses_history_without_user_exchange(context):
    memory, checkpoints, _ = context
    sid = await memory.new_session("undo_no_user")
    await memory.add_turn(sid, "assistant", "retain")
    clock = checkpoints.clock_snapshot(sid)

    with pytest.raises(RewindRefused, match="no current user exchange"):
        await _undo()(memory, sid, clock)

    assert [row["content"] for row in await memory.get_history(sid)] == ["retain"]
    assert memory._rollback_tickets == {}


@pytest.mark.asyncio
async def test_undo_discards_prepared_ticket_when_commit_fails(context, monkeypatch):
    memory, checkpoints, root = context
    sid = await memory.new_session("undo_commit_fails")
    await memory.add_turn(sid, "user", "retain")
    clock = checkpoints.clock_snapshot(sid)
    before = (root / f"{sid}.json").read_bytes()

    async def failed_commit(_ticket):
        raise RewindRefused("simulated commit failure")

    monkeypatch.setattr(memory, "commit_rollback_rewind", failed_commit)
    with pytest.raises(RewindRefused, match="simulated commit failure"):
        await _undo()(memory, sid, clock)

    assert memory._rollback_tickets == {}
    assert (root / f"{sid}.json").read_bytes() == before
    assert [row["content"] for row in await memory.get_history(sid)] == ["retain"]


@pytest.mark.asyncio
async def test_undo_discards_prepared_ticket_when_cancelled(context, monkeypatch):
    memory, checkpoints, root = context
    sid = await memory.new_session("undo_cancelled")
    await memory.add_turn(sid, "user", "retain")
    clock = checkpoints.clock_snapshot(sid)
    before = (root / f"{sid}.json").read_bytes()
    entered = asyncio.Event()

    async def waiting_commit(_ticket):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(memory, "commit_rollback_rewind", waiting_commit)
    task = asyncio.create_task(_undo()(memory, sid, clock))
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert memory._rollback_tickets == {}
    assert (root / f"{sid}.json").read_bytes() == before
    assert [row["content"] for row in await memory.get_history(sid)] == ["retain"]
