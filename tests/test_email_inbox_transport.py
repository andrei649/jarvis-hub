"""Safe Comms channel inbox transport — email (B5, handoff 2026-07-07).

Extends the #551 v0 loop (telegram/web) to email, entirely against test
doubles — no network: inbound IMAP messages become inbox threads whose reply
metadata carries the SMTP kwargs (`to` = the inbound sender, `subject`), a
governed reply queues through the existing approval funnel, and the approved
task's send renders a real MIME message via the EmailChannel with the SMTP
seam stubbed. Inbound email senders now pass `sender=` to the gateway so the
H12.19 pairing gate applies to email like every other external channel.
WhatsApp stays out (bridge hardware — the gate that survived the challenge).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.channel_inbox import SUPPORTED_INBOX_CHANNELS, ChannelInboxStore  # noqa: E402
from agents.core.channel_reply import ChannelReplyBroker  # noqa: E402
from agents.core.channels.email import EmailChannel  # noqa: E402


def test_email_is_a_supported_inbox_channel():
    assert "email" in SUPPORTED_INBOX_CHANNELS


def test_email_inbound_records_thread_with_smtp_reply_metadata(tmp_path):
    store = ChannelInboxStore(tmp_path / "inbox.json")
    rec = store.record_inbound(
        "email",
        "Can you check the calendar for Friday?",
        sender="ana@example.com",
        metadata={"from_addr": "ana@example.com", "subject": "Friday plans"},
        now=10.0,
    )
    assert rec is not None
    assert rec["channel"] == "email"
    assert rec["sender"] == "ana@example.com"
    # reply metadata carries exactly what EmailChannel.send() needs
    assert rec["reply"] == {"to": "ana@example.com", "subject": "Friday plans"}


def test_email_sender_derived_from_from_addr_when_not_passed(tmp_path):
    store = ChannelInboxStore(tmp_path / "inbox.json")
    rec = store.record_inbound(
        "email", "hello", metadata={"from_addr": "bob@example.com", "subject": "s"},
    )
    assert rec["sender"] == "bob@example.com"


def test_email_reply_broker_queues_and_approved_task_sends(tmp_path):
    store = ChannelInboxStore(tmp_path / "inbox.json")
    rec = store.record_inbound(
        "email", "ping", sender="ana@example.com",
        metadata={"from_addr": "ana@example.com", "subject": "Ping"}, now=10.0,
    )

    queued = []

    def enqueue(agent, kind, title, **kwargs):
        queued.append({"agent": agent, "kind": kind, "title": title, **kwargs})
        return "task-1"

    broker = ChannelReplyBroker(inbox=store, enqueue=enqueue)
    out = broker.request(rec["thread_id"], "pong — calendar is clear", agent="pepper")
    assert out["ok"] is True and out["queued"] is True
    assert len(queued) == 1
    payload = queued[0]["payload"]
    assert payload["channel"] == "email"
    assert payload["reply"] == {"to": "ana@example.com", "subject": "Ping"}

    sends = []

    class FakeChannelManager:
        async def send_channel_reply(self, channel, text, **kwargs):
            sends.append((channel, text, kwargs))
            return True

    class FakeTask:
        def __init__(self, payload):
            self.payload = payload

    broker2 = ChannelReplyBroker(inbox=store,
                                 channel_manager=FakeChannelManager())
    result = asyncio.run(broker2.execute(FakeTask(payload)))
    assert result["status"] == "ok"
    assert sends == [("email", "pong — calendar is clear",
                      {"to": "ana@example.com", "subject": "Ping"})]
    # the outbound message lands back in the same thread
    directions = [m["direction"] for m in store.messages(rec["thread_id"])]
    assert directions == ["in", "out"]


def test_email_channel_passes_sender_to_gateway_for_pairing():
    seen = {}

    async def handler(text, **kwargs):
        seen.update(kwargs, text=text)
        return "ok"

    ch = EmailChannel(handler=handler,
                      smtp_config={"host": "smtp.local"},
                      imap_config={"host": "imap.local"})
    ch._imap_fetch = lambda: [("ana@example.com", "Friday plans", "body text")]
    asyncio.run(ch._check_imap())
    assert seen["channel"] == "email"
    assert seen["sender"] == "ana@example.com"       # pairing gate applies
    assert seen["from_addr"] == "ana@example.com"    # back-compat kwarg kept
    assert seen["subject"] == "Friday plans"


def test_approved_reply_renders_real_mime_via_stubbed_smtp():
    ch = EmailChannel(smtp_config={"host": "smtp.local", "from": "jarvis@local"},
                      imap_config={"host": "imap.local"})
    sent = []
    ch._smtp_send = lambda msg, to_addr: sent.append((msg, to_addr))
    ok = asyncio.run(ch.send("calendar is clear",
                             to="ana@example.com", subject="Ping"))
    assert ok is True
    msg, to_addr = sent[0]
    assert to_addr == "ana@example.com"
    assert msg["To"] == "ana@example.com"
    assert msg["Subject"] == "Ping"
    assert "calendar is clear" in msg.get_payload()
