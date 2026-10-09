"""Physical governed approval precedes workspace native delivery and receipts."""

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.action_origin import bind_action_origin, reset_action_origin
from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.channel_inbox import ChannelInboxStore
from agents.core.channels.manager import ChannelManager
from tests.test_session_command_kernel import governed  # noqa: F401

MARKUP = {"inline_keyboard": [[{"text": "Local", "callback_data": "h067:abcdefghijklmnop:0:c0"}]]}
RECEIPT = {"channel": "slack", "target": "C1", "message_id": "171.001",
           "thread_id": "170.001", "team_id": "T1"}


@pytest.fixture
def prompt_broker(governed, tmp_path):
    _consent, _ledger, queue, worker, executor, _kill, calls = governed
    worker.policy = AutonomyPolicy(mode="ask")
    broker = executor.resolve("channel.reply").__self__
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    broker._inbox = inbox
    manager = ChannelManager()
    sent = []
    state = {"current": True, "receipt": RECEIPT.copy()}

    async def send_pending_card(text, **kwargs):
        sent.append((text, kwargs))
        return state["receipt"]

    adapter = SimpleNamespace(channel_id="slack", _running=True,
                              _pending_callback_generation=object(),
                              send_pending_card=send_pending_card)
    manager.register(adapter)
    broker._channel_manager = manager
    inbound = inbox.record_inbound("slack", "ask", sender="T1:U2",
                                   metadata={"slack_channel": "C1", "thread_ts": "170.001"})
    return broker, queue, worker, sent, state, inbound, calls, manager


async def start_delivery(host, timeout=2):
    broker, queue, _worker, _sent, state, inbound, _calls, _manager = host
    token = bind_action_origin("inbound")
    try:
        task = asyncio.create_task(broker.deliver_prompt(
            inbound["id"], "Choose a route", channel="slack", sender="T1:U2",
            markup=MARKUP, current=lambda: state["current"], timeout_seconds=timeout))
    finally:
        reset_action_origin(token)
    for _ in range(30):
        await asyncio.sleep(0)
        if task.done() or queue.list():
            break
    return task


@pytest.mark.asyncio
async def test_signed_channel_reply_requires_approval_before_native_receipt(prompt_broker):
    broker, queue, worker, sent, _state, _inbound, calls, manager = prompt_broker
    task = await start_delivery(prompt_broker)
    try:
        [queued] = queue.list()
        assert queued.status == "blocked" and queued.mediation_receipt is not None
        assert queued.origin == "inbound" and len(calls) == 1
        assert queued.payload == broker._pending_prompts[queued.id].payload
        assert sent == [] and not task.done()
        assert not await manager.send("slack", "unapproved", slack_channel="C1")
        await worker.apply_decision(queued.id, "accept", decided_by="owner")
        assert (await worker.tick(task_id=queued.id))["done"] == 1
        assert queue.get(queued.id).result["status"] == "ok", queue.get(queued.id).result
        assert await task == RECEIPT
        assert sent[0][1]["reply_markup"] == MARKUP
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["revoked", "payload", "inbound"])
async def test_expired_changed_or_revoked_prompt_cannot_send(prompt_broker, changed):
    broker, queue, worker, sent, state, inbound, _calls, _manager = prompt_broker
    task = await start_delivery(prompt_broker)
    try:
        [queued] = queue.list()
        await worker.apply_decision(queued.id, "accept", decided_by="owner")
        if changed == "revoked":
            state["current"] = False
        elif changed == "payload":
            queue.update_payload(queued.id, {**queued.payload, "text": "changed"})
        else:
            broker._inbox = ChannelInboxStore(broker._inbox.path, max_messages=1)
            broker._inbox.record_inbound("slack", "new", sender="T1:U2",
                                        metadata={"slack_channel": "C1"})
        await worker.tick(task_id=queued.id)
        assert await asyncio.wait_for(task, 1) is None
        assert sent == []
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_timeout_removes_delivery_binding_before_late_approval(prompt_broker):
    broker, queue, worker, sent, _state, _inbound, _calls, _manager = prompt_broker
    task = await start_delivery(prompt_broker, timeout=0.01)
    assert await asyncio.wait_for(task, 1) is None
    [queued] = queue.list()
    assert broker._pending_prompts == {}
    await worker.apply_decision(queued.id, "accept", decided_by="owner")
    await worker.tick(task_id=queued.id)
    assert sent == []
