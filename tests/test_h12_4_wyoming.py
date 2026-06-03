"""Tests for H12.4 — Wyoming protocol.

Protocol framing + event router are tested fully offline (asyncio.StreamReader
fed in memory, an injected handler, a fake writer). Plus the status endpoint.
"""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.voice.wyoming import (
    WyomingEvent, WyomingServer, encode_event, read_event,
)


def _reader(data: bytes) -> asyncio.StreamReader:
    r = asyncio.StreamReader()
    r.feed_data(data)
    r.feed_eof()
    return r


class _FakeWriter:
    def __init__(self):
        self.buf = bytearray()
    def write(self, data):
        self.buf.extend(data)
    async def drain(self):
        pass
    def close(self):
        pass


# ── framing round-trips ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_encode_decode_no_payload():
    ev = WyomingEvent(type="transcript", data={"text": "hello"})
    got = await read_event(_reader(encode_event(ev)))
    assert got.type == "transcript"
    assert got.data["text"] == "hello"
    assert got.payload is None


@pytest.mark.asyncio
async def test_encode_decode_with_payload():
    ev = WyomingEvent(type="audio-chunk", data={"rate": 16000}, payload=b"\x00\x01\x02\x03")
    got = await read_event(_reader(encode_event(ev)))
    assert got.type == "audio-chunk"
    assert got.data["rate"] == 16000
    assert got.payload == b"\x00\x01\x02\x03"


@pytest.mark.asyncio
async def test_read_event_eof_returns_none():
    assert await read_event(_reader(b"")) is None


@pytest.mark.asyncio
async def test_two_events_in_stream():
    blob = encode_event(WyomingEvent("ping", {"a": 1})) + encode_event(WyomingEvent("describe"))
    r = _reader(blob)
    first = await read_event(r)
    second = await read_event(r)
    assert first.type == "ping"
    assert second.type == "describe"


# ── event router ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_describe_returns_info():
    srv = WyomingServer(handler=_noop)
    resp = await srv.dispatch(WyomingEvent("describe"))
    assert resp.type == "info"
    assert resp.data["handle"][0]["name"] == "jarvis-hub"


@pytest.mark.asyncio
async def test_transcript_bridges_to_handler():
    seen = []

    async def handler(text):
        seen.append(text)
        return f"you said {text}"

    srv = WyomingServer(handler=handler)
    resp = await srv.dispatch(WyomingEvent("transcript", {"text": "turn on lights"}))
    assert resp.type == "synthesize"
    assert resp.data["text"] == "you said turn on lights"
    assert seen == ["turn on lights"]


@pytest.mark.asyncio
async def test_empty_transcript_ignored():
    srv = WyomingServer(handler=_noop)
    assert await srv.dispatch(WyomingEvent("transcript", {"text": "  "})) is None


@pytest.mark.asyncio
async def test_handler_error_yields_empty_synthesize():
    async def boom(text):
        raise RuntimeError("nope")

    srv = WyomingServer(handler=boom)
    resp = await srv.dispatch(WyomingEvent("transcript", {"text": "hi"}))
    assert resp.type == "synthesize"
    assert resp.data["text"] == ""


@pytest.mark.asyncio
async def test_ping_pong():
    srv = WyomingServer(handler=_noop)
    resp = await srv.dispatch(WyomingEvent("ping", {"x": 1}))
    assert resp.type == "pong" and resp.data == {"x": 1}


@pytest.mark.asyncio
async def test_handle_connection_full_roundtrip():
    async def handler(text):
        return "ack"

    stream = encode_event(WyomingEvent("describe")) + \
        encode_event(WyomingEvent("transcript", {"text": "hello"}))
    writer = _FakeWriter()
    await WyomingServer(handler).handle_connection(_reader(stream), writer)

    # parse the two responses the server wrote back
    r = _reader(bytes(writer.buf))
    info = await read_event(r)
    synth = await read_event(r)
    assert info.type == "info"
    assert synth.type == "synthesize" and synth.data["text"] == "ack"


async def _noop(text):
    return ""


# ── status endpoint ─────────────────────────────────────────────────────────

def test_wyoming_status_endpoint():
    from agents import web
    with TestClient(web.app) as c:
        resp = c.get("/api/voice/wyoming")
        assert resp.status_code == 200
        body = resp.json()
        assert body["protocol"] == "wyoming"
        assert body["enabled"] is False      # disabled by default
        assert body["role"] == "handle"
