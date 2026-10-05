"""H063: real channel entry point, preserved history and stable-route leases."""

import asyncio
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from agents.core.channels.session import SessionSource, build_session_key
from agents.core.orchestrator import TURN_BUSY_REPLY
from tests.test_channel_handler_session_wiring import _bare_orchestrator


def host(tmp_path, settings=None, *, resumable=()):
    orch, cap = _bare_orchestrator(resumable=resumable)
    orch._runtime_settings = settings or {}
    orch._session_lifecycle_path = tmp_path / "routes.sqlite"
    clock = {"now": datetime(2026, 10, 5, 1, tzinfo=UTC).timestamp()}
    orch._session_clock = lambda: clock["now"]
    orch._session_progress_clock = lambda: clock["now"]
    orch._telegram_owner_settings = lambda: {}
    return orch, cap, clock


async def incoming(orch, text="hello", **kwargs):
    return await orch.channel_handler(text, channel="telegram", chat_id="123", sender="42", **kwargs)


@pytest.mark.asyncio
async def test_idle_reset_rotates_the_route_without_replacing_the_old_session(tmp_path):
    orch, cap, clock = host(tmp_path, {"sessions.reset_mode": "idle", "sessions.idle_minutes": 1})
    await incoming(orch)
    original = cap["new_session_ids"][0]
    clock["now"] += 60
    await incoming(orch, "next")
    assert cap["new_session_ids"] == [original, original + "_g1"]
    assert cap["sessions"] == ["mem:" + original, "mem:" + original + "_g1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["/new", "/reset"])
async def test_explicit_reset_acknowledges_without_running_the_model(tmp_path, trigger):
    orch, cap, _ = host(tmp_path)
    await incoming(orch)
    before = list(cap["sessions"])
    reply = await incoming(orch, trigger)
    assert cap["sessions"] == before
    assert "new conversation" in reply.lower()
    assert cap["new_session_ids"][-1].endswith("_g1")
    assert cap["sent"][-1][1] == reply


@pytest.mark.asyncio
async def test_custom_reset_text_is_exact_and_old_commands_can_be_disabled(tmp_path):
    orch, cap, _ = host(tmp_path, {"sessions.reset_triggers": ["fresh please"]})
    await incoming(orch, "/new")
    await incoming(orch, "fresh please extra")
    assert len(cap["sessions"]) == 2
    await incoming(orch, "fresh please")
    assert len(cap["sessions"]) == 2


@pytest.mark.asyncio
async def test_daily_boundary_rotates_once_and_does_not_repeat_before_another_day(tmp_path):
    orch, cap, clock = host(tmp_path, {"sessions.reset_mode": "daily", "sessions.daily_hour": 4,
                                    "general.timezone": "UTC"})
    clock["now"] = datetime(2026, 10, 5, 3, 59, tzinfo=UTC).timestamp()
    await incoming(orch)
    clock["now"] += 60
    await incoming(orch)
    await incoming(orch)
    assert len(cap["new_session_ids"]) == 2


@pytest.mark.asyncio
async def test_restart_resumes_the_current_generation(tmp_path):
    first, cap, _ = host(tmp_path)
    await incoming(first)
    await incoming(first, "/new")
    newest = cap["new_session_ids"][-1]
    second, after, _ = host(tmp_path, resumable={newest})
    await incoming(second)
    assert newest.endswith("_g1")
    assert after["resumed_ids"] == [newest]
    assert after["new_session_ids"] == []


@pytest.mark.asyncio
async def test_type_and_channel_policy_override_do_not_reset_other_routes(tmp_path):
    orch, cap, clock = host(tmp_path, {"sessions.reset_mode": "idle", "sessions.idle_minutes": 1,
                                    "sessions.reset_by_type": {"group": {"mode": "none"}}})
    await incoming(orch, chat_type="group")
    clock["now"] += 600
    await incoming(orch, chat_type="group")
    assert len(cap["new_session_ids"]) == 1
    await orch.channel_handler("hello", channel="email", sender="other")
    clock["now"] += 60
    await orch.channel_handler("again", channel="email", sender="other")
    assert cap["new_session_ids"][-1].endswith("_g1")


@pytest.mark.asyncio
async def test_shared_opt_in_reset_remains_shared_across_channels(tmp_path):
    orch, cap, _ = host(tmp_path, {"memory.cross_channel_sessions": True})
    await incoming(orch)
    await incoming(orch, "/new")
    await orch.channel_handler("hello", channel="web")
    assert cap["sessions"] == ["web_shared", "mem:web_shared_g1"]
    assert orch.session_id == "web_shared"


@pytest.mark.asyncio
async def test_corrupt_route_store_refuses_the_turn_instead_of_reusing_generation_zero(tmp_path):
    orch, cap, _ = host(tmp_path)
    orch._session_lifecycle_path.write_bytes(b"not a database")
    reply = await incoming(orch)
    assert "unavailable" in reply.lower()
    assert cap["new_session_ids"] == cap["sessions"] == []


@pytest.mark.asyncio
async def test_reset_during_an_active_turn_does_not_rotate_or_start_parallel_work(tmp_path):
    orch, cap, _ = host(tmp_path)
    orch._turn_lease_max_wait = 0.01
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(text, channel="voice"):
        cap["sessions"].append(orch.session_id)
        entered.set()
        await release.wait()
        return "finished"

    orch.handle_input = slow
    running = asyncio.create_task(incoming(orch))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        reply = await incoming(orch, "/new")
        assert reply == TURN_BUSY_REPLY
        assert len(cap["sessions"]) == len(cap["new_session_ids"]) == 1
    finally:
        release.set()
        await running
    reply = await incoming(orch, "/new")
    assert "new conversation" in reply.lower()
    assert len(cap["sessions"]) == 1


@pytest.mark.asyncio
async def test_forum_topics_have_separate_routes_and_reset_generation(tmp_path):
    orch, cap, _ = host(tmp_path)
    await incoming(orch, message_thread_id="10", chat_type="supergroup")
    await incoming(orch, message_thread_id="20", chat_type="supergroup")
    assert len(set(cap["sessions"])) == 2
    await incoming(orch, "/new", message_thread_id="10", chat_type="supergroup")
    await incoming(orch, "same second topic", message_thread_id="20", chat_type="supergroup")
    assert cap["sessions"][-1] == cap["sessions"][1]


def test_normalized_session_type_does_not_treat_every_chat_id_as_a_thread():
    from agents.core.channels.session import session_type

    assert session_type(SessionSource(channel="telegram", thread_id="123", chat_type="private")) == "dm"
    assert session_type(SessionSource(channel="telegram", thread_id="123", chat_type="supergroup")) == "group"
    assert session_type(SessionSource(channel="slack", thread_id="C:1", chat_type="thread")) == "thread"
    assert session_type(SessionSource(channel="email", sender="someone")) == "dm"


@pytest.mark.asyncio
async def test_expiry_and_pruning_preserve_real_transcripts_and_the_generation_fence(tmp_path, monkeypatch):
    from agents.core.channels.session_lifecycle import lifecycle
    from agents.core.memory import conversation, persistence

    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    monkeypatch.setattr(conversation, "MEMORY_DIR", transcripts)
    monkeypatch.setattr(persistence, "MEMORY_DIR", transcripts)
    orch, cap, clock = host(tmp_path, {"sessions.reset_mode": "idle", "sessions.idle_minutes": 1})
    orch.memory = conversation.ConversationMemory()

    async def save(text, channel="voice"):
        cap["sessions"].append(orch.session_id)
        await orch.memory.add_turn(orch.session_id, "user", text)
        return "saved"

    orch.handle_input = save
    await incoming(orch, "old conversation")
    base = build_session_key(SessionSource(channel="telegram", sender="42", thread_id="123"))
    original = transcripts / f"{base}.json"
    original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    clock["now"] += 60
    assert await lifecycle(orch).expire() == {"retired": 0, "rotated": 1}
    await incoming(orch, "new conversation")
    assert cap["sessions"] == [base, base + "_g1"]
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash
    orch._runtime_settings.update({"sessions.reset_mode": "none", "sessions.store_max_age_days": 1})
    clock["now"] += 86_400
    assert await lifecycle(orch).expire() == {"retired": 1, "rotated": 0}
    assert not lifecycle(orch).store.state(base).active
    assert lifecycle(orch).store.state(base).generation == 2
    await incoming(orch, "after index pruning")
    assert cap["sessions"][-1] == base + "_g2"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash
    assert (transcripts / f"{base}_g1.json").is_file()


@pytest.mark.asyncio
async def test_watcher_exempts_route_and_direct_actual_session_leases(tmp_path):
    from agents.core.channels.session_lifecycle import lifecycle

    orch, _, clock = host(tmp_path, {"sessions.reset_mode": "idle", "sessions.idle_minutes": 1,
                                  "sessions.store_max_age_days": 1})
    await incoming(orch)
    base, actual = next(iter(orch._channel_sessions.items()))
    clock["now"] += 86_400
    async with orch.turn_lease(base):
        assert await lifecycle(orch).expire() == {"retired": 0, "rotated": 0}
    async with orch.turn_lease(actual):
        assert await lifecycle(orch).expire() == {"retired": 0, "rotated": 0}
    assert lifecycle(orch).store.state(base).generation == 0
    assert await lifecycle(orch).expire() == {"retired": 1, "rotated": 0}


@pytest.mark.asyncio
async def test_observe_only_reset_is_context_and_never_rotates_or_replies(tmp_path):
    from agents.core.channels.session_lifecycle import lifecycle

    orch, cap, _ = host(tmp_path)
    observed = []

    async def add_turn(*args, **kwargs):
        observed.append(args)

    orch.memory.add_turn = add_turn
    assert await incoming(orch, "/new", observe_only=True) is None
    assert observed[0][2] == "/new"
    assert cap["sessions"] == cap["sent"] == []
    assert lifecycle(orch).store.entries()[0].generation == 0


@pytest.mark.asyncio
async def test_workspace_reset_ack_keeps_the_existing_inbox_approval_path(tmp_path):
    orch, cap, _ = host(tmp_path)
    requests = []

    def request(message_id, text, **kwargs):
        requests.append((message_id, text, kwargs))
        return {"ok": True, "queued": True}

    orch.channel_replies = SimpleNamespace(request_for_message=request)
    reply = await orch.channel_handler("/new", channel="ntfy", sender="home", chat_id="home",
                                       _inbox_message_id="stored-reset")
    assert requests == [("stored-reset", reply, {"channel": "ntfy", "source": "channel.auto_reply"})]
    assert "new conversation" in reply.lower()
    assert cap["sent"] == cap["sessions"] == []


@pytest.mark.asyncio
async def test_actual_processing_progress_notifies_once_and_completion_drains(tmp_path, monkeypatch):
    from agents.core.channels import outbound
    from agents.core.channels.session_lifecycle import lifecycle

    orch, _, clock = host(tmp_path, {"sessions.stall_seconds": 30})
    entered, release = asyncio.Event(), asyncio.Event()
    delivered = []

    async def slow(*args, **kwargs):
        entered.set()
        await release.wait()
        return "done"

    async def notify(*args, **kwargs):
        delivered.append((args, kwargs))
        return {"ok": True}

    orch.handle_input = slow
    monkeypatch.setattr(outbound, "send_to_target", notify)
    running = asyncio.create_task(incoming(orch, "PRIVATE-INBOUND-MUST-NOT-BE-NOTIFIED"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        clock["now"] += 30
        assert await lifecycle(orch).check_stalls() == 1
        assert await lifecycle(orch).check_stalls() == 0
        assert "PRIVATE-INBOUND" not in str(delivered)
        assert delivered[0][0][1] == "telegram"
    finally:
        release.set()
        await running
    clock["now"] += 300
    assert await lifecycle(orch).check_stalls() == 0


@pytest.mark.asyncio
async def test_actual_tool_event_reports_progress_even_without_a_ui_sink():
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.channels import session_lifecycle

    calls = []
    token = session_lifecycle._activity.set(lambda: calls.append("progress"))
    try:
        runtime = AgentToolRuntime.__new__(AgentToolRuntime)
        await runtime._emit(None, {"event": "tool.completed"})
    finally:
        session_lifecycle._activity.reset(token)
    assert calls == ["progress"]


def test_session_lifecycle_jobs_are_registered_on_the_existing_scheduler():
    from agents.core.scheduler_service import SchedulerService

    jobs = []
    scheduler = SimpleNamespace(add_job=lambda *args, **kwargs: jobs.append((args, kwargs)))
    service = SchedulerService(SimpleNamespace(heartbeat_scheduler=SimpleNamespace(scheduler=scheduler)))
    service.schedule_session_lifecycle()
    assert {job[1]["id"]: job[1]["seconds"] for job in jobs} == {
        "channel-session-expiry": 300, "channel-session-stalls": 30,
    }


@pytest.mark.asyncio
async def test_real_telegram_ingress_preserves_group_and_forum_metadata(monkeypatch):
    from tests.test_telegram_group_gate import _channel, _drain, _message

    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")
    channel, received = _channel()
    await _drain(channel, [_message("@nerva_bot hi", message_thread_id=10)])
    assert received[0][1]["chat_type"] == "supergroup"
    assert received[0][1]["message_thread_id"] == 10


@pytest.mark.asyncio
async def test_batched_telegram_topics_never_merge_and_keep_their_metadata(monkeypatch):
    from tests.test_telegram_group_gate import GROUP, _channel, _message

    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "1000")
    channel, received = _channel()
    try:
        for topic in (10, 20):
            message = _message("@nerva_bot hi", message_thread_id=topic)["message"]
            await channel._handle_message_content(message, 42, GROUP, message["text"], None)
        assert len(channel._batch) == 2
        await channel._flush_all_turns()
        assert [meta["message_thread_id"] for _, meta in received] == [10, 20]
        assert all(meta["chat_type"] == "supergroup" for _, meta in received)
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("guild,parent,kind", [(None, None, "private"), (object(), None, "group"),
                                              (object(), 7, "thread")])
async def test_real_discord_ingress_carries_the_normalized_chat_type(monkeypatch, guild, parent, kind):
    from agents.core.channels.discord import DiscordChannel

    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")
    received = []

    async def handle(text, **meta):
        received.append(meta)

    channel = DiscordChannel(token="synthetic", handler=handle)
    message = SimpleNamespace(author=SimpleNamespace(id=42), channel=SimpleNamespace(id=12, parent_id=parent),
                              guild=guild, content="hello")
    await channel._handle_message(message)
    assert received[0]["chat_type"] == kind


@pytest.mark.asyncio
async def test_telegram_reset_reply_targets_the_same_forum_topic():
    import json

    import httpx

    from tests.test_telegram_group_gate import GROUP, _channel

    channel, _ = _channel()
    await channel.client.aclose()
    posts = []

    def transport(request):
        posts.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 2}})

    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    try:
        assert await channel.send("New conversation", chat_id=GROUP, message_thread_id=10, voice=False, plain=True)
        assert posts[0]["message_thread_id"] == 10
        assert posts[0]["chat_id"] == GROUP
    finally:
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_shared_busy_request_does_not_drain_the_running_stall_episode(tmp_path, monkeypatch):
    from agents.core.channels import outbound
    from agents.core.channels.session_lifecycle import lifecycle

    orch, _, clock = host(tmp_path, {"sessions.stall_seconds": 10})
    orch._turn_lease_max_wait = 0.01
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(*args, **kwargs):
        entered.set()
        await release.wait()
        return "done"

    async def notify(*args, **kwargs):
        return {"ok": True}

    orch.handle_input = slow
    monkeypatch.setattr(outbound, "send_to_target", notify)
    running = asyncio.create_task(orch.channel_handler("first", channel="web"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert await orch.channel_handler("second", channel="web") == TURN_BUSY_REPLY
        clock["now"] += 20
        assert await lifecycle(orch).check_stalls() == 1
    finally:
        release.set()
        await running
    assert await lifecycle(orch).check_stalls() == 0


@pytest.mark.asyncio
async def test_reset_cannot_rotate_into_a_directly_leased_next_generation(tmp_path):
    from agents.core.channels.session_lifecycle import lifecycle

    orch, cap, _ = host(tmp_path)
    orch._turn_lease_max_wait = 0.01
    await incoming(orch)
    base = next(iter(orch._channel_sessions))
    entered, release = asyncio.Event(), asyncio.Event()

    async def occupy():
        async with orch.turn_lease(base + "_g1"):
            entered.set()
            await release.wait()

    occupying = asyncio.create_task(occupy())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert await incoming(orch, "/new") == TURN_BUSY_REPLY
        assert lifecycle(orch).store.state(base).generation == 0
        assert len(cap["new_session_ids"]) == 1
    finally:
        release.set()
        await occupying
    assert "new conversation" in (await incoming(orch, "/new")).lower()


@pytest.mark.asyncio
async def test_shared_generation_zero_still_updates_activity_after_policy_change_and_restart(tmp_path):
    from agents.core.channels.session_lifecycle import lifecycle

    first, _, clock = host(tmp_path, {"sessions.reset_mode": "idle"})
    await first.channel_handler("first", channel="web")
    baseline = clock["now"]
    restarted, _, later = host(tmp_path)
    later["now"] = baseline + 89 * 86_400
    await restarted.channel_handler("recent", channel="web")
    later["now"] = baseline + 91 * 86_400
    assert await lifecycle(restarted).expire() == {"retired": 0, "rotated": 0}
    assert lifecycle(restarted).store.state(restarted._session_id_default).generation == 0


@pytest.mark.asyncio
async def test_expiry_does_not_fill_the_turn_lease_table_with_inactive_routes(tmp_path):
    from agents.core.channels.session_lifecycle import lifecycle

    orch, _, _ = host(tmp_path)
    service = lifecycle(orch)
    for i in range(20):
        service.store.touch(f"route_{i}", service.now(), "telegram", "dm")
    assert await service.expire() == {"retired": 0, "rotated": 0}
    assert orch._turn_leases == {}


@pytest.mark.asyncio
async def test_reset_memory_creation_failure_keeps_the_existing_route(tmp_path):
    from agents.core.channels.session_lifecycle import lifecycle

    orch, _, _ = host(tmp_path)
    await incoming(orch)
    base, original = next(iter(orch._channel_sessions.items()))

    async def failed(*args):
        raise OSError("synthetic disk failure")

    orch.memory.new_session = failed
    assert "unavailable" in (await incoming(orch, "/new")).lower()
    assert lifecycle(orch).store.state(base).generation == 0
    assert orch._channel_sessions[base] == original


@pytest.mark.asyncio
async def test_rewind_refusal_returns_a_controlled_channel_reply(tmp_path):
    from agents.core.memory.manager import RewindRefused

    orch, _, _ = host(tmp_path)

    async def refused(*args, **kwargs):
        raise RewindRefused("synthetic protected write refusal")

    orch.handle_input = refused
    assert "unavailable" in (await incoming(orch)).lower()


@pytest.mark.asyncio
async def test_non_draft_model_tokens_are_observed_without_publishing_them(tmp_path):
    from agents.core.agent import Agent
    from agents.core.channels.session_lifecycle import lifecycle

    orch, cap, clock = host(tmp_path, {"sessions.stall_seconds": 10})
    observed = []

    class Backend:
        async def generate(self, **kwargs):
            raise AssertionError("streamable backend must expose genuine token activity")

        async def generate_stream(self, *, on_token, **kwargs):
            for piece in ("one", "two", "three"):
                clock["now"] += 9
                emitted = on_token(piece)
                if hasattr(emitted, "__await__"):
                    await emitted
                assert await lifecycle(orch).check_stalls() == 0
                assert cap["sent"] == []
                observed.append(piece)
            return "final complete response"

    agent = Agent("jarvis", {"name": "Jarvis"})
    agent.tool_runtime = None

    async def generate(*args, **kwargs):
        return await agent.generate_response(Backend(), "synthetic-model", "hello", "system", 50, 0.2)

    orch.handle_input = generate
    assert await incoming(orch) == "final complete response"
    assert observed == ["one", "two", "three"]
    assert len(cap["sent"]) == 1


@pytest.mark.asyncio
async def test_channel_shutdown_closes_the_stall_watcher_before_transport(tmp_path):
    from agents.core.channels.session_lifecycle import lifecycle

    orch, _, _ = host(tmp_path)
    service = lifecycle(orch)
    episode = service.stalls.begin("pending")
    service.stalls.progress("pending", episode)
    order = []

    async def stop_transports():
        assert not service.stalls.matches("pending", episode)
        assert await service.check_stalls() == 0
        order.append("transports")

    async def close_plugins():
        order.append("plugins")

    orch.channel_manager.stop_all = stop_transports
    orch.heartbeat_scheduler = SimpleNamespace(stop=lambda: order.append("scheduler"))
    orch.plugin_manager = SimpleNamespace(close_all=close_plugins)
    await orch.stop_channels()
    assert order == ["scheduler", "transports", "plugins"]
    assert "unavailable" in (await incoming(orch)).lower()


@pytest.mark.asyncio
async def test_telegram_forum_voice_fallback_stays_in_the_reply_topic(tmp_path):
    from agents.core.channels.voice_mode import ALWAYS
    from tests.test_telegram_voice_reply import _channel

    channel, client, _ = _channel(tmp_path, mode=ALWAYS, statuses={"sendVoice": [400]})
    await channel._run_turn(42, 42, "hello", chat_type="supergroup", message_thread_id=10)
    assert {method for method, _ in client.calls} >= {"sendMessage", "sendVoice", "sendAudio"}
    for method, body in client.calls:
        if method == "sendMessage":
            assert body["json"]["message_thread_id"] == 10
        if method in {"sendVoice", "sendAudio"}:
            assert body["data"]["message_thread_id"] == "10"


@pytest.mark.asyncio
async def test_telegram_html_fallback_keeps_topic_and_late_child_send_does_not_inherit_it(monkeypatch):
    import json

    import httpx

    from tests.test_telegram_group_gate import GROUP, _channel

    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "0")
    channel, _ = _channel()
    await channel.client.aclose()
    posts = []

    def transport(request):
        posts.append(json.loads(request.content))
        return httpx.Response(400 if len(posts) == 1 else 200, json={"ok": True, "result": {"message_id": 2}})

    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    release = asyncio.Event()
    children = []

    async def handler(*args, **kwargs):
        async def late():
            await release.wait()
            await channel.send("late notice", chat_id=GROUP, voice=False)

        children.append(asyncio.create_task(late()))
        await channel.send("**reply**", chat_id=GROUP, voice=False)

    channel.handler = handler
    try:
        await channel._run_turn(GROUP, 42, "hello", chat_type="supergroup", message_thread_id=10)
        assert [p["message_thread_id"] for p in posts] == [10, 10]
        release.set()
        await asyncio.gather(*children)
        assert "message_thread_id" not in posts[-1]
    finally:
        release.set()
        await asyncio.gather(*children)
        await channel.client.aclose()


@pytest.mark.asyncio
async def test_batched_voice_mark_and_transcript_echo_do_not_cross_forum_topics(tmp_path, monkeypatch):
    from agents.core.channels.inbound_media import classify
    from agents.core.channels.voice_mode import VOICE
    from tests.test_telegram_voice_reply import _channel

    monkeypatch.setenv("JARVIS_INBOUND_BATCH_MS", "1000")
    ch, client, synth = _channel(tmp_path, mode=VOICE)
    ch._echo_transcripts = lambda: True
    voice = {"chat": {"id": 42, "type": "supergroup"}, "message_thread_id": 10,
             "caption": "@nerva_bot question", "voice": {"file_id": "synthetic", "file_size": 100}}
    typed = {"chat": {"id": 42, "type": "supergroup"}, "message_thread_id": 20}
    await ch._handle_message_content(voice, 42, 42, voice["caption"], classify(voice))
    echo = next(body["json"] for method, body in client.calls if method == "sendMessage")
    assert echo["message_thread_id"] == 10
    await ch._handle_message_content(typed, 42, 42, "@nerva_bot typed", None)
    await ch._flush_turn((42, "42", 20))
    assert synth.seen == []
    await ch._flush_all_turns()
    assert len(synth.seen) == 1
    audio = next(body for method, body in client.calls if method == "sendVoice")
    assert audio["data"]["message_thread_id"] == "10"
    assert ch._voice_pending == set()
    assert ch._batch_session_meta == {}


@pytest.mark.asyncio
async def test_stall_notification_respects_safe_mode_egress(tmp_path, monkeypatch):
    from agents.core import safe_mode
    from agents.core.channels.session_lifecycle import lifecycle, note_session_activity

    orch, cap, clock = host(tmp_path, {"sessions.stall_seconds": 1})
    monkeypatch.setenv(safe_mode.ENV_NAME, "1")
    safe_mode.reset()
    try:
        service = lifecycle(orch)
        with service.track("safe_mode_alert"):
            note_session_activity()
            clock["now"] += 2
            assert await service.check_stalls() == 0
            assert cap["sent"] == []
        assert await service.check_stalls() == 0
    finally:
        safe_mode.reset()


@pytest.mark.asyncio
@pytest.mark.parametrize("sink_kind", ["async", "sync", "none"])
async def test_activity_observer_preserves_the_real_provider_token_emitter_contract(tmp_path, sink_kind):
    from agents.core.agent import Agent
    from agents.core.channels.session_lifecycle import lifecycle
    from agents.core.llm.base import _emit

    orch, _, clock = host(tmp_path, {"sessions.stall_seconds": 10})
    seen = []

    async def async_sink(piece):
        await asyncio.sleep(0)
        seen.append(piece)

    sink = async_sink if sink_kind == "async" else seen.append if sink_kind == "sync" else None

    class Backend:
        async def generate_stream(self, *, on_token, **kwargs):
            clock["now"] += 20
            await _emit(on_token, "actual token")
            assert await lifecycle(orch).check_stalls() == 0
            assert seen == ([] if sink_kind == "none" else ["actual token"])
            return "final response"

    agent = Agent("jarvis", {"name": "Jarvis"})
    agent.tool_runtime = None

    async def generate(*args, **kwargs):
        return await agent.generate_response(Backend(), "synthetic-model", "hello", "system", 50, 0.2,
                                             on_token=sink)

    orch.handle_input = generate
    assert await incoming(orch) == "final response"
