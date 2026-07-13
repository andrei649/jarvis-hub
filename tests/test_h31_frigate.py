"""H31.2 — the Frigate seam is local, read-only, bounded, and privacy-gated."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from PIL import Image

from agents.core.cameras.frigate import (
    FrigateConfig,
    FrigateEventSource,
    _FrigateSnapshotSource,
)
from agents.core.cameras.models import (
    CameraConfig,
    HouseholdConsent,
    PrivacyMask,
    PrivacyPollingGrant,
)
from agents.core.cameras.privacy import CameraPrivacyPolicy
from agents.core.cameras.source import CameraSourceError
from agents.core.plugin_gate import BUILTIN_PLUGINS, DataScope, NetworkAccess
from agents.core.security.secret_broker import SecretBroker


class _KillSwitch:
    def __init__(self) -> None:
        self.halted: set[str] = set()

    def is_halted(self, scope: str = "global") -> bool:
        return "global" in self.halted or scope in self.halted


class _Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], *, error: Exception | None = None) -> None:
        self.chunks = chunks
        self.error = error
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk
        if self.error is not None:
            raise self.error

    async def aclose(self) -> None:
        self.closed = True


def _config(**overrides) -> FrigateConfig:
    values = {
        "origin": "http://frigate.local:5000",
        "credential_ref": "{{secret:frigate.token}}",
        "enabled": True,
    }
    values.update(overrides)
    return FrigateConfig(**values)


def _event(
    event_id: str,
    *,
    occurred_at: float,
    camera: str = "front-door",
    label: str = "person",
) -> dict:
    return {
        "id": event_id,
        "camera": camera,
        "label": label,
        "start_time": occurred_at,
        "has_snapshot": True,
        "thumbnail": "/media/frigate/event.jpg",
        "data": {
            "top_score": 0.91,
            "zones": ["porch"],
            "sub_label": "Alice",
            "license_plate": "B-00-BAD",
            "face": [0.1, 0.2],
        },
    }


def _broker() -> SecretBroker:
    broker = SecretBroker()
    broker.put("frigate.token", "top-secret-token")
    return broker


def _resolver(*_args) -> tuple[str, ...]:
    return ("192.168.1.40",)


def _poll_grant() -> PrivacyPollingGrant:
    return PrivacyPollingGrant(
        camera_ids=("front-door",),
        consent_version=2,
        generation=1,
    )


def _source(
    handler,
    *,
    config: FrigateConfig | None = None,
    poll_gate=_poll_grant,
    kill_switch=None,
    resolver=_resolver,
    sleep=None,
    max_event_bytes: int = 1024 * 1024,
    max_attempts: int = 2,
) -> FrigateEventSource:
    return FrigateEventSource(
        config=config or _config(),
        secret_broker=_broker(),
        poll_gate=poll_gate,
        kill_switch=kill_switch or _KillSwitch(),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        sleep=sleep,
        max_event_bytes=max_event_bytes,
        max_attempts=max_attempts,
    )


def _privacy_policy(*, kill_switch=None) -> CameraPrivacyPolicy:
    mask = PrivacyMask(points=((0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)))
    return CameraPrivacyPolicy(
        configs=(
            CameraConfig(
                camera_id="front-door",
                name="Front door",
                enabled=True,
                required_consent_version=2,
                masks=(mask,),
            ),
        ),
        consent=HouseholdConsent(
            version=2,
            generation=4,
            granted=True,
            camera_ids=("front-door",),
            accepted_at=1.0,
        ),
        kill_switch=kill_switch or _KillSwitch(),
    )


def _jpeg() -> bytes:
    image = Image.new("RGB", (8, 8), (20, 160, 90))
    output = io.BytesIO()
    image.save(output, format="JPEG", exif=b"Exif\x00\x00private")
    image.close()
    return output.getvalue()


def test_frigate_manifest_is_lan_only_and_local_data_only():
    manifest = BUILTIN_PLUGINS["camera-frigate"]
    assert manifest.network_access is NetworkAccess.LAN
    assert manifest.data_scope is DataScope.LOCAL_ONLY
    assert manifest.agents_served == ["jarvis"]


@pytest.mark.asyncio
async def test_default_off_missing_gate_and_kill_refuse_before_transport():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[])

    with pytest.raises(CameraSourceError, match="source_disabled"):
        await _source(handler, config=_config(enabled=False)).list_events(None, 10)
    with pytest.raises(CameraSourceError, match="poll_gate_required"):
        await _source(handler, poll_gate=None).list_events(None, 10)
    with pytest.raises(CameraSourceError, match="consent_required"):
        await _source(handler, poll_gate=lambda: ()).list_events(None, 10)

    kill = _KillSwitch()
    kill.halted.add("camera-source")
    with pytest.raises(CameraSourceError, match="source_halted"):
        await _source(handler, kill_switch=kill).list_events(None, 10)
    assert calls == []


@pytest.mark.asyncio
async def test_origin_is_exact_lan_only_and_connection_is_pinned_even_when_strict_egress_is_off(
    monkeypatch,
):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")
    page = await _source(handler).list_events(None, 10)
    assert page.events == ()
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert seen[0].url.host == "192.168.1.40"
    assert seen[0].headers["host"] == "frigate.local:5000"
    assert seen[0].headers["authorization"] == "Bearer top-secret-token"
    assert "front-door" in seen[0].url.params["cameras"]

    for origin in (
        "ftp://192.168.1.40",
        "http://user:pass@192.168.1.40",
        "http://192.168.1.40/base",
        "http://192.168.1.40?token=bad",
        "http://bad host:5000",
    ):
        with pytest.raises(ValueError, match="Frigate origin"):
            _config(origin=origin)

    def mixed_resolver(*_args):
        return ("192.168.1.40", "8.8.8.8")

    with pytest.raises(CameraSourceError, match="lan_origin_required"):
        await _source(handler, resolver=mixed_resolver).list_events(None, 10)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_list_events_is_metadata_only_normalized_bounded_and_never_fetches_snapshots():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[
                _event("event-1", occurred_at=100.0),
                _event("event-2", occurred_at=101.0, camera="garage"),
                _event("event-3", occurred_at=102.0, label="face"),
            ],
        )

    page = await _source(handler).list_events(None, 2)
    assert len(page.events) == 1
    public = page.events[0].to_public()
    assert public == {
        "event_id": "event-1",
        "camera_id": "front-door",
        "label": "person",
        "occurred_at": 100.0,
        "confidence": 0.91,
        "anonymous": True,
        "zone": "porch",
    }
    assert not any(
        key in str(public).lower()
        for key in ("alice", "plate", "face", "thumbnail", "snapshot", "sub_label")
    )
    assert all("snapshot" not in request.url.path for request in requests)
    assert not hasattr(_source(handler), "fetch_snapshot")

    with pytest.raises(ValueError, match="limit"):
        await _source(handler).list_events(None, 101)
    with pytest.raises(CameraSourceError, match="cursor_invalid"):
        await _source(handler).list_events("not-a-cursor", 10)


@pytest.mark.asyncio
async def test_cursor_is_stable_and_duplicate_events_are_idempotently_filtered():
    call = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call
        call += 1
        events = [
            _event("event-a", occurred_at=10.0),
            _event("event-b", occurred_at=10.0),
        ]
        if call > 1:
            assert request.url.params["after"] == "10.0"
            events.append(_event("event-c", occurred_at=11.0))
        return httpx.Response(200, json=events)

    source = _source(handler)
    first = await source.list_events(None, 10)
    assert [event.event_id for event in first.events] == ["event-a", "event-b"]
    assert first.next_cursor
    second = await source.list_events(first.next_cursor, 10)
    assert [event.event_id for event in second.events] == ["event-c"]
    assert second.next_cursor != first.next_cursor


@pytest.mark.asyncio
async def test_transport_byte_limit_ignores_false_length_and_always_closes_stream():
    stream = _Chunks([b"[", b"x" * 80, b"]"])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": "2"}, stream=stream)

    with pytest.raises(CameraSourceError, match="response_too_large"):
        await _source(handler, max_event_bytes=64, max_attempts=1).list_events(None, 10)
    assert stream.closed is True

    declared = _Chunks([b"[]"])

    def declared_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": "65"}, stream=declared)

    with pytest.raises(CameraSourceError, match="response_too_large"):
        await _source(declared_handler, max_event_bytes=64, max_attempts=1).list_events(None, 10)
    assert declared.closed is True


@pytest.mark.asyncio
async def test_timeout_retries_read_only_with_bounded_backoff_and_offline_health():
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("offline", request=request)
        return httpx.Response(200, json=[])

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    source = _source(handler, sleep=sleep)
    assert (await source.list_events(None, 10)).events == ()
    assert attempts == 2
    assert sleeps == [0.1]
    assert source.health().status == "online"

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    failed = _source(offline, max_attempts=1)
    with pytest.raises(CameraSourceError, match="source_offline"):
        await failed.list_events(None, 10)
    health = failed.health().to_public()
    assert health["status"] == "offline"
    assert "origin" not in health
    assert "token" not in str(health).lower()


@pytest.mark.asyncio
async def test_redirects_and_non_identity_content_encoding_are_refused_without_forwarding_auth():
    calls: list[httpx.Request] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://8.8.8.8/steal"})

    with pytest.raises(CameraSourceError, match="redirect_refused"):
        await _source(redirect, max_attempts=1).list_events(None, 10)
    assert len(calls) == 1
    assert calls[0].headers["authorization"] == "Bearer top-secret-token"

    def compressed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            stream=_Chunks([b"[]"]),
        )

    with pytest.raises(CameraSourceError, match="content_encoding_refused"):
        await _source(compressed, max_attempts=1).list_events(None, 10)


@pytest.mark.asyncio
async def test_private_snapshot_source_masks_before_return_and_raw_api_is_not_public():
    raw = _jpeg()
    raw_digest = hashlib.sha256(raw).hexdigest()
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        assert request.url.path == "/api/events/event-1/snapshot.jpg"
        return httpx.Response(200, content=raw)

    event_source = _source(handler)
    policy = _privacy_policy()
    lease = policy.begin("front-door")
    snapshot_source = _FrigateSnapshotSource(
        http=event_source._http,
        privacy_policy=policy,
    )
    masked = await snapshot_source.fetch_masked(lease, "event-1")
    assert masked.format == "PNG"
    assert raw_digest not in repr(masked)
    assert raw_digest not in str(masked.public_metadata())
    assert methods == ["GET"]
    assert "_FrigateSnapshotSource" not in __import__(
        "agents.core.cameras.frigate", fromlist=["__all__"]
    ).__all__

    with pytest.raises(CameraSourceError, match="event_id_invalid"):
        await snapshot_source.fetch_masked(lease, "../admin")
    assert methods == ["GET"]


@pytest.mark.asyncio
async def test_truncated_stream_releases_response_and_does_not_claim_health():
    stream = _Chunks(
        [json.dumps([_event("event-1", occurred_at=1.0)]).encode()[:20]],
        error=httpx.ReadError("truncated"),
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    source = _source(handler, max_attempts=1)
    with pytest.raises(CameraSourceError, match="source_offline"):
        await source.list_events(None, 10)
    assert stream.closed is True
    assert source.health().status == "offline"


@pytest.mark.asyncio
async def test_consent_generation_change_during_poll_discards_the_metadata_page():
    generation = 1

    def gate() -> PrivacyPollingGrant:
        return PrivacyPollingGrant(
            camera_ids=("front-door",),
            consent_version=2,
            generation=generation,
        )

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal generation
        generation += 1
        return httpx.Response(200, json=[_event("event-1", occurred_at=1.0)])

    source = _source(handler, poll_gate=gate)
    with pytest.raises(CameraSourceError, match="stale_consent_generation"):
        await source.list_events(None, 10)
    assert source.health().status == "degraded"
