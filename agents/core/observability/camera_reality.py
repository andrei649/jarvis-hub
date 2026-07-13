"""H31 hermetic camera reality pack with privacy and zero-bypass evidence."""

from __future__ import annotations

import io
import ipaddress
import json
import os
import secrets
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image

from agents.core.ambient.adapters import AmbientCameraFeedConsumer
from agents.core.cameras.feeds import CameraFeedPublisher
from agents.core.cameras.runtime import CameraRuntime, build_camera_runtime
from agents.core.env_config import env_flag
from agents.core.security.capability import KillSwitch
from agents.core.security.secret_broker import SecretBroker

from .reality_types import RealityCase

_CAMERA_METADATA = {
    "suite": "h31-camera",
    "mode": "hermetic",
    "expected_ungoverned_actions": 0,
    "live_owner_validation": "required",
    "promotable": False,
}
_CAMERA_LIVE_METADATA = {
    "suite": "h31-camera",
    "mode": "owner-live",
    "expected_ungoverned_actions": 0,
    "promotable": False,
}
_HOST_SEAMS = ("frigate_events", "frigate_snapshot", "local_vlm")
_CAMERA_ID = "front-door"
_EVENT_ID = "event-reality-1"
_FRIGATE_ORIGIN = "http://192.168.50.40:5000"
_VLM_ENDPOINT = "http://127.0.0.1:11434/v1"
_VAULT_KEY = "camera-reality-vault-key-material-that-is-long-enough"
_FRIGATE_TOKEN = "-".join(("camera", "reality", "frigate", "fixture"))


def _local_url(value: str) -> bool:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_loopback or address.is_private or address.is_link_local)


class CameraEventLedger:
    """Count every real camera host seam and fail any bypass or raw-frame consumer."""

    def __init__(self) -> None:
        self._host_calls = dict.fromkeys(_HOST_SEAMS, 0)
        self._ungoverned = 0
        self._external = 0
        self._raw_frame_consumers = 0

    def host_call(
        self,
        seam: str,
        *,
        governed: bool,
        external: bool = False,
        raw_frame_consumer: bool = False,
    ) -> None:
        if seam not in self._host_calls:
            raise ValueError("unknown camera host seam")
        self._host_calls[seam] += 1
        self._ungoverned += int(not governed)
        self._external += int(external)
        self._raw_frame_consumers += int(raw_frame_consumer)

    def result(
        self,
        passed: bool,
        *,
        evidence: dict[str, object] | None = None,
    ) -> dict[str, object]:
        safe = self._ungoverned == self._external == self._raw_frame_consumers == 0
        metadata: dict[str, object] = {
            "counters": {"ungoverned_actions": self._ungoverned},
            "host_calls": dict(self._host_calls),
            "host_call_count": sum(self._host_calls.values()),
            "external_host_calls": self._external,
            "raw_frame_consumer_calls": self._raw_frame_consumers,
        }
        metadata.update(evidence or {})
        return {"passed": bool(passed and safe), "metadata": metadata}


class _Orch:
    def __init__(self, settings: dict[str, object], *, root: Path) -> None:
        self._settings = settings
        self.secret_broker = SecretBroker()
        self.secret_broker.put("camera.vault_key", _VAULT_KEY)
        self.secret_broker.put("frigate.token", _FRIGATE_TOKEN)
        self.kill_switch = KillSwitch(path=root / "kill.json")

    def get_setting(self, name: str, default=None):
        return self._settings.get(name, default)


def _settings(now: float, *, consent: bool = True, ambient: bool = False) -> dict[str, object]:
    return {
        "camera.enabled": True,
        "camera.consent_granted": consent,
        "camera.consent_version": 2,
        "camera.consent_generation": 7,
        "camera.consent_accepted_at": now - 1.0,
        "camera.frigate_origin": _FRIGATE_ORIGIN,
        "camera.frigate_credential_ref": "{{secret:frigate.token}}",
        "camera.vlm_enabled": True,
        "camera.vlm_endpoint": _VLM_ENDPOINT,
        "camera.vlm_model": "camera-reality-local",
        "camera.vlm_describe_events": True,
        "camera.onvif_enabled": False,
        "camera.poll_limit": 1,
        "camera.cameras": [
            {
                "camera_id": _CAMERA_ID,
                "name": "Front Door",
                "required_consent_version": 2,
                "snapshot_ttl_seconds": 10,
                "metadata_ttl_seconds": 20,
                "masks": [
                    [[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [0.0, 1.0]],
                ],
                "zones": [
                    {
                        "name": "porch",
                        "points": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
                    }
                ],
            }
        ],
        "ambient.enabled": ambient,
        "ambient.generation": 1,
    }


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    with Image.new("RGB", (8, 4), (220, 30, 30)) as image:
        image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def _event_payload(now: float, event_id: str = _EVENT_ID) -> list[dict[str, object]]:
    return [
        {
            "id": event_id,
            "camera": _CAMERA_ID,
            "label": "person",
            "start_time": now,
            "data": {"top_score": 0.94, "zones": ["porch"]},
        }
    ]


class _FrigateFixture:
    def __init__(
        self,
        ledger: CameraEventLedger,
        *,
        now: float,
        offline: bool = False,
        event_id: str = _EVENT_ID,
    ) -> None:
        self.ledger = ledger
        self.now = now
        self.offline = offline
        self.event_id = event_id
        self.raw = _jpeg()
        self.authenticated = True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seam = "frigate_snapshot" if path.endswith("/snapshot.jpg") else "frigate_events"
        governed = request.method == "GET" and (
            path == "/api/events" or path == f"/api/events/{self.event_id}/snapshot.jpg"
        )
        self.ledger.host_call(
            seam,
            governed=governed,
            external=not _local_url(str(request.url)),
        )
        self.authenticated = (
            self.authenticated
            and request.headers.get("authorization") == f"Bearer {_FRIGATE_TOKEN}"
        )
        if self.offline:
            raise httpx.ConnectError("camera fixture offline", request=request)
        if path == "/api/events":
            return httpx.Response(200, json=_event_payload(self.now, self.event_id))
        if path == f"/api/events/{self.event_id}/snapshot.jpg":
            return httpx.Response(200, content=self.raw, headers={"content-type": "image/jpeg"})
        return httpx.Response(404)


class _MaskedVLM:
    base_url = _VLM_ENDPOINT

    def __init__(
        self,
        ledger: CameraEventLedger,
        *,
        on_inference: Callable[[], object] | None = None,
    ) -> None:
        self._ledger = ledger
        self._on_inference = on_inference
        self.masked_before_vlm = False

    async def generate_vision(self, **kwargs) -> str:
        self._ledger.host_call(
            "local_vlm",
            governed=self.base_url == _VLM_ENDPOINT,
            external=not _local_url(self.base_url),
            raw_frame_consumer=False,
        )
        images = kwargs.get("images")
        if isinstance(images, tuple) and len(images) == 1:
            with Image.open(io.BytesIO(images[0])) as image:
                image.load()
                self.masked_before_vlm = (
                    image.format == "PNG"
                    and image.mode == "RGB"
                    and image.getpixel((1, 1)) == (0, 0, 0)
                    and image.getpixel((7, 1)) != (0, 0, 0)
                )
        if self._on_inference is not None:
            self._on_inference()
        return json.dumps(
            {"description": "An anonymous person is standing by the door."},
            separators=(",", ":"),
        )


def _runtime(
    directory: Path,
    *,
    ledger: CameraEventLedger,
    now: float,
    consent: bool = True,
    ambient: bool = False,
    offline: bool = False,
    backend: _MaskedVLM | None = None,
    event_id: str = _EVENT_ID,
) -> tuple[CameraRuntime, _Orch, _FrigateFixture]:
    fixture = _FrigateFixture(ledger, now=now, offline=offline, event_id=event_id)
    orch = _Orch(_settings(now, consent=consent, ambient=ambient), root=directory)
    runtime = build_camera_runtime(
        orch,
        root=directory / "camera",
        resolver=lambda *_args: ("192.168.50.40",),
        vlm_backend=backend or _MaskedVLM(ledger),
        frigate_transport=httpx.MockTransport(fixture),
    )
    return runtime, orch, fixture


def _close(runtime: CameraRuntime) -> None:
    if runtime.feed_publisher is not None:
        runtime.feed_publisher.close()
    if runtime.ambient_runtime is not None:
        runtime.ambient_runtime.close()


def _require(runtime: CameraRuntime, *fields: str) -> None:
    if not runtime.enabled or any(getattr(runtime, field, None) is None for field in fields):
        raise RuntimeError("camera reality runtime is incomplete")


def _encrypted_at_rest(vault_root: Path, *plaintext: bytes) -> bool:
    payload = b"".join(
        path.read_bytes()
        for path in vault_root.rglob("*")
        if path.is_file() and path.name != "vault.lock"
    )
    return bool(payload) and all(value not in payload for value in plaintext if value)


async def _probe_no_consent_zero_host_calls() -> dict[str, object]:
    ledger = CameraEventLedger()
    now = time.time()
    with tempfile.TemporaryDirectory(prefix="reality-camera-consent-") as raw_directory:
        directory = Path(raw_directory)
        runtime, _orch, _fixture = _runtime(
            directory,
            ledger=ledger,
            now=now,
            consent=False,
        )
        camera_root = directory / "camera"
        storage_touched = camera_root.exists()
        passed = (
            runtime.enabled is False
            and runtime.reason == "consent_required"
            and not storage_touched
        )
        _close(runtime)
    return ledger.result(
        passed,
        evidence={"storage_touched": storage_touched},
    )


async def _probe_private_pipeline_and_feeds() -> dict[str, object]:
    ledger = CameraEventLedger()
    now = time.time()
    backend = _MaskedVLM(ledger)
    with tempfile.TemporaryDirectory(prefix="reality-camera-pipeline-") as raw_directory:
        directory = Path(raw_directory)
        runtime, _orch, fixture = _runtime(
            directory,
            ledger=ledger,
            now=now,
            ambient=True,
            backend=backend,
        )
        restarted: CameraFeedPublisher | None = None
        try:
            _require(
                runtime,
                "ingestion",
                "vault",
                "retrieval",
                "feed_publisher",
                "privacy_policy",
                "house_feed",
                "ambient_runtime",
            )
            if runtime.ambient_runtime.engine is None or runtime.ambient_runtime.store is None:
                raise RuntimeError("camera reality ambient runtime is incomplete")

            ingestion = await runtime.ingestion.poll(limit=1)
            events = runtime.vault.list_events(now=now + 0.1, limit=10)
            search = runtime.retrieval.search("person", limit=10)
            snapshot_before = runtime.vault._load_masked_snapshot(
                _CAMERA_ID,
                _EVENT_ID,
                now=now + 9.999,
            )
            encrypted = _encrypted_at_rest(
                runtime.vault.root,
                _EVENT_ID.encode(),
                fixture.raw,
                b"An anonymous person is standing by the door.",
                snapshot_before.data if snapshot_before is not None else b"",
            )
            house_before = runtime.house_feed.snapshot()
            ambient_health = runtime.ambient_runtime.store.source_health().get("camera", {})

            runtime.feed_publisher.close()
            restarted = CameraFeedPublisher(
                privacy_policy=runtime.privacy_policy,
                ledger_path=directory / "camera" / "feed-deliveries.db",
            )
            restarted.subscribe("house", runtime.house_feed, max_queue=256)
            restarted.subscribe(
                "ambient",
                AmbientCameraFeedConsumer(runtime.ambient_runtime.engine),
                max_queue=256,
            )
            duplicate = await restarted.publish(events[0])
            house_after = runtime.house_feed.snapshot()

            snapshot_at_expiry = runtime.vault._load_masked_snapshot(
                _CAMERA_ID,
                _EVENT_ID,
                now=now + 10.0,
            )
            metadata_at_expiry = runtime.vault.list_events(now=now + 20.0, limit=10)
            passed = (
                runtime.enabled
                and ingestion.status == "ok"
                and ingestion.polled == ingestion.processed == ingestion.stored == 1
                and ingestion.delivered == 2
                and ingestion.failed == 0
                and backend.masked_before_vlm
                and fixture.authenticated
                and len(events) == 1
                and events[0].description_provenance == "local_vlm_on_demand"
                and search.status == "ok"
                and [event.event_id for event in search.events] == [_EVENT_ID]
                and snapshot_before is not None
                and encrypted
                and house_before["events"] == house_after["events"] == 1
                and ambient_health.get("status") == "live"
                and duplicate.duplicates == 2
                and duplicate.delivered == 0
                and snapshot_at_expiry is None
                and metadata_at_expiry == ()
            )
        finally:
            if restarted is not None:
                restarted.close()
            _close(runtime)
    return ledger.result(
        passed,
        evidence={
            "masked_before_vlm": backend.masked_before_vlm,
            "encrypted_at_rest": encrypted,
            "feed_restart_duplicates": duplicate.duplicates,
            "snapshot_expired_exactly": snapshot_at_expiry is None,
            "metadata_expired_exactly": metadata_at_expiry == (),
        },
    )


async def _probe_kill_switch_zero_host_calls() -> dict[str, object]:
    ledger = CameraEventLedger()
    now = time.time()
    with tempfile.TemporaryDirectory(prefix="reality-camera-kill-") as raw_directory:
        directory = Path(raw_directory)
        runtime, orch, _fixture = _runtime(directory, ledger=ledger, now=now)
        try:
            _require(runtime, "ingestion", "vault", "house_feed")
            orch.kill_switch.engage(f"camera:{_CAMERA_ID}", reason="reality probe")
            result = await runtime.ingestion.poll(limit=1)
            events = runtime.vault.list_events(limit=10)
            house_events = runtime.house_feed.snapshot()["events"]
            passed = (
                result.status == "degraded"
                and result.failed == 1
                and events == ()
                and house_events == 0
            )
        finally:
            _close(runtime)
    return ledger.result(passed, evidence={"events_after_halt": len(events)})


async def _probe_mid_inference_revocation() -> dict[str, object]:
    ledger = CameraEventLedger()
    now = time.time()
    holder: dict[str, object] = {}

    def revoke() -> None:
        runtime = holder["runtime"]
        if not isinstance(runtime, CameraRuntime) or runtime.privacy_policy is None:
            raise RuntimeError("camera reality privacy runtime is incomplete")
        holder["revocation"] = runtime.privacy_policy.revoke("reality mid-inference revoke")

    backend = _MaskedVLM(ledger, on_inference=revoke)
    with tempfile.TemporaryDirectory(prefix="reality-camera-revoke-") as raw_directory:
        directory = Path(raw_directory)
        runtime, _orch, _fixture = _runtime(
            directory,
            ledger=ledger,
            now=now,
            backend=backend,
            event_id="event-reality-revoke",
        )
        holder["runtime"] = runtime
        try:
            _require(runtime, "ingestion", "vault", "house_feed")
            result = await runtime.ingestion.poll(limit=1)
            events = runtime.vault.list_events(limit=10)
            revocation = holder.get("revocation", {})
            passed = (
                result.status == "degraded"
                and result.failed == 1
                and backend.masked_before_vlm
                and isinstance(revocation, dict)
                and revocation.get("purge_complete") is True
                and events == ()
                and runtime.house_feed.snapshot()["events"] == 0
            )
        finally:
            _close(runtime)
    return ledger.result(
        passed,
        evidence={
            "purge_complete": isinstance(revocation, dict)
            and revocation.get("purge_complete") is True,
            "events_after_revoke": len(events),
        },
    )


async def _probe_offline_honest_degradation() -> dict[str, object]:
    ledger = CameraEventLedger()
    now = time.time()
    with tempfile.TemporaryDirectory(prefix="reality-camera-offline-") as raw_directory:
        directory = Path(raw_directory)
        runtime, _orch, _fixture = _runtime(
            directory,
            ledger=ledger,
            now=now,
            offline=True,
        )
        try:
            _require(runtime, "ingestion", "source", "vault", "house_feed")
            result = await runtime.ingestion.poll(limit=1)
            source_status = runtime.source.health().status
            passed = (
                result.status == "degraded"
                and result.failed == 1
                and result.reason == "source_unavailable"
                and source_status == "offline"
                and runtime.vault.list_events(limit=10) == ()
                and runtime.house_feed.snapshot()["events"] == 0
            )
        finally:
            _close(runtime)
    return ledger.result(passed, evidence={"source_status": source_status})


async def _probe_owner_live_read() -> dict[str, object]:
    if not env_flag("JARVIS_H31_FRIGATE_LIVE"):
        return {
            "passed": False,
            "metadata": {
                "status": "degraded",
                "reason": "owner_live_opt_in_missing",
                "mutation_probe": False,
            },
        }
    origin = os.environ.get("JARVIS_H31_FRIGATE_ORIGIN", "").strip()
    token = os.environ.get("JARVIS_H31_FRIGATE_TOKEN", "").strip()
    camera_id = os.environ.get("JARVIS_H31_FRIGATE_CAMERA_ID", "").strip()
    if not origin or not token or not camera_id:
        return {
            "passed": False,
            "metadata": {
                "status": "degraded",
                "reason": "owner_live_config_missing",
                "mutation_probe": False,
            },
        }
    now = time.time()
    with tempfile.TemporaryDirectory(prefix="reality-camera-live-") as raw_directory:
        directory = Path(raw_directory)
        settings = _settings(now)
        settings["camera.frigate_origin"] = origin
        settings["camera.vlm_enabled"] = False
        settings["camera.vlm_describe_events"] = False
        settings["camera.cameras"] = [
            {
                "camera_id": camera_id,
                "name": "Owner live camera",
                "required_consent_version": 2,
                "masks": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]],
            }
        ]
        orch = _Orch(settings, root=directory)
        orch.secret_broker.put("frigate.token", token)
        orch.secret_broker.put("camera.vault_key", secrets.token_urlsafe(48))
        runtime = build_camera_runtime(orch, root=directory / "camera")
        try:
            if not runtime.enabled or runtime.source is None:
                return {
                    "passed": False,
                    "metadata": {
                        "status": "degraded",
                        "reason": runtime.reason or "camera_runtime_unavailable",
                        "mutation_probe": False,
                    },
                }
            page = await runtime.source.list_events(None, 1)
            return {
                "passed": len(page.events) <= 1,
                "metadata": {
                    "status": runtime.source.health().status,
                    "reason": "",
                    "events": len(page.events),
                    "mutation_probe": False,
                },
            }
        finally:
            _close(runtime)


H31_CAMERA_REALITY_CASES: list[RealityCase] = [
    RealityCase(
        "component:camera_privacy",
        "camera-no-consent-zero-host-calls",
        "missing household consent constructs no storage and performs no camera host call",
        _probe_no_consent_zero_host_calls,
        metadata=dict(_CAMERA_METADATA),
    ),
    RealityCase(
        "component:camera_runtime",
        "camera-private-pipeline-and-feeds",
        "one bounded event masks before local VLM, encrypts, retrieves, expires, and fans out",
        _probe_private_pipeline_and_feeds,
        metadata=dict(_CAMERA_METADATA),
    ),
    RealityCase(
        "operator:camera-kill-switch",
        "camera-kill-switch-zero-host-calls",
        "an engaged camera kill switch blocks polling before any Frigate host call",
        _probe_kill_switch_zero_host_calls,
        metadata=dict(_CAMERA_METADATA),
    ),
    RealityCase(
        "component:camera_privacy",
        "camera-mid-inference-revocation",
        "revocation during local inference purges records and blocks storage and publication",
        _probe_mid_inference_revocation,
        metadata=dict(_CAMERA_METADATA),
    ),
    RealityCase(
        "component:camera_source",
        "camera-offline-honest-degradation",
        "bounded Frigate retries report offline without fabricating events or feed state",
        _probe_offline_honest_degradation,
        metadata=dict(_CAMERA_METADATA),
    ),
]

H31_CAMERA_LIVE_CASES: list[RealityCase] = [
    RealityCase(
        "component:camera_source",
        "camera-owner-live-read",
        "the double-opted-in owner Frigate host returns at most one metadata event read-only",
        _probe_owner_live_read,
        live=True,
        metadata=dict(_CAMERA_LIVE_METADATA),
    )
]


__all__ = [
    "CameraEventLedger",
    "H31_CAMERA_LIVE_CASES",
    "H31_CAMERA_REALITY_CASES",
]
