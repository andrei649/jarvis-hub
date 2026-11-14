"""Caller-local card outcomes prevent a second prompt after uncertain delivery."""

import asyncio

import pytest

from agents.core.channels import delivery_ledger
from agents.core.channels.manager import CardAttempt, ChannelManager


class Cards:
    def __init__(self):
        self.calls = []
        self.reply = None
        self.note = None

    async def send_pending_card(self, text, *, reply_markup, **kwargs):
        self.calls.append((text, reply_markup, kwargs))
        if self.note:
            self.note()
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


def rig(monkeypatch):
    manager, adapter = ChannelManager(), Cards()
    manager.channels["telegram"] = adapter
    monkeypatch.setattr(manager, "_contract_denial", lambda *_args: None)
    return manager, adapter


@pytest.fixture
def store(tmp_path, monkeypatch):
    ledger = delivery_ledger.ReliabilityStore(tmp_path / "card.sqlite")
    monkeypatch.setattr(delivery_ledger, "store", lambda: ledger)
    yield ledger
    ledger.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reply,note,expected", [
    (19, None, "sent"),
    (None, None, "unknown"),
    (True, None, "unknown"),
    (None, delivery_ledger.note_partial, "partial"),
    (None, lambda: delivery_ledger.note_send_failure(status=403), "failed"),
])
async def test_attempt_reports_transport_truth_without_changing_native_return(store, monkeypatch, reply, note, expected):
    manager, adapter = rig(monkeypatch)
    adapter.reply, adapter.note = reply, note
    contract_keys = []

    def contract(_channel, _response, kwargs):
        contract_keys.append(set(kwargs))
        return None

    monkeypatch.setattr(manager, "_contract_denial", contract)
    attempt = CardAttempt()
    receipt = await manager.send_pending_card("telegram", "private prompt", {"inline_keyboard": []},
                                              chat_id=42, attempt=attempt)
    assert receipt == (19 if reply == 19 and type(reply) is int else None)
    assert attempt.disposition == expected
    assert contract_keys == [{"chat_id", "reply_markup"}]
    assert adapter.calls == [("private prompt", {"inline_keyboard": []}, {"chat_id": 42})]
    assert store.recent(1)[0]["state"] == expected


@pytest.mark.asyncio
async def test_attempt_survives_ledger_outage_and_preserves_outer_outcome(monkeypatch):
    manager, adapter = rig(monkeypatch)
    adapter.reply = None
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    outer, token = delivery_ledger.begin_outcome()
    try:
        attempt = CardAttempt()
        assert await manager.send_pending_card("telegram", "prompt", {}, chat_id=42, attempt=attempt) is None
        assert attempt.disposition == "unknown"
        assert outer == delivery_ledger.SendOutcome()
    finally:
        delivery_ledger.end_outcome(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("raised", [RuntimeError("lost ack"), asyncio.CancelledError()])
async def test_raised_transport_marks_local_unknown_and_propagates(store, monkeypatch, raised):
    manager, adapter = rig(monkeypatch)
    adapter.reply = raised
    attempt = CardAttempt()
    with pytest.raises(type(raised)):
        await manager.send_pending_card("telegram", "prompt", {}, chat_id=42, attempt=attempt)
    assert attempt.disposition == "unknown"
    assert store.recent(1)[0]["state"] == "unknown"
    fresh, token = delivery_ledger.begin_outcome()
    try:
        assert fresh == delivery_ledger.SendOutcome()
    finally:
        delivery_ledger.end_outcome(token)


@pytest.mark.asyncio
async def test_denied_and_dead_target_are_not_attempted_or_skipped(store, monkeypatch):
    manager, adapter = rig(monkeypatch)
    denied = CardAttempt()
    monkeypatch.setattr(manager, "_contract_denial", lambda *_args: "no")
    assert await manager.send_pending_card("telegram", "prompt", {}, chat_id=42, attempt=denied) is None
    assert denied.disposition == "not_attempted" and adapter.calls == []
    monkeypatch.setattr(manager, "_contract_denial", lambda *_args: None)
    store.mark_dead("telegram", "42", "forbidden")
    skipped = CardAttempt()
    assert await manager.send_pending_card("telegram", "prompt", {}, chat_id=42, attempt=skipped) is None
    assert skipped.disposition == "skipped" and adapter.calls == []


@pytest.mark.asyncio
async def test_concurrent_attempts_keep_independent_outcomes(monkeypatch):
    manager, adapter = rig(monkeypatch)
    monkeypatch.setattr(delivery_ledger, "store", lambda: None)
    ready = asyncio.Event()

    async def send(_text, *, reply_markup, chat_id):
        if chat_id == 1:
            ready.set()
            await asyncio.sleep(0)
            delivery_ledger.note_unconfirmed_ack()
            return None
        await ready.wait()
        return 72

    adapter.send_pending_card = send
    first, second = CardAttempt(), CardAttempt()
    got = await asyncio.gather(
        manager.send_pending_card("telegram", "a", {}, chat_id=1, attempt=first),
        manager.send_pending_card("telegram", "b", {}, chat_id=2, attempt=second),
    )
    assert got == [None, 72]
    assert (first.disposition, second.disposition) == ("unknown", "sent")


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt", [None, "701", 701])
async def test_uninstrumented_manager_cannot_trigger_plain_fallback(tmp_path, monkeypatch, receipt):
    from tests.test_pending_input_native_transport import finish, native_host
    from tests.test_pending_input_runtime import incoming

    orch, _cap, gateway, _server, _ready, _pairing, answers, channel, _requests = await native_host(tmp_path)
    runtime = orch._pending_input_service()
    if receipt == 701:
        monkeypatch.setattr(runtime.cards, "bind", lambda *_args, **_kwargs: False)
    calls = []

    class AlternateManager:
        channels = {"telegram": channel}

        async def send_pending_card(self, _channel, _text, _markup, **kwargs):
            calls.append(("card", kwargs))
            return receipt

        async def send(self, _channel, text, **kwargs):
            if "Choose a route" in str(text):
                calls.append(("fallback", kwargs))
            return False

    orch.channel_manager = AlternateManager()
    turn = asyncio.create_task(incoming(gateway, message_thread_id=8))
    try:
        await asyncio.wait_for(turn, 1)
        assert [kind for kind, _ in calls] == ["card"]
        assert "attempt" in calls[0][1]
        assert answers[0][0]["result"]["reason"] == "prompt_delivery_failed"
        assert not runtime._card_tokens
    finally:
        await finish(orch, channel, turn)
