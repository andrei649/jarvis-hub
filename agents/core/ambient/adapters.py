"""Allowlisted H30, H31, and legacy digital projections into AmbientEvent."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from agents.core.autonomy.observer import Signal
from agents.core.cameras.feeds import CameraFeedEvent
from agents.core.house.contracts import HouseEvent

from .contracts import AmbientEvent, EventProvenance
from .engine import AmbientEngine
from .store import AmbientStore

LEGACY_SOURCE_OWNERSHIP = (
    {"source": "digital.resources", "legacy_owner": "ProactiveObserver", "ambient_adapter": "observer.resource"},
    {"source": "digital.services", "legacy_owner": "ProactiveObserver", "ambient_adapter": "observer.service"},
    {"source": "digital.email", "legacy_owner": "EventWatcher", "ambient_adapter": "watcher.email"},
    {"source": "digital.calendar", "legacy_owner": "EventWatcher", "ambient_adapter": "watcher.calendar"},
    {"source": "digital.finance", "legacy_owner": "EventWatcher", "ambient_adapter": "watcher.finance"},
    {"source": "digital.health", "legacy_owner": "EventWatcher", "ambient_adapter": "watcher.health"},
    {"source": "digital.worldview", "legacy_owner": "EventWatcher", "ambient_adapter": "watcher.worldview"},
)


def house_event(event: HouseEvent, *, consent_generation: int) -> AmbientEvent:
    if not isinstance(event, HouseEvent):
        raise ValueError("ambient house adapter requires HouseEvent")
    return AmbientEvent(
        source="house",
        schema="house.event.v1",
        source_event_id=event.source_event_id,
        subject_id=event.entity_id,
        occurred_at=event.occurred_at,
        observed_at=event.observed_at,
        dedupe_key=event.dedupe_key,
        provenance=EventProvenance(adapter="house.event", version=1),
        attributes=(
            ("event_type", event.event_type),
            ("previous_state", event.previous_state),
            ("current_state", event.current_state),
        ),
        privacy=event.privacy_class,
        consent_generation=consent_generation,
    )


def camera_feed_event(event: CameraFeedEvent) -> AmbientEvent:
    if not isinstance(event, CameraFeedEvent):
        raise ValueError("ambient camera adapter requires CameraFeedEvent")
    return AmbientEvent(
        source="camera",
        schema="camera.event.v1",
        source_event_id=event.event_id,
        subject_id=f"camera.{event.camera_id}",
        occurred_at=event.occurred_at,
        observed_at=event.observed_at,
        dedupe_key=event.dedupe_key,
        provenance=EventProvenance(adapter="camera.feed", version=1),
        attributes=(
            ("anonymous", True),
            ("camera_id", event.camera_id),
            ("confidence", event.confidence),
            ("label", event.label),
        ),
        privacy="household",
        consent_generation=event.consent_generation,
        critical=False,
    )


def digital_signal_event(signal: Signal, *, observed_at: float, sequence: int) -> AmbientEvent:
    if not isinstance(signal, Signal):
        raise ValueError("ambient digital adapter requires Signal")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise ValueError("ambient digital sequence must be non-negative")
    severity = str(signal.severity.name).lower()
    stable = f"{signal.key}:{int(signal.healthy)}:{sequence}"
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:32]
    attributes: list[tuple[str, object]] = [
        ("healthy", bool(signal.healthy)),
        ("severity", severity),
    ]
    if signal.value is not None:
        attributes.append(("value", float(signal.value)))
    return AmbientEvent(
        source="digital",
        schema="digital.signal.v1",
        source_event_id=f"signal-{digest}",
        subject_id=signal.key,
        occurred_at=observed_at,
        observed_at=observed_at,
        dedupe_key=f"digital:{digest}",
        provenance=EventProvenance(adapter="observer.signal", version=1),
        attributes=tuple(attributes),
        privacy="public",
        consent_generation=0,
        critical=severity == "critical" and not signal.healthy,
    )


class AmbientCameraFeedConsumer:
    """Real H31 subscriber; every consume runs one bounded ambient tick."""

    def __init__(self, engine: AmbientEngine) -> None:
        if not isinstance(engine, AmbientEngine):
            raise ValueError("ambient engine is required")
        self._engine = engine

    async def consume(self, event: CameraFeedEvent) -> None:
        projected = camera_feed_event(event)
        result = self._engine.submit(projected)
        if result["status"] not in {"queued", "backpressured", "duplicate"}:
            raise RuntimeError(str(result.get("reason") or "ambient_intake_failed"))
        self._engine.process_tick()


class SourceOwnershipManager:
    """Two-phase ownership cutover with the legacy watermark preserved for rollback."""

    def __init__(self, store: AmbientStore) -> None:
        if not isinstance(store, AmbientStore):
            raise ValueError("ambient store is required")
        self._store = store

    def claim(
        self,
        source: str,
        *,
        watermark: str,
        health_check: Callable[[], bool],
        disable_legacy: Callable[[], None],
    ) -> dict[str, object]:
        if not callable(health_check) or not callable(disable_legacy):
            raise ValueError("source ownership callbacks are required")
        if not health_check():
            raise RuntimeError("health_check_failed")
        self._store.set_ownership(
            source,
            state="claiming",
            watermark=watermark,
            owner="legacy",
        )
        try:
            disable_legacy()
        except Exception as exc:
            self._store.set_ownership(
                source,
                state="legacy",
                watermark=watermark,
                owner="legacy",
            )
            raise RuntimeError("legacy_disable_failed") from exc
        self._store.set_ownership(
            source,
            state="ambient",
            watermark=watermark,
            owner="ambient",
        )
        return {"status": "claimed", "source": source, "watermark": watermark}

    def rollback(
        self,
        source: str,
        *,
        resume_legacy: Callable[[str], None],
    ) -> dict[str, object]:
        if not callable(resume_legacy):
            raise ValueError("legacy resume callback is required")
        current = self._store.ownership(source)
        watermark = str(current.get("watermark", ""))
        resume_legacy(watermark)
        self._store.set_ownership(
            source,
            state="legacy",
            watermark=watermark,
            owner="legacy",
        )
        return {"status": "legacy", "source": source, "watermark": watermark}


__all__ = [
    "AmbientCameraFeedConsumer",
    "LEGACY_SOURCE_OWNERSHIP",
    "SourceOwnershipManager",
    "camera_feed_event",
    "digital_signal_event",
    "house_event",
]
