"""Hermes workspace replies use the same approval path as the owner inbox."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.channel_inbox import ChannelInboxStore
from agents.core.channel_reply import ChannelReplyBroker
from agents.core.channels.discord import DiscordChannel
from agents.core.channels.gateway import Gateway
from agents.core.channels.manager import ChannelManager
from agents.core.channels.session import SessionSource
from agents.core.channels.slack import SlackChannel
from agents.core.kernel import Decision, Verdict
from tests.test_channel_handler_session_wiring import _bare_orchestrator

CASES = [
    ("slack", {"slack_channel": "C123", "thread_ts": "100.001"}),
    ("discord", {"channel_id": "123"}),
]


@pytest.mark.parametrize("channel,reply", CASES)
def test_workspace_inbox_is_scoped_to_room_not_sender(tmp_path, channel, reply):
    path = tmp_path / "inbox.json"
    inbox = ChannelInboxStore(path)
    first = inbox.record_inbound(channel, "one", sender="7", metadata=reply)
    same = inbox.record_inbound(channel, "two", sender="8", metadata=reply)
    other_reply = {**reply, ("slack_channel" if channel == "slack" else "channel_id"): "456"}
    other = inbox.record_inbound(channel, "three", sender="7", metadata=other_reply)
    assert first is not None and same is not None and other is not None
    assert first["thread_id"] == same["thread_id"] != other["thread_id"]
    restored = ChannelInboxStore(path)
    assert restored.get_message(first["id"])["reply"] == reply
    assert len(restored.threads()) == 2


def test_slack_threads_in_one_room_have_distinct_inbox_identity(tmp_path):
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    records = [inbox.record_inbound("slack", "hi", sender="U1", metadata={
        "slack_channel": "C1", **({"thread_ts": ts} if ts else {}),
    }) for ts in ("100.001", "100.002", "")]
    assert all(records)
    assert len({r["thread_id"] for r in records}) == 3


@pytest.mark.parametrize("channel,reply", CASES)
@pytest.mark.asyncio
async def test_workspace_reply_waits_for_approval_then_uses_reply_transport(tmp_path, channel, reply):
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    inbound = inbox.record_inbound(channel, "ping", sender="7", metadata=reply)
    assert inbound is not None
    queue = TaskQueue(db_path=str(tmp_path / "queue.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(), executor=None)
    adapter = SimpleNamespace(channel_id=channel, send=AsyncMock(return_value=True))
    manager = ChannelManager()
    manager.register(adapter)
    broker = ChannelReplyBroker(inbox=inbox, enqueue=worker.govern_enqueue, channel_manager=manager)

    result = broker.request(inbound["thread_id"], "pong")
    assert result["ok"] and result["queued"]
    task = queue.get(result["task_id"])
    assert task.status == TaskStatus.BLOCKED.value
    adapter.send.assert_not_awaited()
    assert await manager.send(channel, "bypass", **reply) is False
    adapter.send.assert_not_awaited()

    # Simulate the approved worker entering the already-governed executor seam.
    assert (await broker.execute(task))["status"] == "ok"
    adapter.send.assert_awaited_once_with("pong", **reply)
    assert inbox.messages(inbound["thread_id"])[-1]["reply_to"] == inbound["id"]


@pytest.mark.parametrize("channel,reply", CASES)
def test_workspace_kernel_denial_never_queues(tmp_path, monkeypatch, channel, reply):
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    inbound = inbox.record_inbound(channel, "ping", sender="7", metadata=reply)
    assert inbound is not None
    enqueue = Mock()
    monkeypatch.setattr("agents.core.kernel.kernel_enabled", lambda: True)
    broker = ChannelReplyBroker(inbox=inbox, enqueue=enqueue,
                                kernel=lambda a: Decision(Verdict.DENY, reason="policy_denied"))
    assert broker.request(inbound["thread_id"], "pong")["reason"] == "policy_denied"
    enqueue.assert_not_called()


@pytest.mark.parametrize("channel,reply", [
    ("slack", {}), ("slack", {"slack_channel": ""}),
    ("slack", {"slack_channel": "C1", "thread_ts": "bad"}),
    ("discord", {}), ("discord", {"channel_id": True}),
    ("discord", {"channel_id": "not-a-snowflake"}),
])
@pytest.mark.asyncio
async def test_missing_or_invalid_workspace_target_cannot_execute(channel, reply):
    manager = SimpleNamespace(send_channel_reply=AsyncMock())
    broker = ChannelReplyBroker(channel_manager=manager, inbox=ChannelInboxStore(None))
    result = await broker.execute(SimpleNamespace(payload={
        "thread_id": "known", "message_id": "m1", "channel": channel,
        "text": "pong", "reply": reply,
    }))
    assert result["status"] == "blocked"
    manager.send_channel_reply.assert_not_awaited()


@pytest.mark.parametrize("channel,reply", CASES)
def test_automatic_reply_binds_original_message_even_after_a_new_arrival(tmp_path, channel, reply):
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    first = inbox.record_inbound(channel, "first", sender="7", metadata=reply, now=10)
    second = inbox.record_inbound(channel, "second", sender="7", metadata=reply, now=11)
    assert first is not None and second is not None
    enqueue = Mock(return_value=1)
    broker = ChannelReplyBroker(inbox=inbox, enqueue=enqueue)
    result = broker.request_for_message(first["id"], "answer one", channel=channel)
    assert result["queued"]
    assert enqueue.call_args.kwargs["payload"]["message_id"] == first["id"]
    enqueue.reset_mock()
    assert not broker.request_for_message(first["id"], "wrong", channel="email")["ok"]
    assert not broker.request_for_message("unknown", "wrong", channel=channel)["ok"]
    enqueue.assert_not_called()


@pytest.mark.parametrize("channel,reply", CASES)
@pytest.mark.asyncio
async def test_adapter_gateway_and_orchestrator_queue_once_without_direct_echo(tmp_path, channel, reply):
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    enqueue = Mock(return_value=1)
    orch, captured = _bare_orchestrator(response="pong")
    orch.channel_replies = ChannelReplyBroker(inbox=inbox, enqueue=enqueue)
    gateway = Gateway(handler=orch.channel_handler, inbox_store=inbox)
    if channel == "slack":
        adapter = SlackChannel(handler=gateway.route)
        await adapter.receive_event("ping", reply["slack_channel"], user="7",
                                    thread_ts=reply["thread_ts"], _inbox_message_id="forged")
    else:
        adapter = DiscordChannel(handler=gateway.route)
        sink = SimpleNamespace(id=123, send=AsyncMock())
        await adapter._handle_message(SimpleNamespace(
            content="ping", author=SimpleNamespace(id=7), channel=sink,
        ))
        sink.send.assert_not_awaited()
    enqueue.assert_called_once()
    payload = enqueue.call_args.kwargs["payload"]
    assert payload["reply"] == reply and payload["channel"] == channel
    assert inbox.get_message(payload["message_id"])["text"] == "ping"
    assert captured["sent"] == []


@pytest.mark.parametrize("channel,reply", CASES)
@pytest.mark.asyncio
async def test_gateway_store_failure_cannot_reuse_an_injected_message_id(tmp_path, channel, reply):
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    old = inbox.record_inbound(channel, "old", sender="7", metadata=reply)
    assert old is not None
    orch, cap = _bare_orchestrator()
    enqueue = Mock()
    orch.channel_replies = ChannelReplyBroker(inbox=inbox, enqueue=enqueue)
    gateway = Gateway(handler=orch.channel_handler,
                      inbox_store=SimpleNamespace(record_inbound=Mock(side_effect=OSError("disk"))))
    await gateway.route("new", channel=channel, sender="7", _inbox_message_id=old["id"], **reply)
    enqueue.assert_not_called()
    assert cap["sent"] == []


@pytest.mark.asyncio
async def test_workspace_sessions_separate_rooms_and_slack_threads():
    orch, cap = _bare_orchestrator()
    for room, ts in (("C1", "100.001"), ("C1", "100.002"), ("C2", "100.001")):
        await orch.channel_handler("hi", channel="slack", sender="7", slack_channel=room, thread_ts=ts)
    for room in ("123", "456"):
        await orch.channel_handler("hi", channel="discord", sender="7", channel_id=room)
    assert len(set(cap["sessions"])) == 5


@pytest.mark.parametrize("channel,reply", CASES)
@pytest.mark.asyncio
async def test_failed_workspace_transport_does_not_claim_delivery(tmp_path, channel, reply):
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    inbound = inbox.record_inbound(channel, "ping", sender="7", metadata=reply)
    assert inbound is not None
    broker = ChannelReplyBroker(inbox=inbox, channel_manager=SimpleNamespace(
        send_channel_reply=AsyncMock(return_value=False),
    ))
    result = await broker.execute(SimpleNamespace(payload={
        "thread_id": inbound["thread_id"], "message_id": inbound["id"],
        "channel": channel, "text": "pong", "reply": reply,
    }))
    assert result["status"] == "failed"
    assert len(inbox.messages(inbound["thread_id"])) == 1


@pytest.mark.parametrize("channel,reply", CASES)
def test_edit_support_alone_cannot_publish_unapproved_tokens(channel, reply):
    orch, _ = _bare_orchestrator()
    adapter = SimpleNamespace(descriptor=SimpleNamespace(supports_edit=True), begin_stream=Mock())
    orch.channel_manager.channels = {channel: adapter}
    assert orch._begin_channel_draft(channel, SessionSource(channel=channel), reply) is None
    adapter.begin_stream.assert_not_called()
