"""Prompt transports keep native receipts while recording metadata-only outcomes."""

import asyncio

import pytest

from agents.core.channels import delivery_ledger
from agents.core.channels.manager import ChannelManager

MARKUP = {"inline_keyboard": [[{"text": "Private choice", "callback_data": "h067:" + "A" * 16 + ":1:a"}]]}
SLACK_RECEIPT = {"channel": "slack", "target": "C123", "message_id": "123.456",
                 "thread_id": None, "team_id": "T123"}


class Adapter:
    def __init__(self, value, note=None):
        self.value = value
        self.note = note
        self.calls = []
        self.publish_topic = "topic"

    async def send_pending_card(self, response, *, reply_markup, **kwargs):
        self.calls.append((response, reply_markup, kwargs))
        if self.note:
            self.note()
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value

    async def send_reply(self, response, **kwargs):
        self.calls.append((response, kwargs))
        if self.note:
            self.note()
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    store = delivery_ledger.ReliabilityStore(tmp_path / "receipts.sqlite")
    monkeypatch.setattr(delivery_ledger, "store", lambda: store)
    yield store
    store.close()


def rig(channel, value, monkeypatch, note=None):
    manager = ChannelManager()
    adapter = Adapter(value, note)
    manager.channels[channel] = adapter
    monkeypatch.setattr(manager, "_contract_denial", lambda *_args: None)
    monkeypatch.setattr(manager, "_reply_contract_denial", lambda *_args: None)
    return manager, adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("channel,value,expected", [
    ("telegram", 19, 19),
    ("slack", SLACK_RECEIPT, SLACK_RECEIPT),
])
async def test_card_ack_records_sent_without_payload(ledger, monkeypatch, channel, value, expected):
    manager, adapter = rig(channel, value, monkeypatch)
    if channel == "telegram":
        result = await manager.send_pending_card(channel, "Private prompt", MARKUP, chat_id=42)
        target = "42"
    else:
        result = await manager.send_channel_prompt(channel, "Private prompt", MARKUP, slack_channel="C123")
        target = "C123"
    assert result == expected and len(adapter.calls) == 1
    row = ledger.recent(1)[0]
    assert (row["channel"], row["target"], row["state"], row["keyed"]) == (channel, target, "sent", False)
    assert "Private prompt" not in str(row) and "Private choice" not in str(row)
    assert "message_id" not in row and "reply_markup" not in row


@pytest.mark.asyncio
@pytest.mark.parametrize("channel,value", [
    ("telegram", True), ("telegram", 0), ("telegram", None),
    ("slack", {**SLACK_RECEIPT, "message_id": "bad"}), ("slack", None),
])
async def test_missing_or_malformed_card_ack_is_unknown(ledger, monkeypatch, channel, value):
    manager, _adapter = rig(channel, value, monkeypatch)
    result = (await manager.send_pending_card(channel, "prompt", MARKUP, chat_id=42)
              if channel == "telegram" else
              await manager.send_channel_prompt(channel, "prompt", MARKUP, slack_channel="C123"))
    assert result is None
    row = ledger.recent(1)[0]
    assert (row["state"], row["error"]) == ("unknown", "missing_ack")


@pytest.mark.asyncio
async def test_adapter_failure_and_partial_notes_win_over_missing_ack(ledger, monkeypatch):
    manager, _adapter = rig("telegram", None, monkeypatch,
                           lambda: delivery_ledger.note_send_failure(status=403))
    assert await manager.send_pending_card("telegram", "prompt", MARKUP, chat_id=42) is None
    assert ledger.recent(1)[0]["state"] == "failed"
    assert ledger.is_dead("telegram", "42")
    second, _adapter = rig("slack", None, monkeypatch, delivery_ledger.note_partial)
    assert await second.send_channel_prompt("slack", "prompt", MARKUP, slack_channel="C123") is None
    assert ledger.recent(1)[0]["state"] == "partial"


@pytest.mark.asyncio
async def test_text_prompt_keeps_current_guard_and_records_ack(ledger, monkeypatch):
    manager, adapter = rig("ntfy", True, monkeypatch)
    checks = []

    async def guarded_send(response, **kwargs):
        adapter.calls.append((response, kwargs))
        checks.append(kwargs["current"]())
        return checks[-1]

    adapter.send_reply = guarded_send
    def current():
        return True
    assert await manager.send_channel_text_prompt("ntfy", "Private prompt", current=current,
                                                  ntfy_topic="topic", ntfy_context="ctx") is True
    assert adapter.calls[0][1]["current"] is current
    assert adapter.calls[0][1]["plain"] is True
    assert ledger.recent(1)[0]["state"] == "sent"
    assert await manager.send_channel_text_prompt("ntfy", "Private prompt", current=lambda: False,
                                                  ntfy_topic="topic", ntfy_context="ctx") is False
    assert ledger.recent(1)[0]["state"] == "failed"
    assert checks == [True, False]


@pytest.mark.asyncio
async def test_governed_prompt_denials_do_not_claim_or_send(ledger, monkeypatch):
    slack, slack_adapter = rig("slack", SLACK_RECEIPT, monkeypatch)
    ntfy, ntfy_adapter = rig("ntfy", True, monkeypatch)
    monkeypatch.setattr(slack, "_reply_contract_denial", lambda *_args: "denied")
    monkeypatch.setattr(ntfy, "_reply_contract_denial", lambda *_args: "denied")
    assert await slack.send_channel_prompt("slack", "prompt", MARKUP, slack_channel="C123") is None
    assert await ntfy.send_channel_text_prompt("ntfy", "prompt", current=lambda: True,
                                               ntfy_topic="topic", ntfy_context="ctx") is False
    assert slack_adapter.calls == ntfy_adapter.calls == []
    assert ledger.recent(5) == []


@pytest.mark.asyncio
async def test_outage_unkeyed_best_effort_and_explicit_keys_refused(ledger, monkeypatch):
    manager, adapter = rig("telegram", 19, monkeypatch)
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    assert await manager.send_pending_card("telegram", "prompt", MARKUP, chat_id=42) == 19
    assert len(adapter.calls) == 1
    assert await manager.send_pending_card("telegram", "prompt", MARKUP, chat_id=42,
                                           delivery_key="card:1") is None
    assert len(adapter.calls) == 1
    slack, slack_adapter = rig("slack", SLACK_RECEIPT, monkeypatch)
    assert await slack.send_channel_prompt("slack", "prompt", MARKUP, slack_channel="C123",
                                           delivery_key="prompt:1") is None
    assert slack_adapter.calls == []
    ntfy, ntfy_adapter = rig("ntfy", True, monkeypatch)
    assert await ntfy.send_channel_text_prompt("ntfy", "prompt", current=lambda: True,
                                               ntfy_topic="topic", ntfy_context="ctx",
                                               delivery_key=None) is False
    assert ntfy_adapter.calls == []


@pytest.mark.asyncio
async def test_denial_dead_target_and_cancellation_preserve_authority(ledger, monkeypatch):
    manager, adapter = rig("telegram", 19, monkeypatch)
    monkeypatch.setattr(manager, "_contract_denial", lambda *_args: "denied")
    assert await manager.send_pending_card("telegram", "prompt", MARKUP, chat_id=42) is None
    assert adapter.calls == [] and ledger.recent(5) == []
    monkeypatch.setattr(manager, "_contract_denial", lambda *_args: None)
    ledger.mark_dead("telegram", "42", "forbidden")
    assert await manager.send_pending_card("telegram", "prompt", MARKUP, chat_id=42) is None
    assert adapter.calls == [] and ledger.recent(1)[0]["state"] == "skipped"
    ledger.clear_dead("telegram", "42")
    adapter.value = asyncio.CancelledError()
    outer, token = delivery_ledger.begin_outcome()
    try:
        with pytest.raises(asyncio.CancelledError):
            await manager.send_pending_card("telegram", "prompt", MARKUP, chat_id=42)
        assert outer == delivery_ledger.SendOutcome()
    finally:
        delivery_ledger.end_outcome(token)
    assert ledger.recent(1)[0]["state"] == "unknown"
