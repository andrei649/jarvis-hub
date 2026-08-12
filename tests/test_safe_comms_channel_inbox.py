"""Safe Comms channel inbox transport v0.

The product loop is intentionally narrow: supported inbound messages become
bounded inbox threads, a reply draft enters the existing approval funnel, and an
approved task sends through the live channel manager.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.channel_inbox import ChannelInboxStore
from agents.core.channel_reply import ChannelReplyBroker
from agents.core.channels.email import EmailChannel
from agents.core.channels.gateway import Gateway
from agents.core.channels.manager import ChannelManager
from agents.core.kernel import Decision, Verdict


def test_inbox_store_persists_bounded_threads(tmp_path):
    path = tmp_path / "channel_inbox.json"
    store = ChannelInboxStore(path, max_messages=2)

    first = store.record_inbound(
        "telegram",
        "first",
        sender="42",
        metadata={"chat_id": 99, "ignored": object()},
        now=10.0,
    )
    store.record_inbound("telegram", "second", sender="42", metadata={"chat_id": 99}, now=11.0)
    newest = store.record_inbound(
        "web",
        "third",
        sender="client-a",
        metadata={"client_id": "client-a"},
        now=12.0,
    )

    reloaded = ChannelInboxStore(path, max_messages=2)
    assert reloaded.get_message(first["id"]) is None
    assert reloaded.get_message(newest["id"])["text"] == "third"
    threads = reloaded.threads()
    assert [t["channel"] for t in threads] == ["web", "telegram"]
    assert threads[0]["count"] == 1
    assert threads[1]["reply"]["chat_id"] == 99


@pytest.mark.asyncio
async def test_gateway_records_supported_inbound_after_pairing_allows(tmp_path):
    store = ChannelInboxStore(tmp_path / "inbox.json")
    seen = []

    async def handler(text, **kwargs):
        seen.append((text, kwargs))
        return "ok"

    gateway = Gateway(handler=handler, inbox_store=store)
    reply = await gateway.route("hello", channel="telegram", sender="42", chat_id=99)

    assert reply == "ok"
    assert seen[0][1]["origin"] == "inbound"
    threads = store.threads()
    assert len(threads) == 1
    assert threads[0]["channel"] == "telegram"
    assert threads[0]["reply"] == {"chat_id": 99}


@pytest.mark.asyncio
async def test_gateway_does_not_store_held_pairing_messages(tmp_path):
    store = ChannelInboxStore(tmp_path / "inbox.json")

    class Pairing:
        def gate_inbound(self, channel, sender, code=None):
            return {"allowed": False, "message": "pair first"}

    async def handler(text, **kwargs):  # pragma: no cover - should not be reached
        raise AssertionError("held senders must not reach the handler")

    gateway = Gateway(handler=handler, pairing=Pairing(), inbox_store=store)
    reply = await gateway.route("secret", channel="telegram", sender="42", chat_id=99)

    assert reply == "pair first"
    assert store.threads() == []


def test_channel_reply_request_reaches_decision_inbox(tmp_path, monkeypatch):
    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(), executor=None)
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    inbound = inbox.record_inbound("telegram", "ping", sender="42", metadata={"chat_id": 99})

    broker = ChannelReplyBroker(inbox=inbox, enqueue=worker.govern_enqueue)
    result = broker.request(inbound["thread_id"], "pong", agent="veronica", source="test")

    assert result["ok"] is True
    assert result["queued"] is True
    task = queue.get(result["task_id"])
    assert task.status == TaskStatus.BLOCKED.value
    assert task.kind == "channel.reply"
    assert task.payload["reply"] == {"chat_id": 99}
    assert any(t.id == task.id for t in queue.pending_decisions())

    # Email remains governed by the same action boundary: a kernel DENY blocks
    # before an executor or SMTP transport can be reached.
    email = inbox.record_inbound(
        "email",
        "please answer",
        sender="ana@example.com",
        metadata={"from_addr": "ana@example.com", "subject": "Ping"},
    )
    monkeypatch.setattr("agents.core.kernel.kernel_enabled", lambda: True)
    denied = ChannelReplyBroker(
        inbox=inbox,
        kernel=lambda action: Decision(Verdict.DENY, reason="policy_denied"),
    ).request(email["thread_id"], "do not send")
    assert denied["ok"] is False
    assert denied["reason"] == "policy_denied"


@pytest.mark.asyncio
async def test_approved_channel_reply_sends_and_records_outbound(tmp_path):
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    inbound = inbox.record_inbound("telegram", "ping", sender="42", metadata={"chat_id": 99})

    class FakeTelegram:
        channel_id = "telegram"

        def __init__(self):
            self.sent = []

        async def send(self, message, **kwargs):
            self.sent.append((message, kwargs))
            return True

    manager = ChannelManager()
    fake = FakeTelegram()
    manager.register(fake)
    broker = ChannelReplyBroker(inbox=inbox, channel_manager=manager)
    task = SimpleNamespace(payload={
        "thread_id": inbound["thread_id"],
        "message_id": inbound["id"],
        "channel": "telegram",
        "text": "pong",
        "reply": {"chat_id": 99},
    })

    out = await broker.execute(task)

    assert out["status"] == "ok"
    assert fake.sent == [("pong", {"chat_id": 99})]
    messages = inbox.messages(inbound["thread_id"])
    assert [m["direction"] for m in messages] == ["in", "out"]
    assert messages[-1]["reply_to"] == inbound["id"]

    # Registering EmailChannel must NOT make the generic inbound-response path
    # capable of SMTP. Only the governed ChannelReplyBroker executor can use the
    # dedicated reply transport.
    smtp = []
    email_channel = EmailChannel(smtp_config={"host": "smtp.local", "from": "jarvis@local"})
    email_channel._smtp_send = lambda msg, to_addr: smtp.append((msg, to_addr))
    manager.register(email_channel)
    assert await manager.send(
        "email", "must not send", to="ana@example.com", subject="Ping"
    ) is False
    assert smtp == []

    email_inbound = inbox.record_inbound(
        "email",
        "hello",
        sender="ana@example.com",
        metadata={"from_addr": "ana@example.com", "subject": "Ping"},
    )
    email_task = SimpleNamespace(payload={
        "thread_id": email_inbound["thread_id"],
        "message_id": email_inbound["id"],
        "channel": "email",
        "text": "calendar is clear",
        "reply": {"to": "ana@example.com", "subject": "Ping"},
    })
    email_out = await broker.execute(email_task)
    assert email_out["status"] == "ok"
    assert len(smtp) == 1
    assert smtp[0][1] == "ana@example.com"
    assert smtp[0][0]["Subject"] == "Ping"


def test_channel_inbox_api_lists_threads_messages_and_status(monkeypatch, tmp_path):
    from agents import web

    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    inbound = inbox.record_inbound("telegram", "ping", sender="42", metadata={"chat_id": 99})
    monkeypatch.setattr(web, "orch", SimpleNamespace(channel_inbox=inbox))
    client = TestClient(web.app)

    status = client.get("/api/channels/inbox/status")
    threads = client.get("/api/channels/inbox")
    messages = client.get(f"/api/channels/inbox/{inbound['thread_id']}")

    assert status.status_code == 200
    assert status.json()["stats"]["threads"] == 1
    assert threads.status_code == 200
    assert threads.json()["threads"][0]["thread_id"] == inbound["thread_id"]
    assert messages.status_code == 200
    assert messages.json()["messages"][0]["text"] == "ping"


def test_channel_inbox_reply_api_enqueues_governed_reply(monkeypatch, tmp_path):
    from agents import web

    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(), executor=None)
    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    inbound = inbox.record_inbound("telegram", "ping", sender="42", metadata={"chat_id": 99})
    broker = ChannelReplyBroker(inbox=inbox, enqueue=worker.govern_enqueue)
    monkeypatch.setattr(web, "orch", SimpleNamespace(channel_inbox=inbox, channel_replies=broker))
    client = TestClient(web.app)

    response = client.post(
        f"/api/channels/inbox/{inbound['thread_id']}/reply",
        json={"text": "pong", "agent": "veronica", "source": "test"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["queued"] is True
    task = queue.get(body["task_id"])
    assert task.status == TaskStatus.BLOCKED.value
    assert task.payload["text"] == "pong"


def test_channel_inbox_reply_api_fallback_uses_governed_enqueue(monkeypatch, tmp_path):
    from agents import web

    inbox = ChannelInboxStore(tmp_path / "inbox.json")
    inbound = inbox.record_inbound("telegram", "ping", sender="42", metadata={"chat_id": 99})
    calls = []

    def govern_enqueue(agent, kind, title, **kwargs):
        calls.append((agent, kind, title, kwargs))
        return 123

    monkeypatch.setattr(web, "orch", SimpleNamespace(
        channel_inbox=inbox,
        autonomy_worker=SimpleNamespace(govern_enqueue=govern_enqueue),
    ))
    client = TestClient(web.app)

    response = client.post(
        f"/api/channels/inbox/{inbound['thread_id']}/reply",
        json={"text": "pong", "agent": "veronica", "source": "test"},
    )

    assert response.status_code == 200
    assert response.json()["task_id"] == 123
    assert calls
    assert calls[0][1] == "channel.reply"
    assert calls[0][3]["autonomy_level"] == "ask"
