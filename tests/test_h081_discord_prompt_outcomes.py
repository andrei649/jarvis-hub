"""Offline Discord SDK fakes through the governed manager prompt transport."""

import asyncio

import pytest

from agents.core.channels import delivery_ledger
from agents.core.channels.manager import ChannelManager
from tests.test_pending_input_discord_transport import Sent, View, channel, markup  # noqa: F401


@pytest.fixture
def store(tmp_path, monkeypatch):
    ledger = delivery_ledger.ReliabilityStore(tmp_path / "discord-receipts.sqlite")
    monkeypatch.setattr(delivery_ledger, "store", lambda: ledger)
    try:
        yield ledger
    finally:
        ledger.close()


def manager_for(ch):
    manager = ChannelManager()
    manager.register(ch)
    return manager


async def send(manager, text="Private prompt", **kwargs):
    return await manager.send_channel_prompt("discord", text, markup("c0"), channel_id=123, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["not_running", "bad_channel", "bad_view", "capacity"])
async def test_preflight_refusal_is_failed_without_post_or_view_eviction(channel, store, monkeypatch, reason):
    ch, sink = channel
    manager = manager_for(ch)
    existing = {}
    if reason == "not_running":
        ch._running = False
    if reason == "capacity":
        for index in range(128):
            key = (str(index + 1), str(index + 1000))
            existing[key] = View()
            ch._pending_views[key] = existing[key]
    if reason == "bad_channel":
        sink.id = 456
    if reason == "bad_view":
        monkeypatch.setattr(ch, "_pending_view", lambda *_args: None)
    result = await send(manager)
    assert result is None and sink.calls == []
    assert store.recent(1)[0]["state"] == "failed"
    assert ch._pending_sending == 0
    assert ch._pending_views == existing
    assert all(not view.stopped for view in existing.values())


@pytest.mark.asyncio
async def test_verified_ack_is_sent_and_preserves_native_receipt(channel, store):
    ch, sink = channel
    receipt = await send(manager_for(ch))
    assert receipt == {"channel": "discord", "target": "123", "message_id": "701",
                       "thread_id": None, "team_id": None}
    row = store.recent(1)[0]
    assert (row["state"], row["target"], row["keyed"]) == ("sent", "123", False)
    assert "Private prompt" not in str(row) and "h067:" not in str(row)
    assert sink.calls and ch._pending_sending == 0 and len(ch._pending_views) == 1
    ch.discard_pending_card(receipt)
    assert not ch._pending_views and sink.calls[-1][1]["view"].stopped


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["missing", "wrong_author", "boolean_author", "boolean_channel", "sdk_exception"])
async def test_uncertain_first_post_is_unknown_and_stops_view(channel, store, kind):
    ch, sink = channel
    if kind == "boolean_channel":
        sink.id = 1
    if kind == "missing":
        sink.message_id = True
    elif kind in {"wrong_author", "boolean_author", "boolean_channel"}:
        async def wrong(content, **kwargs):
            sink.calls.append((content, kwargs))
            sent = Sent(author_id=901 if kind == "wrong_author" else 900)
            if kind == "boolean_author":
                ch._client.user.id = 1
                sent.author.id = True
            if kind == "boolean_channel":
                sent.channel.id = True
            return sent
        sink.send = wrong
    else:
        async def fail(content, **kwargs):
            sink.calls.append((content, kwargs))
            raise RuntimeError("provider detail must not leak")
        sink.send = fail
    manager = manager_for(ch)
    assert (await manager.send_channel_prompt("discord", "Private prompt", markup("c0"),
                                              channel_id=1 if kind == "boolean_channel" else 123)) is None
    row = store.recent(1)[0]
    assert (row["state"], row["error"]) == ("unknown", "missing_ack")
    assert "provider detail" not in str(row)
    assert sink.calls[-1][1]["view"].stopped
    assert not ch._pending_views and ch._pending_sending == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("second", ["missing", "sdk_exception", "stale_before_post", "stale_after_post"])
async def test_verified_prefix_then_failure_is_partial(channel, store, second):
    ch, sink = channel

    async def post(content, **kwargs):
        sink.calls.append((content, kwargs))
        if len(sink.calls) == 1:
            if second == "stale_before_post":
                # First ACK is valid but callbacks become stale before the next POST.
                ch._pending_callback_generation = object()
            return Sent()
        if second == "sdk_exception":
            raise RuntimeError("provider detail must not leak")
        if second == "stale_after_post":
            ch._pending_callback_generation = object()
        return Sent(message_id=True if second == "missing" else 701)

    sink.send = post
    assert await send(manager_for(ch), "A" * 2100) is None
    row = store.recent(1)[0]
    assert row["state"] == "partial"
    assert "provider detail" not in str(row)
    assert len(sink.calls) == (1 if second == "stale_before_post" else 2)
    assert not ch._pending_views and ch._pending_sending == 0
    # The final-view reservation is retired on every unsuccessful path.
    if len(sink.calls) == 2:
        assert sink.calls[-1][1]["view"].stopped


@pytest.mark.asyncio
async def test_cancellation_still_propagates_and_releases_reservation(channel, store):
    ch, sink = channel

    async def cancel(content, **kwargs):
        sink.calls.append((content, kwargs))
        raise asyncio.CancelledError()

    sink.send = cancel
    with pytest.raises(asyncio.CancelledError):
        await send(manager_for(ch))
    assert ch._pending_sending == 0 and not ch._pending_views
    assert sink.calls[-1][1]["view"].stopped
    assert store.recent(1)[0]["state"] == "unknown"
