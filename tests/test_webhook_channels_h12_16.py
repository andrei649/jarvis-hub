"""H12.16 — Broaden governed channels (WhatsApp/Signal/Matrix/Teams/Google Chat).

All offline: per-provider request building + inbound parsing are pure; outbound
send uses an injected transport; inbound routing is verified to pass through the
governed gateway (H12.19 pairing holds unknown senders).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.channels.webhook_channels import (
    WebhookChannel, WhatsAppChannel, SignalChannel, MatrixChannel, TeamsChannel,
    GoogleChatChannel, build_channel, channels_from_config, SUPPORTED_CHANNELS,
)
from agents.core.channels.gateway import Gateway
from agents.core.channels.pairing import SenderPairing


class _Resp:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        pass


class _Transport:
    def __init__(self):
        self.calls = []

    async def request(self, method, url, headers=None, json=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return _Resp()


# ── factory ───────────────────────────────────────────────────────────────────

def test_supported_channels():
    assert set(SUPPORTED_CHANNELS) == {"whatsapp", "signal", "matrix", "teams", "google_chat"}


def test_build_channel_and_imessage_excluded():
    assert isinstance(build_channel("whatsapp"), WhatsAppChannel)
    assert isinstance(build_channel("Matrix"), MatrixChannel)  # case-insensitive
    assert build_channel("imessage") is None    # host-bound, intentionally excluded
    assert build_channel("nonsense") is None


def test_channels_from_config():
    chans = channels_from_config(
        {"whatsapp": {"phone_id": "1", "token": "t"}, "bogus": {}}, handler=None)
    assert [c.channel_id for c in chans] == ["whatsapp"]  # bogus dropped


# ── build_send (pure outbound mapping) ────────────────────────────────────────

def test_whatsapp_build_send():
    ch = WhatsAppChannel(config={"phone_id": "PH", "token": "tok"})
    spec = ch.build_send("hi", {"to": "15551234"})
    assert spec["url"] == "https://graph.facebook.com/v20.0/PH/messages"
    assert spec["headers"]["Authorization"] == "Bearer tok"
    assert spec["json"]["text"]["body"] == "hi" and spec["json"]["to"] == "15551234"


def test_whatsapp_build_send_incomplete_returns_none():
    assert WhatsAppChannel(config={"phone_id": "PH"}).build_send("hi", {}) is None  # no recipient


def test_signal_build_send():
    ch = SignalChannel(config={"base_url": "http://localhost:8080/", "number": "+1"})
    spec = ch.build_send("yo", {"to": "+2"})
    assert spec["url"] == "http://localhost:8080/v2/send"
    assert spec["json"] == {"message": "yo", "number": "+1", "recipients": ["+2"]}


def test_matrix_build_send():
    ch = MatrixChannel(config={"homeserver": "https://hs/", "token": "T", "default_room": "!r:hs"})
    spec = ch.build_send("hi", {})
    assert spec["url"] == "https://hs/_matrix/client/v3/rooms/!r:hs/send/m.room.message"
    assert spec["json"] == {"msgtype": "m.text", "body": "hi"}


def test_teams_and_google_chat_build_send():
    t = TeamsChannel(config={"webhook": "https://teams/hook"}).build_send("x", {})
    assert t["url"] == "https://teams/hook" and t["json"] == {"text": "x"}
    g = GoogleChatChannel(config={"webhook": "https://chat/hook"}).build_send("y", {})
    assert g["url"] == "https://chat/hook" and g["json"] == {"text": "y"}


# ── parse_inbound (pure inbound mapping) ──────────────────────────────────────

def test_whatsapp_parse_inbound():
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "15551234", "text": {"body": "hello"}}]}}]}]}
    out = WhatsAppChannel().parse_inbound(payload)
    assert out == {"text": "hello", "sender": "15551234", "to": "15551234"}


def test_whatsapp_parse_inbound_malformed_returns_none():
    assert WhatsAppChannel().parse_inbound({"entry": []}) is None
    assert WhatsAppChannel().parse_inbound({}) is None


def test_signal_parse_inbound():
    payload = {"envelope": {"source": "+15550000", "dataMessage": {"message": "ping"}}}
    assert SignalChannel().parse_inbound(payload) == {
        "text": "ping", "sender": "+15550000", "to": "+15550000"}


def test_matrix_parse_inbound():
    payload = {"type": "m.room.message", "sender": "@a:hs", "room_id": "!r:hs",
               "content": {"body": "hey"}}
    assert MatrixChannel().parse_inbound(payload) == {
        "text": "hey", "sender": "@a:hs", "room_id": "!r:hs"}


def test_teams_parse_inbound():
    payload = {"text": "hi", "from": {"id": "u1"}, "conversation": {"id": "c1"}}
    assert TeamsChannel().parse_inbound(payload) == {
        "text": "hi", "sender": "u1", "conversation": "c1"}


def test_google_chat_parse_inbound():
    payload = {"message": {"text": "hi", "sender": {"name": "users/1"}},
               "space": {"name": "spaces/9"}}
    assert GoogleChatChannel().parse_inbound(payload) == {
        "text": "hi", "sender": "users/1", "space": "spaces/9"}


# ── outbound send via injected transport ──────────────────────────────────────

@pytest.mark.asyncio
async def test_send_uses_transport():
    tr = _Transport()
    ch = WhatsAppChannel(config={"phone_id": "PH", "token": "tok"}, transport=tr)
    ok = await ch.send("hi", to="15551234")
    assert ok is True
    assert tr.calls[0]["url"].endswith("/PH/messages")
    assert tr.calls[0]["json"]["text"]["body"] == "hi"


@pytest.mark.asyncio
async def test_send_incomplete_does_not_touch_network():
    tr = _Transport()
    ch = WhatsAppChannel(config={"phone_id": "PH"}, transport=tr)
    ok = await ch.send("hi")  # no recipient → build_send None
    assert ok is False and tr.calls == []


# ── inbound is governed ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_inbound_threads_sender():
    seen = []

    async def handler(text, channel="web", **kw):
        seen.append({"text": text, "channel": channel, "sender": kw.get("sender")})
        return "ok"

    ch = WhatsAppChannel(handler=handler)
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "15551234", "text": {"body": "hello"}}]}}]}]}
    out = await ch.handle_inbound(payload)
    assert out == "ok"
    assert seen[0] == {"text": "hello", "channel": "whatsapp", "sender": "15551234"}


@pytest.mark.asyncio
async def test_inbound_is_governed_by_pairing(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "1")
    pairing = SenderPairing(path=str(tmp_path / "p.json"))
    routed = []

    async def inner(text, channel="web", **kw):
        routed.append((text, kw.get("sender")))
        return "routed"

    gw = Gateway(handler=inner, pairing=pairing)
    gw.register_channel("matrix")
    ch = MatrixChannel(handler=gw.route, config={"default_room": "!r:hs"})
    payload = {"type": "m.room.message", "sender": "@mallory:hs", "room_id": "!r:hs",
               "content": {"body": "hi"}}

    # Unknown sender → held at the gateway; the inner handler is never reached.
    await ch.handle_inbound(payload)
    assert routed == []

    # Owner approves → now it routes through.
    pairing.approve("matrix", "@mallory:hs")
    out = await ch.handle_inbound(payload)
    assert out == "routed" and routed == [("hi", "@mallory:hs")]
