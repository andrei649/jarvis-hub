"""An unconfirmed 2xx send cannot become a retryable delivery failure."""

from __future__ import annotations

import os

import httpx
import pytest

from agents.core.channels import delivery_ledger
from agents.core.channels.manager import ChannelManager


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    previous_umask = os.umask(0o077)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    store = delivery_ledger.ReliabilityStore(private / "delivery.sqlite")
    monkeypatch.setattr(delivery_ledger, "store", lambda: store)
    try:
        yield store
    finally:
        store.close()
        os.umask(previous_umask)


def test_unconfirmed_ack_noops_without_context_and_marks_only_current_context():
    delivery_ledger.note_unconfirmed_ack()
    outcome, token = delivery_ledger.begin_outcome()
    try:
        assert outcome == delivery_ledger.SendOutcome()
        delivery_ledger.note_unconfirmed_ack()
        assert outcome.kind == "missing_ack"
        assert outcome.ambiguous is True
        assert outcome.partial is False and outcome.dead is False and outcome.fatal is None
    finally:
        delivery_ledger.end_outcome(token)
    fresh, token = delivery_ledger.begin_outcome()
    try:
        assert fresh == delivery_ledger.SendOutcome()
    finally:
        delivery_ledger.end_outcome(token)


@pytest.mark.parametrize("status,dead,fatal", [
    (403, True, None), (401, False, "unauthorized"),
])
def test_unconfirmed_ack_preserves_prior_partial_dead_and_fatal(status, dead, fatal):
    outcome, token = delivery_ledger.begin_outcome()
    try:
        delivery_ledger.note_send_failure(status=status)
        delivery_ledger.note_partial()
        delivery_ledger.note_unconfirmed_ack()
        assert (outcome.kind, outcome.ambiguous) == ("missing_ack", True)
        assert (outcome.partial, outcome.dead, outcome.fatal) == (True, dead, fatal)
        assert delivery_ledger.Delivery(None, None, send=True).finished(False, outcome) == "partial"
    finally:
        delivery_ledger.end_outcome(token)


def test_unconfirmed_ack_alone_finishes_unknown():
    outcome, token = delivery_ledger.begin_outcome()
    try:
        delivery_ledger.note_unconfirmed_ack()
        assert delivery_ledger.Delivery(None, None, send=True).finished(False, outcome) == "unknown"
    finally:
        delivery_ledger.end_outcome(token)


@pytest.mark.parametrize("error_type,ambiguous,kind", [
    (httpx.DecodingError, True, "no_answer"),
    (httpx.TooManyRedirects, True, "no_answer"),
    (httpx.ConnectError, False, "not_connected"),
    (httpx.ConnectTimeout, False, "not_connected"),
    (httpx.PoolTimeout, False, "not_connected"),
])
def test_request_errors_preserve_preconnect_distinction(error_type, ambiguous, kind):
    outcome = delivery_ledger.classify_send_failure(exc=error_type("transport failed"))
    assert (outcome.kind, outcome.ambiguous) == (kind, ambiguous)
    expected = "unknown" if ambiguous else "failed"
    assert delivery_ledger.Delivery(None, None, send=True).finished(False, outcome) == expected


class _UnconfirmedAdapter:
    def __init__(self, *, partial=False):
        self.calls = 0
        self.partial = partial

    async def send(self, _response, **_kwargs):
        self.calls += 1
        if self.partial:
            delivery_ledger.note_partial()
        delivery_ledger.note_unconfirmed_ack()
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("partial,expected", [
    (False, "unknown"), (True, "partial"),
])
async def test_real_manager_keyed_unconfirmed_ack_blocks_replay(ledger, partial, expected):
    manager = ChannelManager()
    adapter = _UnconfirmedAdapter(partial=partial)
    manager.channels["telegram"] = adapter
    key = "ack:1"

    assert await manager.send("telegram", "notice", chat_id=7, delivery_key=key) is False
    first = ledger.recent(1)[0]
    assert (first["state"], first["error"], first["keyed"]) == (
        expected, "missing_ack", True)
    assert await manager.send("telegram", "notice", chat_id=7, delivery_key=key) is False
    assert adapter.calls == 1
    assert ledger.stats()["by_state"][expected] == 1
    assert ledger.stats()["by_state"]["skipped"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.DecodingError, httpx.TooManyRedirects])
async def test_request_errors_are_durable_unknown_keyed_tombstones(ledger, error_type):
    class Adapter:
        calls = 0

        async def send(self, _response, **_kwargs):
            self.calls += 1
            delivery_ledger.note_send_failure(exc=error_type("response unavailable"))
            return False

    manager = ChannelManager()
    adapter = Adapter()
    manager.channels["telegram"] = adapter
    assert await manager.send("telegram", "notice", chat_id=7, delivery_key="response:1") is False
    assert ledger.recent(1)[0]["state"] == "unknown"
    assert await manager.send("telegram", "notice", chat_id=7, delivery_key="response:1") is False
    assert adapter.calls == 1
