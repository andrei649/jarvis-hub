"""Entry-point checks for generation-fenced conversation changes."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from agents.core.channels.session import SessionSource, build_session_key
from agents.core.channels.session_lifecycle import lifecycle
from agents.core.memory import persistence
from agents.core.memory.conversation import ConversationMemory
from agents.core.orchestrator import (
    TURN_BUSY_REPLY,
    Orchestrator,
    Principal,
    bind_turn_principal,
    reset_turn_principal,
)
from agents.core.scheduler_service import SchedulerService
from tests.test_channel_handler_session_wiring import _bare_orchestrator


def host(tmp_path, settings=None, *, resumable=()):
    orch, cap = _bare_orchestrator(resumable=resumable)
    orch._session_lifecycle_path = tmp_path / "routes.sqlite"
    orch._runtime_settings = settings or {}
    orch.channels = {"telegram": SimpleNamespace(allowed_users=[42])}
    clock = {"now": 1_780_000_000.0}
    orch._session_clock = lambda: clock["now"]
    orch._session_progress_clock = lambda: clock["now"]
    return orch, cap, clock


async def incoming(orch, text, sender="42", **kwargs):
    return await orch.channel_handler(text, channel="telegram", chat_id="123", sender=sender, **kwargs)


@pytest.mark.asyncio
async def test_owner_reset_preserves_route_and_guest_cannot_rotate(tmp_path):
    orch, cap, _ = host(tmp_path)
    await incoming(orch, "first")
    base = build_session_key(SessionSource(channel="telegram", sender="42", thread_id="123"))
    before = cap["sessions"][-1]
    assert "owner command" in await incoming(orch, "/new", sender="99")
    assert orch._channel_sessions[base] == before
    assert "new conversation" in (await incoming(orch, "/new")).lower()
    assert cap["sessions"] == [before]
    await incoming(orch, "second")
    assert cap["sessions"] == [before, f"mem:{base}_g1"]
    assert cap["new_session_ids"] == [base, f"{base}_g1"]


@pytest.mark.asyncio
async def test_restart_resumes_new_generation_and_old_transcript_is_untouched(tmp_path):
    first, cap, _ = host(tmp_path)
    await incoming(first, "old")
    await incoming(first, "/reset")
    new_key = cap["new_session_ids"][-1]
    second, after, _ = host(tmp_path, resumable={new_key})
    await incoming(second, "new")
    assert after["resumed_ids"] == [new_key]
    assert after["new_session_ids"] == []
    assert after["sessions"] == [new_key]


@pytest.mark.asyncio
async def test_idle_reset_and_forum_topics_use_separate_generations(tmp_path):
    orch, cap, clock = host(tmp_path, {"sessions.reset_mode": "idle", "sessions.idle_minutes": 1})
    await incoming(orch, "first", message_thread_id=10)
    await incoming(orch, "other", message_thread_id=20)
    clock["now"] += 61
    await incoming(orch, "next", message_thread_id=10)
    assert cap["sessions"][2] != cap["sessions"][0]
    assert cap["sessions"][2].endswith("_g1")
    assert cap["sessions"][1] != cap["sessions"][2]


@pytest.mark.asyncio
async def test_scheduler_expires_idle_route_without_new_inbound_message(tmp_path):
    orch, cap, clock = host(tmp_path, {"sessions.reset_mode": "idle", "sessions.idle_minutes": 1})
    await incoming(orch, "old topic")
    old = cap["sessions"][-1]
    registered = {}

    class Scheduler:
        def add_job(self, callback, trigger, **kwargs):
            registered[kwargs["id"]] = (callback, trigger, kwargs)

    orch.heartbeat_scheduler = SimpleNamespace(scheduler=Scheduler())
    service = SchedulerService(orch)
    service.schedule_session_expiry()
    callback, trigger, args = registered["channel-session-expiry"]
    assert trigger == "interval" and args["minutes"] == 1
    clock["now"] += 61
    assert await callback() == {"retired": 0, "rotated": 1}
    await incoming(orch, "new topic")
    assert cap["sessions"][-1] != old
    assert cap["sessions"][-1].endswith("_g1")


@pytest.mark.asyncio
async def test_reset_waits_for_active_turn_and_old_reply_stays_on_old_session(tmp_path):
    orch, cap, _ = host(tmp_path)
    orch._turn_lease_max_wait = 0.01
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(text, channel="voice"):
        cap["sessions"].append(orch.session_id)
        entered.set()
        await release.wait()
        return "old reply"

    orch.handle_input = slow
    running = asyncio.create_task(incoming(orch, "slow"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert await incoming(orch, "/new") == TURN_BUSY_REPLY
        assert len(cap["new_session_ids"]) == 1
    finally:
        release.set()
        assert await running == "old reply"
    assert "new conversation" in (await incoming(orch, "/new")).lower()
    assert cap["sessions"] == [f"mem:{cap['new_session_ids'][0]}"]


@pytest.mark.asyncio
async def test_web_and_cli_owner_commands_are_preappend(tmp_path):
    orch, cap, _ = host(tmp_path)
    async def new_session(sid):
        cap["new_session_ids"].append(sid)
        orch.session_id = sid
        return sid
    orch.new_session = new_session
    for channel in ("web", "cli"):
        token = bind_turn_principal(Principal(channel=channel, admin=True))
        try:
            reply = await Orchestrator.handle_input(
                orch, "/new", channel=channel, session_id=f"{channel}_shared")
        finally:
            reset_turn_principal(token)
        assert "new conversation" in reply.lower()
        assert cap["new_session_ids"][-1].startswith("session_")
        assert cap["new_session_ids"][-1] in reply
        assert cap["sessions"] == []


@pytest.mark.asyncio
async def test_direct_web_turn_returns_concrete_id_without_aliasing_old_transcript(tmp_path):
    orch, _, _ = host(tmp_path)

    class Memory:
        def __init__(self):
            self.conversation = SimpleNamespace(sessions={})

        async def new_session(self, sid):
            self.conversation.sessions[sid] = []
            return sid

        async def resume_session(self, sid):
            return sid in self.conversation.sessions

    orch.memory = Memory()
    async def checkpoint():
        return None
    orch._flush_checkpoint = checkpoint
    token = bind_turn_principal(Principal(channel="web", admin=True))
    try:
        reply = await orch._direct_session_command("/new", "web", "web_shared")
        assert "new conversation" in reply.lower()
        new_id = orch.session_id
        assert new_id.startswith("session_") and new_id in reply
        assert new_id != "web_shared"
        assert await orch._direct_session_command("next", "web", "web_shared") is None
        assert "web_shared" not in orch.memory.conversation.sessions
        assert new_id in orch.memory.conversation.sessions
    finally:
        reset_turn_principal(token)


@pytest.mark.asyncio
async def test_empty_new_session_is_resumable_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    initial = ConversationMemory(persist=True)
    sid = await initial.new_session("session_new_topic")
    initial._save_snapshot(sid)
    restarted = ConversationMemory(persist=True)
    assert restarted.current_session_id == sid
    assert restarted.sessions[sid] == []
    later = ConversationMemory(persist=True)
    later.sessions.clear()
    assert await later.resume_session(sid) is True
    assert later.sessions[sid] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"session_id": "session_corrupt", "instance_id": "stale"},
    {"session_id": "session_corrupt", "turns": None, "instance_id": "stale"},
    {"session_id": "session_corrupt", "turns": {}, "instance_id": "stale"},
])
async def test_resume_refuses_corrupt_snapshot_without_claiming_session(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    (tmp_path / "session_corrupt.json").write_text(json.dumps(payload), encoding="utf-8")
    memory = ConversationMemory(persist=True)
    assert memory.current_session_id is None
    assert await memory.resume_session("session_corrupt") is False
    assert memory.current_session_id is None
    assert "session_corrupt" not in memory.sessions
    assert "session_corrupt" not in memory.instances


@pytest.mark.asyncio
async def test_undo_copies_prior_exchange_into_new_generation(tmp_path):
    orch, cap, _ = host(tmp_path)
    base = build_session_key(SessionSource(channel="telegram", sender="42", thread_id="123"))
    old = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "reply one"},
        {"role": "user", "content": "two"},
        {"role": "assistant", "content": "reply two"},
    ]

    class Memory:
        def __init__(self):
            self.conversation = SimpleNamespace(sessions={base: list(old)})

        async def resume_session(self, sid):
            return sid in self.conversation.sessions

        async def new_session(self, sid=None):
            cap["new_session_ids"].append(sid)
            self.conversation.sessions[sid] = []
            return sid

        async def get_history(self, sid):
            return list(self.conversation.sessions[sid])

        async def add_turn(self, sid, role, content, **kwargs):
            self.conversation.sessions[sid].append({"role": role, "content": content})

    orch.memory = Memory()
    assert "owner command" in await incoming(orch, "/undo", sender="99")
    assert "Removed the last exchange" in await incoming(orch, "/undo")
    assert orch.memory.conversation.sessions[base] == old
    assert orch.memory.conversation.sessions[f"{base}_g1"] == old[:2]


@pytest.mark.asyncio
async def test_stalled_turn_notifies_once_after_actual_processing_stops(tmp_path):
    orch, _, clock = host(tmp_path, {"sessions.stall_seconds": 0.01})
    service = lifecycle(orch)
    started, release = asyncio.Event(), asyncio.Event()
    notices = []

    async def slow(text, channel="voice"):
        started.set()
        await release.wait()
        return "done"

    async def notify(base, episode, idle):
        notices.append((base, episode, idle))
        return True

    orch.handle_input = slow
    service._notify_stall = notify
    task = asyncio.create_task(incoming(orch, "work"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        clock["now"] += 1
        await asyncio.sleep(0.05)
        assert len(notices) == 1
    finally:
        release.set()
        await task
    await asyncio.sleep(0.02)
    assert len(notices) == 1


@pytest.mark.asyncio
async def test_reset_persists_empty_new_route_across_restart(tmp_path, monkeypatch):
    from agents.core.memory import persistence
    from agents.core.memory.conversation import ConversationMemory

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path / "transcripts")
    first, _, _ = host(tmp_path)
    conversation = ConversationMemory(persist=True)
    first.memory = SimpleNamespace(conversation=conversation, new_session=conversation.new_session,
                                   resume_session=conversation.resume_session)
    await incoming(first, "first")
    await incoming(first, "/new")
    base = build_session_key(SessionSource(channel="telegram", sender="42", thread_id="123"))
    assert (persistence.memory_dir() / f"{base}_g1.json").is_file()
    second, cap, _ = host(tmp_path)
    conversation = ConversationMemory(persist=True)
    second.memory = SimpleNamespace(conversation=conversation, new_session=conversation.new_session,
                                    resume_session=conversation.resume_session)
    await incoming(second, "next")
    assert cap["sessions"] == [f"{base}_g1"]


@pytest.mark.asyncio
async def test_corrupt_existing_transcript_refuses_recreation(tmp_path, monkeypatch):
    from agents.core.memory import persistence
    from agents.core.memory.conversation import ConversationMemory

    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    monkeypatch.setattr(persistence, "MEMORY_DIR", transcripts)
    base = build_session_key(SessionSource(channel="telegram", sender="42", thread_id="123"))
    (transcripts / f"{base}.json").write_text("broken", encoding="utf-8")
    orch, cap, _ = host(tmp_path, {"sessions.reset_mode": "idle"})
    conversation = ConversationMemory(persist=True)
    orch.memory = SimpleNamespace(conversation=conversation, new_session=conversation.new_session,
                                  resume_session=conversation.resume_session)
    assert "unavailable" in (await incoming(orch, "hello")).lower()
    assert cap["sessions"] == []
    assert (transcripts / f"{base}.json").read_text(encoding="utf-8") == "broken"
