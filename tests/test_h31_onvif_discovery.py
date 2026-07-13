"""H31 optional ONVIF is discovery/onboarding only, never an ingest path."""

from __future__ import annotations

import asyncio

import pytest

from agents.core.cameras.onvif import (
    OnvifCameraMapping,
    OnvifDiscoveryConfig,
    OnvifDiscoveryError,
    OnvifDiscoveryService,
    onvif_device_key,
)


def _resolver(host: str, _port: int) -> tuple[str, ...]:
    values = {
        "camera.local": ("192.168.1.50",),
        "192.168.1.51": ("192.168.1.51",),
        "public.example": ("8.8.8.8",),
    }
    return values.get(host, ())


def _service(
    discoverer=None,
    *,
    enabled=True,
    admin_gate=lambda: True,
    mappings=(),
    max_results=16,
    timeout_seconds=1.0,
) -> OnvifDiscoveryService:
    return OnvifDiscoveryService(
        config=OnvifDiscoveryConfig(
            enabled=enabled,
            mappings=mappings,
            max_results=max_results,
            timeout_seconds=timeout_seconds,
        ),
        admin_gate=admin_gate,
        discoverer=discoverer,
        resolver=_resolver,
    )


@pytest.mark.asyncio
async def test_discovery_is_default_off_and_requires_server_owned_admin_gate():
    calls = 0

    def discoverer():
        nonlocal calls
        calls += 1
        return []

    with pytest.raises(OnvifDiscoveryError, match="discovery_disabled"):
        await _service(discoverer, enabled=False).discover()
    with pytest.raises(OnvifDiscoveryError, match="admin_required"):
        await _service(discoverer, admin_gate=lambda: False).discover()
    assert calls == 0


@pytest.mark.asyncio
async def test_dependency_is_loaded_lazily_and_missing_dependency_is_honest(monkeypatch):
    service = _service(discoverer=None)
    monkeypatch.setattr(service, "_load_default_discoverer", lambda: None)
    result = await service.discover()
    assert result.status == "unavailable"
    assert result.reason == "onvif_dependency_missing"
    assert result.devices == ()


@pytest.mark.asyncio
async def test_results_are_lan_only_deduplicated_bounded_and_strip_every_stream_or_secret_field():
    raw = [
        {
            "xaddrs": ["http://camera.local:80/onvif/device_service"],
            "name": "Front camera",
            "rtsp_uri": "rtsp://admin:secret@camera.local/live",
            "username": "admin",
            "password": "secret",
            "scopes": ["onvif://www.onvif.org/name/Front%20camera"],
        },
        {
            "xaddrs": ["http://camera.local:80/onvif/device_service"],
            "name": "Duplicate front camera",
        },
        {
            "xaddrs": ["http://192.168.1.51/onvif/device_service"],
            "name": "Garage camera",
        },
        {
            "xaddrs": ["http://public.example/onvif/device_service"],
            "name": "External camera",
        },
    ]
    key = onvif_device_key("camera.local", 80)
    mapping = OnvifCameraMapping(
        device_key=key,
        frigate_camera_id="front-door",
        credential_ref="{{secret:onvif.front-door}}",
    )
    service = _service(lambda: raw, mappings=(mapping,), max_results=2)
    result = await service.discover()
    assert result.status == "online"
    assert len(result.devices) == 2
    assert [device.host for device in result.devices] == ["192.168.1.51", "camera.local"]
    mapped = next(device for device in result.devices if device.host == "camera.local")
    assert mapped.frigate_camera_id == "front-door"
    public = result.to_public()
    serialized = str(public).lower()
    for forbidden in ("rtsp", "admin", "secret", "password", "credential", "xaddrs"):
        assert forbidden not in serialized
    assert public["devices"][0]["device_id"]


def test_mapping_accepts_only_secret_references_and_safe_frigate_ids():
    key = onvif_device_key("camera.local", 80)
    with pytest.raises(ValueError, match="SecretBroker"):
        OnvifCameraMapping(
            device_key=key,
            frigate_camera_id="front-door",
            credential_ref="plaintext-password",
        )
    with pytest.raises(ValueError, match="Frigate camera id"):
        OnvifCameraMapping(
            device_key=key,
            frigate_camera_id="../camera",
            credential_ref="{{secret:onvif.camera}}",
        )


@pytest.mark.asyncio
async def test_discovery_timeout_is_degraded_and_does_not_leak_exception_details():
    async def slow_discovery():
        await asyncio.sleep(0.05)
        return []

    result = await _service(slow_discovery, timeout_seconds=0.01).discover()
    assert result.status == "degraded"
    assert result.reason == "discovery_timeout"
    assert "asyncio" not in str(result.to_public()).lower()


@pytest.mark.asyncio
async def test_discovery_surface_has_no_stream_open_or_camera_control_capability():
    calls: list[str] = []

    class DiscoveryOnly:
        def __call__(self):
            calls.append("discover")
            return [
                {
                    "xaddrs": ["http://camera.local/onvif/device_service"],
                    "name": "Front",
                }
            ]

        def open_stream(self):  # pragma: no cover - tripwire only
            calls.append("open_stream")
            raise AssertionError("ONVIF discovery must never open a stream")

        def get_rtsp_uri(self):  # pragma: no cover - tripwire only
            calls.append("get_rtsp_uri")
            raise AssertionError("ONVIF discovery must never request an RTSP URI")

    result = await _service(DiscoveryOnly()).discover()
    assert result.status == "online"
    assert calls == ["discover"]
    assert not hasattr(_service(lambda: []), "open_stream")


@pytest.mark.asyncio
async def test_malformed_and_oversized_raw_results_fail_boundedly():
    result = await _service(lambda: "not-a-list").discover()
    assert result.status == "degraded"
    assert result.reason == "discovery_payload_invalid"

    oversized = [
        {"xaddrs": [f"http://192.168.1.{(index % 200) + 1}/onvif/device_service"]}
        for index in range(129)
    ]
    result = await _service(lambda: oversized).discover()
    assert result.status == "degraded"
    assert result.reason == "discovery_payload_too_large"

    malformed = [{"xaddrs": ["http://camera.local:99999/onvif/device_service"]}]
    result = await _service(lambda: malformed).discover()
    assert result.status == "online"
    assert result.devices == ()
