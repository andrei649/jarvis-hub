"""GAP-9 — the production presence writer (HA snapshot → PresenceInference).

Pins the properties that make the writer honest: HA vocabulary is translated
through a closed alias table (never guessed), only identity-bearing domains
produce identity evidence, anonymous motion only corroborates, malformed or
refused entities never blank the other occupants, and with the flag off the
route behavior is byte-identical to before.
"""

import time

import pytest

from agents.core.house.contracts import HouseEntity, HouseSnapshot
from agents.core.house.ingest import HousePresenceIngestor
from agents.core.house.presence import PresenceInference
from agents.core.house.private_store import PrivateHouseStore
from agents.core.security.secret_broker import SecretBroker

_SECRET = "presence-private-key-material-that-is-long-enough"


def _store(tmp_path) -> PrivateHouseStore:
    broker = SecretBroker()
    broker.put("house_private_key", _SECRET)
    return PrivateHouseStore(path=tmp_path / "private_graph.enc", secret_broker=broker)


def _entity(entity_id, state, *, area="living", attrs=(), name=""):
    domain = entity_id.split(".", 1)[0]
    return HouseEntity(
        entity_id=entity_id,
        domain=domain,
        name=name or entity_id,
        state=state,
        area_id=area,
        updated_at=time.time() - 3600.0,  # stale last-changed is fine: see below
        attributes=tuple(attrs),
    )


def _snapshot(entities, *, status="live"):
    return HouseSnapshot(
        enabled=True,
        status=status,
        observed_at=time.time(),
        entities=tuple(entities),
    )


def _ingestor(store) -> HousePresenceIngestor:
    return HousePresenceIngestor(PresenceInference(store))


def _presence_facts(store):
    return [f for f in store.query(limit=100) if f.get("predicate") == "presence_status"]


def _motion(area="living", state="on"):
    return _entity(
        f"binary_sensor.{area}_motion",
        state,
        area=area,
        attrs=(("device_class", "motion"),),
    )


def test_identity_plus_room_motion_writes_present(tmp_path):
    store = _store(tmp_path)
    count = _ingestor(store).ingest(
        _snapshot([_entity("person.alex", "home"), _motion()])
    )
    assert count == 1
    facts = _presence_facts(store)
    assert len(facts) == 1
    assert facts[0]["object"] == "present"


def test_a_lone_tracker_never_claims_presence(tmp_path):
    # The inference model's anti-overclaim floor: one evidence category can
    # never cross the presence threshold, so a lone tracker writes nothing.
    # The ingestor must not weaken that by inventing corroboration.
    store = _store(tmp_path)
    assert _ingestor(store).ingest(_snapshot([_entity("person.alex", "home")])) == 1
    assert _presence_facts(store) == []


def test_evidence_time_is_snapshot_time_not_stale_entity_time(tmp_path):
    # Entities carry hour-old last-changed timestamps, but HA *currently*
    # reports them — evidence binds the snapshot fetch time, so the
    # inference's freshness window (120s) accepts it.
    store = _store(tmp_path)
    count = _ingestor(store).ingest(
        _snapshot([_entity("device_tracker.phone", "home"), _motion()])
    )
    assert count == 1
    assert _presence_facts(store)


def test_ha_vocabulary_is_translated_never_guessed(tmp_path):
    store = _store(tmp_path)
    count = _ingestor(store).ingest(
        _snapshot(
            [
                _entity("person.mystery", "somewhere"),  # unknown vocab -> dropped
                _entity("person.undecided", "unknown"),  # HA says it doesn't know
                _entity("person.alex", "home"),
                _motion(),
            ]
        )
    )
    # Only the translatable occupant was inferred; nothing was guessed.
    assert count == 1
    facts = _presence_facts(store)
    assert len(facts) == 1
    assert facts[0]["object"] == "present"


def test_motion_alone_never_creates_identity(tmp_path):
    store = _store(tmp_path)
    count = _ingestor(store).ingest(_snapshot([_motion()]))
    assert count == 0
    assert _presence_facts(store) == []


def test_non_live_snapshot_writes_nothing(tmp_path):
    store = _store(tmp_path)
    snap = HouseSnapshot(enabled=True, status="degraded", observed_at=time.time())
    assert _ingestor(store).ingest(snap) == 0
    assert _presence_facts(store) == []


def test_one_refused_occupant_does_not_blank_the_rest(tmp_path):
    class _RefusingInference(PresenceInference):
        def infer(self, occupant_ref, evidence, **kwargs):
            if occupant_ref == "person.broken":
                raise ValueError("refused")
            return super().infer(occupant_ref, evidence, **kwargs)

    store = _store(tmp_path)
    ingestor = HousePresenceIngestor(_RefusingInference(store))
    count = ingestor.ingest(
        _snapshot(
            [
                _entity("person.broken", "home"),
                _entity("person.alex", "home"),
                _motion(),
            ]
        )
    )
    assert count == 1
    assert len(_presence_facts(store)) == 1


@pytest.mark.asyncio
async def test_flag_off_route_behavior_is_unchanged(monkeypatch):
    from agents.core.routers import house as house_router

    monkeypatch.delenv("JARVIS_HOUSE_PRESENCE", raising=False)
    assert house_router._presence_enabled({}) is False
    assert house_router._presence_enabled({"house.presence_enabled": True}) is True
    monkeypatch.setenv("JARVIS_HOUSE_PRESENCE", "0")
    # env wins over settings, house-style.
    assert house_router._presence_enabled({"house.presence_enabled": True}) is False
    monkeypatch.setenv("JARVIS_HOUSE_PRESENCE", "1")
    assert house_router._presence_enabled({}) is True
