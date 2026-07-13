"""H33.1 allowlisted H30/H31/digital adapters and source ownership."""

from __future__ import annotations

import json

import pytest

from agents.core.ambient.adapters import (
    LEGACY_SOURCE_OWNERSHIP,
    AmbientCameraFeedConsumer,
    SourceOwnershipManager,
    camera_feed_event,
    digital_signal_event,
    house_event,
)
from agents.core.ambient.contracts import MonitorDefinition, MonitorPredicate
from agents.core.ambient.engine import AmbientEngine
from agents.core.ambient.registry import MonitorRegistry
from agents.core.ambient.store import AmbientStore
from agents.core.autonomy.observer import Remediation, Severity, Signal
from agents.core.cameras.feeds import CameraFeedEvent
from agents.core.house.contracts import HouseEvent


def test_house_and_camera_adapters_are_metadata_only():
    house = house_event(
        HouseEvent(
            event_id="ha-event-1",
            source_event_id="ha-source-1",
            entity_id="binary_sensor.entry",
            event_type="state_changed",
            previous_state="off",
            current_state="on",
            occurred_at=1_000,
            observed_at=1_001,
            dedupe_key="ha:1",
        ),
        consent_generation=4,
    )
    camera = camera_feed_event(
        CameraFeedEvent(
            event_id="camera-event-1",
            camera_id="front-door",
            label="person",
            occurred_at=1_000,
            observed_at=1_001,
            confidence=0.9,
            consent_generation=7,
            dedupe_key="camera:front-door:camera-event-1",
            room_id="entry",
            zone="porch",
        )
    )
    encoded = json.dumps([house.to_dict(), camera.to_dict()]).lower()
    assert house.schema == "house.event.v1"
    assert camera.schema == "camera.event.v1"
    assert camera.attribute("anonymous") is True
    assert not any(term in encoded for term in ("frame", "snapshot", "clip", "description", "vault", "rtsp"))


def test_digital_signal_projection_drops_detail_host_and_remediation_payload():
    signal = Signal(
        key="service.backup",
        healthy=False,
        severity=Severity.CRITICAL,
        detail="backup failed on secret-host.example",
        value=1,
        remediation=Remediation(
            kind="restart_service",
            title="Restart secret service?",
            payload={"host": "secret-host.example", "cmd": "danger"},
        ),
    )
    event = digital_signal_event(signal, observed_at=1_000, sequence=3)
    encoded = json.dumps(event.to_dict()).lower()
    assert event.attributes == (("healthy", False), ("severity", "critical"), ("value", 1.0))
    assert not any(term in encoded for term in ("secret-host", "restart", "danger", "detail", "remediation"))


@pytest.mark.asyncio
async def test_real_camera_feed_consumer_drives_named_monitor(tmp_path):
    store = AmbientStore(tmp_path / "ambient.db", clock=lambda: 1_001.0)
    registry = MonitorRegistry(store, enabled=True)
    registry.create(
        MonitorDefinition(
            monitor_id="monitor.front-door",
            version=1,
            source="camera",
            schema="camera.event.v1",
            predicates=(MonitorPredicate("attributes.label", "eq", "person"),),
        ),
        actor="owner",
    )
    engine = AmbientEngine(store=store, registry=registry, enabled=True)
    consumer = AmbientCameraFeedConsumer(engine)
    await consumer.consume(
        CameraFeedEvent(
            event_id="camera-event-1",
            camera_id="front-door",
            label="person",
            occurred_at=1_000,
            observed_at=1_001,
            confidence=0.9,
            consent_generation=7,
            dedupe_key="camera:front-door:camera-event-1",
            room_id="entry",
            zone="porch",
        )
    )
    assert [row["transition"] for row in store.journal()] == ["alert"]
    store.close()


def test_source_ownership_cutover_is_atomic_and_rollback_preserves_watermark(tmp_path):
    store = AmbientStore(tmp_path / "ambient.db", clock=lambda: 1_000.0)
    manager = SourceOwnershipManager(store)
    calls: list[str] = []

    claimed = manager.claim(
        "digital.backups",
        watermark="cursor-42",
        health_check=lambda: True,
        disable_legacy=lambda: calls.append("disable"),
    )
    assert claimed["status"] == "claimed"
    assert calls == ["disable"]
    assert store.ownership("digital.backups")["watermark"] == "cursor-42"

    rolled_back = manager.rollback(
        "digital.backups",
        resume_legacy=lambda watermark: calls.append(f"resume:{watermark}"),
    )
    assert rolled_back["status"] == "legacy"
    assert calls[-1] == "resume:cursor-42"

    with pytest.raises(RuntimeError, match="health_check_failed"):
        manager.claim(
            "digital.calendar",
            watermark="cursor-1",
            health_check=lambda: False,
            disable_legacy=lambda: calls.append("must-not-disable"),
        )
    assert "must-not-disable" not in calls
    assert {row["legacy_owner"] for row in LEGACY_SOURCE_OWNERSHIP} == {
        "ProactiveObserver",
        "EventWatcher",
    }
    store.close()
