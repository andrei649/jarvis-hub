"""H31.5 — camera runtime composition and metadata-only user/admin API."""

from __future__ import annotations

import json
from datetime import UTC

import pytest

from agents.core.cameras.models import CameraEvent
from agents.core.cameras.onvif import OnvifDiscoveryError
from agents.core.cameras.retrieval import CameraEventRetrieval
from agents.core.cameras.runtime import CameraRuntime, build_camera_runtime
from agents.core.routers import cameras as camera_router
from agents.core.security.capability import KillSwitch
from agents.core.security.secret_broker import SecretBroker

_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


class _Index:
    def list_events(self, *, now=None, limit=100):
        return (
            CameraEvent(
                event_id="event-1",
                camera_id="front-door",
                label="person",
                occurred_at=100.0,
                confidence=0.91,
                zone="porch",
                room_id="entry",
                description="An anonymous person left a package.",
                description_provenance="local_vlm_on_demand",
            ),
        )


class _Health:
    def snapshot(self):
        return {
            "status": "healthy",
            "source": {
                "status": "online",
                "camera_count": 1,
                "last_success_at": 100.0,
                "last_error": None,
            },
            "storage": {"status": "ready", "items": 1, "bytes": 200, "last_sweep_at": 100.0},
        }


class _DiscoveryResult:
    def to_public(self):
        return {
            "status": "online",
            "reason": None,
            "devices": [
                {
                    "device_id": "a" * 24,
                    "name": "Front Door",
                    "host": "192.168.1.40",
                    "port": 80,
                    "secure": False,
                    "mapped": True,
                    "frigate_camera_id": "front-door",
                }
            ],
        }


class _Discovery:
    async def discover(self):
        return _DiscoveryResult()


class _DisabledDiscovery:
    async def discover(self):
        raise OnvifDiscoveryError("discovery_disabled")


def _runtime(*, enabled: bool = True, discovery=None) -> CameraRuntime:
    return CameraRuntime(
        enabled=enabled,
        status="ready" if enabled else "disabled",
        reason=None if enabled else "camera_disabled",
        retrieval=(
            CameraEventRetrieval(index=_Index(), clock=lambda: 200.0, timezone=UTC)
            if enabled
            else None
        ),
        health=_Health() if enabled else None,
        discovery=discovery,
    )


def _payload(response) -> dict:
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_status_events_and_search_are_bounded_metadata_only(monkeypatch):
    monkeypatch.setattr(camera_router, "_get_runtime", lambda: _runtime())
    status = _payload(await camera_router.camera_status())
    events = _payload(await camera_router.camera_events(limit=10))
    search = _payload(
        await camera_router.camera_search(
            camera_router.CameraSearchBody(query="person", limit=10)
        )
    )

    assert status["enabled"] is True
    assert status["status"] == "healthy"
    assert events["events"] == search["events"]
    assert events["events"][0]["anonymous"] is True
    encoded = json.dumps({"status": status, "events": events, "search": search}).lower()
    assert all(
        term not in encoded
        for term in (
            "snapshot",
            "frame",
            "clip",
            "vault_id",
            ".blob",
            "rtsp",
            "credential",
            "image_url",
        )
    )


@pytest.mark.asyncio
async def test_disabled_runtime_is_honest_and_never_reads_an_index(monkeypatch):
    monkeypatch.setattr(camera_router, "_get_runtime", lambda: _runtime(enabled=False))
    assert _payload(await camera_router.camera_status()) == {
        "enabled": False,
        "status": "disabled",
        "reason": "camera_disabled",
        "source": None,
        "storage": None,
    }
    assert _payload(await camera_router.camera_events(limit=10)) == {
        "enabled": False,
        "status": "disabled",
        "reason": "camera_disabled",
        "interpretation": {},
        "events": [],
    }


@pytest.mark.asyncio
async def test_onvif_discovery_is_admin_surface_and_failure_is_stable(monkeypatch):
    monkeypatch.setattr(camera_router, "_get_runtime", lambda: _runtime(discovery=_Discovery()))
    live = _payload(await camera_router.camera_onvif_discover())
    assert live["enabled"] is True
    assert live["devices"][0]["mapped"] is True
    assert "xaddrs" not in json.dumps(live).lower()

    monkeypatch.setattr(
        camera_router,
        "_get_runtime",
        lambda: _runtime(discovery=_DisabledDiscovery()),
    )
    disabled = _payload(await camera_router.camera_onvif_discover())
    assert disabled == {
        "enabled": True,
        "status": "disabled",
        "reason": "discovery_disabled",
        "devices": [],
    }


class _Orch:
    def __init__(self, settings: dict, *, root) -> None:
        self._settings = settings
        self.secret_broker = SecretBroker()
        self.secret_broker.put("camera.vault_key", _KEY)
        self.secret_broker.put("frigate.token", "local-frigate-token")
        self.kill_switch = KillSwitch(path=str(root / "kill.json"))

    def get_setting(self, name, default=None):
        return self._settings.get(name, default)


def _settings() -> dict:
    return {
        "camera.enabled": True,
        "camera.consent_granted": True,
        "camera.consent_version": 2,
        "camera.consent_generation": 3,
        "camera.consent_accepted_at": 50.0,
        "camera.frigate_origin": "http://192.168.1.40:5000",
        "camera.frigate_credential_ref": "{{secret:frigate.token}}",
        "camera.vlm_enabled": False,
        "camera.onvif_enabled": False,
        "camera.cameras": [
            {
                "camera_id": "front-door",
                "name": "Front Door",
                "required_consent_version": 2,
                "masks": [
                    [[0.0, 0.0], [0.2, 0.0], [0.2, 1.0], [0.0, 1.0]],
                ],
                "zones": [
                    {
                        "name": "porch",
                        "points": [[0.0, 0.0], [0.6, 0.0], [0.6, 1.0], [0.0, 1.0]],
                    }
                ],
                "lines": [
                    {
                        "name": "threshold",
                        "start": [0.5, 0.0],
                        "end": [0.5, 1.0],
                        "direction": "any",
                    }
                ],
            }
        ],
    }


def test_runtime_is_default_off_and_does_not_touch_storage(tmp_path):
    runtime = build_camera_runtime(_Orch({}, root=tmp_path), root=tmp_path / "camera")
    assert runtime.enabled is False
    assert runtime.status == "disabled"
    assert runtime.reason == "camera_disabled"
    assert not (tmp_path / "camera").exists()


def test_runtime_composes_real_privacy_source_pipeline_vault_and_retrieval(tmp_path):
    runtime = build_camera_runtime(
        _Orch(_settings(), root=tmp_path),
        root=tmp_path / "camera",
        resolver=lambda *_args: ("192.168.1.40",),
    )
    assert runtime.enabled is True
    assert runtime.status == "ready"
    assert runtime.source is not None
    assert runtime.pipeline is not None
    assert runtime.privacy_policy is not None
    assert runtime.vault is not None
    assert runtime.retrieval is not None
    assert runtime.scheduler is not None
    assert runtime.feed_publisher is not None
    assert runtime.ingestion is not None
    assert runtime.ingestion_service is not None
    assert runtime.house_feed is not None
    assert set(runtime.feed_publisher.health()["sinks"]) == {"house"}
    assert not hasattr(runtime.source, "fetch_snapshot")
    assert runtime.vault.health()["status"] == "ready"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        (lambda settings: settings.update({"camera.consent_granted": False}), "consent_required"),
        (lambda settings: settings.update({"camera.cameras": []}), "camera_config_invalid"),
        (
            lambda settings: settings.update({"camera.frigate_origin": "https://api.example.com"}),
            "camera_runtime_unavailable",
        ),
    ),
)
def test_runtime_fails_closed_on_missing_consent_or_invalid_configuration(
    tmp_path,
    mutation,
    reason,
):
    settings = _settings()
    mutation(settings)
    runtime = build_camera_runtime(
        _Orch(settings, root=tmp_path),
        root=tmp_path / "camera",
        resolver=lambda *_args: ("8.8.8.8",),
    )
    assert runtime.enabled is False
    assert runtime.reason == reason


def test_runtime_subscribes_real_ambient_monitor_consumer_only_after_opt_in(tmp_path):
    settings = _settings()
    settings["ambient.enabled"] = True
    settings["ambient.generation"] = 2
    runtime = build_camera_runtime(
        _Orch(settings, root=tmp_path),
        root=tmp_path / "camera",
        resolver=lambda *_args: ("192.168.1.40",),
    )
    assert runtime.enabled is True
    assert runtime.ambient_runtime is not None
    assert runtime.ambient_runtime.enabled is True
    assert runtime.feed_publisher is not None
    assert set(runtime.feed_publisher.health()["sinks"]) == {"house", "ambient"}
    runtime.feed_publisher.close()
    runtime.ambient_runtime.close()


def test_router_declares_no_snapshot_clip_or_frame_route():
    paths = {route.path for route in camera_router.router.routes}
    assert paths == {
        "/api/cameras/status",
        "/api/cameras/events",
        "/api/cameras/search",
        "/api/cameras/onvif/discover",
    }
    assert not any(term in path for path in paths for term in ("snapshot", "clip", "frame"))


@pytest.mark.asyncio
async def test_camera_runtime_lifecycle_helpers_start_and_stop_service(monkeypatch):
    calls: list[str] = []

    class _Service:
        def start(self):
            calls.append("start")
            return True

        async def stop(self):
            calls.append("stop")

    class _Publisher:
        def close(self):
            calls.append("close")

    runtime = _runtime()
    runtime.ingestion_service = _Service()
    runtime.feed_publisher = _Publisher()
    monkeypatch.setattr(camera_router, "_get_runtime", lambda: runtime)

    assert await camera_router.start_camera_ingestion() is True
    await camera_router.stop_camera_ingestion()

    assert calls == ["start", "stop", "close"]
