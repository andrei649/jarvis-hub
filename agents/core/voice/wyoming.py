"""Wyoming protocol core plus H30.6 authenticated room-aware voice context."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from agents.core.env_config import env_flag
from agents.core.media_director import MediaError
from agents.core.satellite_hub import SatelliteHub, SatellitePrincipal

logger = logging.getLogger("jarvis.voice.wyoming")

PROTOCOL_VERSION = "1.0.0"
ROOM_AWARE_VOICE_ENV = "JARVIS_ROOM_AWARE_VOICE"
_MAX_HEADER_BYTES = 16_384
_MAX_PAYLOAD_BYTES = 1_000_000
_MAX_EVENT_TYPE = 64

TextHandler = Callable[[str], Awaitable[str]]
RoomTextHandler = Callable[[str, "VoiceRequestContext"], Awaitable[str]]


def room_aware_voice_enabled() -> bool:
    return env_flag(ROOM_AWARE_VOICE_ENV, default=False)


@dataclass
class WyomingEvent:
    type: str
    data: dict = field(default_factory=dict)
    payload: Optional[bytes] = None


@dataclass(frozen=True)
class VoiceRequestContext:
    principal: SatellitePrincipal
    default_media_target: str
    privacy_context: str


class RoomContextError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = str(reason)[:128]
        super().__init__(self.reason)


class WyomingProtocolError(Exception):
    """Malformed or resource-unbounded Wyoming frame."""


class RoomVoiceContextResolver:
    """Pure room/privacy/target lookup; intentionally has no media driver."""

    def __init__(self, device_registry, *, privacy_provider) -> None:
        if not callable(privacy_provider):
            raise ValueError("privacy_provider must be callable")
        self._registry = device_registry
        self._privacy_provider = privacy_provider

    def resolve(self, principal: SatellitePrincipal) -> VoiceRequestContext:
        if not isinstance(principal, SatellitePrincipal):
            raise RoomContextError("satellite_identity_refused")
        try:
            privacy = self._privacy_provider(principal.room_id)
        except Exception as exc:
            raise RoomContextError("room_privacy_unavailable") from exc
        if not isinstance(privacy, str) or privacy.strip().lower() not in {"normal", "household"}:
            raise RoomContextError("room_privacy_refused")
        try:
            target = self._registry.resolve_room_default(principal.room_id, mode="announce")
        except MediaError as exc:
            raise RoomContextError(exc.reason) from exc
        return VoiceRequestContext(
            principal=principal,
            default_media_target=target.id,
            privacy_context=privacy.strip().lower(),
        )


def encode_event(event: WyomingEvent) -> bytes:
    """Serialize an event to the Wyoming wire format."""
    header: dict = {"type": event.type}
    if event.data:
        header["data"] = event.data
    if event.payload:
        header["payload_length"] = len(event.payload)
    output = (json.dumps(header, ensure_ascii=False) + "\n").encode("utf-8")
    if event.payload:
        output += event.payload
    return output


async def read_event(reader: asyncio.StreamReader) -> Optional[WyomingEvent]:
    """Read one event from a stream reader; None at EOF."""
    line = await reader.readline()
    if not line:
        return None
    if len(line) > _MAX_HEADER_BYTES:
        raise WyomingProtocolError("header_too_large")
    try:
        header = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WyomingProtocolError("invalid_header") from exc
    if not isinstance(header, dict):
        raise WyomingProtocolError("header_must_be_object")
    event_type = header.get("type", "")
    if not isinstance(event_type, str) or len(event_type) > _MAX_EVENT_TYPE:
        raise WyomingProtocolError("invalid_event_type")
    data = header.get("data")
    if data is None:
        data = {}
    elif not isinstance(data, dict):
        raise WyomingProtocolError("data_must_be_object")
    payload = None
    length = header.get("payload_length")
    if length is not None:
        if isinstance(length, bool) or not isinstance(length, int) or not 0 <= length <= _MAX_PAYLOAD_BYTES:
            raise WyomingProtocolError("invalid_payload_length")
        if length:
            payload = await reader.readexactly(length)
    return WyomingEvent(
        type=event_type,
        data=data,
        payload=payload,
    )


def _info_payload() -> dict:
    return {
        "asr": [],
        "tts": [],
        "handle": [
            {
                "name": "jarvis-hub",
                "description": "Jarvis Hub assistant — handles transcripts, returns speech.",
                "installed": True,
                "version": PROTOCOL_VERSION,
                "models": [],
            }
        ],
        "wake": [],
        "intent": [],
    }


def _peer_host(writer: asyncio.StreamWriter) -> str:
    try:
        peer = writer.get_extra_info("peername")
    except Exception:
        return ""
    if isinstance(peer, (tuple, list)) and peer:
        return str(peer[0])
    return str(peer or "")


class WyomingServer:
    """Routes legacy Wyoming events or a paired H30 room-aware voice session."""

    def __init__(
        self,
        handler: TextHandler | None,
        *,
        satellite_hub: SatelliteHub | None = None,
        context_resolver: RoomVoiceContextResolver | None = None,
        room_handler: RoomTextHandler | None = None,
        require_authenticated_satellite: bool = False,
    ) -> None:
        self.handler = handler
        self._satellite_hub = satellite_hub
        self._context_resolver = context_resolver
        self._room_handler = room_handler
        self._require_auth = bool(require_authenticated_satellite)
        if self._require_auth and not all((satellite_hub, context_resolver, room_handler)):
            raise ValueError("room-aware Wyoming requires hub, context resolver and handler")

    @classmethod
    def room_aware(
        cls,
        *,
        satellite_hub: SatelliteHub,
        context_resolver: RoomVoiceContextResolver,
        handler: RoomTextHandler,
        enabled: bool | None = None,
    ) -> WyomingServer:
        """Build the paired rail only after owner opt-in or explicit test enablement."""
        active = room_aware_voice_enabled() if enabled is None else enabled
        if active is not True:
            raise ValueError(f"room-aware voice disabled; set {ROOM_AWARE_VOICE_ENV}=1")
        return cls(
            None,
            satellite_hub=satellite_hub,
            context_resolver=context_resolver,
            room_handler=handler,
            require_authenticated_satellite=True,
        )

    async def dispatch(
        self,
        event: WyomingEvent,
        *,
        context: VoiceRequestContext | None = None,
    ) -> Optional[WyomingEvent]:
        if event.type == "describe":
            return WyomingEvent(type="info", data=_info_payload())
        if event.type == "transcript":
            text = (event.data or {}).get("text", "")
            if not isinstance(text, str) or not text.strip():
                return None
            if self._require_auth and context is None:
                return WyomingEvent("voice-context-refused", {"reason": "authentication_required"})
            try:
                if context is not None and self._room_handler is not None:
                    reply = await self._room_handler(text, context)
                elif self.handler is not None:
                    reply = await self.handler(text)
                else:
                    reply = ""
            except Exception as exc:
                logger.warning("wyoming handler error: %s", exc)
                reply = ""
            return WyomingEvent(type="synthesize", data={"text": str(reply)})
        if event.type == "ping":
            return WyomingEvent(type="pong", data=(event.data or {}))
        return None

    def _authenticate(self, event: WyomingEvent, writer) -> dict:
        data = event.data if isinstance(event.data, dict) else {}
        return self._satellite_hub.authenticate(
            satellite_id=data.get("satellite_id"),
            credential=data.get("credential"),
            nonce=data.get("nonce"),
            timestamp=data.get("timestamp"),
            peer=_peer_host(writer),
            transport="wyoming",
        )

    @staticmethod
    async def _write(writer, event: WyomingEvent) -> None:
        writer.write(encode_event(event))
        await writer.drain()

    async def handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        principal: SatellitePrincipal | None = None
        try:
            while True:
                event = await read_event(reader)
                if event is None:
                    break
                if self._require_auth and event.type == "satellite-auth":
                    if principal is not None:
                        result = {"ok": False, "reason": "already_authenticated"}
                    else:
                        result = self._authenticate(event, writer)
                    if not result.get("ok"):
                        await self._write(
                            writer,
                            WyomingEvent(
                                "satellite-auth-refused",
                                {"reason": result.get("reason", "authentication_refused")},
                            ),
                        )
                        continue
                    principal = result["principal"]
                    await self._write(
                        writer,
                        WyomingEvent("satellite-auth-ok", {"satellite_id": principal.satellite_id}),
                    )
                    continue

                context = None
                if self._require_auth and event.type == "transcript":
                    if principal is None:
                        await self._write(
                            writer,
                            WyomingEvent(
                                "voice-context-refused",
                                {"reason": "authentication_required"},
                            ),
                        )
                        continue
                    validity = self._satellite_hub.validate_principal(principal)
                    if not validity.get("ok"):
                        await self._write(
                            writer,
                            WyomingEvent(
                                "voice-context-refused",
                                {"reason": validity.get("reason", "satellite_identity_refused")},
                            ),
                        )
                        continue
                    try:
                        context = self._context_resolver.resolve(principal)
                    except RoomContextError as exc:
                        await self._write(
                            writer,
                            WyomingEvent("voice-context-refused", {"reason": exc.reason}),
                        )
                        continue

                response = await self.dispatch(event, context=context)
                if response is not None:
                    await self._write(writer, response)
        except (asyncio.IncompleteReadError, ConnectionError, WyomingProtocolError):
            pass
        finally:
            with suppress(Exception):
                writer.close()

    async def serve(
        self,
        host: str = "127.0.0.1",
        port: int = 10700,
    ) -> asyncio.AbstractServer:
        server = await asyncio.start_server(self.handle_connection, host, port)
        logger.info("Wyoming server listening on %s:%d", host, port)
        return server
