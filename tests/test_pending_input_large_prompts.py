"""Large prompts keep full signed content without widening mediation limits."""

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from agents.core.action_origin import bind_action_origin, reset_action_origin
from agents.core.autonomy.mediation import MAX_CANONICAL_BYTES, canonical_json
from tests.test_pending_input_workspace_broker import MARKUP, RECEIPT, prompt_broker  # noqa: F401
from tests.test_pending_input_workspace_runtime import (
    approve_delivery,
    button,
    stop_host,
    waiting_prompt,
    workspace_host,
)
from tests.test_session_command_kernel import governed  # noqa: F401


async def start_large(host, text, markup=MARKUP):
    broker, queue, _worker, _sent, state, inbound, _calls, _manager = host
    token = bind_action_origin("inbound")
    try:
        delivery = asyncio.create_task(broker.deliver_prompt(
            inbound["id"], text, channel="slack", sender="T1:U2", markup=markup,
            current=lambda: state["current"], timeout_seconds=2))
    finally:
        reset_action_origin(token)
    for _ in range(30):
        await asyncio.sleep(0)
        if delivery.done() or queue.list():
            break
    return delivery


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["long_text", "unicode_buttons"])
async def test_complete_large_prompt_crosses_real_signed_approval(prompt_broker, shape):
    broker, queue, worker, sent, _state, _inbound, calls, _manager = prompt_broker
    text = "Complete question " + "x" * 17000 if shape == "long_text" else "Choose precisely"
    markup = MARKUP if shape == "long_text" else {"inline_keyboard": [[
        {"text": "🧪" * 16000, "callback_data": f"h067:abcdefghijklmnop:0:c{n}"}
        for n in range(4)]]}
    delivery = await start_large(prompt_broker, text, markup)
    try:
        [queued] = queue.list()
        assert queued.status == "blocked" and queued.mediation_receipt
        assert len(canonical_json(queued.payload)) <= MAX_CANONICAL_BYTES
        assert set(queued.payload["native_prompt"]) == {
            "sender", "expires_at", "content_sha256", "content_size"}
        entry = broker._pending_prompts[queued.id]
        assert hashlib.sha256(entry.content).hexdigest() == queued.payload["native_prompt"]["content_sha256"]
        assert len(entry.content) == queued.payload["native_prompt"]["content_size"]
        assert broker.review_prompt(queued) == {"available": True, "text": text,
                                               "choices": [b["text"] for r in markup["inline_keyboard"] for b in r]}
        assert not sent and not delivery.done() and len(calls) == 1
        await worker.apply_decision(queued.id, "accept", decided_by="owner")
        assert (await worker.tick(task_id=queued.id))["done"] == 1
        assert queue.get(queued.id).result["status"] == "ok"
        assert await delivery == RECEIPT
        assert sent == [(text, {**queued.payload["reply"], "reply_markup": markup})]
    finally:
        delivery.cancel()
        await asyncio.gather(delivery, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["content", "digest", "size", "restart", "revoke", "reject", "inbound", "expire"])
async def test_reference_cannot_outlive_or_change_approved_content(prompt_broker, change):
    broker, queue, worker, sent, state, inbound, _calls, _manager = prompt_broker
    delivery = await start_large(prompt_broker, "Question " + "x" * 17000)
    try:
        [queued] = queue.list()
        if change == "reject":
            await worker.apply_decision(queued.id, "reject", decided_by="owner")
        else:
            await worker.apply_decision(queued.id, "accept", decided_by="owner")
        if change == "content":
            entry = broker._pending_prompts[queued.id]
            entry.content = entry.content.replace(b'Question', b'Changed!')
        elif change in {"digest", "size"}:
            payload = json.loads(json.dumps(queued.payload))
            field = "content_sha256" if change == "digest" else "content_size"
            payload["native_prompt"][field] = "a" * 64 if change == "digest" else 1
            queue.update_payload(queued.id, payload)
        elif change == "restart":
            broker.close_pending_prompts()
        elif change == "revoke":
            state["current"] = False
        elif change == "expire":
            broker._pending_prompts[queued.id].deadline = 0
        elif change == "inbound":
            next(m for m in broker._inbox._messages if m["id"] == inbound["id"])["sender"] = "T1:U3"
        assert broker.review_prompt(queue.get(queued.id)) == {"available": False}
        await worker.tick(task_id=queued.id)
        assert await asyncio.wait_for(delivery, 1) is None
        assert sent == []
    finally:
        delivery.cancel()
        await asyncio.gather(delivery, return_exceptions=True)


@pytest.mark.asyncio
async def test_reference_changed_during_transport_does_not_credit_delivery(prompt_broker):
    broker, queue, worker, _sent, _state, _inbound, _calls, manager = prompt_broker
    delivery = await start_large(prompt_broker, "Question " + "x" * 17000)
    try:
        [queued] = queue.list()
        discarded = []

        async def changed_send(*_args, **_kwargs):
            entry = broker._pending_prompts[queued.id]
            entry.content = entry.content.replace(b'Question', b'Changed!')
            return RECEIPT

        manager.send_channel_prompt = changed_send
        manager.discard_pending_card = lambda channel, receipt: discarded.append((channel, receipt))
        await worker.apply_decision(queued.id, "accept", decided_by="owner")
        await worker.tick(task_id=queued.id)
        assert await delivery is None
        assert discarded == [("slack", RECEIPT)]
        assert all(m["direction"] == "in" for m in broker._inbox._messages)
    finally:
        delivery.cancel()
        await asyncio.gather(delivery, return_exceptions=True)


@pytest.mark.asyncio
async def test_reference_memory_admission_is_bounded_and_does_not_queue(prompt_broker, monkeypatch):
    monkeypatch.setattr("agents.core.channel_reply._PROMPT_CONTENT_TOTAL", 1)
    delivery = await start_large(prompt_broker, "Question " + "x" * 17000)
    broker, queue, _worker, sent, *_rest = prompt_broker
    assert await delivery is None
    assert queue.list() == [] and sent == [] and broker._pending_prompts == {}


@pytest.mark.asyncio
async def test_admin_preview_uses_live_broker_and_never_exposes_lost_content(prompt_broker, monkeypatch):
    from agents.core.routers import autonomy

    broker, queue, _worker, sent, _state, _inbound, _calls, _manager = prompt_broker
    delivery = await start_large(prompt_broker, "Entire question " + "x" * 17000)
    try:
        [queued] = queue.list()
        orch = SimpleNamespace(channel_replies=broker)
        monkeypatch.setattr(autonomy, "require_component", lambda *_args: (orch, queue, None))
        result = await autonomy.autonomy_task_preview(queued.id)
        assert "no-store" in result.headers["cache-control"].split(", ")
        assert json.loads(result.body)["prompt"]["text"].endswith("x" * 17000)
        assert not sent
        broker.close_pending_prompts()
        result = await autonomy.autonomy_task_preview(queued.id)
        assert json.loads(result.body)["prompt"] == {"available": False}
    finally:
        delivery.cancel()
        await asyncio.gather(delivery, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["slack", "discord"])
async def test_large_unicode_question_is_usable_through_actual_sdk_rpc(tmp_path, prompt_broker, channel):
    orch, _cap, gateway, server, _pairing, answers, adapter, requests, meta = await workspace_host(
        tmp_path, prompt_broker, channel)
    original = server.handle
    labels = [prefix + "🧪" * 11000 for prefix in ("Local ", "Remote ")]

    async def large_handle(request, *args, **kwargs):
        return await original({**request, "args": {**request["args"], "choices": labels}}, *args, **kwargs)

    server.handle = large_handle
    turn = asyncio.create_task(gateway.route("ask", channel=channel, **meta))
    broker, queue, worker, *_rest = prompt_broker
    try:
        queued = await waiting_prompt(queue, turn)
        assert "content_sha256" in queued.payload["native_prompt"]
        assert labels[1] in broker.review_prompt(queued)["text"]
        await approve_delivery(orch, queue, worker, turn)
        assert requests
        await button(adapter, channel)
        assert await asyncio.wait_for(turn, 1) == "Finished"
        assert answers[0][0]["result"]["user_response"] == labels[1]
    finally:
        await stop_host(orch, turn, adapter)
