"""H33.1 durable registry, monitor evaluation, and bounded queues."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from agents.core.ambient.contracts import (
    AmbientEvent,
    EventProvenance,
    MonitorDefinition,
    MonitorPredicate,
)
from agents.core.ambient.engine import AmbientEngine
from agents.core.ambient.registry import MonitorRegistry
from agents.core.ambient.runtime import build_ambient_runtime
from agents.core.ambient.store import AmbientStore


def _event(event_id: str, value: float, observed_at: float, *, critical: bool = False) -> AmbientEvent:
    return AmbientEvent(
        source="digital",
        schema="resource.v1",
        source_event_id=event_id,
        subject_id="resource.cpu",
        occurred_at=observed_at - 1,
        observed_at=observed_at,
        dedupe_key=f"resource:cpu:{event_id}",
        provenance=EventProvenance(adapter="observer.resource", version=1),
        attributes=(("value", value), ("healthy", value < 95)),
        privacy="public",
        consent_generation=0,
        critical=critical,
    )


def _definition(**overrides) -> MonitorDefinition:
    values = {
        "monitor_id": "monitor.cpu",
        "version": 1,
        "source": "digital",
        "schema": "resource.v1",
        "predicates": (MonitorPredicate("attributes.value", "gte", 95.0),),
        "clear_predicates": (MonitorPredicate("attributes.value", "lt", 85.0),),
        "debounce_seconds": 0,
        "hold_seconds": 0,
        "cooldown_seconds": 0,
    }
    values.update(overrides)
    return MonitorDefinition(**values)


def test_registry_restart_version_audit_and_delete(tmp_path):
    path = tmp_path / "ambient.db"
    store = AmbientStore(path, clock=lambda: 1_000.0)
    registry = MonitorRegistry(store, enabled=True)
    created = registry.create(_definition(), actor="owner")
    updated = registry.update(_definition(version=2), actor="owner")
    store.close()

    restarted_store = AmbientStore(path, clock=lambda: 1_001.0)
    restarted = MonitorRegistry(restarted_store, enabled=True)
    assert created["status"] == "created"
    assert updated["status"] == "updated"
    assert restarted.get("monitor.cpu").version == 2
    assert [row["operation"] for row in restarted_store.audit()] == ["create", "update"]
    assert restarted.delete("monitor.cpu", actor="owner")["status"] == "deleted"
    restarted_store.close()


def test_store_corruption_degrades_without_recreating_safety_database(tmp_path):
    path = tmp_path / "ambient.db"
    original = b"not-a-sqlite-safety-database"
    path.write_bytes(original)
    store = AmbientStore(path)
    assert store.health()["status"] == "degraded"
    assert store.health()["reason"] == "store_corrupt"
    assert path.read_bytes() == original
    assert MonitorRegistry(store, enabled=True).list() == ()
    store.close()


def test_engine_default_off_and_transition_debounce_are_restart_durable(tmp_path):
    path = tmp_path / "ambient.db"
    store = AmbientStore(path, clock=lambda: 1_000.0)
    registry = MonitorRegistry(store, enabled=True)
    registry.create(_definition(), actor="owner")
    disabled = AmbientEngine(store=store, registry=registry, enabled=False)
    assert disabled.submit(_event("one", 99, 1_000))["status"] == "disabled"
    assert disabled.process_tick() == []

    engine = AmbientEngine(store=store, registry=registry, enabled=True)
    assert engine.submit(_event("one", 99, 1_000))["status"] == "queued"
    first = engine.process_tick()
    assert [(item.transition, item.matched) for item in first] == [("alert", True)]
    assert engine.submit(_event("one", 99, 1_000))["status"] == "duplicate"
    assert engine.process_tick() == []
    engine.submit(_event("two", 98, 1_001))
    assert engine.process_tick() == []
    engine.submit(_event("three", 80, 1_002))
    assert [(item.transition, item.matched) for item in engine.process_tick()] == [("recovery", False)]
    store.close()

    restarted_store = AmbientStore(path, clock=lambda: 1_003.0)
    restarted_registry = MonitorRegistry(restarted_store, enabled=True)
    restarted_engine = AmbientEngine(store=restarted_store, registry=restarted_registry, enabled=True)
    restarted_engine.submit(_event("four", 99, 1_003))
    assert [item.transition for item in restarted_engine.process_tick()] == ["alert"]
    assert len(restarted_store.journal()) == 3
    restarted_store.close()


def test_hold_hysteresis_and_cooldown(tmp_path):
    store = AmbientStore(tmp_path / "ambient.db", clock=lambda: 1_000.0)
    registry = MonitorRegistry(store, enabled=True)
    registry.create(
        _definition(hold_seconds=10, debounce_seconds=5, cooldown_seconds=30),
        actor="owner",
    )
    engine = AmbientEngine(store=store, registry=registry, enabled=True)

    engine.submit(_event("one", 96, 1_000))
    assert engine.process_tick() == []
    engine.submit(_event("two", 96, 1_009))
    assert engine.process_tick() == []
    engine.submit(_event("three", 96, 1_010))
    assert [item.transition for item in engine.process_tick()] == ["alert"]
    engine.submit(_event("four", 90, 1_011))
    assert engine.process_tick() == []
    engine.submit(_event("five", 80, 1_012))
    assert [item.transition for item in engine.process_tick()] == ["recovery"]
    engine.submit(_event("six", 99, 1_020))
    assert engine.process_tick() == []
    engine.submit(_event("seven", 99, 1_040))
    assert [item.transition for item in engine.process_tick()] == ["alert"]
    store.close()


def test_bounded_queue_coalesces_and_durably_backpressures_critical_transition(tmp_path):
    store = AmbientStore(tmp_path / "ambient.db", clock=lambda: 1_000.0)
    registry = MonitorRegistry(store, enabled=True)
    registry.create(_definition(), actor="owner")
    engine = AmbientEngine(
        store=store,
        registry=registry,
        enabled=True,
        per_source_queue=1,
        global_queue=1,
        work_per_tick=1,
    )
    assert engine.submit(_event("one", 80, 1_000))["status"] == "queued"
    assert engine.submit(_event("two", 99, 1_001, critical=True))["status"] == "backpressured"
    assert store.pending_count() == 1
    engine.process_tick()
    decisions = engine.process_tick()
    assert [item.transition for item in decisions] == ["alert"]
    assert store.pending_count() == 0
    health = engine.health()
    assert health["sources"]["digital"]["critical_backpressure"] == 1
    assert health["queue_depth"] <= 1
    store.close()


def test_source_health_and_journal_never_store_event_attributes(tmp_path):
    store = AmbientStore(tmp_path / "ambient.db", clock=lambda: 1_000.0)
    registry = MonitorRegistry(store, enabled=True)
    registry.create(_definition(), actor="owner")
    engine = AmbientEngine(store=store, registry=registry, enabled=True)
    engine.submit(_event("private-source", 99, 1_000))
    engine.process_tick()
    serialized = json.dumps(store.journal()).lower()
    assert "resource.cpu" not in serialized
    assert "99" not in serialized
    assert "attributes" not in serialized
    assert engine.health()["sources"]["digital"]["status"] == "live"
    store.close()


def test_consent_purge_removes_derived_state_and_tombstones_replay(tmp_path):
    store = AmbientStore(tmp_path / "ambient.db", clock=lambda: 1_000.0)
    registry = MonitorRegistry(store, enabled=True)
    registry.create(_definition(), actor="owner")
    engine = AmbientEngine(store=store, registry=registry, enabled=True)
    event = _event("camera-consent-1", 99, 1_000, critical=True)
    engine.submit(event)
    engine.process_tick()
    assert store.journal() and store.monitor_state("monitor.cpu")["matched"] is True

    purged = store.purge_source("digital")
    assert purged["decisions"] == 1
    assert purged["states"] == 1
    assert purged["tombstones"] == 1
    assert store.journal() == []
    assert store.claim_event(event) is False
    store.close()


class _Orch:
    def __init__(self, values):
        self.values = values

    def get_setting(self, name, default=None):
        return self.values.get(name, default)


def test_ambient_runtime_is_default_off_without_touching_storage(tmp_path):
    root = tmp_path / "ambient"
    runtime = build_ambient_runtime(_Orch({}), root=root)
    assert runtime.enabled is False
    assert runtime.status == "disabled"
    assert runtime.reason == "ambient_disabled"
    assert not root.exists()


def test_ambient_runtime_requires_explicit_boolean_opt_in_and_composes_engine(tmp_path):
    invalid = build_ambient_runtime(_Orch({"ambient.enabled": 1}), root=tmp_path / "invalid")
    assert invalid.status == "degraded"
    assert not (tmp_path / "invalid").exists()

    runtime = build_ambient_runtime(
        _Orch({"ambient.enabled": True, "ambient.generation": 3}),
        root=tmp_path / "ambient",
    )
    assert runtime.enabled is True
    assert runtime.status == "ready"
    assert runtime.generation == 3
    assert runtime.store is not None
    assert runtime.registry is not None
    assert runtime.engine is not None
    runtime.close()


def test_concurrent_duplicate_intake_admits_exactly_once(tmp_path):
    store = AmbientStore(tmp_path / "ambient.db", clock=lambda: 1_000.0)
    registry = MonitorRegistry(store, enabled=True)
    registry.create(_definition(), actor="owner")
    engine = AmbientEngine(store=store, registry=registry, enabled=True)
    event = _event("same-event", 99, 1_000)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: engine.submit(event), range(32)))
    assert [item["status"] for item in results].count("queued") == 1
    assert [item["status"] for item in results].count("duplicate") == 31
    assert len(engine.process_tick()) == 1
    store.close()
