from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agents.core.ambient.adapters import AmbientCameraFeedConsumer
from agents.core.ambient.contracts import (
    AmbientDecision,
    AmbientEvent,
    EventProvenance,
    MonitorDefinition,
    MonitorPredicate,
)
from agents.core.ambient.memory import AmbientSituationMemory
from agents.core.ambient.runtime import build_ambient_runtime
from agents.core.cameras.feeds import CameraFeedEvent
from agents.core.memory.bitemporal import BiTemporalKG
from agents.core.memory.decay import DecayMemory


def _definition(source="camera"):
    schema = "camera.event.v1" if source == "camera" else "digital.signal.v1"
    return MonitorDefinition(
        monitor_id=f"monitor.{source}.situation",
        version=1,
        source=source,
        schema=schema,
        predicates=(MonitorPredicate("source", "eq", source),),
        alert_rung="remember",
    )


def _decision(event, source="camera"):
    definition = _definition(source)
    return AmbientDecision(
        decision_id=f"decision-{event.source_event_id}",
        monitor_id=definition.monitor_id,
        monitor_version=1,
        monitor_hash=definition.definition_hash,
        event_fingerprint=event.fingerprint,
        transition="alert",
        matched=True,
        reason="predicate_matched",
        decided_at=event.observed_at,
        consent_generation=event.consent_generation,
        rung="remember",
        attention_mode="none",
    )


def _camera(event_id, observed_at, *, consent=3):
    return AmbientEvent(
        source="camera",
        schema="camera.event.v1",
        source_event_id=event_id,
        subject_id="camera.private-front-door",
        occurred_at=observed_at - 2,
        observed_at=observed_at,
        dedupe_key=f"camera:{event_id}",
        provenance=EventProvenance(adapter="camera.feed", version=1),
        attributes=(
            ("anonymous", True),
            ("camera_id", "private-front-door"),
            ("confidence", 0.91),
            ("label", "person"),
        ),
        privacy="household",
        consent_generation=consent,
    )


def _digital(event_id, observed_at, severity="warning"):
    return AmbientEvent(
        source="digital",
        schema="digital.signal.v1",
        source_event_id=event_id,
        subject_id="service.private-hostname",
        occurred_at=observed_at - 1,
        observed_at=observed_at,
        dedupe_key=f"digital:{event_id}",
        provenance=EventProvenance(adapter="observer.signal", version=1),
        attributes=(("healthy", False), ("severity", severity)),
        privacy="public",
        consent_generation=0,
    )


def _memory(tmp_path):
    return AmbientSituationMemory(
        tmp_path / "situations.db",
        decay=DecayMemory(tmp_path / "decay.json"),
        kg=BiTemporalKG(tmp_path / "kg.json"),
        clock=lambda: 2_000,
    )


def test_repeated_camera_observations_are_anonymous_not_reidentification(tmp_path):
    memory = _memory(tmp_path)
    first = _camera("private-event-one", 1_000)
    second = _camera("private-event-two", 1_010)

    memory.remember(_decision(first), first, _definition())
    memory.remember(_decision(second), second, _definition())
    repeated = memory.repeated_observations(second)

    assert repeated == {
        "kind": "anonymous_person_observation",
        "count": 2,
        "first_observed_at": 1_000.0,
        "last_observed_at": 1_010.0,
        "same_individual": False,
        "interpretation": "repeated anonymous observations in one privacy-safe scope",
    }
    encoded = (tmp_path / "situations.db").read_bytes().lower()
    assert b"private-front-door" not in encoded
    assert b"private-event-one" not in encoded
    assert b"camera.private" not in encoded
    memory.close()


def test_situation_memory_preserves_valid_observed_provenance_and_restart(tmp_path):
    memory = _memory(tmp_path)
    event = _digital("private-digital-event", 1_100)
    result = memory.remember(_decision(event, "digital"), event, _definition("digital"))
    memory.close()

    restarted = _memory(tmp_path)
    [row] = restarted.list_situations()

    assert result["status"] == "remembered"
    assert row["kind"] == "digital_signal_warning"
    assert row["first_valid_at"] == 1_099.0
    assert row["last_observed_at"] == 1_100.0
    assert row["provenance"] == {"adapter": "observer.signal", "version": 1}
    assert row["count"] == 1
    serialized = json.dumps(row)
    assert "private-hostname" not in serialized
    assert "private-digital-event" not in serialized
    restarted.close()


def test_digital_situations_project_bitemporal_fact_and_contradict(tmp_path):
    kg = BiTemporalKG(tmp_path / "kg.json")
    memory = AmbientSituationMemory(
        tmp_path / "situations.db",
        decay=DecayMemory(tmp_path / "decay.json"),
        kg=kg,
        clock=lambda: 2_000,
    )
    warning = _digital("warn", 1_100, "warning")
    critical = _digital("critical", 1_200, "critical")

    memory.remember(_decision(warning, "digital"), warning, _definition("digital"))
    memory.remember(_decision(critical, "digital"), critical, _definition("digital"))

    rows = memory.list_situations(include_contradicted=True)
    assert [(row["kind"], row["contradicted"]) for row in rows] == [
        ("digital_signal_warning", True),
        ("digital_signal_critical", False),
    ]
    facts = kg.known_as_of(1_200)
    assert {fact["object"] for fact in facts} == {
        "digital_signal_warning",
        "digital_signal_critical",
    }
    assert all(fact["valid_from"] in {1_099.0, 1_199.0} for fact in facts)
    memory.close()


def test_private_house_fact_stays_with_owner_store(tmp_path):
    delegated = []
    memory = AmbientSituationMemory(
        tmp_path / "situations.db",
        decay=DecayMemory(tmp_path / "decay.json"),
        kg=BiTemporalKG(tmp_path / "kg.json"),
        private_house_sink=lambda event: delegated.append(event.fingerprint),
    )
    event = AmbientEvent(
        source="house",
        schema="house.event.v1",
        source_event_id="private-house-event",
        subject_id="person.private-name",
        occurred_at=1_000,
        observed_at=1_001,
        dedupe_key="house:private",
        provenance=EventProvenance(adapter="house.event", version=1),
        attributes=(("current_state", "home"), ("event_type", "presence")),
        privacy="private",
        consent_generation=8,
    )
    definition = MonitorDefinition(
        monitor_id="monitor.house.private",
        version=1,
        source="house",
        schema="house.event.v1",
        predicates=(MonitorPredicate("source", "eq", "house"),),
        alert_rung="remember",
    )
    decision = AmbientDecision(
        decision_id="decision-house",
        monitor_id=definition.monitor_id,
        monitor_version=1,
        monitor_hash=definition.definition_hash,
        event_fingerprint=event.fingerprint,
        transition="alert",
        matched=True,
        reason="predicate_matched",
        decided_at=1_001,
        consent_generation=8,
        rung="remember",
        attention_mode="none",
    )

    assert memory.remember(decision, event, definition) == {
        "status": "delegated",
        "reason": "private_house_owner_store",
    }
    assert delegated == [event.fingerprint]
    assert memory.list_situations() == []
    assert b"private-name" not in (tmp_path / "situations.db").read_bytes().lower()
    memory.close()


def test_consent_purge_forgets_decay_invalidates_kg_and_blocks_replay(tmp_path):
    decay = DecayMemory(tmp_path / "decay.json")
    kg = BiTemporalKG(tmp_path / "kg.json")
    memory = AmbientSituationMemory(
        tmp_path / "situations.db", decay=decay, kg=kg, clock=lambda: 2_000
    )
    event = _digital("to-purge", 1_100)
    decision = _decision(event, "digital")
    definition = _definition("digital")
    memory.remember(decision, event, definition)

    purged = memory.purge(source="digital", consent_generation=0, purged_at=1_500)

    assert purged["situations"] == 1
    assert memory.list_situations() == []
    assert decay.ranking(now=1_501) == []
    assert kg.as_of(1_600) == []
    assert memory.remember(decision, event, definition) == {
        "status": "duplicate",
        "reason": "consent_replay_tombstone",
    }
    memory.close()


def test_real_h31_camera_feed_reaches_runtime_situation_memory(tmp_path):
    class Orch:
        autonomy = SimpleNamespace(govern_enqueue=lambda *args, **kwargs: 1)

        @staticmethod
        def get_setting(name, default=None):
            return {
                "ambient.enabled": True,
                "ambient.generation": 5,
                "general.timezone": "Europe/Bucharest",
            }.get(name, default)

    runtime = build_ambient_runtime(Orch(), root=tmp_path / "ambient")
    runtime.registry.create(
        MonitorDefinition(
            monitor_id="monitor.camera.remember",
            version=1,
            source="camera",
            schema="camera.event.v1",
            predicates=(MonitorPredicate("attributes.label", "eq", "person"),),
            alert_rung="remember",
        ),
        actor="owner",
    )
    consumer = AmbientCameraFeedConsumer(runtime.engine)
    event = CameraFeedEvent(
        event_id="camera-event-runtime",
        camera_id="front-door",
        label="person",
        occurred_at=1_000,
        observed_at=1_001,
        confidence=0.9,
        consent_generation=7,
        dedupe_key="camera:front-door:camera-event-runtime",
        room_id="entry",
        zone="porch",
    )

    asyncio.run(consumer.consume(event))

    situations = runtime.memory.list_situations()
    assert [(item["kind"], item["count"]) for item in situations] == [
        ("anonymous_person_observation", 1)
    ]
    runtime.close()
