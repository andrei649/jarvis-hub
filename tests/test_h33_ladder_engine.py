from __future__ import annotations

import json

from agents.core.ambient.contracts import (
    AmbientEvent,
    EventProvenance,
    MonitorDefinition,
    MonitorPredicate,
)
from agents.core.ambient.engine import AmbientEngine
from agents.core.ambient.proposals import AmbientProposalSink
from agents.core.ambient.registry import MonitorRegistry
from agents.core.ambient.store import AmbientStore
from agents.core.security import taint


def _event(event_id: str, *, tainted: bool = False, confidence: float = 1.0):
    return AmbientEvent(
        source="camera",
        schema="camera.event.v1",
        source_event_id=event_id,
        subject_id="camera.front",
        occurred_at=1_000,
        observed_at=1_001,
        dedupe_key=f"camera:{event_id}",
        provenance=EventProvenance(adapter="camera.feed", version=1),
        attributes=(
            ("anonymous", True),
            ("confidence", confidence),
            ("label", "person"),
        ),
        consent_generation=4,
        tainted=tainted,
    )


def _definition(**overrides):
    values = {
        "monitor_id": "monitor.front.person",
        "version": 1,
        "source": "camera",
        "schema": "camera.event.v1",
        "predicates": (MonitorPredicate("attributes.label", "eq", "person"),),
        "alert_rung": "interrupt",
        "recovery_rung": "monitor",
    }
    values.update(overrides)
    return MonitorDefinition(**values)


def test_engine_applies_ladder_downgrade_and_persists_explanation(tmp_path):
    store = AmbientStore(tmp_path / "ambient.db", clock=lambda: 1_001)
    registry = MonitorRegistry(store, enabled=True)
    registry.create(_definition(), actor="owner")
    engine = AmbientEngine(store=store, registry=registry, enabled=True)

    engine.submit(_event("tainted", tainted=True))
    [decision] = engine.process_tick()

    assert decision.rung == "ask"
    assert decision.attention_mode == "digest"
    assert decision.policy_reason == "tainted_downgrade"
    [journal] = store.journal()
    assert journal["rung"] == "ask"
    assert journal["attention_mode"] == "digest"
    assert "camera.front" not in json.dumps(journal)


def test_engine_quiet_hours_downgrade_but_critical_can_interrupt(tmp_path):
    store = AmbientStore(tmp_path / "ambient.db", clock=lambda: 1_001)
    registry = MonitorRegistry(store, enabled=True)
    registry.create(_definition(), actor="owner")
    engine = AmbientEngine(
        store=store,
        registry=registry,
        enabled=True,
        quiet_hours=lambda _timestamp: True,
    )
    engine.submit(_event("quiet"))
    assert engine.process_tick()[0].rung == "ask"

    registry.update(_definition(version=2), actor="owner")
    critical = _event("critical")
    critical = AmbientEvent.from_dict({**critical.to_dict(), "critical": True})
    engine.submit(critical)
    assert engine.process_tick()[0].rung == "interrupt"


def test_proposal_sink_queues_only_sanitized_governed_task(tmp_path):
    calls = []

    def govern_enqueue(*args, **kwargs):
        calls.append((args, kwargs))
        return 73

    sink = AmbientProposalSink(govern_enqueue, generation_provider=lambda: 9)
    store = AmbientStore(tmp_path / "ambient.db", clock=lambda: 1_001)
    registry = MonitorRegistry(store, enabled=True)
    definition = _definition(alert_rung="ask")
    registry.create(definition, actor="owner")
    engine = AmbientEngine(
        store=store,
        registry=registry,
        enabled=True,
        decision_sink=sink,
    )

    event = _event("private-event", tainted=True)
    engine.submit(event)
    [decision] = engine.process_tick()

    assert decision.rung == "ask"
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:3] == ("jarvis", "ambient.decision", "Ambient decision: monitor.front.person")
    assert kwargs["attention_mode"] == "digest"
    assert kwargs["autonomy_level"] == "ask"
    payload = kwargs["payload"]
    assert payload["ambient_generation"] == 9
    assert payload["consent_generation"] == 4
    assert payload["event_fingerprint"] == event.fingerprint
    assert payload["monitor_hash"] == definition.definition_hash
    assert payload["monitor_id"] == "monitor.front.person"
    assert payload["monitor_version"] == 1
    assert payload["rung"] == "ask"
    assert payload["source"] == "camera"
    assert taint.is_tainted(payload) is True
    assert payload["taint_source"] == "ambient:camera"
    encoded = json.dumps(payload)
    assert "camera.front" not in encoded
    assert "private-event" not in encoded

    # A trusted event through the same rebuild path stays trusted. This guards
    # against turning taint propagation into indiscriminate over-tainting.
    sink(decision, _event("trusted-event", tainted=False), definition)
    assert len(calls) == 2
    assert taint.is_tainted(calls[1][1]["payload"]) is False


def test_ignore_monitor_and_remember_do_not_create_unsolicited_delivery(tmp_path):
    queued = []
    remembered = []
    sink = AmbientProposalSink(
        lambda *args, **kwargs: queued.append((args, kwargs)),
        generation_provider=lambda: 2,
        remember_sink=lambda decision, _event, _definition: remembered.append(decision.rung),
    )
    for index, rung in enumerate(("ignore", "monitor", "remember"), start=1):
        store = AmbientStore(tmp_path / f"ambient-{index}.db", clock=lambda: 1_001)
        registry = MonitorRegistry(store, enabled=True)
        registry.create(_definition(alert_rung=rung), actor="owner")
        engine = AmbientEngine(
            store=store, registry=registry, enabled=True, decision_sink=sink
        )
        engine.submit(_event(f"event-{index}"))
        assert engine.process_tick()[0].rung == rung
        store.close()

    assert queued == []
    assert remembered == ["remember"]


def test_silent_action_without_static_proof_downgrades_to_ask(tmp_path):
    store = AmbientStore(tmp_path / "ambient.db", clock=lambda: 1_001)
    registry = MonitorRegistry(store, enabled=True)
    registry.create(_definition(alert_rung="act_silently"), actor="owner")
    engine = AmbientEngine(store=store, registry=registry, enabled=True)

    engine.submit(_event("silent"))
    [decision] = engine.process_tick()

    assert decision.rung == "ask"
    assert decision.policy_reason == "silent_proof_missing"
