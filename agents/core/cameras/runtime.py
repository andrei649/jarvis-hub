"""Default-off composition root for governed local camera intelligence."""

from __future__ import annotations

import ipaddress
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agents.core.ambient.adapters import AmbientCameraFeedConsumer
from agents.core.ambient.runtime import AmbientRuntime, build_ambient_runtime
from agents.core.house.camera_feed import HouseCameraFeedConsumer
from agents.core.llm.vlm import VLMBackend
from agents.core.paths import data_path
from agents.core.security.secret_broker import SecretBroker

from .feeds import CameraFeedPublisher, CameraIngestionCoordinator, CameraIngestionService
from .frigate import FrigateConfig, FrigateEventSource, _FrigateSnapshotSource
from .health import CameraHealthMonitor, CameraRetentionScheduler
from .models import CameraConfig, HouseholdConsent, PrivacyMask
from .onvif import (
    OnvifCameraMapping,
    OnvifDiscoveryConfig,
    OnvifDiscoveryService,
)
from .pipeline import CameraPipeline
from .privacy import CameraPrivacyPolicy
from .retrieval import CameraEventRetrieval
from .rules import CameraRuleEngine, CameraZone, LineRule
from .vault import CameraEventVault
from .vlm import LocalCameraVLM, LocalCameraVLMConfig


@dataclass
class CameraRuntime:
    enabled: bool
    status: str
    reason: str | None
    retrieval: CameraEventRetrieval | None = None
    health: CameraHealthMonitor | None = None
    discovery: OnvifDiscoveryService | None = None
    source: FrigateEventSource | None = None
    pipeline: CameraPipeline | None = None
    privacy_policy: CameraPrivacyPolicy | None = None
    vault: CameraEventVault | None = None
    scheduler: CameraRetentionScheduler | None = None
    feed_publisher: CameraFeedPublisher | None = None
    ingestion: CameraIngestionCoordinator | None = None
    ingestion_service: CameraIngestionService | None = None
    house_feed: HouseCameraFeedConsumer | None = None
    ambient_runtime: AmbientRuntime | None = None
    orch_id: int = 0


def _disabled(reason: str, orch: object | None) -> CameraRuntime:
    status = "disabled" if reason == "camera_disabled" else "unavailable"
    return CameraRuntime(
        enabled=False,
        status=status,
        reason=reason,
        orch_id=id(orch) if orch is not None else 0,
    )


def _setting(orch: object | None, name: str, default: Any = None) -> Any:
    getter = getattr(orch, "get_setting", None)
    return getter(name, default) if callable(getter) else default


def _boolean(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in {0, 1}:
        return bool(value)
    raise ValueError(f"{field_name} must be boolean")


def _integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field_name} must be an integer")
    return value


def _number(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be finite")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field_name} must be finite")
    return result


def _sequence(value: Any, *, field_name: str, maximum: int) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) > maximum:
        raise ValueError(f"{field_name} must be a bounded list")
    return tuple(value)


def _mapping(value: Any, *, field_name: str, allowed: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not set(value).issubset(allowed):
        raise ValueError(f"{field_name} has invalid fields")
    return value


def _points(value: Any, *, field_name: str) -> tuple[tuple[float, float], ...]:
    return tuple(tuple(point) for point in _sequence(value, field_name=field_name, maximum=32))


def _camera_config(raw: Any) -> tuple[CameraConfig, tuple[CameraZone, ...], tuple[LineRule, ...]]:
    value = _mapping(
        raw,
        field_name="camera config",
        allowed=frozenset(
            {
                "camera_id",
                "name",
                "enabled",
                "required_consent_version",
                "masks",
                "snapshot_ttl_seconds",
                "metadata_ttl_seconds",
                "zones",
                "lines",
            }
        ),
    )
    camera_id = value.get("camera_id")
    masks = tuple(
        PrivacyMask(points=_points(mask, field_name="privacy mask"))
        for mask in _sequence(value.get("masks", ()), field_name="privacy masks", maximum=16)
    )
    config = CameraConfig(
        camera_id=camera_id,
        name=value.get("name"),
        enabled=_boolean(value.get("enabled", True), field_name="camera enabled"),
        required_consent_version=_integer(
            value.get("required_consent_version", 1),
            field_name="required consent version",
            minimum=1,
        ),
        masks=masks,
        snapshot_ttl_seconds=_integer(
            value.get("snapshot_ttl_seconds", 24 * 60 * 60),
            field_name="snapshot ttl",
            minimum=1,
        ),
        metadata_ttl_seconds=_integer(
            value.get("metadata_ttl_seconds", 30 * 24 * 60 * 60),
            field_name="metadata ttl",
            minimum=1,
        ),
    )
    zones: list[CameraZone] = []
    for raw_zone in _sequence(value.get("zones", ()), field_name="camera zones", maximum=64):
        zone = _mapping(
            raw_zone,
            field_name="camera zone",
            allowed=frozenset({"name", "points"}),
        )
        zones.append(
            CameraZone(
                camera_id=config.camera_id,
                name=zone.get("name"),
                points=_points(zone.get("points", ()), field_name="zone points"),
            )
        )
    lines: list[LineRule] = []
    for raw_line in _sequence(value.get("lines", ()), field_name="camera lines", maximum=64):
        line = _mapping(
            raw_line,
            field_name="camera line",
            allowed=frozenset({"name", "start", "end", "direction"}),
        )
        lines.append(
            LineRule(
                camera_id=config.camera_id,
                name=line.get("name"),
                start=tuple(line.get("start", ())),
                end=tuple(line.get("end", ())),
                direction=line.get("direction", "any"),
            )
        )
    return config, tuple(zones), tuple(lines)


def _camera_settings(
    orch: object | None,
) -> tuple[tuple[CameraConfig, ...], tuple[CameraZone, ...], tuple[LineRule, ...]]:
    raw = _setting(orch, "camera.cameras", ())
    if isinstance(raw, str):
        if len(raw) > 65_536:
            raise ValueError("camera config is too large")
        raw = json.loads(raw)
    items = _sequence(raw, field_name="camera configs", maximum=128)
    if not items:
        raise ValueError("camera config is empty")
    configs: list[CameraConfig] = []
    zones: list[CameraZone] = []
    lines: list[LineRule] = []
    for item in items:
        config, camera_zones, camera_lines = _camera_config(item)
        configs.append(config)
        zones.extend(camera_zones)
        lines.extend(camera_lines)
    return tuple(configs), tuple(zones), tuple(lines)


def _local_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        (address.is_private or address.is_loopback or address.is_link_local)
        and not address.is_multicast
        and not address.is_unspecified
        and str(address) not in {"100.100.100.200", "169.254.169.254"}
    )


def _origin_preflight(origin: str, resolver: Callable | None) -> None:
    parsed = urlsplit(origin)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not _local_address(str(literal)):
        raise ValueError("Frigate origin must be LAN-only")
    if resolver is not None:
        addresses = tuple(str(item) for item in resolver(host, port))
        if not addresses or any(not _local_address(item) for item in addresses):
            raise ValueError("Frigate origin must resolve only to LAN addresses")


def _onvif_mappings(orch: object | None) -> tuple[OnvifCameraMapping, ...]:
    raw = _setting(orch, "camera.onvif_mappings", ())
    if isinstance(raw, str):
        if len(raw) > 32_768:
            raise ValueError("ONVIF mappings are too large")
        raw = json.loads(raw)
    mappings: list[OnvifCameraMapping] = []
    for item in _sequence(raw, field_name="ONVIF mappings", maximum=128):
        value = _mapping(
            item,
            field_name="ONVIF mapping",
            allowed=frozenset({"device_key", "frigate_camera_id", "credential_ref"}),
        )
        mappings.append(
            OnvifCameraMapping(
                device_key=value.get("device_key"),
                frigate_camera_id=value.get("frigate_camera_id"),
                credential_ref=value.get("credential_ref", ""),
            )
        )
    return tuple(mappings)


async def _disabled_generate(**_kwargs) -> str:
    return ""


def build_camera_runtime(
    orch: object | None,
    *,
    root: str | Path | None = None,
    resolver: Callable | None = None,
    discoverer: Callable | None = None,
    vlm_backend: Any = None,
    frigate_transport: Any = None,
) -> CameraRuntime:
    """Compose the camera stack only after master opt-in and versioned consent."""

    publisher: CameraFeedPublisher | None = None
    ambient_runtime: AmbientRuntime | None = None
    try:
        enabled = _boolean(_setting(orch, "camera.enabled", False), field_name="camera enabled")
    except (TypeError, ValueError):
        return _disabled("camera_runtime_unavailable", orch)
    if not enabled:
        return _disabled("camera_disabled", orch)
    try:
        configs, zones, lines = _camera_settings(orch)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _disabled("camera_config_invalid", orch)
    try:
        consent_granted = _boolean(
            _setting(orch, "camera.consent_granted", False),
            field_name="camera consent",
        )
        if not consent_granted:
            return _disabled("consent_required", orch)
        consent = HouseholdConsent(
            version=_integer(
                _setting(orch, "camera.consent_version", 0),
                field_name="consent version",
                minimum=1,
            ),
            generation=_integer(
                _setting(orch, "camera.consent_generation", 0),
                field_name="consent generation",
            ),
            granted=True,
            camera_ids=tuple(config.camera_id for config in configs if config.enabled),
            accepted_at=_number(
                _setting(orch, "camera.consent_accepted_at", 0.0),
                field_name="consent accepted_at",
            ),
        )
        if any(config.required_consent_version != consent.version for config in configs):
            return _disabled("consent_version_mismatch", orch)
        secret_broker = getattr(orch, "secret_broker", None)
        kill_switch = getattr(orch, "kill_switch", None)
        if not isinstance(secret_broker, SecretBroker) or not callable(
            getattr(kill_switch, "is_halted", None)
        ):
            raise ValueError("camera security services unavailable")
        runtime_root = Path(root) if root is not None else data_path("cameras")
        vault = CameraEventVault(
            runtime_root / "vault",
            configs=configs,
            secret_broker=secret_broker,
        )
        lifecycle: dict[str, Any] = {}

        def _detach_camera_feeds() -> None:
            service = lifecycle.get("service")
            if service is not None:
                service.request_stop()
            active_publisher = lifecycle.get("publisher")
            if active_publisher is not None:
                active_publisher.close()

        privacy = CameraPrivacyPolicy(
            configs=configs,
            consent=consent,
            kill_switch=kill_switch,
            stop_polling=_detach_camera_feeds,
            detach_publishers=_detach_camera_feeds,
            purge_records=lambda _generation: vault.purge(),
        )
        origin = _setting(orch, "camera.frigate_origin", "")
        credential_ref = _setting(orch, "camera.frigate_credential_ref", "")
        frigate_config = FrigateConfig(
            origin=origin,
            credential_ref=credential_ref,
            enabled=True,
        )
        _origin_preflight(frigate_config.origin, resolver)
        source = FrigateEventSource(
            config=frigate_config,
            secret_broker=secret_broker,
            poll_gate=privacy.begin_polling,
            kill_switch=kill_switch,
            transport=frigate_transport,
            resolver=resolver,
        )
        snapshot_source = _FrigateSnapshotSource(http=source._http, privacy_policy=privacy)
        vlm_config = LocalCameraVLMConfig(
            endpoint=_setting(orch, "camera.vlm_endpoint", "http://127.0.0.1:8000/v1"),
            model=_setting(orch, "camera.vlm_model", "qwen3-vl-local"),
            enabled=_boolean(
                _setting(orch, "camera.vlm_enabled", False),
                field_name="camera VLM enabled",
            ),
        )
        if vlm_config.enabled:
            backend = vlm_backend or VLMBackend(base_url=vlm_config.endpoint, api_key="")
            vlm = LocalCameraVLM.from_backend(vlm_config, backend)
        else:
            vlm = LocalCameraVLM(vlm_config, generate=_disabled_generate)
        pipeline = CameraPipeline(
            rules=CameraRuleEngine(zones=zones, lines=lines),
            privacy_policy=privacy,
            snapshots=snapshot_source,
            vlm=vlm,
            store_masked=lambda event, frame: vault.store(event, frame=frame),
        )
        retrieval = CameraEventRetrieval(index=vault)
        scheduler = CameraRetentionScheduler(vault=vault)
        health = CameraHealthMonitor(source=source, vault=vault)
        publisher = CameraFeedPublisher(
            privacy_policy=privacy,
            ledger_path=runtime_root / "feed-deliveries.db",
        )
        lifecycle["publisher"] = publisher
        house_feed = HouseCameraFeedConsumer()
        publisher.subscribe("house", house_feed, max_queue=256)
        ambient_runtime = build_ambient_runtime(
            orch,
            root=runtime_root.parent / "ambient",
        )
        if ambient_runtime.enabled and ambient_runtime.engine is not None:
            publisher.subscribe(
                "ambient",
                AmbientCameraFeedConsumer(ambient_runtime.engine),
                max_queue=256,
            )
        ingestion = CameraIngestionCoordinator(
            source=source,
            pipeline=pipeline,
            vault=vault,
            publisher=publisher,
            privacy_policy=privacy,
            cursor_path=runtime_root / "source-cursor.json",
            describe_selector=(
                lambda _event: _boolean(
                    _setting(orch, "camera.vlm_describe_events", False),
                    field_name="camera VLM describe events",
                )
            ),
        )
        ingestion_service = CameraIngestionService(
            coordinator=ingestion,
            retention_scheduler=scheduler,
            poll_interval=_number(
                _setting(orch, "camera.poll_interval_seconds", 5.0),
                field_name="camera poll interval",
            ),
            poll_limit=_integer(
                _setting(orch, "camera.poll_limit", 100),
                field_name="camera poll limit",
                minimum=1,
            ),
        )
        lifecycle["service"] = ingestion_service
        discovery = OnvifDiscoveryService(
            config=OnvifDiscoveryConfig(
                enabled=_boolean(
                    _setting(orch, "camera.onvif_enabled", False),
                    field_name="ONVIF enabled",
                ),
                mappings=_onvif_mappings(orch),
            ),
            admin_gate=lambda: True,
            discoverer=discoverer,
            resolver=resolver,
        )
        return CameraRuntime(
            enabled=True,
            status="ready",
            reason=None,
            retrieval=retrieval,
            health=health,
            discovery=discovery,
            source=source,
            pipeline=pipeline,
            privacy_policy=privacy,
            vault=vault,
            scheduler=scheduler,
            feed_publisher=publisher,
            ingestion=ingestion,
            ingestion_service=ingestion_service,
            house_feed=house_feed,
            ambient_runtime=ambient_runtime,
            orch_id=id(orch) if orch is not None else 0,
        )
    except Exception:
        if publisher is not None:
            publisher.close()
        if ambient_runtime is not None:
            ambient_runtime.close()
        return _disabled("camera_runtime_unavailable", orch)


__all__ = ["CameraRuntime", "build_camera_runtime"]
