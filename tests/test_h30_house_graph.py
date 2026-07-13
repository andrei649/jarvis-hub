"""H30.2 — public topology plus private bi-temporal household facts."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agents.core.house.contracts import HouseArea, HouseEntity, HouseSnapshot
from agents.core.house.graph import HouseGraph
from agents.core.house.private_store import PrivateHouseStore, PrivateStoreError
from agents.core.memory.bitemporal import BiTemporalKG
from agents.core.memory.graph import InMemoryGraph
from agents.core.security.secret_broker import SecretBroker

_OLD_SECRET = "old-house-private-key-material-that-is-long-enough"
_NEW_SECRET = "new-house-private-key-material-that-is-long-enough"


def _broker(secret: str = _OLD_SECRET) -> SecretBroker:
    broker = SecretBroker()
    broker.put("house_private_key", secret)
    return broker


def _snapshot(*, observed_at: float = 100.0, state: str = "on") -> HouseSnapshot:
    return HouseSnapshot(
        enabled=True,
        status="live",
        observed_at=observed_at,
        areas=(HouseArea(area_id="kitchen", name="Kitchen"),),
        entities=(
            HouseEntity(
                entity_id="light.kitchen",
                domain="light",
                name="Kitchen light",
                state=state,
                area_id="kitchen",
                updated_at=observed_at,
            ),
            HouseEntity(
                entity_id="person.alice_example",
                domain="person",
                name="Alice Example",
                state="home",
                area_id="kitchen",
                updated_at=observed_at,
            ),
        ),
    )


def _record_presence(
    store: PrivateHouseStore,
    *,
    occupant: str = "Alice Example",
    room: str = "kitchen",
    valid_from: float = 100.0,
    observed_at: float = 200.0,
    source_event_id: str = "ha-event-1",
):
    return store.record_presence(
        occupant_ref=occupant,
        room_id=room,
        valid_from=valid_from,
        observed_at=observed_at,
        source_event_id=source_event_id,
        confidence=0.91,
        fresh_until=500.0,
        consent_version="consent-v1",
    )


def test_public_house_graph_projects_only_bounded_room_device_topology():
    generic = InMemoryGraph()
    house = HouseGraph(generic, clock=lambda: 120.0)

    first = house.project_snapshot(_snapshot())
    duplicate = house.project_snapshot(_snapshot())
    stale = house.project_snapshot(_snapshot(observed_at=50.0, state="off"))

    assert first == {"status": "projected", "rooms": 1, "devices": 1, "relations": 1}
    assert duplicate["status"] == "unchanged"
    assert stale["status"] == "stale_ignored"
    assert {item["name"] for item in generic.list_entities()} == {
        "house:room:kitchen",
        "house:device:light.kitchen",
    }
    assert generic.get_relations("house:room:kitchen") == [
        {
            "source": "house:room:kitchen",
            "relation": "CONTAINS",
            "target": "house:device:light.kitchen",
            "properties": {"source": "home_assistant", "observed_at": 100.0},
        }
    ]
    state = house.query_state(room_id="kitchen")
    assert state["status"] == "live"
    assert state["confidence"] == 1.0
    assert state["freshness_seconds"] == 20.0
    assert state["rooms"][0]["room_id"] == "kitchen"
    assert state["devices"][0]["state"] == "on"
    assert "occup" not in json.dumps(generic.list_entities()).lower()
    assert "Alice Example" not in json.dumps(generic.list_entities())


def test_public_house_graph_reports_degraded_when_generic_graph_rejects_writes(
    monkeypatch,
):
    generic = InMemoryGraph()
    house = HouseGraph(generic, clock=lambda: 120.0)
    monkeypatch.setattr(generic, "add_entity", lambda *_args, **_kwargs: False)

    result = house.project_snapshot(_snapshot())

    assert result == {
        "status": "degraded",
        "reason": "graph_projection_failed",
        "rooms": 0,
        "devices": 0,
        "relations": 0,
    }
    assert house.query_state()["status"] == "degraded"
    assert house.query_state()["rooms"] == []


def test_private_store_requires_a_managed_secret_broker(tmp_path):
    with pytest.raises(PrivateStoreError, match="key is unavailable"):
        PrivateHouseStore(path=tmp_path / "private.enc")


def test_private_store_rejects_authenticated_but_malformed_state(tmp_path):
    path = tmp_path / "private.enc"
    broker = _broker()
    store = PrivateHouseStore(path=path, secret_broker=broker)
    malformed = store._state()
    malformed["seq"] = 1
    malformed["facts"] = [{"id": "phf-1"}]
    ciphertext = store._cipher.encrypt_value(json.dumps(malformed))
    path.write_text(json.dumps({"version": 1, "ciphertext": ciphertext}), encoding="utf-8")

    with pytest.raises(PrivateStoreError, match="validate"):
        PrivateHouseStore(path=path, secret_broker=broker)


def test_private_store_is_encrypted_bitemporal_and_replay_idempotent(tmp_path):
    path = tmp_path / "house" / "private_graph.enc"
    store = PrivateHouseStore(path=path, secret_broker=_broker(), clock=lambda: 400.0)

    first = _record_presence(store)
    duplicate = _record_presence(store)
    correction = _record_presence(
        store,
        room="hall",
        valid_from=50.0,
        observed_at=300.0,
        source_event_id="ha-event-correction",
    )

    assert first["status"] == "stored"
    assert duplicate == {"status": "duplicate", "reason": "source_event_seen"}
    assert correction["status"] == "stored"
    pseudonym = store.pseudonym_for("Alice Example")
    assert pseudonym.startswith("occ-") and "Alice" not in pseudonym
    assert [fact["object"] for fact in store.query(occupant_ref="Alice Example", at=75.0)] == [
        "hall"
    ]
    assert [fact["object"] for fact in store.query(occupant_ref="Alice Example", at=150.0)] == [
        "kitchen"
    ]
    assert store.query(occupant_ref="Alice Example", at=75.0, known_at=250.0) == []
    known = store.query(occupant_ref="Alice Example", at=150.0, known_at=250.0)
    assert known[0]["object"] == "kitchen"
    assert known[0]["privacy_class"] == "household_sensitive"
    assert known[0]["consent_version"] == "consent-v1"
    assert known[0]["confidence"] == 0.91
    assert known[0]["fresh"] is True
    assert not any(key.startswith("_") for key in known[0])

    envelope = path.read_text(encoding="utf-8")
    assert "ciphertext" in envelope
    for private_value in ("Alice Example", "kitchen", "hall", "ha-event-1", pseudonym):
        assert private_value not in envelope


def test_room_occupancy_is_multi_valued_without_collapsing_people(tmp_path):
    store = PrivateHouseStore(
        path=tmp_path / "private.enc", secret_broker=_broker(), clock=lambda: 400.0
    )
    metadata = {
        "room_id": "kitchen",
        "valid_from": 100.0,
        "observed_at": 200.0,
        "confidence": 0.9,
        "fresh_until": 500.0,
        "consent_version": "consent-v1",
    }
    store.record_occupancy(
        occupant_ref="Alice Example", source_event_id="occupancy-alice", **metadata
    )
    store.record_occupancy(occupant_ref="Bob Example", source_event_id="occupancy-bob", **metadata)

    occupants = store.query(room_id="kitchen", at=150.0)
    assert len(occupants) == 2
    assert {fact["object"] for fact in occupants} == {
        store.pseudonym_for("Alice Example"),
        store.pseudonym_for("Bob Example"),
    }


def test_consent_purge_clears_facts_cache_history_and_survives_restart(tmp_path):
    path = tmp_path / "house" / "private_graph.enc"
    broker = _broker()
    store = PrivateHouseStore(path=path, secret_broker=broker, clock=lambda: 400.0)
    _record_presence(store)
    store.record_privacy_context(
        occupant_ref="Alice Example",
        context="do_not_interrupt",
        valid_from=100.0,
        observed_at=210.0,
        source_event_id="privacy-event-1",
        confidence=1.0,
        fresh_until=600.0,
        consent_version="consent-v1",
    )
    assert len(store.query(occupant_ref="Alice Example", at=150.0)) == 2
    assert store.stats()["cache_entries"] > 0

    purged = store.purge_occupant("Alice Example", consent_version="consent-v2", purged_at=400.0)

    assert purged == {"status": "purged", "facts_removed": 2, "events_tombstoned": 2}
    assert store.stats()["cache_entries"] == 0
    assert store.query(occupant_ref="Alice Example", at=150.0) == []
    assert store.history("Alice Example") == []

    restarted = PrivateHouseStore(path=path, secret_broker=broker, clock=lambda: 450.0)
    assert restarted.query() == []
    replay = _record_presence(restarted)
    novel = _record_presence(restarted, source_event_id="ha-event-new")
    assert replay == {"status": "suppressed", "reason": "source_event_tombstoned"}
    assert novel == {"status": "suppressed", "reason": "consent_revoked"}
    assert restarted.stats()["identity_refs"] == 0


def test_key_rotation_rekeys_live_and_revoked_pseudonyms_atomically(tmp_path):
    path = tmp_path / "house" / "private_graph.enc"
    old_broker = _broker(_OLD_SECRET)
    store = PrivateHouseStore(path=path, secret_broker=old_broker, clock=lambda: 400.0)
    _record_presence(store, occupant="Bob Example", source_event_id="bob-event-1")
    _record_presence(store, occupant="Alice Example", source_event_id="alice-event-1")
    store.purge_occupant("Alice Example", consent_version="consent-v2", purged_at=400.0)
    old_bob_id = store.pseudonym_for("Bob Example")

    new_broker = _broker(_NEW_SECRET)
    rotated = store.rotate_key(secret_broker=new_broker)

    assert rotated == {"status": "rotated", "key_version": 2, "facts_rekeyed": 1}
    assert store.pseudonym_for("Bob Example") != old_bob_id
    assert store.query(occupant_ref="Bob Example", at=150.0)[0]["object"] == "kitchen"
    assert _record_presence(store, occupant="Alice Example", source_event_id="alice-event-new") == {
        "status": "suppressed",
        "reason": "consent_revoked",
    }

    restarted = PrivateHouseStore(path=path, secret_broker=new_broker, clock=lambda: 450.0)
    assert restarted.query(occupant_ref="Bob Example", at=150.0)
    with pytest.raises(PrivateStoreError, match="decrypt"):
        PrivateHouseStore(path=path, secret_broker=old_broker)


def test_revoked_linked_identity_cannot_be_resurrected_indirectly(tmp_path):
    store = PrivateHouseStore(
        path=tmp_path / "private.enc", secret_broker=_broker(), clock=lambda: 400.0
    )
    store.purge_occupant("Bob Example", consent_version="consent-v2", purged_at=400.0)

    result = store.record_identity_link(
        occupant_ref="Alice Example",
        linked_identity_ref="Bob Example",
        valid_from=100.0,
        observed_at=200.0,
        source_event_id="identity-event-1",
        confidence=1.0,
        fresh_until=500.0,
        consent_version="consent-v1",
    )

    assert result == {"status": "suppressed", "reason": "consent_revoked"}
    assert store.query() == []
    assert store.stats()["identity_refs"] == 0


def test_private_mutations_roll_back_in_memory_when_atomic_save_fails(tmp_path, monkeypatch):
    path = tmp_path / "house" / "private_graph.enc"
    store = PrivateHouseStore(path=path, secret_broker=_broker(), clock=lambda: 400.0)

    def fail_save():
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save_locked", fail_save)
    with pytest.raises(PrivateStoreError, match="persist"):
        _record_presence(store)
    assert store.stats()["facts"] == 0
    assert store.stats()["identity_refs"] == 0

    monkeypatch.undo()
    _record_presence(store)
    monkeypatch.setattr(store, "_save_locked", fail_save)
    with pytest.raises(PrivateStoreError, match="persist"):
        store.purge_occupant("Alice Example", consent_version="consent-v2", purged_at=400.0)
    assert store.stats()["facts"] == 1
    assert store.stats()["tombstones"] == 0
    assert store.stats()["revocations"] == 0


def test_generic_kg_read_routes_cannot_reach_private_house_facts(tmp_path):
    from agents import web

    generic = InMemoryGraph()
    HouseGraph(generic).project_snapshot(_snapshot())
    private = PrivateHouseStore(
        path=tmp_path / "private.enc", secret_broker=_broker(), clock=lambda: 400.0
    )
    _record_presence(private)
    private_id = private.pseudonym_for("Alice Example")

    with TestClient(web.app) as client:
        old_graph = web.orch.memory.graph
        old_bitemporal = web.orch.bitemporal
        try:
            web.orch.memory.graph = generic
            web.orch.bitemporal = BiTemporalKG(tmp_path / "generic_bt.json")
            responses = [
                client.get("/api/kg/entities"),
                client.get("/api/kg/entities", params={"q": "Alice"}),
                client.get("/api/kg/entities/house:room:kitchen"),
                client.get("/api/kg/facts/as-of", params={"at": 150.0}),
                client.get("/api/kg/facts/history", params={"subject": private_id}),
            ]
        finally:
            web.orch.memory.graph = old_graph
            web.orch.bitemporal = old_bitemporal

    assert all(response.status_code == 200 for response in responses)
    serialized = json.dumps(
        [response.json() for response in responses[:4]] + [responses[4].json()["history"]]
    )
    assert "house:room:kitchen" in serialized
    assert "Alice Example" not in serialized
    assert private_id not in serialized
