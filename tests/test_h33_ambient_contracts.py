"""H33.1 bounded declarative monitor contracts."""

from __future__ import annotations

import json

import pytest

from agents.core.ambient.contracts import (
    AmbientDecision,
    AmbientEvent,
    EventProvenance,
    MonitorDefinition,
    MonitorPredicate,
)


def _event(**overrides) -> AmbientEvent:
    values = {
        "source": "digital",
        "schema": "resource.v1",
        "source_event_id": "resource-cpu-1",
        "subject_id": "resource.cpu",
        "occurred_at": 1_000.0,
        "observed_at": 1_001.0,
        "dedupe_key": "resource:cpu:1000",
        "provenance": EventProvenance(adapter="observer.resource", version=1),
        "attributes": (("healthy", False), ("severity", "critical"), ("value", 97.5)),
        "privacy": "public",
        "consent_generation": 0,
        "critical": True,
    }
    values.update(overrides)
    return AmbientEvent(**values)


def _monitor(**overrides) -> MonitorDefinition:
    values = {
        "monitor_id": "monitor.cpu.pressure",
        "version": 1,
        "source": "digital",
        "schema": "resource.v1",
        "predicates": (MonitorPredicate(field="attributes.value", operator="gte", expected=95.0),),
        "clear_predicates": (
            MonitorPredicate(field="attributes.value", operator="lt", expected=85.0),
        ),
        "debounce_seconds": 5,
        "hold_seconds": 10,
        "cooldown_seconds": 300,
    }
    values.update(overrides)
    return MonitorDefinition(**values)


def test_event_is_bounded_canonical_and_contains_no_arbitrary_payload():
    event = _event()
    assert event.attributes == (
        ("healthy", False),
        ("severity", "critical"),
        ("value", 97.5),
    )
    payload = event.to_dict()
    assert payload["provenance"] == {"adapter": "observer.resource", "version": 1}
    assert payload["critical"] is True
    assert len(json.dumps(payload, separators=(",", ":")).encode()) < 16_384
    assert not ({"detail", "body", "host", "payload", "frame", "snapshot"} & payload["attributes"].keys())


@pytest.mark.parametrize("key", ("detail", "body", "host", "sender", "title", "payload", "frame", "snapshot", "clip"))
def test_event_rejects_sensitive_or_arbitrary_attribute_keys(key):
    with pytest.raises(ValueError, match="attribute"):
        _event(attributes=((key, "private"),))


def test_event_rejects_oversize_nonfinite_and_unbounded_attributes():
    with pytest.raises(ValueError):
        _event(attributes=tuple((f"key_{index}", index) for index in range(33)))
    with pytest.raises(ValueError):
        _event(attributes=(("value", float("nan")),))
    with pytest.raises(ValueError):
        _event(attributes=(("value", "x" * 513),))
    with pytest.raises(ValueError, match="16 KiB"):
        _event(attributes=tuple((f"key_{index}", "x" * 512) for index in range(32)))


def test_monitor_is_hash_bound_versioned_and_has_no_action_surface():
    monitor = _monitor()
    same = _monitor()
    changed = _monitor(version=2)
    assert monitor.definition_hash == same.definition_hash
    assert monitor.definition_hash != changed.definition_hash
    payload = monitor.to_dict()
    assert not ({"capability", "action", "target", "template", "parameters"} & payload.keys())

    with pytest.raises(ValueError, match="unsupported"):
        MonitorDefinition.from_payload({**payload, "action_kind": "restart_service"})


@pytest.mark.parametrize("operator", ("eq", "ne", "lt", "lte", "gt", "gte", "in", "changed", "age"))
def test_predicate_dsl_is_finite_and_declarative(operator):
    expected = ("warn", "critical") if operator == "in" else (None if operator == "changed" else 10)
    predicate = MonitorPredicate(field="attributes.value", operator=operator, expected=expected)
    assert predicate.operator == operator

    with pytest.raises(ValueError):
        MonitorPredicate(field="attributes.value", operator="regex", expected=".*")
    with pytest.raises(ValueError):
        MonitorPredicate(field="__class__", operator="eq", expected="x")


def test_monitor_bounds_predicates_and_timing():
    predicate = MonitorPredicate(field="attributes.value", operator="gte", expected=1)
    with pytest.raises(ValueError):
        _monitor(predicates=(predicate,) * 21)
    with pytest.raises(ValueError):
        _monitor(hold_seconds=7 * 24 * 60 * 60 + 1)
    with pytest.raises(ValueError):
        _monitor(cooldown_seconds=7 * 24 * 60 * 60 + 1)


def test_decision_is_a_fingerprint_journal_record_not_event_content():
    decision = AmbientDecision(
        decision_id="decision-1",
        monitor_id="monitor.cpu.pressure",
        monitor_version=1,
        monitor_hash="a" * 64,
        event_fingerprint="b" * 64,
        transition="alert",
        matched=True,
        reason="predicate_matched",
        decided_at=1_010.0,
        consent_generation=0,
    )
    payload = decision.to_dict()
    assert payload["transition"] == "alert"
    assert not ({"attributes", "payload", "detail", "body"} & payload.keys())
