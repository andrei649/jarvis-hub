"""H31.6 — bounded, metadata-only camera feeds into H30 and H33."""

from __future__ import annotations

import asyncio
import json

import pytest

from agents.core.cameras.feeds import (
    CameraFeedEvent,
    CameraFeedPublisher,
    CameraIngestionCoordinator,
    CameraIngestionService,
)
from agents.core.cameras.models import CameraConfig, CameraEvent, HouseholdConsent
from agents.core.cameras.pipeline import CameraPipelineResult
from agents.core.cameras.privacy import CameraPrivacyError, CameraPrivacyPolicy
from agents.core.cameras.source import CameraEventPage
from agents.core.cameras.vault import CameraStoreReceipt
from agents.core.house.camera_feed import HouseCameraFeedConsumer
from agents.core.house.contracts import HouseEvent


class _KillSwitch:
    def __init__(self) -> None:
        self.halted = False

    def is_halted(self, _scope: str) -> bool:
        return self.halted


def _policy() -> CameraPrivacyPolicy:
    return CameraPrivacyPolicy(
        configs=(CameraConfig(camera_id="front-door", name="Front door", enabled=True),),
        consent=HouseholdConsent(
            version=1,
            generation=7,
            granted=True,
            camera_ids=("front-door",),
            accepted_at=900.0,
        ),
        kill_switch=_KillSwitch(),
    )


def _event(event_id: str = "camera-event-1", *, label: str = "person") -> CameraEvent:
    return CameraEvent(
        event_id=event_id,
        camera_id="front-door",
        label=label,
        occurred_at=1_000.0,
        confidence=0.91,
        zone="porch",
        room_id="entry",
        description="An anonymous person left a package.",
        description_provenance="local_vlm_on_demand",
    )


def test_feed_projection_strips_descriptions_and_converts_to_anonymous_house_event():
    record = CameraFeedEvent.from_camera_event(
        _event(), observed_at=1_001.0, consent_generation=7
    )

    public = record.to_public()
    assert public == {
        "event_id": "camera-event-1",
        "camera_id": "front-door",
        "label": "person",
        "occurred_at": 1_000.0,
        "observed_at": 1_001.0,
        "confidence": 0.91,
        "anonymous": True,
        "zone": "porch",
        "room_id": "entry",
        "dedupe_key": "camera:front-door:camera-event-1",
    }
    assert not ({"description", "description_provenance", "snapshot", "bytes", "vault_id"} & public.keys())

    house_event = record.to_house_event()
    assert isinstance(house_event, HouseEvent)
    assert house_event.event_type == "camera_anonymous_occupancy"
    assert house_event.current_state == "occupied"
    assert house_event.entity_id == "camera.front-door"
    assert house_event.provenance == "camera.feed.metadata_only"
    assert house_event.privacy_class == "household"
    assert "person" not in json.dumps(house_event.to_dict()).lower()


@pytest.mark.asyncio
async def test_h30_consumer_updates_only_allowlisted_anonymous_sensor_state():
    consumer = HouseCameraFeedConsumer(max_events=4)
    person = CameraFeedEvent.from_camera_event(
        _event(), observed_at=1_001.0, consent_generation=7
    )
    package = CameraFeedEvent.from_camera_event(
        _event("camera-event-2", label="package"),
        observed_at=1_002.0,
        consent_generation=7,
    )

    await consumer.consume(person)
    await consumer.consume(package)
    await consumer.consume(package)

    snapshot = consumer.snapshot()
    assert snapshot["status"] == "live"
    assert snapshot["events"] == 2
    assert snapshot["duplicates"] == 1
    assert snapshot["sensors"] == [
        {
            "camera_id": "front-door",
            "state": "package",
            "room_id": "entry",
            "zone": "porch",
            "confidence": 0.91,
            "occurred_at": 1_000.0,
            "anonymous": True,
        }
    ]
    serialized = json.dumps(snapshot).lower()
    assert not any(term in serialized for term in ("description", "snapshot", "vault", "identity", "face"))


@pytest.mark.asyncio
async def test_publisher_is_restart_idempotent_per_sink(tmp_path):
    policy = _policy()
    ledger = tmp_path / "camera-feed.db"
    first_consumer = HouseCameraFeedConsumer()
    first = CameraFeedPublisher(
        privacy_policy=policy,
        ledger_path=ledger,
        clock=lambda: 1_001.0,
    )
    first.subscribe("house", first_consumer, max_queue=4)
    result = await first.publish(_event())
    first.close()

    assert result.status == "delivered"
    assert result.delivered == 1
    assert first_consumer.snapshot()["events"] == 1

    restarted_consumer = HouseCameraFeedConsumer()
    restarted = CameraFeedPublisher(
        privacy_policy=policy,
        ledger_path=ledger,
        clock=lambda: 1_002.0,
    )
    restarted.subscribe("house", restarted_consumer, max_queue=4)
    replay = await restarted.publish(_event())
    restarted.close()

    assert replay.status == "duplicate"
    assert replay.duplicates == 1
    assert restarted_consumer.snapshot()["events"] == 0


@pytest.mark.asyncio
async def test_broken_sink_isolated_from_healthy_sink(tmp_path):
    received: list[CameraFeedEvent] = []

    class _Broken:
        async def consume(self, _record: CameraFeedEvent) -> None:
            raise RuntimeError("sink offline with private detail")

    class _Healthy:
        async def consume(self, record: CameraFeedEvent) -> None:
            received.append(record)

    publisher = CameraFeedPublisher(
        privacy_policy=_policy(),
        ledger_path=tmp_path / "camera-feed.db",
        clock=lambda: 1_001.0,
        delivery_timeout=0.1,
    )
    publisher.subscribe("broken", _Broken(), max_queue=2)
    publisher.subscribe("healthy", _Healthy(), max_queue=2)

    result = await publisher.publish(_event())
    health = publisher.health()
    publisher.close()

    assert result.status == "degraded"
    assert result.delivered == 1 and result.failed == 1
    assert [item.event_id for item in received] == ["camera-event-1"]
    assert health["sinks"]["broken"]["failed"] == 1
    assert "private detail" not in json.dumps(health)


@pytest.mark.asyncio
async def test_per_sink_queue_is_bounded_without_blocking_other_sinks(tmp_path):
    started = asyncio.Event()
    release = asyncio.Event()
    fast: list[str] = []

    class _Slow:
        async def consume(self, _record: CameraFeedEvent) -> None:
            started.set()
            await release.wait()

    class _Fast:
        async def consume(self, record: CameraFeedEvent) -> None:
            fast.append(record.event_id)

    publisher = CameraFeedPublisher(
        privacy_policy=_policy(),
        ledger_path=tmp_path / "camera-feed.db",
        clock=lambda: 1_001.0,
        delivery_timeout=2.0,
    )
    publisher.subscribe("slow", _Slow(), max_queue=1)
    publisher.subscribe("fast", _Fast(), max_queue=8)

    first = asyncio.create_task(publisher.publish(_event("camera-event-1")))
    await started.wait()
    second = asyncio.create_task(publisher.publish(_event("camera-event-2")))
    await asyncio.sleep(0)
    third = asyncio.create_task(publisher.publish(_event("camera-event-3")))
    await asyncio.sleep(0)

    assert publisher.health()["sinks"]["slow"]["queued"] <= 1
    assert publisher.health()["sinks"]["slow"]["dropped"] == 1
    release.set()
    await asyncio.gather(first, second, third)
    publisher.close()

    assert fast == ["camera-event-1", "camera-event-2", "camera-event-3"]


@pytest.mark.asyncio
async def test_missing_sink_and_revoked_consent_fail_closed(tmp_path):
    policy = _policy()
    publisher = CameraFeedPublisher(
        privacy_policy=policy,
        ledger_path=tmp_path / "camera-feed.db",
        clock=lambda: 1_001.0,
    )
    missing = await publisher.publish(_event())
    assert missing.status == "degraded"
    assert missing.reason == "no_subscribers"

    policy.revoke("owner disabled cameras")
    consumer = HouseCameraFeedConsumer()
    publisher.subscribe("house", consumer)
    with pytest.raises(CameraPrivacyError, match="consent_required"):
        await publisher.publish(_event("camera-event-2"))
    assert consumer.snapshot()["events"] == 0
    publisher.close()


class _Source:
    def __init__(self, event: CameraEvent) -> None:
        self.event = event
        self.after: list[str | None] = []

    async def list_events(self, after: str | None, limit: int) -> CameraEventPage:
        self.after.append(after)
        if after == "cursor-1":
            return CameraEventPage(events=(), next_cursor="cursor-1")
        return CameraEventPage(events=(self.event,), next_cursor="cursor-1")


class _Pipeline:
    async def process(self, event: CameraEvent, *, describe: bool = False) -> CameraPipelineResult:
        return CameraPipelineResult(
            event=event,
            zones=tuple(value for value in (event.zone,) if value),
            line_crossings=(),
            status="metadata_only" if not describe else "described",
        )


class _Vault:
    def __init__(self) -> None:
        self.events: list[CameraEvent] = []

    def store(self, event: CameraEvent) -> CameraStoreReceipt:
        stored = not any(item.event_id == event.event_id for item in self.events)
        self.events.append(event)
        return CameraStoreReceipt(stored=stored, snapshot_stored=False)


class _FlakyVault(_Vault):
    def __init__(self) -> None:
        super().__init__()
        self.fail_once = True

    def store(self, event: CameraEvent) -> CameraStoreReceipt:
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("disk detail that must not escape")
        return super().store(event)


@pytest.mark.asyncio
async def test_ingestion_coordinator_runs_source_pipeline_vault_feed_and_persists_cursor(tmp_path):
    source = _Source(_event())
    vault = _Vault()
    policy = _policy()
    house = HouseCameraFeedConsumer()
    publisher = CameraFeedPublisher(
        privacy_policy=policy,
        ledger_path=tmp_path / "deliveries.db",
        clock=lambda: 1_001.0,
    )
    publisher.subscribe("house", house)
    cursor_path = tmp_path / "cursor.json"
    coordinator = CameraIngestionCoordinator(
        source=source,
        pipeline=_Pipeline(),
        vault=vault,
        publisher=publisher,
        privacy_policy=policy,
        cursor_path=cursor_path,
    )

    first = await coordinator.poll(limit=10)
    restarted = CameraIngestionCoordinator(
        source=source,
        pipeline=_Pipeline(),
        vault=vault,
        publisher=publisher,
        privacy_policy=policy,
        cursor_path=cursor_path,
    )
    second = await restarted.poll(limit=10)
    publisher.close()

    assert first.status == "ok"
    assert first.polled == first.processed == first.stored == 1
    assert first.delivered == 1 and first.cursor_advanced is True
    assert second.status == "idle" and second.polled == 0
    assert source.after == [None, "cursor-1"]
    assert house.snapshot()["events"] == 1
    assert cursor_path.read_text(encoding="utf-8").strip().startswith("{")


@pytest.mark.asyncio
async def test_ingestion_does_not_advance_cursor_while_any_sink_is_degraded(tmp_path):
    source = _Source(_event())
    vault = _Vault()
    policy = _policy()
    healthy = HouseCameraFeedConsumer()

    class _Broken:
        async def consume(self, _event: CameraFeedEvent) -> None:
            raise RuntimeError("offline")

    publisher = CameraFeedPublisher(
        privacy_policy=policy,
        ledger_path=tmp_path / "deliveries.db",
        clock=lambda: 1_001.0,
    )
    publisher.subscribe("healthy", healthy)
    publisher.subscribe("broken", _Broken())
    coordinator = CameraIngestionCoordinator(
        source=source,
        pipeline=_Pipeline(),
        vault=vault,
        publisher=publisher,
        privacy_policy=policy,
        cursor_path=tmp_path / "cursor.json",
    )

    first = await coordinator.poll()
    second = await coordinator.poll()
    health = coordinator.health()
    publisher.close()

    assert first.status == second.status == "degraded"
    assert first.cursor_advanced is second.cursor_advanced is False
    assert source.after == [None, None]
    assert healthy.snapshot()["events"] == 1
    assert health["last_error"] == "feed_delivery_degraded"
    assert "offline" not in json.dumps(health)


@pytest.mark.asyncio
async def test_ingestion_retries_store_without_reprocessing_rule_duplicate(tmp_path):
    source = _Source(_event())
    vault = _FlakyVault()
    policy = _policy()
    house = HouseCameraFeedConsumer()
    publisher = CameraFeedPublisher(
        privacy_policy=policy,
        ledger_path=tmp_path / "deliveries.db",
        clock=lambda: 1_001.0,
    )
    publisher.subscribe("house", house)
    coordinator = CameraIngestionCoordinator(
        source=source,
        pipeline=_Pipeline(),
        vault=vault,
        publisher=publisher,
        privacy_policy=policy,
        cursor_path=tmp_path / "cursor.json",
    )

    failed = await coordinator.poll()
    retried = await coordinator.poll()
    publisher.close()

    assert failed.status == "degraded"
    assert failed.reason == "event_store_failed"
    assert failed.cursor_advanced is False
    assert retried.status == "ok" and retried.stored == 1 and retried.delivered == 1
    assert source.after == [None, None]
    assert house.snapshot()["events"] == 1
    assert "disk detail" not in json.dumps(coordinator.health())


@pytest.mark.asyncio
async def test_ingestion_service_is_explicitly_started_and_stops_cleanly(tmp_path):
    source = _Source(_event())
    vault = _Vault()
    policy = _policy()
    house = HouseCameraFeedConsumer()
    publisher = CameraFeedPublisher(
        privacy_policy=policy,
        ledger_path=tmp_path / "deliveries.db",
        clock=lambda: 1_001.0,
    )
    publisher.subscribe("house", house)
    coordinator = CameraIngestionCoordinator(
        source=source,
        pipeline=_Pipeline(),
        vault=vault,
        publisher=publisher,
        privacy_policy=policy,
        cursor_path=tmp_path / "cursor.json",
    )
    service = CameraIngestionService(coordinator=coordinator, poll_interval=0.01)

    assert service.health()["running"] is False
    assert service.start() is True
    assert service.start() is False
    for _ in range(50):
        if house.snapshot()["events"]:
            break
        await asyncio.sleep(0.01)
    await service.stop()
    publisher.close()

    assert house.snapshot()["events"] == 1
    assert service.health()["running"] is False
    assert service.health()["status"] == "stopped"
