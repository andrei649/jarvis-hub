"""
wyoming.py — H12.4 Wyoming protocol support.

Speaks the Wyoming protocol so Jarvis interoperates with the local-voice
ecosystem (Home Assistant Voice satellites, Rhasspy, Wyoming satellites). Wyoming
decouples wake / STT / TTS from the assistant: a satellite streams audio, an ASR
service emits a ``transcript``, the assistant handles it and replies with a
``synthesize`` event for a TTS service to speak.

Wire format (matches the reference ``wyoming`` library): each event is a single
JSON header line — ``{"type", "data"?, "payload_length"?}\\n`` — optionally
followed by ``payload_length`` raw bytes. ``data`` is inline JSON; only the
binary ``payload`` is length-prefixed.

This module is the protocol core + an event router that bridges ``transcript`` →
orchestrator → ``synthesize``. The handler is injected, so it's offline-testable
with no sockets and no orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("jarvis.voice.wyoming")

PROTOCOL_VERSION = "1.0.0"

# handler: ``async (text) -> str`` — recognized speech in, reply text out.
TextHandler = Callable[[str], Awaitable[str]]


@dataclass
class WyomingEvent:
    type: str
    data: dict = field(default_factory=dict)
    payload: Optional[bytes] = None


def encode_event(event: WyomingEvent) -> bytes:
    """Serialize an event to the Wyoming wire format."""
    header: dict = {"type": event.type}
    if event.data:
        header["data"] = event.data
    if event.payload:
        header["payload_length"] = len(event.payload)
    out = (json.dumps(header, ensure_ascii=False) + "\n").encode("utf-8")
    if event.payload:
        out += event.payload
    return out


async def read_event(reader: asyncio.StreamReader) -> Optional[WyomingEvent]:
    """Read one event from a stream reader; None at EOF."""
    line = await reader.readline()
    if not line:
        return None
    header = json.loads(line.decode("utf-8"))
    payload = None
    n = header.get("payload_length")
    if n:
        payload = await reader.readexactly(int(n))
    return WyomingEvent(
        type=header.get("type", ""),
        data=header.get("data") or {},
        payload=payload,
    )


# ── server / event router ────────────────────────────────────────────────────

# Capabilities advertised in response to a `describe` request. Jarvis is the
# *intent/handle* stage: it consumes transcripts and produces speech to synth.
def _info_payload() -> dict:
    return {
        "asr": [],
        "tts": [],
        "handle": [{
            "name": "jarvis-hub",
            "description": "Jarvis Hub assistant — handles transcripts, returns a reply to speak.",
            "installed": True,
            "version": PROTOCOL_VERSION,
            "models": [],
        }],
        "wake": [],
        "intent": [],
    }


class WyomingServer:
    """Routes Wyoming events; bridges transcript → handler → synthesize."""

    def __init__(self, handler: TextHandler) -> None:
        self.handler = handler

    async def dispatch(self, event: WyomingEvent) -> Optional[WyomingEvent]:
        """Return the response event for *event*, or None if nothing to send."""
        if event.type == "describe":
            return WyomingEvent(type="info", data=_info_payload())
        if event.type == "transcript":
            text = (event.data or {}).get("text", "")
            if not text.strip():
                return None
            try:
                reply = await self.handler(text)
            except Exception as exc:
                logger.warning("wyoming handler error: %s", exc)
                reply = ""
            return WyomingEvent(type="synthesize", data={"text": str(reply)})
        if event.type == "ping":
            return WyomingEvent(type="pong", data=(event.data or {}))
        return None

    async def handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Serve one Wyoming client connection until EOF."""
        try:
            while True:
                event = await read_event(reader)
                if event is None:
                    break
                response = await self.dispatch(event)
                if response is not None:
                    writer.write(encode_event(response))
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            # Client disconnected mid-stream — a normal end to a connection.
            pass
        finally:
            try:
                writer.close()
            except Exception:
                # Best-effort close; the connection is already going away.
                pass

    async def serve(self, host: str = "0.0.0.0", port: int = 10700) -> asyncio.AbstractServer:
        """Start a Wyoming TCP server (default port 10700)."""
        server = await asyncio.start_server(self.handle_connection, host, port)
        logger.info("Wyoming server listening on %s:%d", host, port)
        return server
