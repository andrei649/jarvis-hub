"""STAB-4 residual (#933): governed email replies.

Two gaps that #869 left open, closed in ChannelReplyBroker.execute —
the last step before SMTP, not at queue time:

1. No sender check: the reply recipient must be exactly the inbound
   sender who opened the thread, and, when an explicit allowlist is
   configured, must also be in it. A task that redirects the reply to
   any other address is blocked and never reaches the transport.
2. No rate limit: email replies are capped per recipient per hour
   (default 10, JARVIS_EMAIL_REPLY_MAX_PER_HOUR / constructor override),
   and only successful sends consume quota.

Existing behaviour is preserved: a governed reply to the actual inbound
sender, within the cap, still sends and is recorded outbound.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.channel_inbox import ChannelInboxStore  # noqa: E402
from agents.core.channel_reply import (  # noqa: E402
    ChannelReplyBroker,
    EmailReplyRateLimiter,
)


def _inbound(store, sender="ana@example.com"):
    return store.record_inbound(
        "email", "ping", sender=sender,
        metadata={"from_addr": sender, "subject": "Ping"}, now=10.0,
    )


def _payload(rec, to=None):
    reply = dict(rec["reply"])
    if to is not None:
        reply["to"] = to
    return {
        "channel": "email",
        "text": "pong",
        "reply": reply,
        "thread_id": rec["thread_id"],
        "message_id": rec["id"],
    }


class _FakeTask:
    def __init__(self, payload):
        self.payload = payload


class _FakeManager:
    def __init__(self):
        self.sends = []

    async def send_channel_reply(self, channel, text, **kwargs):
        self.sends.append((channel, text, kwargs))
        return True


def _execute(store, manager, payload, **broker_kwargs):
    broker = ChannelReplyBroker(
        inbox=store, channel_manager=manager, **broker_kwargs)
    return asyncio.run(broker.execute(_FakeTask(payload)))


def test_email_reply_to_inbound_sender_still_sends(tmp_path):
    store = ChannelInboxStore(tmp_path / "inbox.json")
    rec = _inbound(store)
    manager = _FakeManager()
    result = _execute(store, manager, _payload(rec))
    assert result["status"] == "ok"
    assert manager.sends == [("email", "pong", {"to": "ana@example.com", "subject": "Ping"})]


def test_email_reply_redirected_to_another_address_is_blocked(tmp_path):
    store = ChannelInboxStore(tmp_path / "inbox.json")
    rec = _inbound(store)
    manager = _FakeManager()
    result = _execute(store, manager, _payload(rec, to="attacker@example.com"))
    assert result["status"] == "blocked"
    assert result["reason"] == "reply_recipient_mismatch"
    assert manager.sends == []


def test_email_reply_without_inbound_binding_is_blocked(tmp_path):
    store = ChannelInboxStore(tmp_path / "inbox.json")
    rec = _inbound(store)
    manager = _FakeManager()
    payload = _payload(rec)
    payload["message_id"] = "no-such-message"
    result = _execute(store, manager, payload)
    assert result["status"] == "blocked"
    assert result["reason"] == "inbound_binding_changed"
    assert manager.sends == []


def test_email_reply_allowlist_blocks_non_allowlisted_sender(tmp_path):
    store = ChannelInboxStore(tmp_path / "inbox.json")
    rec = _inbound(store, sender="other@example.com")
    manager = _FakeManager()
    result = _execute(
        store, manager, _payload(rec),
        email_allowlist=["ana@example.com"])
    assert result["status"] == "blocked"
    assert result["reason"] == "sender_not_allowlisted"
    assert manager.sends == []


def test_email_reply_allowlist_allows_listed_sender(tmp_path):
    store = ChannelInboxStore(tmp_path / "inbox.json")
    rec = _inbound(store)
    manager = _FakeManager()
    result = _execute(
        store, manager, _payload(rec),
        email_allowlist=["ANA@example.com"])  # case-insensitive
    assert result["status"] == "ok"
    assert len(manager.sends) == 1


def test_email_reply_rate_limit_blocks_after_cap_and_only_counts_success(tmp_path):
    store = ChannelInboxStore(tmp_path / "inbox.json")
    rec = _inbound(store)
    manager = _FakeManager()
    broker = ChannelReplyBroker(
        inbox=store, channel_manager=manager, email_reply_max_per_hour=2)
    for _ in range(2):
        assert asyncio.run(broker.execute(_FakeTask(_payload(rec))))["status"] == "ok"
    third = asyncio.run(broker.execute(_FakeTask(_payload(rec))))
    assert third["status"] == "blocked"
    assert third["reason"] == "email_reply_rate_limited"
    assert len(manager.sends) == 2


def test_email_reply_rate_limiter_window_and_failed_sends(tmp_path):
    limiter = EmailReplyRateLimiter(max_per_hour=1, now_fn=lambda: 1000.0)
    assert limiter.blocked("ana@example.com") is False
    limiter.record("ana@example.com", now=1000.0)
    assert limiter.blocked("ana@example.com", now=1001.0) is True
    # A different recipient has its own budget.
    assert limiter.blocked("bob@example.com", now=1001.0) is False
    # After the window passes, the budget is free again.
    assert limiter.blocked("ana@example.com", now=1000.0 + 3600.0) is False


def test_email_reply_to_another_recipient_has_its_own_budget(tmp_path):
    store = ChannelInboxStore(tmp_path / "inbox.json")
    ana = _inbound(store, sender="ana@example.com")
    bob = _inbound(store, sender="bob@example.com")
    manager = _FakeManager()
    broker = ChannelReplyBroker(
        inbox=store, channel_manager=manager, email_reply_max_per_hour=1)
    assert asyncio.run(broker.execute(_FakeTask(_payload(ana))))["status"] == "ok"
    assert asyncio.run(broker.execute(_FakeTask(_payload(ana))))["reason"] == "email_reply_rate_limited"
    assert asyncio.run(broker.execute(_FakeTask(_payload(bob))))["status"] == "ok"
    assert len(manager.sends) == 2
