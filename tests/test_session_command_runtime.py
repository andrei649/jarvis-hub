"""H067 destructive commands use real durable memory and preappend confirmation."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.channels.gateway import Gateway
from agents.core.channels.session import SessionSource, build_session_key
from agents.core.channels.session_lifecycle import lifecycle
from agents.core.checkpoint import CheckpointManager
from agents.core.memory.manager import MemoryManager
from agents.core.permission_ledger import PermissionLedger
from tests.test_h011_rollback_conversation import context
from tests.test_session_lifecycle_integration import host


def command_host(tmp_path, context):
    memory, checkpoints, _root = context
    orch, captured, _clock = host(tmp_path, {"channels.pending_inputs_enabled": True})
    orch.memory, orch.checkpoints = memory, checkpoints
    orch._telegram_owner_settings = lambda: {"autonomy.owner_user_ids": [42]}
    pairing = SimpleNamespace(allowed=True)
    pairing.is_allowed = lambda *_args: pairing.allowed
    pairing.gate_inbound = lambda *_args, **_kwargs: {"allowed": pairing.allowed}
    orch.channels = {"telegram": SimpleNamespace(_pairing=pairing, allowed_users=[])}
    ready = asyncio.Event()
    original = orch.channel_manager.send

    async def send(channel, text, **kwargs):
        await original(channel, text, **kwargs)
        if "Approve Once" in text:
            ready.set()
        return True

    orch.channel_manager.send = send
    captured["model_texts"] = []

    async def model(text, channel="voice", **_kwargs):
        captured["model_texts"].append(text)
        await memory.add_turn(orch.session_id, "user", text, channel=channel)
        await memory.add_turn(orch.session_id, "assistant", "reply", channel=channel)
        return "reply"

    orch.handle_input = model
    gateway = Gateway(orch.channel_handler, pairing=pairing,
                      pending_handler=getattr(orch, "channel_pending_handler", None))
    source = SessionSource(channel="telegram", sender="42", thread_id="123:topic:8", chat_type="thread")
    return orch, captured, gateway, ready, pairing, build_session_key(source)


async def message(gateway, text, *, sender="42", message_thread_id=8, **kwargs):
    return await gateway.route(text, channel="telegram", chat_id=123, sender=sender,
                               message_thread_id=message_thread_id, **kwargs)


async def cold_command_host(tmp_path, context, *, shared=False):
    first, _cap, gateway, _ready, _pairing, topic_base = command_host(tmp_path, context)
    first._runtime_settings["memory.cross_channel_sessions"] = shared
    if shared:
        first._runtime_settings["sessions.reset_mode"] = "idle"
        await context[0].new_session(first._session_id_default)
    await message(gateway, "keep")
    await message(gateway, "remove")
    route_base = first._session_id_default if shared else topic_base
    # Generation zero of the shared route uses the default session directly;
    # it intentionally has no entry in the channel route cache.
    sid = first._channel_sessions.get(route_base, route_base)
    root = context[2]
    transcript = root / f"{sid}.json"
    assert transcript.is_file()
    # ConversationMemory restores only its newest session at startup. Keep the
    # target on disk while making a different session the only warm cache entry.
    await context[0].new_session("zz_recent_other")
    await context[0].add_turn("zz_recent_other", "user", "unrelated")
    context[1].close()
    restarted_cp = CheckpointManager(str(tmp_path / "checkpoints.db"))
    restarted_cp.initialize()
    restarted_memory = MemoryManager()
    restarted_memory.set_checkpoint_manager(restarted_cp)
    assert sid not in restarted_memory.conversation.sessions
    restarted, cap, restarted_gateway, ready, pairing, _ = command_host(
        tmp_path, (restarted_memory, restarted_cp, root),
    )
    restarted._runtime_settings["memory.cross_channel_sessions"] = shared
    if shared:
        restarted._runtime_settings["sessions.reset_mode"] = "idle"
    assert restarted._channel_sessions == {}
    assert lifecycle(restarted).store.state(route_base).active
    return restarted, cap, restarted_gateway, ready, pairing, route_base, sid, transcript, restarted_cp


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/new", "/reset", "/undo"])
async def test_cancelled_command_never_changes_or_enters_the_conversation(tmp_path, context, command):
    orch, cap, gateway, ready, _pairing, base = command_host(tmp_path, context)
    await message(gateway, "keep")
    sid = orch._channel_sessions[base]
    before = await orch.memory.get_history(sid)
    task = asyncio.create_task(message(gateway, command))
    try:
        await asyncio.wait({task}, timeout=0.05)
        assert not task.done(), "destructive command executed without a confirmation"
        await asyncio.wait_for(ready.wait(), 1)
        assert await orch.memory.get_history(sid) == before
        assert await message(gateway, "/cancel") == ""
        response = await asyncio.wait_for(task, 1)
        assert "cancel" in response.lower()
        assert orch._channel_sessions[base] == sid
        assert await orch.memory.get_history(sid) == before
        assert cap["model_texts"] == ["keep"]
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_confirmed_undo_removes_last_exchange_without_appending_command(tmp_path, context):
    orch, cap, gateway, ready, _pairing, base = command_host(tmp_path, context)
    await message(gateway, "keep")
    await message(gateway, "remove")
    sid = orch._channel_sessions[base]
    task = asyncio.create_task(message(gateway, "/undo"))
    try:
        await asyncio.wait({task}, timeout=0.05)
        assert not task.done(), "undo did not ask for confirmation"
        await asyncio.wait_for(ready.wait(), 1)
        assert await message(gateway, "/approve") == ""
        response = await asyncio.wait_for(task, 1)
        assert "last exchange" in response.lower()
        assert [x["content"] for x in await orch.memory.get_history(sid)] == ["keep", "reply"]
        assert cap["model_texts"] == ["keep", "remove"]
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("shared", [False, True], ids=["topic", "shared"])
async def test_cold_undo_resumes_persisted_transcript_before_confirmation(tmp_path, context, shared):
    orch, cap, gateway, ready, _pairing, base, sid, _transcript, cp = await cold_command_host(
        tmp_path, context, shared=shared,
    )
    task = asyncio.create_task(message(gateway, "/undo"))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert sid in orch.memory.conversation.sessions
        assert [row["content"] for row in await orch.memory.get_history(sid)] == [
            "keep", "reply", "remove", "reply",
        ]
        assert await message(gateway, "/approve") == ""
        assert "last exchange" in (await asyncio.wait_for(task, 1)).lower()
        assert [row["content"] for row in await orch.memory.get_history(sid)] == [
            "keep", "reply",
        ]
        assert lifecycle(orch).store.state(base).generation == 0
        assert cap["model_texts"] == []
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        cp.close()


@pytest.mark.asyncio
async def test_cold_undo_cancel_preserves_persisted_transcript_bytes(tmp_path, context):
    orch, cap, gateway, ready, _pairing, base, sid, transcript, cp = await cold_command_host(
        tmp_path, context,
    )
    before = transcript.read_bytes()
    log_before = transcript.with_suffix(".jsonl").read_bytes()
    task = asyncio.create_task(message(gateway, "/undo"))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert await message(gateway, "/cancel") == ""
        assert "cancel" in (await asyncio.wait_for(task, 1)).lower()
        assert transcript.read_bytes() == before
        assert transcript.with_suffix(".jsonl").read_bytes() == log_before
        assert [row["content"] for row in await orch.memory.get_history(sid)] == [
            "keep", "reply", "remove", "reply",
        ]
        assert lifecycle(orch).store.state(base).generation == 0
        assert orch._channel_sessions == {}
        assert cap["model_texts"] == []
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        cp.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["missing", "corrupt"])
async def test_cold_undo_missing_or_corrupt_snapshot_fails_closed(tmp_path, context, damage):
    orch, cap, gateway, ready, _pairing, base, sid, transcript, cp = await cold_command_host(
        tmp_path, context,
    )
    if damage == "missing":
        transcript.unlink()
    else:
        transcript.write_bytes(b"{broken")
    task = asyncio.create_task(message(gateway, "/undo"))
    try:
        response = await asyncio.wait_for(task, 1)
        assert "unavailable" in response.lower() or "nothing changed" in response.lower()
        assert not ready.is_set()
        assert lifecycle(orch).store.state(base).generation == 0
        assert orch._channel_sessions == {}
        assert sid not in orch.memory.conversation.sessions
        assert cap["model_texts"] == []
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        cp.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["pairing", "generation"])
async def test_cold_undo_authority_change_while_resuming_stops_before_prompt(tmp_path, context, change):
    orch, cap, gateway, ready, pairing, base, sid, transcript, cp = await cold_command_host(
        tmp_path, context,
    )
    before = transcript.read_bytes()
    original_resume = orch.memory.resume_session

    async def resume_then_change(actual):
        result = await original_resume(actual)
        if change == "pairing":
            pairing.allowed = False
        else:
            service = lifecycle(orch)
            service.store.rotate(base, service.now(), "telegram", "thread")
        return result

    orch.memory.resume_session = resume_then_change
    task = asyncio.create_task(message(gateway, "/undo"))
    try:
        response = await asyncio.wait_for(task, 1)
        assert "nothing was applied" in response.lower()
        assert not ready.is_set()
        assert transcript.read_bytes() == before
        assert orch._channel_sessions == {}
        assert cap["model_texts"] == []
        assert sid in orch.memory.conversation.sessions
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        cp.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/new", "/reset"])
async def test_approved_reset_rotates_route_and_preserves_old_transcript(tmp_path, context, command):
    orch, cap, gateway, ready, _pairing, base = command_host(tmp_path, context)
    await message(gateway, "old conversation")
    old = orch._channel_sessions[base]
    before = await orch.memory.get_history(old)
    task = asyncio.create_task(message(gateway, command))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert await message(gateway, "/approve") == ""
        response = await asyncio.wait_for(task, 1)
        assert "new conversation" in response.lower()
        newest = orch._channel_sessions[base]
        assert newest != old and newest.endswith("_g1")
        assert lifecycle(orch).store.state(base).generation == 1
        assert await orch.memory.get_history(old) == before
        assert await orch.memory.get_history(newest) == []
        await message(gateway, "fresh conversation")
        assert [row["content"] for row in await orch.memory.get_history(newest)] == [
            "fresh conversation", "reply",
        ]
        assert await orch.memory.get_history(old) == before
        assert cap["model_texts"] == ["old conversation", "fresh conversation"]
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["clock", "generation"])
async def test_reset_refuses_when_conversation_changes_during_confirmation(tmp_path, context, change):
    orch, cap, gateway, ready, _pairing, base = command_host(tmp_path, context)
    await message(gateway, "keep")
    sid = orch._channel_sessions[base]
    task = asyncio.create_task(message(gateway, "/reset"))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        service = lifecycle(orch)
        if change == "clock":
            clock = orch.checkpoints.clock_snapshot(sid)
            assert orch.checkpoints.commit_clock(clock, "accepted compaction") is not None
        else:
            service.store.rotate(base, service.now(), "telegram", "thread")
        expected_generation = service.store.state(base).generation
        before = await orch.memory.get_history(sid)
        assert await message(gateway, "/approve") == ""
        response = await asyncio.wait_for(task, 1)
        assert "nothing was applied" in response.lower()
        assert service.store.state(base).generation == expected_generation
        assert orch._channel_sessions[base] == sid
        assert await orch.memory.get_history(sid) == before
        assert cap["model_texts"] == ["keep"]
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/reset", "/undo"])
@pytest.mark.parametrize("append", ["memory", "gateway"])
async def test_later_exchange_fences_waiting_command(tmp_path, context, command, append):
    orch, cap, gateway, ready, _pairing, base = command_host(tmp_path, context)
    await message(gateway, "keep")
    if command == "/undo":
        await message(gateway, "remove only if still latest")
    sid = orch._channel_sessions[base]
    task = asyncio.create_task(message(gateway, command))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        if append == "memory":
            await orch.memory.add_turn(sid, "user", "newer exchange", channel="telegram")
            await orch.memory.add_turn(sid, "assistant", "newer reply", channel="telegram")
        else:
            await message(gateway, "newer exchange")
        before = await orch.memory.get_history(sid)
        assert await message(gateway, "/approve") == ""
        response = await asyncio.wait_for(task, 1)
        assert "nothing was applied" in response.lower()
        assert orch._channel_sessions[base] == sid
        assert lifecycle(orch).store.state(base).generation == 0
        assert await orch.memory.get_history(sid) == before
        assert command not in cap["model_texts"]
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_reset_can_create_first_route_without_preexisting_transcript(tmp_path, context):
    orch, cap, gateway, ready, _pairing, base = command_host(tmp_path, context)
    task = asyncio.create_task(message(gateway, "/reset"))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert await message(gateway, "/approve") == ""
        assert "new conversation" in (await asyncio.wait_for(task, 1)).lower()
        assert lifecycle(orch).store.state(base).generation == 1
        assert cap["model_texts"] == []
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_non_owner_cannot_answer_waiting_confirmation(tmp_path, context):
    orch, cap, gateway, ready, _pairing, base = command_host(tmp_path, context)
    await message(gateway, "keep")
    sid = orch._channel_sessions[base]
    task = asyncio.create_task(message(gateway, "/reset"))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        await message(gateway, "/approve", sender="43")
        assert not task.done()
        assert orch._channel_sessions[base] == sid
        assert lifecycle(orch).store.state(base).generation == 0
        before = await orch.memory.get_history(sid)
        assert await message(gateway, "/approve") == ""
        assert "nothing was applied" in (await asyncio.wait_for(task, 1)).lower()
        assert await orch.memory.get_history(sid) == before
        assert cap["model_texts"] == ["keep", "/approve"]
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", ["pairing", "owner"])
async def test_authority_revocation_during_wait_cancels_without_effect(tmp_path, context, revoked):
    orch, cap, gateway, ready, pairing, base = command_host(tmp_path, context)
    await message(gateway, "keep")
    sid = orch._channel_sessions[base]
    before = await orch.memory.get_history(sid)
    task = asyncio.create_task(message(gateway, "/reset"))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        if revoked == "pairing":
            pairing.allowed = False
        else:
            orch._telegram_owner_settings = lambda: {"autonomy.owner_user_ids": [999]}
        response = await asyncio.wait_for(task, 2)
        assert "cancel" in response.lower()
        assert orch._channel_sessions[base] == sid
        assert lifecycle(orch).store.state(base).generation == 0
        assert await orch.memory.get_history(sid) == before
        assert cap["model_texts"] == ["keep"]
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_always_request_failure_applies_once_without_permanence_promise(tmp_path, context):
    orch, cap, gateway, ready, _pairing, base = command_host(tmp_path, context)
    await message(gateway, "old")
    old = orch._channel_sessions[base]
    task = asyncio.create_task(message(gateway, "/reset"))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert await message(gateway, "/always") == ""
        response = await asyncio.wait_for(task, 1)
        assert "could not be requested" in response.lower()
        assert "once only" in response.lower()
        assert "pending" not in response.lower()
        assert orch._channel_sessions[base] != old
        assert await orch.memory.get_history(old)
        assert cap["model_texts"] == ["old"]
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_private_chat_undo_preserves_dm_route_kind(tmp_path, context):
    orch, _cap, gateway, ready, _pairing, _base = command_host(tmp_path, context)
    async def private(text):
        return await message(gateway, text, message_thread_id=None, chat_type="private")
    await private("keep")
    await private("remove")
    base = build_session_key(SessionSource(channel="telegram", sender="42", thread_id="123",
                                           chat_type="private"))
    assert lifecycle(orch).store.state(base).kind == "dm"
    task = asyncio.create_task(private("/undo"))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert await private("/approve") == ""
        assert "last exchange" in (await asyncio.wait_for(task, 1)).lower()
        assert lifecycle(orch).store.state(base).kind == "dm"
        sid = orch._channel_sessions[base]
        assert [row["content"] for row in await orch.memory.get_history(sid)] == ["keep", "reply"]
    finally:
        orch._pending_input_service().close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_approved_standing_grant_skips_prompt_and_revoke_restores_it(tmp_path, context):
    orch, cap, gateway, ready, _pairing, base = command_host(tmp_path, context)
    ledger = PermissionLedger(tmp_path / "permissions.db", enabled=False)
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    worker = AutonomyWorker(queue)
    executor = TaskExecutor(execution_guard=worker.execution_allowed)
    executor.register("permission.grant", ledger.apply_grant)
    worker.executor = executor.execute
    orch.permission_ledger = ledger
    orch.autonomy = worker
    await message(gateway, "old")
    first = asyncio.create_task(message(gateway, "/reset"))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert await message(gateway, "/always") == ""
        response = await asyncio.wait_for(first, 1)
        assert "permanent approval is pending" in response.lower()
        task = queue.list()[0]
        assert task.status == "blocked"
        assert ledger.list_grants() == []
        assert lifecycle(orch).store.state(base).generation == 1

        await worker.apply_decision(task.id, "accept", decided_by="owner-42")
        assert (await worker.tick(task_id=task.id))["done"] == 1
        grant = ledger.list_grants()[0]
        ready.clear()
        response = await asyncio.wait_for(message(gateway, "/reset"), 1)
        assert "new conversation" in response.lower()
        assert not ready.is_set()
        assert lifecycle(orch).store.state(base).generation == 2

        assert ledger.revoke(grant.id).status == "revoked"
        waiting = asyncio.create_task(message(gateway, "/reset"))
        await asyncio.wait_for(ready.wait(), 1)
        assert not waiting.done()
        assert lifecycle(orch).store.state(base).generation == 2
        assert await message(gateway, "/cancel") == ""
        assert "cancel" in (await asyncio.wait_for(waiting, 1)).lower()
        assert cap["model_texts"] == ["old"]
    finally:
        orch._pending_input_service().close()
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        queue.close()
        ledger.close()
