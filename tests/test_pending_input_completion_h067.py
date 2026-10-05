"""H067 completion via real gateway, signed delivery and durable conversation."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.channels.ephemeral import EphemeralReply
from agents.core.channels.gateway import Gateway
from agents.core.channels.session import SessionSource, build_session_key
from tests.test_h011_rollback_conversation import context  # noqa: F401
from tests.test_pending_input_runtime import incoming, runtime_host
from tests.test_pending_input_workspace_broker import prompt_broker  # noqa: F401
from tests.test_session_command_kernel import governed  # noqa: F401
from tests.test_session_command_runtime import command_host


def workspace_commands(tmp_path, context, prompt_broker, channel):
    orch, cap, _, _, pairing, _ = command_host(tmp_path, context)
    broker, queue, worker, sent, state, _, _, manager = prompt_broker
    sender = "T1:U2" if channel == "slack" else "42"
    delivery = {"slack_channel": "C1", "thread_ts": "170.001"} if channel == "slack" else {"channel_id": "123"}
    receipt = {"channel": channel, "target": "C1" if channel == "slack" else "123",
               "message_id": "171.001" if channel == "slack" else "456",
               "thread_id": "170.001" if channel == "slack" else None,
               "team_id": "T1" if channel == "slack" else None}
    state["receipt"] = receipt

    async def send_pending_card(text, **kwargs):
        sent.append((text, kwargs))
        return state["receipt"]

    adapter = SimpleNamespace(channel_id=channel, _running=True, pairing=pairing,
                              _pending_callback_generation=object(),
                              send_pending_card=send_pending_card)
    manager.register(adapter)
    orch.channel_manager, orch.channel_replies = manager, broker
    orch.autonomy, orch.autonomy_queue = worker, queue
    orch.permission_ledger = prompt_broker[2].executor.__self__.resolve("permission.grant").__self__
    orch._runtime_settings["channels.owner_senders"] = {channel: [sender]}
    gateway = Gateway(orch.channel_handler, pairing=pairing, inbox_store=broker._inbox,
                      pending_handler=orch.channel_pending_handler)
    source = SessionSource(channel=channel, sender=sender,
                           thread_id="C1:170.001" if channel == "slack" else "123",
                           chat_type="thread" if channel == "slack" else "private")
    return orch, cap, gateway, pairing, adapter, build_session_key(source), sender, delivery


async def approve_prompt(orch, queue, worker, turn):
    for _ in range(100):
        await asyncio.sleep(0)
        prompts = [t for t in queue.list() if "native_prompt" in t.payload]
        if prompts:
            queued = prompts[-1]
            assert queued.status == "blocked" and queued.mediation_receipt is not None
            await worker.apply_decision(queued.id, "accept", decided_by="owner")
            assert (await worker.tick(task_id=queued.id))["done"] == 1
            for _ in range(100):
                await asyncio.sleep(0)
                if orch._pending_input_service()._delivered:
                    return queued
        if turn.done():
            break
    raise AssertionError("destructive command did not wait for a governed native prompt")


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["slack", "discord"])
@pytest.mark.parametrize("choice", ["!cancel", "Approve Once", "!always"])
async def test_workspace_reset_confirmations_preserve_history_and_govern_permanence(
    tmp_path, context, prompt_broker, channel, choice,
):
    orch, cap, gateway, _, _, base, sender, delivery = workspace_commands(
        tmp_path, context, prompt_broker, channel)
    _, queue, worker, sent, *_ = prompt_broker
    await gateway.route("keep", channel=channel, sender=sender, **delivery)
    sid = orch._channel_sessions[base]
    history = await orch.memory.get_history(sid)
    turn = asyncio.create_task(gateway.route("/new", channel=channel, sender=sender, **delivery))
    try:
        await approve_prompt(orch, queue, worker, turn)
        assert sent and await orch.memory.get_history(sid) == history
        assert await gateway.route(choice, channel=channel, sender=sender, **delivery) == ""
        response = await asyncio.wait_for(turn, 1)
        assert isinstance(response, EphemeralReply)
        notices = [t for t in queue.list() if t.payload.get("text") == response]
        assert notices and notices[-1].payload["ephemeral_ttl"] == 0
        assert await orch.memory.get_history(sid) == history
        assert cap["model_texts"] == ["keep"]
        if choice == "!cancel":
            assert orch._channel_sessions[base] == sid
        else:
            assert orch._channel_sessions[base] != sid
        grants = [t for t in queue.list() if t.kind == "permission.grant"]
        assert bool(grants) == (choice == "!always")
        if grants:
            from agents.core.channels.session_command_consent import SessionCommandConsent
            consent = SessionCommandConsent(orch.permission_ledger, worker.govern_enqueue)
            key = (channel, base, sender)
            assert consent.check(key, "reset") == "ask"
            await worker.apply_decision(grants[-1].id, "accept", decided_by="owner")
            assert (await worker.tick(task_id=grants[-1].id))["done"] == 1
            assert consent.check(key, "reset") == "allow"
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["slack", "discord"])
@pytest.mark.parametrize("state", ["ok", "failed", "stopped"])
async def test_workspace_notice_deletes_only_acknowledged_owned_messages(channel, state):
    from agents.core.channels.discord import DiscordChannel
    from agents.core.channels.ephemeral import EphemeralDeletes
    from agents.core.channels.slack import SlackChannel

    release, entered, deleted = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    async def sleep(_delay):
        entered.set()
        await release.wait()

    if channel == "slack":
        def post(**kwargs):
            calls.append(("post", kwargs))
            return {"ok": state != "failed", "channel": "C1", "ts": "171.001"}

        def remove(**kwargs):
            calls.append(("delete", kwargs))
            deleted.set()
            return {"ok": True}

        adapter = SlackChannel()
        adapter._client = SimpleNamespace(chat_postMessage=post, chat_delete=remove)
        target = {"slack_channel": "C1", "thread_ts": "170.001"}
    else:
        async def remove():
            calls.append(("delete", "456"))
            deleted.set()

        async def send(text):
            calls.append(("post", text))
            if state == "failed":
                raise RuntimeError("synthetic send failure")
            return SimpleNamespace(id=456, channel=SimpleNamespace(id=123), delete=remove)

        adapter = DiscordChannel()
        adapter._client = SimpleNamespace(is_ready=lambda: True,
                                         get_channel=lambda _id: SimpleNamespace(send=send))
        target = {"channel_id": "123"}
    adapter._running = True
    adapter._pending_callback_generation = object()
    adapter._ephemeral_deletes = EphemeralDeletes(sleep=sleep)
    try:
        sent = await adapter.send(EphemeralReply("temporary notice", 7), **target)
        if state == "failed":
            assert sent is False and adapter._ephemeral_deletes.pending_count == 0
        else:
            assert sent is True
            await asyncio.wait_for(entered.wait(), 1)
            assert not deleted.is_set()
            if state == "stopped":
                adapter._pending_callback_generation = object()
            release.set()
            if state == "ok":
                await asyncio.wait_for(deleted.wait(), 1)
                if channel == "slack":
                    assert calls[-1] == ("delete", {"channel": "C1", "ts": "171.001"})
            else:
                await asyncio.sleep(0)
                assert not deleted.is_set()
    finally:
        await adapter._ephemeral_deletes.aclose()


@pytest.mark.asyncio
async def test_signed_reply_retains_ephemeral_marker_until_transport(prompt_broker):
    from agents.core.action_origin import bind_action_origin, reset_action_origin
    broker, queue, worker, _, _, inbound, _, manager = prompt_broker
    seen = []

    async def send_reply(channel, text, **reply):
        seen.append((channel, text, reply))
        return True

    manager.send_channel_reply = send_reply
    token = bind_action_origin("inbound")
    try:
        proposed = broker.request_for_message(inbound["id"], EphemeralReply("notice", 7), channel="slack")
    finally:
        reset_action_origin(token)
    assert proposed["ok"] and proposed["queued"]
    task = queue.get(proposed["task_id"])
    assert not seen and task.status == "blocked" and task.mediation_receipt is not None
    assert task.payload["ephemeral_ttl"] == 7
    await worker.apply_decision(task.id, "accept", decided_by="owner")
    assert (await worker.tick(task_id=task.id))["done"] == 1
    assert isinstance(seen[0][1], EphemeralReply) and seen[0][1].ttl_seconds == 7


@pytest.mark.parametrize("channel,sender", [("slack", "T1:U2"), ("discord", "42")])
def test_workspace_owner_is_explicit_and_pairing_revocable(tmp_path, channel, sender):
    orch, _, _, _, pairing, _ = command_host(tmp_path, (None, None, None))
    adapter = SimpleNamespace(channel_id=channel, _running=True, pairing=pairing)
    orch.channels[channel] = adapter
    assert not orch._channel_principal(channel, sender, None).admin
    orch._runtime_settings["channels.owner_senders"] = {channel: [sender]}
    assert orch._channel_principal(channel, sender, None).admin
    assert not orch._channel_principal(channel, "T2:U2" if channel == "slack" else "43", None).admin
    pairing.allowed = False
    assert not orch._channel_principal(channel, sender, None).admin


@pytest.mark.asyncio
async def test_registered_clarify_tool_uses_new_runtime_after_same_instance_close(tmp_path):
    orch, _, gateway, _, ready, _, answers = runtime_host(tmp_path)
    prior = orch._pending_input_service()
    prior.close()
    turn = asyncio.create_task(incoming(gateway))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert orch._pending_input_service() is not prior
        assert await incoming(gateway, "2") == ""
        await asyncio.wait_for(turn, 1)
        assert answers[0][0]["result"]["user_response"] == "Remote"
        assert prior.closed and not prior._delivered
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["slack", "discord"])
@pytest.mark.parametrize("changed", ["pairing", "owner", "transport"])
async def test_workspace_confirmation_revocation_preserves_conversation(
    tmp_path, context, prompt_broker, channel, changed,
):
    orch, _, gateway, pairing, adapter, base, sender, delivery = workspace_commands(
        tmp_path, context, prompt_broker, channel)
    _, queue, worker, *_ = prompt_broker
    await gateway.route("keep", channel=channel, sender=sender, **delivery)
    sid = orch._channel_sessions[base]
    before = await orch.memory.get_history(sid)
    turn = asyncio.create_task(gateway.route("/new", channel=channel, sender=sender, **delivery))
    try:
        await approve_prompt(orch, queue, worker, turn)
        if changed == "pairing":
            pairing.allowed = False
        elif changed == "owner":
            orch._runtime_settings["channels.owner_senders"] = {}
        else:
            adapter._pending_callback_generation = object()
        result = await asyncio.wait_for(turn, 1)
        assert "cancel" in result.lower() or "changed" in result.lower()
        assert orch._channel_sessions[base] == sid
        assert await orch.memory.get_history(sid) == before
        assert not [t for t in queue.list() if t.kind == "permission.grant"]
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_second", [False, True])
async def test_batch_clarify_keeps_completed_answers_and_stops_after_timeout(tmp_path, stop_second):
    orch, _, gateway, server, ready, _, answers = runtime_host(tmp_path)
    original = server.handle

    async def handle(request, *args, **kwargs):
        request = {**request, "args": {"questions": [
            {"id": "route", "question": "Choose a route", "choices": [{"label": "Local"}, "Remote"]},
            {"id": "tag", "question": "Choose a tag", "choices": ["Blue", "Green"], "multi_select": True},
            {"id": "memo", "question": "Choose a note"},
        ]}}
        return await original(request, *args, **kwargs)

    server.handle = handle
    orch._runtime_settings["agent.clarify_timeout"] = 0.04 if stop_second else 1
    turn = asyncio.create_task(incoming(gateway))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert await incoming(gateway, "2") == ""
        for _ in range(100):
            await asyncio.sleep(0)
            delivered = list(orch._pending_input_service()._delivered)
            if delivered:
                prompt = orch._pending_input_service().inputs._active.get(delivered[0])
                if prompt is not None and prompt.question == "Choose a tag":
                    break
        assert prompt.question == "Choose a tag"
        if not stop_second:
            assert await incoming(gateway, "1,2") == ""
            for _ in range(100):
                await asyncio.sleep(0)
                delivered = list(orch._pending_input_service()._delivered)
                prompt = orch._pending_input_service().inputs._active.get(delivered[0]) if delivered else None
                if prompt is not None and prompt.question == "Choose a note":
                    break
            assert await incoming(gateway, "my note") == ""
        await asyncio.wait_for(turn, 1)
        result = answers[0][0]["result"]
        assert result["ok"] and result["responses"][0]["id"] == "route"
        assert result["responses"][0]["user_response"] == "Remote"
        assert result["responses"][0]["choices_offered"] == ["Local", "Remote"]
        if stop_second:
            assert result["timed_out"] is True
            assert result["responses"][1]["user_response"] == result["responses"][2]["user_response"] == ""
            assert len(orch._pending_input_service()._delivered) == 0
        else:
            assert result["responses"][1]["user_response"] == ["Blue", "Green"]
            assert result["responses"][2]["user_response"] == "my note"
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)


def test_flatten_unwraps_label_first():
    """Unmodified donor assertion from tests/tools/test_clarify_tool.py (MIT)."""
    from agents.core.channels.clarify_protocol import _flatten_choice

    assert _flatten_choice({"label": "Short", "description": "Long"}) == "Short"


@pytest.mark.parametrize("questions", [None, "bad", [False], [{"question": " "}], ["Q"] * 6,
                                       [{"question": "Q", "choices": "bad"}]])
def test_donor_batch_validation_refuses_invalid_questions(questions):
    from agents.core.channels.clarify_protocol import _normalize_questions

    normalized, error = _normalize_questions(questions)
    assert normalized is None and error


def test_donor_batch_stable_ids_choice_cap_and_recommendation():
    from agents.core.channels.clarify_protocol import _normalize_questions

    normalized, error = _normalize_questions([
        {"id": "owner-label", "question": " Q ", "choices": [{"description": " A "}, "B", "C", "D", "E"]},
        {"question": "memo", "multi_select": True},
    ])
    assert not error and [entry["qid"] for entry in normalized] == ["q0", "q1"]
    assert normalized[0]["id"] == "owner-label"
    assert normalized[0]["choices"] == ["A (Recommended)", "B", "C", "D"]
    assert normalized[0]["choices_offered"] == ["A", "B", "C", "D"]
    assert not normalized[1]["multi_select"]


@pytest.mark.asyncio
async def test_stopping_channels_cannot_recreate_a_pending_runtime(tmp_path):
    from unittest.mock import AsyncMock

    orch, _, _, server, _, _, _ = runtime_host(tmp_path)
    prior = orch._pending_input_service()
    orch.heartbeat_scheduler = SimpleNamespace(stop=lambda: None)
    orch.plugin_manager = SimpleNamespace(close_all=AsyncMock())
    orch.channel_manager.stop_all = AsyncMock()
    await orch.stop_channels()
    assert prior.closed
    assert orch._pending_input_service() is None
    result = await server.handle({"tool": "clarify", "args": {"question": "Choose"}})
    assert result["result"]["ok"] is False
    assert orch._pending_inputs is prior


@pytest.mark.asyncio
async def test_same_instance_channel_restart_reopens_route_without_losing_history(tmp_path, context, monkeypatch):
    from unittest.mock import AsyncMock

    from tests.test_session_command_runtime import message

    monkeypatch.setenv("JARVIS_TESTING", "1")
    orch, _, gateway, _, _, base = command_host(tmp_path, context)
    await message(gateway, "keep")
    sid = orch._channel_sessions[base]
    history = await orch.memory.get_history(sid)
    prior = orch._channel_lifecycle
    orch.heartbeat_scheduler = SimpleNamespace(stop=lambda: None, start=lambda _orch: None)
    orch.plugin_manager = SimpleNamespace(close_all=AsyncMock())
    orch.channel_manager.stop_all = AsyncMock()
    orch.channel_manager.start_all = AsyncMock()
    orch._settings_watcher_loop = AsyncMock()
    orch._autonomy = SimpleNamespace(wire=lambda: None, loop=AsyncMock())
    orch._scheduler = SimpleNamespace(schedule_all=lambda: None)
    orch.oracle_bridge = None
    orch.components = SimpleNamespace(summary=lambda: {})
    await orch.stop_channels()
    await orch.start_channels()
    try:
        assert await message(gateway, "next") == "reply"
        assert orch._channel_lifecycle is not prior and prior.closed
        assert orch._channel_sessions[base] == sid
        assert (await orch.memory.get_history(sid))[:len(history)] == history
    finally:
        await orch.stop_channels()


@pytest.mark.asyncio
async def test_other_explains_typed_fallback_even_if_edit_and_instruction_send_fail(tmp_path, monkeypatch):
    import httpx

    from tests.test_pending_input_native_transport import (
        applied_tap,
        finish,
        keyboard,
        native_host,
        tap,
    )

    orch, _, gateway, _, ready, _, answers, channel, requests = await native_host(tmp_path)
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        original = channel.client.post

        async def post(url, **kwargs):
            if url.endswith(("/editMessageReplyMarkup", "/sendMessage")):
                return httpx.Response(400, json={"ok": False}, request=httpx.Request("POST", url))
            return await original(url, **kwargs)

        monkeypatch.setattr(channel.client, "post", post)
        await applied_tap(channel, tap(keyboard(requests)[-2][0]["callback_data"]))
        assert any(method == "answerCallbackQuery" and "Type your answer" in body["text"]
                   for method, body in requests)
        assert await incoming(gateway, "my route", message_thread_id=8) == ""
        await asyncio.wait_for(turn, 1)
        assert answers[0][0]["result"]["user_response"] == "my route"
    finally:
        await finish(orch, channel, turn)


@pytest.mark.asyncio
async def test_telegram_restart_reopens_http_and_owned_deletion_lifecycle(monkeypatch):
    from unittest.mock import AsyncMock

    from agents.core.channels.telegram import TelegramChannel

    channel = TelegramChannel(token="synthetic")
    await channel.stop()
    old_client = channel.client
    monkeypatch.setattr(channel, "_get_me", AsyncMock(return_value={"id": 1, "username": "synthetic"}))
    monkeypatch.setattr(channel, "_poll_loop", AsyncMock())
    try:
        await channel.start()
        assert not channel.client.is_closed and channel.client is not old_client
        assert not channel._ephemeral_deletes._closed
    finally:
        await channel.stop()
