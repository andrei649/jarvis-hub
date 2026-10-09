"""Actual SDK cards, signed governed delivery and ToolRPC pending answers."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.channels.discord import DiscordChannel
from agents.core.channels.slack import SlackChannel
from tests.test_pending_input_discord_transport import Client, Interaction, Sink
from tests.test_pending_input_runtime import runtime_host
from tests.test_pending_input_workspace_broker import prompt_broker  # noqa: F401
from tests.test_session_command_kernel import governed  # noqa: F401


async def workspace_host(tmp_path, broker_host, channel, *, multi_select=False):
    broker, queue, worker, _sent, _state, _inbound, _calls, manager = broker_host
    orch, captured, gateway, server, _ready, pairing, answers = runtime_host(tmp_path)
    orch.channel_manager = manager
    orch.channel_replies = broker
    orch.autonomy = worker
    orch.autonomy_queue = queue
    orch._begin_channel_draft = lambda *_a: None
    gateway.inbox_store = broker._inbox
    gateway.pending_handler = orch.channel_pending_handler
    gateway.pending_callback_handler = orch.channel_pending_callback
    if multi_select:
        original_handle = server.handle

        async def handle(request, *args, **kwargs):
            request = {**request, "args": {**request["args"], "multi_select": True}}
            return await original_handle(request, *args, **kwargs)

        server.handle = handle
    requests = []
    if channel == "slack":
        pytest.importorskip("slack_sdk")
        from slack_sdk.web.slack_response import SlackResponse

        def response(data):
            return SlackResponse(client=None, http_verb="POST", api_url="https://slack.invalid",
                                 req_args={}, data=data, headers={}, status_code=200)

        def post(**kwargs):
            requests.append(kwargs)
            return response({"ok": True, "channel": kwargs["channel"], "ts": "171.001"})

        def edit(**kwargs):
            requests.append({"edit": True, **kwargs})
            return response({"ok": True})

        adapter = SlackChannel(token="synthetic", app_token="synthetic", handler=gateway.route,
                               pairing=pairing, pending_reply_handler=gateway.route_pending,
                               pending_callback_handler=gateway.route_pending_callback)
        adapter._client = SimpleNamespace(chat_postMessage=post, chat_update=edit, requests=requests)
        adapter._team_id, adapter._bot_user_id = "T1", "U9"
        adapter._loop = asyncio.get_running_loop()
        adapter._socket_client = SimpleNamespace(send_socket_mode_response=lambda _r: None,
                                                close=lambda: None)
        adapter._inbound_ready = asyncio.Event()
        metadata = {"sender": "T1:U2", "slack_channel": "C1", "thread_ts": "170.001"}
    else:
        pytest.importorskip("discord")
        adapter = DiscordChannel(token="synthetic", handler=gateway.route, pairing=pairing,
                                 pending_reply_handler=gateway.route_pending,
                                 pending_callback_handler=gateway.route_pending_callback)
        sink = Sink()
        adapter._client = Client(sink)
        requests = sink.calls
        metadata = {"sender": "42", "channel_id": "123", "chat_type": "private"}
    adapter._running = True
    adapter._pending_callback_generation = object()
    manager.register(adapter)
    return orch, captured, gateway, server, pairing, answers, adapter, requests, metadata


async def waiting_prompt(queue, turn):
    for _ in range(100):
        await asyncio.sleep(0)
        native = [t for t in queue.list() if "native_prompt" in t.payload]
        if native:
            return native[0]
        if turn.done():
            break
    raise AssertionError("the actual ToolRPC clarification did not queue a governed prompt")


async def button(adapter, channel, index=1, sender=None):
    if channel == "slack":
        from slack_sdk.socket_mode.request import SocketModeRequest

        body = next(request for request in reversed(adapter._client.requests) if "blocks" in request)
        buttons = [element for block in body["blocks"] if block["type"] == "actions"
                   for element in block["elements"]]
        data = buttons[index]["value"]
        payload = {"type": "block_actions", "team": {"id": "T1"},
                   "user": {"id": sender or "U2"}, "channel": {"id": "C1"},
                   "container": {"type": "message", "channel_id": "C1", "message_ts": "171.001"},
                   "message": {"ts": "171.001", "thread_ts": "170.001", "user": "U9"},
                   "actions": [{"type": "button", "action_id": "h067_pending", "value": data}]}
        adapter._on_socket_request(adapter._socket_client,
                                   SocketModeRequest(type="interactive", envelope_id="tap", payload=payload))
        for _ in range(30):
            await asyncio.sleep(0)
            if adapter._pending_fast:
                await asyncio.gather(*tuple(adapter._pending_fast.values()))
                break
    else:
        sink = adapter._client.sink
        edits = sink.messages[-1].edits
        view = edits[-1]["view"] if edits else sink.calls[-1][1]["view"]
        choice = view.children[index]
        await choice.callback(Interaction(adapter, sink.messages[-1], choice.custom_id,
                                          sender=42 if sender is None else sender))
        if adapter._pending_callback_fast:
            await asyncio.gather(*tuple(adapter._pending_callback_fast.values()))


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["slack", "discord"])
async def test_sdk_button_resumes_actual_rpc_after_signed_approval(tmp_path, prompt_broker, channel):
    orch, cap, gateway, _server, _pairing, answers, adapter, requests, meta = await workspace_host(
        tmp_path, prompt_broker, channel)
    _broker, queue, worker, *_ = prompt_broker
    gateway.set_rate_limit(1)
    turn = asyncio.create_task(gateway.route("ask", channel=channel, **meta))
    try:
        queued = await waiting_prompt(queue, turn)
        assert queued.status == "blocked" and queued.mediation_receipt is not None
        assert not requests and cap["credit"].seconds() == 0
        await worker.apply_decision(queued.id, "accept", decided_by="owner")
        assert (await worker.tick(task_id=queued.id))["done"] == 1
        for _ in range(30):
            await asyncio.sleep(0)
            if orch._pending_input_service()._delivered:
                break
        await button(adapter, channel)
        assert await asyncio.wait_for(turn, 1) == "Finished"
        assert answers[0][0]["result"]["user_response"] == "Remote"
        assert len(cap["sessions"]) == 1
        assert "Rate limit" in await gateway.route("ordinary", channel=channel, **meta)
    finally:
        orch._pending_input_service().close()
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await adapter.stop()


async def approve_delivery(orch, queue, worker, turn):
    queued = await waiting_prompt(queue, turn)
    await worker.apply_decision(queued.id, "accept", decided_by="owner")
    assert (await worker.tick(task_id=queued.id))["done"] == 1
    for _ in range(100):
        await asyncio.sleep(0)
        if orch._pending_input_service()._delivered:
            return queued
    raise AssertionError("approved native delivery did not bind a live prompt")


async def stop_host(orch, turn, adapter):
    orch._pending_input_service().close()
    turn.cancel()
    await asyncio.gather(turn, return_exceptions=True)
    await adapter.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["slack", "discord"])
async def test_other_and_typed_answer_bypass_occupied_model_and_rate_budget(tmp_path, prompt_broker, channel):
    orch, cap, gateway, _, _, answers, adapter, _, meta = await workspace_host(tmp_path, prompt_broker, channel)
    _, queue, worker, *_ = prompt_broker
    gateway.set_rate_limit(1)
    turn = asyncio.create_task(gateway.route("ask", channel=channel, **meta))
    try:
        delivered = await approve_delivery(orch, queue, worker, turn)
        wrong = "U3" if channel == "slack" else 43
        await button(adapter, channel, sender=wrong)
        assert not answers and not turn.done()
        await button(adapter, channel, index=2)
        notices = [task for task in queue.list() if task.id != delivered.id]
        assert len(notices) == 1 and notices[0].status == "blocked"
        assert notices[0].payload["text"] == "Type your answer."
        assert notices[0].payload["message_id"] == delivered.payload["message_id"]
        assert await asyncio.wait_for(gateway.route_pending("A custom route", channel=channel, **meta), 1)
        assert await asyncio.wait_for(turn, 1) == "Finished"
        assert answers[0][0]["result"]["user_response"] == "A custom route"
        assert len(cap["sessions"]) == 1
    finally:
        await stop_host(orch, turn, adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["slack", "discord"])
async def test_multiselect_edits_actual_sdk_keyboard_before_submit(tmp_path, prompt_broker, channel):
    orch, cap, gateway, _, _, answers, adapter, _, meta = await workspace_host(
        tmp_path, prompt_broker, channel, multi_select=True)
    _, queue, worker, *_ = prompt_broker
    turn = asyncio.create_task(gateway.route("ask", channel=channel, **meta))
    try:
        await approve_delivery(orch, queue, worker, turn)
        await button(adapter, channel, index=0)
        assert not turn.done() and not answers
        await button(adapter, channel, index=1)
        await button(adapter, channel, index=2)
        assert await asyncio.wait_for(turn, 1) == "Finished"
        assert answers[0][0]["result"]["user_response"] == ["Local", "Remote"]
        assert len(cap["sessions"]) == 1
    finally:
        await stop_host(orch, turn, adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["slack", "discord"])
@pytest.mark.parametrize("revocation", ["pairing", "generation"])
async def test_revocation_before_approval_prevents_delivery_and_wait_credit(
        tmp_path, prompt_broker, channel, revocation):
    orch, cap, gateway, _, pairing, answers, adapter, requests, meta = await workspace_host(
        tmp_path, prompt_broker, channel)
    _, queue, worker, *_ = prompt_broker
    turn = asyncio.create_task(gateway.route("ask", channel=channel, **meta))
    try:
        queued = await waiting_prompt(queue, turn)
        if revocation == "pairing":
            pairing.allowed = False
        else:
            adapter._pending_callback_generation = object()
        await worker.apply_decision(queued.id, "accept", decided_by="owner")
        await worker.tick(task_id=queued.id)
        assert queue.get(queued.id).result["status"] == "blocked"
        assert await asyncio.wait_for(turn, 1) == "Finished"
        assert not requests and cap["credit"].seconds() == 0
        assert answers[0][0]["result"]["reason"] == "prompt_delivery_failed"
    finally:
        await stop_host(orch, turn, adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["slack", "discord"])
async def test_generation_revoked_after_delivery_cannot_accept_typed_answer(tmp_path, prompt_broker, channel):
    orch, _, gateway, _, _, answers, adapter, _, meta = await workspace_host(tmp_path, prompt_broker, channel)
    _, queue, worker, *_ = prompt_broker
    turn = asyncio.create_task(gateway.route("ask", channel=channel, **meta))
    try:
        await approve_delivery(orch, queue, worker, turn)
        adapter._pending_callback_generation = object()
        assert await gateway.route_pending("2", channel=channel, **meta) is False
        assert await asyncio.wait_for(turn, 1.5) == "Finished"
        assert answers[0][0]["result"]["reason"] == "prompt_binding_lost"
    finally:
        await stop_host(orch, turn, adapter)
