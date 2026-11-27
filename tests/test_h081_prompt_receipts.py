"""Prompt transports keep native receipts while recording metadata-only outcomes."""

import asyncio

import pytest

from agents.core.channels import delivery_ledger
from agents.core.channels.manager import ChannelManager

MARKUP = {"inline_keyboard": [[{"text": "Private choice", "callback_data": "h067:" + "A" * 16 + ":1:a"}]]}


class Adapter:
    def __init__(self, value, note=None):
        self.value = value
        self.note = note
        self.calls = []

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
async def test_card_ack_records_sent_without_payload(ledger, monkeypatch):
    manager, adapter = rig("telegram", 19, monkeypatch)
    result = await manager.send_pending_card("telegram", "Private prompt", MARKUP, chat_id=42)
    assert result == 19 and len(adapter.calls) == 1
    row = ledger.recent(1)[0]
    assert (row["channel"], row["target"], row["state"], row["keyed"]) == ("telegram", "42", "sent", False)
    assert "Private prompt" not in str(row) and "Private choice" not in str(row)
    assert "message_id" not in row and "reply_markup" not in row


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, 0, None])
async def test_missing_or_malformed_card_ack_is_unknown(ledger, monkeypatch, value):
    manager, _adapter = rig("telegram", value, monkeypatch)
    result = await manager.send_pending_card("telegram", "prompt", MARKUP, chat_id=42)
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
    ledger.clear_dead("telegram", "42")
    second, _adapter = rig("telegram", None, monkeypatch, delivery_ledger.note_partial)
    assert await second.send_pending_card("telegram", "prompt", MARKUP, chat_id=42) is None
    assert ledger.recent(1)[0]["state"] == "partial"


@pytest.mark.asyncio
async def test_outage_unkeyed_best_effort_and_explicit_keys_refused(ledger, monkeypatch):
    manager, adapter = rig("telegram", 19, monkeypatch)
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    assert await manager.send_pending_card("telegram", "prompt", MARKUP, chat_id=42) == 19
    assert len(adapter.calls) == 1
    assert await manager.send_pending_card("telegram", "prompt", MARKUP, chat_id=42,
                                           delivery_key="card:1") is None
    assert len(adapter.calls) == 1


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
