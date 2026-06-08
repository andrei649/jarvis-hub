"""Tests for the Snapshot dataclass + provenance shape (ticket H19.5.7)."""

from __future__ import annotations

import dataclasses

import pytest

from worldview_ingest.capture.snapshot import SCHEMA, Snapshot, snapshot_key

T0 = 1_700_000_000.0


def _snap(**overrides) -> Snapshot:
    base = {
        "source": "adsb",
        "entity_id": "ABC123",
        "captured_at": T0,
        "ttl_s": 120.0,
        "trigger": "squawk-7700",
        "payload": {"squawk": "7700"},
        "run_id": "run-42",
    }
    base.update(overrides)
    return Snapshot.create(**base)


def test_key_is_stable_source_entity_trigger() -> None:
    """The key is ``source:entity_id:trigger`` and matches the free function."""
    snap = _snap()
    assert snap.key() == "adsb:ABC123:squawk-7700"
    assert snap.key() == snapshot_key("adsb", "ABC123", "squawk-7700")


def test_provenance_shape_and_presence() -> None:
    """Provenance is ALWAYS present with the {source, captured_at, trigger, run_id} shape."""
    prov = _snap().provenance
    assert dict(prov) == {
        "source": "adsb",
        "captured_at": T0,
        "trigger": "squawk-7700",
        "run_id": "run-42",
    }


def test_provenance_is_read_only() -> None:
    """The provenance mapping cannot be mutated in place."""
    prov = _snap().provenance
    with pytest.raises(TypeError):
        prov["source"] = "tampered"  # type: ignore[index]


def test_to_dict_contract() -> None:
    """to_dict emits the worldview.capture.v1 contract incl. nested provenance."""
    d = _snap().to_dict()
    assert set(d) == {
        "schema", "key", "source", "entity_id", "captured_at",
        "ttl_s", "trigger", "payload", "provenance",
    }
    assert d["schema"] == SCHEMA == "worldview.capture.v1"
    assert d["key"] == "adsb:ABC123:squawk-7700"
    assert d["captured_at"] == T0
    assert d["ttl_s"] == 120.0
    assert d["payload"] == {"squawk": "7700"}
    assert d["provenance"] == {
        "source": "adsb",
        "captured_at": T0,
        "trigger": "squawk-7700",
        "run_id": "run-42",
    }


def test_to_dict_payload_is_a_copy() -> None:
    """Mutating the dict's payload must not bleed back into the snapshot."""
    snap = _snap()
    d = snap.to_dict()
    d["payload"]["squawk"] = "changed"
    assert snap.payload["squawk"] == "7700"


def test_create_copies_payload_so_caller_cannot_mutate() -> None:
    """The snapshot snapshots the payload; later caller mutation can't change it."""
    payload = {"k": "v"}
    snap = _snap(payload=payload)
    payload["k"] = "mutated"
    assert snap.payload["k"] == "v"


def test_is_active_boundaries() -> None:
    """Active over ``[captured_at, captured_at+ttl)`` — start inclusive, end exclusive."""
    snap = _snap(captured_at=T0, ttl_s=50.0)
    assert snap.is_active(T0) is True
    assert snap.is_active(T0 + 49.999) is True
    assert snap.is_active(T0 + 50.0) is False
    assert snap.is_active(T0 - 0.001) is False
    assert snap.expires_at == T0 + 50.0


def test_frozen() -> None:
    """The dataclass is immutable."""
    snap = _snap()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.captured_at = T0 + 1  # type: ignore[misc]
