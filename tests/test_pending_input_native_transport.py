"""H067 real Telegram transport, pending ToolRPC, gateway and callback ingress."""

import asyncio
import json

import httpx
import pytest

from agents.core.channels.batching import Coalescer
from agents.core.channels.manager import ChannelManager
from agents.core.channels.telegram import TelegramChannel
from tests.test_h011_rollback_conversation import context
from tests.test_pending_input_ingress import update
from tests.test_pending_input_runtime import incoming, runtime_host
from tests.test_session_command_runtime import command_host, message


async def native_host(tmp_path, *, receipt=701, fallback_receipt=701):
    orch, cap, gateway, server, ready, pairing, answers = runtime_host(tmp_path)
    channel, requests = await install_native(orch, gateway, ready, pairing, receipt=receipt,
                                             fallback_receipt=fallback_receipt)
    return orch, cap, gateway, server, ready, pairing, answers, channel, requests


async def install_native(orch, gateway, ready, pairing, *, receipt=701, fallback_receipt=701):
    gateway.pending_handler = orch.channel_pending_handler
    gateway.pending_callback_handler = getattr(orch, "channel_pending_callback", None)
    channel = TelegramChannel(token="synthetic", handler=gateway.route, pairing=pairing)
    channel.pending_reply_handler = gateway.route_pending
    channel.pending_callback_handler = getattr(gateway, "route_pending_callback", None)
    await channel.client.aclose()
    requests = []

    async def bot_api(request):
        body = json.loads(request.content)
        requests.append((request.url.path.rsplit("/", 1)[-1], body))
        if request.url.path.endswith("/sendMessage"):
            ready.set()
            ack = receipt if "reply_markup" in body else fallback_receipt
            return httpx.Response(200, json={"ok": True, "result": {"message_id": ack}})
        return httpx.Response(200, json={"ok": True, "result": True})

    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(bot_api))
    channel._running = True
    channel._batch = Coalescer(0, 0)
    manager = ChannelManager()
    manager.register(channel)
    orch.channel_manager = manager
    orch._begin_channel_draft = lambda *_args: None
    return channel, requests


def tap(data, *, uid=42, chat=123, topic=8, message_id=701, callback_id="tap"):
    return {"id": callback_id, "data": data, "from": {"id": uid},
            "message": {"message_id": message_id, "chat": {"id": chat, "type": "private"},
                        "message_thread_id": topic}}


def keyboard(requests):
    return next(body["reply_markup"]["inline_keyboard"] for method, body in requests
                if method == "sendMessage" and "reply_markup" in body)


async def finish(orch, channel, task):
    orch._pending_input_service().close()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await channel.stop()


@pytest.mark.asyncio
async def test_native_choice_resumes_actual_rpc_without_another_model_turn(tmp_path):
    orch, cap, gateway, _server, ready, _pairing, answers, channel, requests = await native_host(tmp_path)
    gateway.set_rate_limit(1)
    task = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert any("reply_markup" in body for method, body in requests if method == "sendMessage"), \
            "the actual clarification transport sent no native choices"
        data = keyboard(requests)[1][0]["callback_data"]
        await channel._handle_update({"callback_query": tap(data)})
        assert await asyncio.wait_for(task, 1) == "Finished"
        assert answers[0][0]["result"]["user_response"] == "Remote"
        assert len(cap["sessions"]) == 1
        assert "Rate limit" in await incoming(gateway, "ordinary", message_thread_id=8)
    finally:
        await finish(orch, channel, task)


@pytest.mark.asyncio
async def test_polling_callback_bypasses_the_waiting_chat_lane(tmp_path):
    orch, cap, _gateway, _server, ready, _pairing, answers, channel, requests = await native_host(tmp_path)
    done = asyncio.Event()
    page = 0

    async def pages(timeout=25):
        nonlocal page
        page += 1
        if page == 1:
            return [update("ask")]
        if page == 2:
            await ready.wait()
            assert any("reply_markup" in body for method, body in requests if method == "sendMessage")
            return [{"update_id": 101, "callback_query": tap(keyboard(requests)[1][0]["callback_data"])}]
        while not answers:
            await asyncio.sleep(0.01)
        channel._running = False
        done.set()
        return []

    channel._get_updates = pages
    poll = asyncio.create_task(channel._poll_loop())
    try:
        await asyncio.wait_for(done.wait(), 1)
        await asyncio.wait_for(poll, 1)
        assert answers[0][0]["result"]["user_response"] == "Remote"
        assert len(cap["sessions"]) == 1
    finally:
        await finish(orch, channel, poll)


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt", [True, "701", 0, -1])
async def test_card_transport_requires_positive_exact_integer_ack(tmp_path, receipt):
    orch, _cap, _gateway, _server, _ready, _pairing, _answers, channel, requests = await native_host(
        tmp_path, receipt=receipt)
    sender = getattr(orch.channel_manager, "send_pending_card", None)
    try:
        assert callable(sender), "no gated native card transport is available"
        assert await sender("telegram", "Choose", {"inline_keyboard": []},
                            chat_id=123, message_thread_id=8) is None
        assert requests[0][1]["message_thread_id"] == 8
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_native_transport_chunks_utf16_and_binds_only_final_plain_topic_message(tmp_path):
    orch, _cap, _gateway, _server, _ready, _pairing, _answers, channel, requests = await native_host(tmp_path)
    sender = getattr(orch.channel_manager, "send_pending_card", None)
    try:
        assert callable(sender), "no gated native card transport is available"
        markup = {"inline_keyboard": [[{"text": "One", "callback_data": "synthetic"}]]}
        assert await sender("telegram", "😀" * 2049, markup, chat_id=123, message_thread_id=8) == 701
        bodies = [body for method, body in requests if method == "sendMessage"]
        assert [len(body["text"].encode("utf-16-le")) // 2 for body in bodies] == [4096, 2]
        assert "reply_markup" not in bodies[0] and bodies[1]["reply_markup"] == markup
        assert all(body["message_thread_id"] == 8 and "parse_mode" not in body for body in bodies)
        assert not any(method == "sendVoice" for method, _body in requests)
    finally:
        await channel.stop()


async def applied_tap(channel, callback):
    await channel._handle_update({"callback_query": callback})
    tasks = tuple(getattr(channel, "_pending_callback_fast", {}).values())
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), 1)


@pytest.mark.asyncio
async def test_other_changes_to_free_text_and_explains_the_next_reply(tmp_path):
    orch, _cap, gateway, _server, ready, _pairing, answers, channel, requests = await native_host(tmp_path)
    task = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        rows = keyboard(requests)
        await applied_tap(channel, tap(rows[-2][0]["callback_data"]))
        assert not task.done()
        assert any(method == "sendMessage" and body["text"] == "Type your answer."
                   for method, body in requests), "Other did not explain how to answer"
        assert await incoming(gateway, "my own route", message_thread_id=8) == ""
        await asyncio.wait_for(task, 1)
        assert answers[0][0]["result"]["user_response"] == "my own route"
    finally:
        await finish(orch, channel, task)


@pytest.mark.asyncio
async def test_multiselect_edits_revision_then_submits_clean_choice_values(tmp_path):
    orch, cap, gateway, server, ready, _pairing, answers, channel, requests = await native_host(tmp_path)

    async def model(text, channel="voice", **_kwargs):
        cap["sessions"].append(orch.session_id)
        result = await server.handle({"tool": "clarify", "args": {
            "question": "Choose routes", "choices": ["Local", "Remote"], "multi_select": True}})
        answers.append((result, 0))
        return "Finished"

    orch.handle_input = model
    task = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        initial = keyboard(requests)
        await applied_tap(channel, tap(initial[0][0]["callback_data"]))
        edits = [body for method, body in requests if method == "editMessageReplyMarkup"]
        assert edits and "✓" in edits[-1]["reply_markup"]["inline_keyboard"][0][0]["text"]
        second = edits[-1]["reply_markup"]["inline_keyboard"]
        await applied_tap(channel, tap(initial[1][0]["callback_data"], callback_id="stale"))
        assert not task.done()
        await applied_tap(channel, tap(second[1][0]["callback_data"], callback_id="second"))
        current = [body for method, body in requests if method == "editMessageReplyMarkup"][-1]
        submit = current["reply_markup"]["inline_keyboard"][2][0]["callback_data"]
        await applied_tap(channel, tap(submit, callback_id="submit"))
        await asyncio.wait_for(task, 1)
        assert answers[0][0]["result"]["user_response"] == ["Local", "Remote"]
    finally:
        await finish(orch, channel, task)


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong", [{"uid": 99}, {"chat": 124}, {"topic": 9},
                                  {"message_id": 702}, {"uid": True}, {"topic": True}])
async def test_wrong_callback_identity_cannot_resolve_then_exact_owner_can(tmp_path, wrong):
    orch, _cap, gateway, _server, ready, _pairing, answers, channel, requests = await native_host(tmp_path)
    task = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        data = keyboard(requests)[1][0]["callback_data"]
        await applied_tap(channel, tap(data, **wrong))
        assert not task.done() and not answers
        await applied_tap(channel, tap(data, callback_id="right"))
        await asyncio.wait_for(task, 1)
        assert answers[0][0]["result"]["user_response"] == "Remote"
        before = len(answers)
        await applied_tap(channel, tap(data, callback_id="replay"))
        assert len(answers) == before
        assert requests[-1][1]["text"] == "Not applied."
    finally:
        await finish(orch, channel, task)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/new", "/reset", "/undo"])
@pytest.mark.parametrize("choice", ["once", "cancel", "always"])
async def test_native_command_choices_change_only_confirmed_real_memory(tmp_path, context, command, choice):
    orch, cap, gateway, ready, pairing, base = command_host(tmp_path, context)
    channel, requests = await install_native(orch, gateway, ready, pairing)
    await message(gateway, "keep")
    await message(gateway, "last")
    sid = orch._channel_sessions[base]
    before = await orch.memory.get_history(sid)
    ready.clear()
    requests.clear()
    task = asyncio.create_task(message(gateway, command))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert not task.done()
        rows = keyboard(requests)
        button = rows[0][0 if choice == "once" else 1] if choice != "cancel" else rows[-1][0]
        await applied_tap(channel, tap(button["callback_data"]))
        response = await asyncio.wait_for(task, 1)
        assert cap["model_texts"] == ["keep", "last"]
        if choice == "cancel":
            assert orch._channel_sessions[base] == sid
            assert await orch.memory.get_history(sid) == before
        elif command == "/undo":
            assert [turn["content"] for turn in await orch.memory.get_history(sid)] == ["keep", "reply"]
        else:
            assert orch._channel_sessions[base] != sid
            assert await orch.memory.get_history(sid) == before
            assert await orch.memory.get_history(orch._channel_sessions[base]) == []
        if choice == "always":
            assert "once" in response.lower() and "could not be requested" in response.lower()
    finally:
        await finish(orch, channel, task)


@pytest.mark.asyncio
async def test_pairing_revoked_after_delivery_refuses_callback_and_releases_wait(tmp_path):
    orch, _cap, gateway, _server, ready, pairing, answers, channel, requests = await native_host(tmp_path)
    task = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        data = keyboard(requests)[1][0]["callback_data"]
        pairing.allowed = False
        await applied_tap(channel, tap(data))
        assert requests[-1][1]["text"] == "Not applied."
        await asyncio.wait_for(task, 1)
        assert answers[0][0]["result"] == {"ok": False, "reason": "prompt_binding_lost"}
    finally:
        await finish(orch, channel, task)


@pytest.mark.asyncio
async def test_restarted_transport_cannot_resolve_old_card_then_typed_fallback_can(tmp_path):
    orch, _cap, gateway, _server, ready, _pairing, answers, channel, requests = await native_host(tmp_path)
    task = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        data = keyboard(requests)[1][0]["callback_data"]
        channel._pending_callback_generation = object()
        await applied_tap(channel, tap(data))
        assert not task.done()
        assert requests[-1][1]["text"] == "Not applied."
        assert await incoming(gateway, "2", message_thread_id=8) == ""
        await asyncio.wait_for(task, 1)
        assert answers[0][0]["result"]["user_response"] == "Remote"
    finally:
        await finish(orch, channel, task)


@pytest.mark.asyncio
async def test_stop_cancels_owned_callback_before_closing_transport(tmp_path):
    orch, _cap, _gateway, _server, _ready, _pairing, _answers, channel, requests = await native_host(tmp_path)
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked(callback):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    channel.pending_callback_handler = blocked
    await channel._handle_update({"callback_query": tap("h067:synthetic:0:c0")})
    await asyncio.wait_for(entered.wait(), 1)
    await channel.stop()
    assert cancelled.is_set() and not channel._pending_callback_fast
    assert channel.client.is_closed
    assert not requests


@pytest.mark.asyncio
async def test_card_send_does_not_bypass_contract_or_workspace_governance(tmp_path):
    orch, _cap, _gateway, _server, _ready, _pairing, _answers, channel, requests = await native_host(tmp_path)
    manager = orch.channel_manager
    manager.channels["slack"] = channel
    try:
        assert await manager.send_pending_card("slack", "Choose", {}, chat_id=123) is None
        assert await manager.send_pending_card("telegram", "Choose", {},
                                               **{"chat_id": 123, "bad\nkey": 1}) is None
        assert not requests
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_unverified_native_receipt_leaves_buttons_unbound_and_text_fallback_usable(tmp_path):
    orch, _cap, gateway, _server, ready, _pairing, answers, channel, requests = await native_host(
        tmp_path, receipt="701")
    task = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        data = keyboard(requests)[1][0]["callback_data"]
        await applied_tap(channel, tap(data))
        assert not task.done() and not answers
        assert requests[-1][1]["text"] == "Not applied."
        assert not orch._pending_input_service()._card_tokens
        assert await incoming(gateway, "2", message_thread_id=8) == ""
        await asyncio.wait_for(task, 1)
        assert answers[0][0]["result"]["user_response"] == "Remote"
    finally:
        await finish(orch, channel, task)


@pytest.mark.asyncio
async def test_failed_button_edit_keeps_old_revision_inert_and_free_text_usable(tmp_path):
    orch, _cap, gateway, _server, ready, _pairing, answers, channel, requests = await native_host(tmp_path)
    task = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        old_rows = keyboard(requests)
        await channel.client.aclose()

        async def failed_edit(request):
            body = json.loads(request.content)
            method = request.url.path.rsplit("/", 1)[-1]
            requests.append((method, body))
            return httpx.Response(200, json={"ok": method != "editMessageReplyMarkup",
                                           "result": {"message_id": 703}})

        channel.client = httpx.AsyncClient(transport=httpx.MockTransport(failed_edit))
        await applied_tap(channel, tap(old_rows[-2][0]["callback_data"]))
        await applied_tap(channel, tap(old_rows[1][0]["callback_data"], callback_id="stale"))
        assert not task.done() and requests[-1][1]["text"] == "Not applied."
        assert await incoming(gateway, "still my answer", message_thread_id=8) == ""
        await asyncio.wait_for(task, 1)
        assert answers[0][0]["result"]["user_response"] == "still my answer"
    finally:
        await finish(orch, channel, task)


@pytest.mark.asyncio
async def test_failed_native_and_text_delivery_cancels_prompt_without_credit(tmp_path):
    orch, cap, gateway, _server, ready, _pairing, answers, channel, requests = await native_host(
        tmp_path, receipt="701", fallback_receipt="701")
    task = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        data = keyboard(requests)[1][0]["callback_data"]
        await asyncio.wait_for(task, 1)
        assert answers[0][0]["result"] == {"ok": False, "reason": "prompt_delivery_failed"}
        assert cap["credit"].seconds() == 0
        assert not orch._pending_input_service()._delivered
        await applied_tap(channel, tap(data))
        assert requests[-1][1]["text"] == "Not applied."
    finally:
        await finish(orch, channel, task)


@pytest.mark.asyncio
async def test_pairing_revoked_during_native_ack_cannot_send_a_new_fallback_prompt(tmp_path):
    orch, _cap, gateway, _server, _ready, pairing, answers, channel, requests = await native_host(tmp_path)
    await channel.client.aclose()

    async def revoke_at_receipt(request):
        body = json.loads(request.content)
        method = request.url.path.rsplit("/", 1)[-1]
        requests.append((method, body))
        pairing.allowed = False
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 701}})

    channel.client = httpx.AsyncClient(transport=httpx.MockTransport(revoke_at_receipt))
    task = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(task, 1)
        # The already-started card send can finish; loss of pairing must prevent
        # initiating a second delivery as a fallback for that rejected receipt.
        prompts = [body for method, body in requests if method == "sendMessage" and "Choose" in body["text"]]
        assert len(prompts) == 1, "a new prompt was sent after pairing was revoked"
        assert answers[0][0]["result"]["ok"] is False
        assert not orch._pending_input_service()._delivered
    finally:
        await finish(orch, channel, task)
