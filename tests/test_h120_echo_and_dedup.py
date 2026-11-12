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
from agents.core.channels.webhook_channels import (
    GoogleChatChannel,
    MatrixChannel,
    SignalChannel,
    TeamsChannel,
    WhatsAppChannel,
)
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
        first = await gw.route("approve the invoice", channel="matrix", sender="@a:hs",
                               dedup_key="matrix:$ev1")
        again = await gw.route("approve the invoice", channel="matrix", sender="@a:hs",
                               dedup_key="matrix:$ev1")
        other = await gw.route("approve the invoice", channel="matrix", sender="@a:hs",
                               dedup_key="matrix:$ev2")
        plain = await gw.route("approve the invoice", channel="matrix", sender="@a:hs")
        return first, again, other, plain

    first, again, other, plain = asyncio.run(run())
    assert (first, again, other, plain) == ("ok", None, "ok", "ok")
    assert len(seen) == 3
    assert all("dedup_key" not in kw for _c, _t, kw in seen)   # never reaches the handler
    assert gw.get_channel_info("matrix")["duplicates"] == 1


def test_the_window_is_per_channel_bounded_and_expires():
    gw = Gateway()
    assert gw.is_duplicate("signal", "k", now=0.0) is False
    assert gw.is_duplicate("signal", "k", now=1.0) is True
    assert gw.is_duplicate("matrix", "k", now=1.0) is False      # another channel
    assert gw.is_duplicate("signal", "k", now=DEDUP_WINDOW_S + 2) is False   # expired
    for n in range(DEDUP_MAX + 10):
        gw.is_duplicate("x", f"id{n}", now=DEDUP_WINDOW_S + 3)
    assert len(gw._seen_ids) <= DEDUP_MAX
    for bad in (None, "", 5, "a" * 300, "a\nb"):
        assert gw.is_duplicate("x", bad) is False
        assert gw.is_duplicate("x", bad) is False


# ── own-message (echo) guards on the webhook channels ───────────────────────

def _route(channel, payload):
    seen, handler = _collector()
    channel.handler = handler
    asyncio.run(channel.handle_inbound(payload))
    return seen


def _wa(msg, own="15550001"):
    return {"entry": [{"changes": [{"value": {
        "metadata": {"display_phone_number": own}, "messages": [msg]}}]}]}


def test_whatsapp_echo_status_broadcast_and_system_are_not_turns():
    ch = WhatsAppChannel()
    assert _route(ch, _wa({"from": "15550001", "id": "wamid.1", "text": {"body": "x"}})) == []
    assert _route(ch, _wa({"from": "status@broadcast", "text": {"body": "x"}})) == []
    assert _route(ch, _wa({"from": "123@newsletter", "text": {"body": "x"}})) == []
    assert _route(ch, _wa({"from": "15552222", "type": "system", "text": {"body": "x"}})) == []
    statuses = {"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.1"}]}}]}]}
    assert _route(ch, statuses) == []
    [(_c, text, kw)] = _route(ch, _wa({"from": "15552222", "id": "wamid.9",
                                       "text": {"body": "hello"}}))
    assert text == "hello" and kw["dedup_key"] == "whatsapp:wamid.9" and "_own" not in kw


def test_signal_own_number_and_sync_messages_are_not_turns():
    ch = SignalChannel(config={"number": "+15550001"})
    own = {"envelope": {"source": "+15550001", "timestamp": 1, "dataMessage": {"message": "x"}}}
    sync = {"envelope": {"source": "+15550001", "syncMessage": {"sentMessage": {"message": "x"}}}}
    assert _route(ch, own) == [] and _route(ch, sync) == []
    assert ch.echoes_dropped == 1
    [(_c, _t, kw)] = _route(ch, {"envelope": {"source": "+15552222", "timestamp": 7,
                                              "dataMessage": {"message": "hi", "timestamp": 7}}})
    assert kw["dedup_key"] == "signal:+15552222:7"


def test_matrix_own_user_is_not_a_turn():
    ch = MatrixChannel(config={"user_id": "@nerva:hs"})
    event = {"type": "m.room.message", "sender": "@nerva:hs", "room_id": "!r:hs",
             "event_id": "$e1", "content": {"body": "my own reply"}}
    assert _route(ch, event) == []
    ch2 = MatrixChannel()
    ch2._own_user_id = "@bot:hs"            # learned from /account/whoami
    assert _route(ch2, {**event, "sender": "@bot:hs"}) == []
    [(_c, _t, kw)] = _route(ch, {**event, "sender": "@ana:hs"})
    assert kw["dedup_key"] == "matrix:$e1"


def test_matrix_origin_mark_and_listed_bridge_users_are_not_turns():
    ch = MatrixChannel(config={"homeserver": "https://hs", "default_room": "!r:hs",
                               "ignore_users": ["@telegrambot:hs"]})
    sent = ch.build_send("reply", {})["json"]
    assert sent["io.nerva.origin"] is True
    echoed = {"type": "m.room.message", "sender": "@other-login:hs", "room_id": "!r:hs",
              "event_id": "$e3", "content": dict(sent)}
    assert _route(ch, echoed) == []                           # our message, carried back
    bridged = {"type": "m.room.message", "sender": "@telegrambot:hs", "room_id": "!r:hs",
               "event_id": "$e4", "content": {"body": "reply"}}
    assert _route(ch, bridged) == []
    assert ch.echoes_dropped == 2


def test_teams_own_activity_and_non_messages_are_not_turns():
    ch = TeamsChannel()
    base = {"type": "message", "id": "act1", "text": "hi", "from": {"id": "bot"},
            "recipient": {"id": "bot"}, "conversation": {"id": "c1"}}
    assert _route(ch, base) == []
    assert _route(ch, {**base, "type": "conversationUpdate", "from": {"id": "u1"}}) == []
    [(_c, _t, kw)] = _route(ch, {**base, "from": {"id": "u1"}})
    assert kw["dedup_key"] == "teams:act1"


def test_google_chat_bot_messages_are_not_turns():
    ch = GoogleChatChannel()
    bot = {"message": {"name": "spaces/s/messages/m1", "text": "hi",
                       "sender": {"name": "users/app", "type": "BOT"}}, "space": {"name": "spaces/s"}}
    assert _route(ch, bot) == []
    human = {"message": {"name": "spaces/s/messages/m2", "text": "hi",
                         "sender": {"name": "users/1", "type": "HUMAN"}}, "space": {"name": "spaces/s"}}
    [(_c, _t, kw)] = _route(ch, human)
    assert kw["dedup_key"] == "google_chat:spaces/s/messages/m2"


def test_end_to_end_a_retried_webhook_reaches_the_handler_once():
    seen, handler = _collector()
    gw = Gateway(handler=handler)
    ch = MatrixChannel(handler=gw.route)
    event = {"type": "m.room.message", "sender": "@ana:hs", "room_id": "!r:hs",
             "event_id": "$retry", "content": {"body": "pay the bill"}}

    async def run():
        await ch.handle_inbound(event)
        await ch.handle_inbound(event)       # the homeserver retried the push

    asyncio.run(run())
    assert [t for _c, t, _k in seen] == ["pay the bill"]


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

def test_a_redelivered_message_never_gets_a_second_reply_card(tmp_path):
    from agents.core.channel_inbox import ChannelInboxStore
    from agents.core.channel_reply import ChannelReplyBroker

    store = ChannelInboxStore(tmp_path / "inbox.json")
    queued = []

    def enqueue(agent, kind, title, **kwargs):
        queued.append(title)
        return 41 + len(queued)

    broker = ChannelReplyBroker(inbox=store, enqueue=enqueue)
    meta = {"sms_to": "+15551234567", "provider_id": "SM" + "a" * 32}
    first = store.record_inbound("sms", "lights off", sender="15551234567", metadata=meta, now=10.0)
    out = broker.request_for_message(first["id"], "Done?", channel="sms")
    assert out["queued"] is True and out["task_id"] == 42
    # The same stored turn again, and the provider's redelivery an hour later (past the
    # gateway's window, or after a restart): the existing card, never a second one.
    again = broker.request_for_message(first["id"], "Done?", channel="sms")
    later = store.record_inbound("sms", "lights off", sender="15551234567", metadata=meta,
                                 now=3_610.0)
    redelivered = broker.request_for_message(later["id"], "Done?", channel="sms")
    assert again == redelivered == {"ok": True, "queued": False, "duplicate": True,
                                    "task_id": 42, "kind": "channel.reply"}
    assert len(queued) == 1
    # A different message from the same number is a new turn and gets its own card.
    other = store.record_inbound("sms", "lights on", sender="15551234567",
                                 metadata={**meta, "provider_id": "SM" + "b" * 32}, now=3_700.0)
    assert broker.request_for_message(other["id"], "On?", channel="sms")["task_id"] == 43
    # The marker survives a restart (it is in the stored inbox).
    reloaded = ChannelReplyBroker(inbox=ChannelInboxStore(tmp_path / "inbox.json"), enqueue=enqueue)
    assert reloaded.request_for_message(later["id"], "Done?", channel="sms")["duplicate"] is True


def test_the_gateway_uses_the_provider_id_and_keeps_it_for_the_inbox():
    seen, handler = _collector()
    gw = Gateway(handler=handler)

    async def run():
        await gw.route("hi", channel="sms", sender="1555", provider_id="SM1")
        await gw.route("hi", channel="sms", sender="1555", provider_id="SM1")

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
