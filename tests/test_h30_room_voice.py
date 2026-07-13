"""H30.6 — authenticated room-aware Wyoming voice routing.

The tests keep actuation out of the voice layer: a verified satellite may earn a
server-resolved Media Director target, but only the H29 action rail may touch a
device driver.
"""

from __future__ import annotations

import asyncio

import pytest

from agents.core.media_director import DeviceRegistry, MediaDevice, MediaDirector
from agents.core.satellite_hub import SatelliteHub, SatellitePairing
from agents.core.voice.wyoming import (
    RoomVoiceContextResolver,
    WyomingEvent,
    WyomingProtocolError,
    WyomingServer,
    encode_event,
    read_event,
    room_aware_voice_enabled,
)

NOW = 1_000.0
PEER = "192.168.50.21"
TOKEN = "owner-paired-token"


def _reader(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


class _PeerWriter:
    def __init__(self, peer: str = PEER) -> None:
        self.buf = bytearray()
        self.peer = peer

    def write(self, data: bytes) -> None:
        self.buf.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    def get_extra_info(self, name: str, default=None):
        if name == "peername":
            return (self.peer, 10700)
        return default


def _pairing(**overrides) -> SatellitePairing:
    values = {
        "satellite_id": "sat-kitchen",
        "room_id": "kitchen",
        "token": TOKEN,
        "allowed_peer": PEER,
        "allowed_transport": "wyoming",
        "expires_at": NOW + 600,
    }
    values.update(overrides)
    return SatellitePairing.from_token(**values)


def _hub(*pairings: SatellitePairing) -> SatelliteHub:
    return SatelliteHub(pairings=pairings or (_pairing(),), clock=lambda: NOW)


def _registry(*devices: MediaDevice) -> DeviceRegistry:
    registry = DeviceRegistry()
    for device in devices or (
        MediaDevice(
            id="speaker-kitchen",
            name="Kitchen speaker",
            kind="speaker",
            room="kitchen",
            supports=("announce",),
            room_default=True,
        ),
    ):
        registry.register(device)
    return registry


def _auth_event(*, nonce: str = "nonce-00000001", **overrides) -> WyomingEvent:
    data = {
        "satellite_id": "sat-kitchen",
        "credential": TOKEN,
        "nonce": nonce,
        "timestamp": NOW,
        # A client-supplied room must never influence the trusted context.
        "room_id": "garage",
    }
    data.update(overrides)
    return WyomingEvent("satellite-auth", data)


def _stream(*events: WyomingEvent) -> bytes:
    return b"".join(encode_event(event) for event in events)


async def _responses(writer: _PeerWriter) -> list[WyomingEvent]:
    reader = _reader(bytes(writer.buf))
    result = []
    while True:
        event = await read_event(reader)
        if event is None:
            return result
        result.append(event)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wire",
    [
        b"[]\n",
        b'{"type":"transcript","data":[]}\n',
        b'{"type":"audio-chunk","payload_length":1000001}\n',
    ],
)
async def test_malformed_or_oversized_wyoming_frames_fail_closed(wire):
    with pytest.raises(WyomingProtocolError):
        await read_event(_reader(wire))


def test_room_aware_voice_is_default_off(monkeypatch):
    monkeypatch.delenv("JARVIS_ROOM_AWARE_VOICE", raising=False)
    assert room_aware_voice_enabled() is False
    with pytest.raises(ValueError, match="disabled"):
        WyomingServer.room_aware(
            satellite_hub=_hub(),
            context_resolver=RoomVoiceContextResolver(
                _registry(), privacy_provider=lambda room: "normal"
            ),
            handler=lambda text, context: None,
        )


@pytest.mark.asyncio
async def test_paired_satellite_identity_maps_to_server_room_and_default_media_target():
    contexts = []

    async def handler(text, context):
        contexts.append((text, context))
        return "ack"

    registry = _registry(
        MediaDevice(
            id="tv-kitchen",
            name="Kitchen TV",
            kind="tv",
            room="kitchen",
            supports=("show",),
        ),
        MediaDevice(
            id="speaker-kitchen",
            name="Kitchen speaker",
            kind="speaker",
            room="kitchen",
            supports=("announce",),
            room_default=True,
        ),
    )
    server = WyomingServer.room_aware(
        enabled=True,
        satellite_hub=_hub(),
        context_resolver=RoomVoiceContextResolver(
            registry,
            privacy_provider=lambda room: "normal",
        ),
        handler=handler,
    )
    writer = _PeerWriter()

    await server.handle_connection(
        _reader(_stream(_auth_event(), WyomingEvent("transcript", {"text": "announce dinner"}))),
        writer,
    )

    responses = await _responses(writer)
    assert [response.type for response in responses] == ["satellite-auth-ok", "synthesize"]
    assert contexts[0][0] == "announce dinner"
    context = contexts[0][1]
    assert context.principal.satellite_id == "sat-kitchen"
    assert context.principal.room_id == "kitchen"
    assert context.default_media_target == "speaker-kitchen"
    assert context.privacy_context == "normal"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("auth_overrides", "reason"),
    [
        ({"satellite_id": "unknown"}, "unknown_satellite"),
        ({"credential": "spoofed"}, "credential_refused"),
    ],
)
async def test_unknown_or_spoofed_satellite_never_reaches_handler(auth_overrides, reason):
    called = []

    async def handler(text, context):
        called.append((text, context))
        return "should not run"

    server = WyomingServer.room_aware(
        enabled=True,
        satellite_hub=_hub(),
        context_resolver=RoomVoiceContextResolver(_registry(), privacy_provider=lambda room: "normal"),
        handler=handler,
    )
    writer = _PeerWriter()
    await server.handle_connection(
        _reader(_stream(_auth_event(**auth_overrides), WyomingEvent("transcript", {"text": "x"}))),
        writer,
    )

    responses = await _responses(writer)
    assert responses[0].type == "satellite-auth-refused"
    assert responses[0].data == {"reason": reason}
    assert called == []


@pytest.mark.asyncio
async def test_replayed_auth_frame_is_refused_across_connections():
    async def handler(text, context):
        return "ack"

    hub = _hub()
    server = WyomingServer.room_aware(
        enabled=True,
        satellite_hub=hub,
        context_resolver=RoomVoiceContextResolver(_registry(), privacy_provider=lambda room: "normal"),
        handler=handler,
    )
    first = _PeerWriter()
    second = _PeerWriter()

    await server.handle_connection(_reader(_stream(_auth_event())), first)
    await server.handle_connection(_reader(_stream(_auth_event())), second)

    assert (await _responses(first))[0].type == "satellite-auth-ok"
    replay = (await _responses(second))[0]
    assert replay.type == "satellite-auth-refused"
    assert replay.data == {"reason": "replayed_nonce"}


@pytest.mark.parametrize(
    ("pairing", "claim", "peer", "transport", "reason"),
    [
        (_pairing(), {"timestamp": NOW - 31}, PEER, "wyoming", "stale_timestamp"),
        (
            _pairing(expires_at=NOW - 1),
            {"timestamp": NOW},
            PEER,
            "wyoming",
            "credential_expired",
        ),
        (_pairing(), {"timestamp": NOW}, "192.168.50.99", "wyoming", "peer_refused"),
        (_pairing(), {"timestamp": NOW}, PEER, "http", "transport_refused"),
    ],
)
def test_expired_stale_or_wrong_transport_claims_never_gain_a_room(
    pairing, claim, peer, transport, reason
):
    result = _hub(pairing).authenticate(
        satellite_id="sat-kitchen",
        credential=TOKEN,
        nonce="nonce-00000002",
        timestamp=claim["timestamp"],
        peer=peer,
        transport=transport,
    )

    assert result == {"ok": False, "reason": reason}
    assert "principal" not in result


def test_live_principal_is_revalidated_for_expiry_and_revocation():
    clock = [NOW]
    hub = SatelliteHub(pairings=(_pairing(),), clock=lambda: clock[0])
    authenticated = hub.authenticate(
        satellite_id="sat-kitchen",
        credential=TOKEN,
        nonce="nonce-00000003",
        timestamp=NOW,
        peer=PEER,
        transport="wyoming",
    )
    principal = authenticated["principal"]

    assert hub.validate_principal(principal) == {"ok": True}
    clock[0] = NOW + 601
    assert hub.validate_principal(principal) == {
        "ok": False,
        "reason": "credential_expired",
    }

    hub = _hub()
    authenticated = hub.authenticate(
        satellite_id="sat-kitchen",
        credential=TOKEN,
        nonce="nonce-00000004",
        timestamp=NOW,
        peer=PEER,
        transport="wyoming",
    )
    hub.unregister("sat-kitchen")
    assert hub.validate_principal(authenticated["principal"]) == {
        "ok": False,
        "reason": "pairing_revoked",
    }


def test_satellite_inventory_never_exposes_pairing_credentials():
    hub = _hub()
    hub.register(
        "legacy",
        {"room": "office", "token": "leak", "credential_digest": "also-leak"},
    )

    serialized = repr(hub.list())
    assert TOKEN not in serialized
    assert "leak" not in serialized
    assert "credential_digest" not in serialized


@pytest.mark.asyncio
async def test_ambiguous_room_refuses_before_the_voice_handler():
    called = []

    async def handler(text, context):
        called.append(context)
        return "no"

    registry = _registry(
        MediaDevice("speaker-a", "A", "speaker", "kitchen", ("announce",)),
        MediaDevice("speaker-b", "B", "speaker", "kitchen", ("announce",)),
    )
    server = WyomingServer.room_aware(
        enabled=True,
        satellite_hub=_hub(),
        context_resolver=RoomVoiceContextResolver(registry, privacy_provider=lambda room: "normal"),
        handler=handler,
    )
    writer = _PeerWriter()

    await server.handle_connection(
        _reader(_stream(_auth_event(), WyomingEvent("transcript", {"text": "music"}))),
        writer,
    )

    refusal = (await _responses(writer))[1]
    assert refusal.type == "voice-context-refused"
    assert refusal.data == {"reason": "ambiguous_room_media_target"}
    assert called == []


@pytest.mark.asyncio
@pytest.mark.parametrize("privacy", ["private", "do_not_interrupt", "unknown", ""])
async def test_private_or_untrusted_room_context_refuses_automatic_media_target(privacy):
    called = []

    async def handler(text, context):
        called.append(context)
        return "no"

    server = WyomingServer.room_aware(
        enabled=True,
        satellite_hub=_hub(),
        context_resolver=RoomVoiceContextResolver(
            _registry(),
            privacy_provider=lambda room: privacy,
        ),
        handler=handler,
    )
    writer = _PeerWriter()
    await server.handle_connection(
        _reader(_stream(_auth_event(), WyomingEvent("transcript", {"text": "announce"}))),
        writer,
    )

    refusal = (await _responses(writer))[1]
    assert refusal.type == "voice-context-refused"
    assert refusal.data == {"reason": "room_privacy_refused"}
    assert called == []


@pytest.mark.asyncio
async def test_voice_context_resolution_never_calls_a_media_driver_before_h29_action_rail():
    class DriverTripwire:
        supports_duration = False

        def __getattr__(self, name):
            raise AssertionError(f"voice layer attempted media driver operation: {name}")

    director = MediaDirector(
        registry=_registry(),
        drivers={"speaker": DriverTripwire()},
    )
    seen_targets = []

    async def handler(text, context):
        seen_targets.append(context.default_media_target)
        return "queued through action plane later"

    server = WyomingServer.room_aware(
        enabled=True,
        satellite_hub=_hub(),
        context_resolver=RoomVoiceContextResolver(
            director.registry,
            privacy_provider=lambda room: "normal",
        ),
        handler=handler,
    )
    writer = _PeerWriter()
    await server.handle_connection(
        _reader(_stream(_auth_event(), WyomingEvent("transcript", {"text": "play radio"}))),
        writer,
    )

    assert seen_targets == ["speaker-kitchen"]
    assert (await _responses(writer))[1].type == "synthesize"
