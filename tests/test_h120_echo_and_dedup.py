"""H120 — not answering itself: echo, duplicate and late-delivery guards (hermetic).

Owner side: a provider retry of one webhook is one turn, not two approval requests. A
person's ordinary message still gets through. Attacker/loop side: the bot's own message
read back on Signal, Matrix, WhatsApp, Teams or Google Chat is never a turn; WhatsApp
status/broadcast/channel posts are not conversations; a Telegram command delivered late
by a stuck queue is refused, not run.
"""

from __future__ import annotations

import asyncio

import pytest

from agents.core.channels import backfill
from agents.core.channels.gateway import DEDUP_MAX, DEDUP_WINDOW_S, Gateway
from tests.test_g15_channel_reliability import (  # noqa: F401 - fixture reused
    OWNER,
    STRANGER,
    FakeTelegram,
    _gated,
    _telegram,
    _until,
    quick_batches,
)


def _collector():
    seen = []

    async def handler(text, channel="web", **kwargs):
        seen.append((channel, text, kwargs))
        return "ok"

    return seen, handler


# ── the gateway's duplicate window ──────────────────────────────────────────

def test_a_provider_retry_is_one_turn():
    seen, handler = _collector()
    gw = Gateway(handler=handler)

    async def run():
        first = await gw.route("approve the invoice", channel="web", sender="a",
                               dedup_key="web:ev1")
        again = await gw.route("approve the invoice", channel="web", sender="a",
                               dedup_key="web:ev1")
        other = await gw.route("approve the invoice", channel="web", sender="a",
                               dedup_key="web:ev2")
        plain = await gw.route("approve the invoice", channel="web", sender="a")
        return first, again, other, plain

    first, again, other, plain = asyncio.run(run())
    assert (first, again, other, plain) == ("ok", None, "ok", "ok")
    assert len(seen) == 3
    assert all("dedup_key" not in kw for _c, _t, kw in seen)   # never reaches the handler
    assert gw.get_channel_info("web")["duplicates"] == 1


def test_the_window_is_per_channel_bounded_and_expires():
    gw = Gateway()
    assert gw.is_duplicate("telegram", "k", now=0.0) is False
    assert gw.is_duplicate("telegram", "k", now=1.0) is True
    assert gw.is_duplicate("web", "k", now=1.0) is False      # another channel
    assert gw.is_duplicate("telegram", "k", now=DEDUP_WINDOW_S + 2) is False   # expired
    for n in range(DEDUP_MAX + 10):
        gw.is_duplicate("x", f"id{n}", now=DEDUP_WINDOW_S + 3)
    assert len(gw._seen_ids) <= DEDUP_MAX
    for bad in (None, "", 5, "a" * 300, "a\nb"):
        assert gw.is_duplicate("x", bad) is False
        assert gw.is_duplicate("x", bad) is False


# ── Telegram late-delivery guard ─────────────────────────────────────────────

T = 1_750_000_000


def test_late_threshold():
    assert backfill.delivered_late(T, T + backfill.DEFAULT_LATE_S + 1, None) is True
    assert backfill.delivered_late(T, T + 10) is False
    assert backfill.delivered_late(None, T) is False
    assert backfill.delivered_late(True, T + 99_999) is False
    assert backfill.delivered_late(T, T + 99_999, 0) is False        # off
    # A broken or hostile date, or an unreadable clock, never makes a message "late".
    for date, now in ((-10**308, T), (10**400, T), (5, T), (T, float("inf")), (T, None)):
        assert backfill.delivered_late(date, now) is False


def test_late_threshold_env(monkeypatch):
    monkeypatch.setenv(backfill.LATE_ENV, "0")
    assert backfill.delivered_late(T, T + 99_999) is False
    monkeypatch.setenv(backfill.LATE_ENV, "60")
    assert backfill.delivered_late(T, T + 61) is True


@pytest.mark.asyncio
async def test_a_late_telegram_command_is_refused_and_a_late_message_is_kept(tmp_path, quick_batches):
    server = FakeTelegram()
    gateway, seen = _gated(tmp_path)
    channel = _telegram(server, gateway.route)
    channel.allowed_users = []
    channel._pairing = gateway.pairing
    await channel.start()
    try:
        await _until(lambda: len(server.offsets) >= 3)          # caught up: live now
        server.message("/resume", age=backfill.DEFAULT_LATE_S + 60)
        server.message("/start let-me-in", uid=STRANGER, age=backfill.DEFAULT_LATE_S + 60)
        server.message("the delayed words", age=backfill.DEFAULT_LATE_S + 60)
        server.message("/status", age=-1)
        await _until(lambda: len(seen) == 2)
    finally:
        await channel.stop()
    assert [t for t, *_ in seen] == ["the delayed words", "/status"]
    told = [m for m in server.sent if "late" in m["text"]]
    assert [m["chat_id"] for m in told] == [OWNER]               # the stranger hears nothing
    assert channel.late_deliveries == 3


# ── security review round 1 ──────────────────────────────────────────────────


def test_the_gateway_uses_the_provider_id_and_keeps_it_for_the_inbox():
    seen, handler = _collector()
    gw = Gateway(handler=handler)

    async def run():
        await gw.route("hi", channel="web", sender="1555", provider_id="SM1")
        await gw.route("hi", channel="web", sender="1555", provider_id="SM1")

    asyncio.run(run())
    assert len(seen) == 1 and seen[0][2]["provider_id"] == "SM1"


@pytest.mark.asyncio
async def test_a_late_plain_message_is_kept_even_with_backfill_off(tmp_path, quick_batches, monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_BACKFILL_WINDOW_S", "0")
    server = FakeTelegram()
    gateway, seen = _gated(tmp_path)
    channel = _telegram(server, gateway.route)
    await channel.start()
    try:
        await _until(lambda: len(server.offsets) >= 3)
        server.message("words that arrived late", age=backfill.DEFAULT_LATE_S + 60)
        await _until(lambda: len(seen) == 1)
    finally:
        await channel.stop()
    assert [t for t, *_ in seen] == ["words that arrived late"]


@pytest.mark.asyncio
async def test_with_pairing_off_an_unknown_sender_is_never_told(tmp_path, quick_batches, monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "0")
    server = FakeTelegram()
    gateway, seen = _gated(tmp_path)
    channel = _telegram(server, gateway.route)
    channel.allowed_users = []
    channel._pairing = gateway.pairing
    await channel.start()
    try:
        await _until(lambda: len(server.offsets) >= 3)
        server.message("/resume", uid=STRANGER, age=backfill.DEFAULT_LATE_S + 60)
        server.message("/status", uid=STRANGER, age=-1)
        await _until(lambda: len(seen) == 1)
    finally:
        await channel.stop()
    assert [m for m in server.sent if "late" in m["text"]] == []
    assert channel.late_deliveries == 1
