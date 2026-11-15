"""A keyed outbound send needs its durable claim before transport starts."""

from __future__ import annotations

import asyncio

import pytest

from agents.core.channels import delivery_ledger
from agents.core.channels.manager import ChannelManager


class _Adapter:
    def __init__(self):
        self.sent: list[tuple[object, dict]] = []
        self.success = True

    async def send(self, response, **kwargs):
        self.sent.append((response, kwargs))
        return self.success


def _manager() -> tuple[ChannelManager, _Adapter]:
    manager = ChannelManager()
    adapter = _Adapter()
    manager.channels["telegram"] = adapter
    return manager, adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [False, True])
async def test_keyed_send_withholds_when_ledger_is_unavailable(monkeypatch, reply):
    manager, adapter = _manager()
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    send = manager.send_channel_reply if reply else manager.send

    assert await send("telegram", "notice", chat_id=7, delivery_key="restart:123:notice") is False
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_unkeyed_send_remains_best_effort_without_ledger(monkeypatch):
    manager, adapter = _manager()
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)

    assert await manager.send("telegram", "notice", chat_id=7) is True
    assert adapter.sent == [("notice", {"chat_id": 7})]


class _BrokenOpen:
    def open_delivery(self, *_args, **_kwargs):
        raise OSError("ledger write unavailable")


@pytest.mark.asyncio
async def test_keyed_open_failure_withholds_but_unkeyed_send_survives(monkeypatch):
    manager, adapter = _manager()
    monkeypatch.setattr(delivery_ledger, "store", lambda: _BrokenOpen())

    assert await manager.send("telegram", "one", chat_id=7, delivery_key="notice:1") is False
    assert adapter.sent == []
    assert await manager.send("telegram", "two", chat_id=7) is True
    assert adapter.sent == [("two", {"chat_id": 7})]


class _Claim:
    send = True
    already_sent = False

    def __init__(self, *, checked: bool = False, error: BaseException | None = None):
        self.checked = checked
        self.error = error
        self.attempts = 0

    def attempting(self):
        self.attempts += 1

    def attempting_checked(self):
        self.attempts += 1
        if self.error is not None:
            raise self.error
        return self.checked


class _ClaimStore:
    def __init__(self, claim):
        self.claim = claim

    def open_delivery(self, *_args, **_kwargs):
        return self.claim


@pytest.mark.asyncio
async def test_keyed_failed_attempt_transition_withholds_before_transport(monkeypatch):
    manager, adapter = _manager()
    claim = _Claim(checked=False)
    monkeypatch.setattr(delivery_ledger, "store", lambda: _ClaimStore(claim))

    assert await manager.send("telegram", "notice", chat_id=7, delivery_key="notice:1") is False
    assert claim.attempts == 1
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_keyed_attempt_cancellation_propagates_without_transport(monkeypatch):
    manager, adapter = _manager()
    claim = _Claim(error=asyncio.CancelledError())
    monkeypatch.setattr(delivery_ledger, "store", lambda: _ClaimStore(claim))

    with pytest.raises(asyncio.CancelledError):
        await manager.send("telegram", "notice", chat_id=7, delivery_key="notice:1")
    assert adapter.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_key", ["", 123, False, "bad\nkey", "bad\tkey", "é", "x" * 201])
async def test_supplied_invalid_key_never_becomes_an_unkeyed_send(monkeypatch, bad_key):
    manager, adapter = _manager()
    opened = []
    monkeypatch.setattr(delivery_ledger, "store", lambda: opened.append(True))

    assert await manager.send("telegram", "notice", chat_id=7, delivery_key=bad_key) is False
    assert opened == []
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_silent_send_does_not_accept_invalid_supplied_key(monkeypatch):
    manager, adapter = _manager()
    opened = []
    monkeypatch.setattr(delivery_ledger, "store", lambda: opened.append(True))

    assert await manager.send("telegram", "SILENT", chat_id=7, delivery_key="bad\nkey") is False
    assert opened == []
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_keyed_duplicate_already_sent_is_truthful_without_transport(monkeypatch):
    manager, adapter = _manager()
    claim = _Claim()
    claim.send = False
    claim.already_sent = True
    monkeypatch.setattr(delivery_ledger, "store", lambda: _ClaimStore(claim))

    assert await manager.send("telegram", "notice", chat_id=7, delivery_key="notice:1") is True
    assert claim.attempts == 0
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_keyed_missing_claim_withholds(monkeypatch):
    manager, adapter = _manager()
    monkeypatch.setattr(delivery_ledger, "store", lambda: _ClaimStore(None))

    assert await manager.send("telegram", "notice", chat_id=7, delivery_key="notice:1") is False
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_real_keyed_failed_retry_then_duplicate_sent(tmp_path, monkeypatch):
    manager, adapter = _manager()
    store = delivery_ledger.ReliabilityStore(tmp_path / "delivery.db")
    monkeypatch.setattr(delivery_ledger, "store", lambda: store)
    try:
        adapter.success = False
        assert await manager.send("telegram", "notice", chat_id=7, delivery_key="notice:1") is False
        adapter.success = True
        assert await manager.send("telegram", "notice", chat_id=7, delivery_key="notice:1") is True
        assert await manager.send("telegram", "notice", chat_id=7, delivery_key="notice:1") is True
        assert len(adapter.sent) == 2
        counts = store.stats()["by_state"]
        assert (counts["failed"], counts["sent"], counts["skipped"]) == (1, 1, 1)
    finally:
        store.close()
