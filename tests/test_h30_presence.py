"""H30.3 — deterministic, strict-local presence and privacy inference."""

from __future__ import annotations

import json

import pytest

from agents.core.house.contracts import HouseEvent
from agents.core.house.presence import (
    LocalPresenceExplainer,
    PresenceEvidence,
    PresenceInference,
)
from agents.core.house.private_store import PrivateHouseStore
from agents.core.observability.egress_monitor import EGRESS_MONITOR
from agents.core.security.secret_broker import SecretBroker

_SECRET = "presence-private-key-material-that-is-long-enough"


def _store(tmp_path) -> PrivateHouseStore:
    broker = SecretBroker()
    broker.put("house_private_key", _SECRET)
    return PrivateHouseStore(
        path=tmp_path / "house" / "private_graph.enc",
        secret_broker=broker,
        clock=lambda: 1_000.0,
    )


def _evidence(
    category: str,
    *,
    state: str = "present",
    room: str = "kitchen",
    occupant: str = "Alice Example",
    observed_at: float = 995.0,
    confidence: float = 1.0,
    event_id: str | None = None,
) -> PresenceEvidence:
    return PresenceEvidence(
        source_event_id=event_id or f"event-{category}-{room}-{state}",
        category=category,
        state=state,
        room_id=room,
        occupant_ref=occupant,
        observed_at=observed_at,
        confidence=confidence,
    )


def _present_evidence() -> list[PresenceEvidence]:
    return [
        _evidence("bluetooth", confidence=0.9),
        _evidence("motion", occupant="", confidence=0.9),
    ]


def test_sensor_fusion_persists_bounded_explainable_facts_and_emits_event(tmp_path):
    store = _store(tmp_path)
    engine = PresenceInference(store, clock=lambda: 1_000.0)

    outcome = engine.infer("Alice Example", _present_evidence())

    assert outcome.decision.status == "present"
    assert outcome.decision.room_id == "kitchen"
    assert outcome.decision.confidence >= 0.5
    assert outcome.decision.evidence_categories == ("bluetooth", "motion")
    assert outcome.decision.freshness_seconds == 5.0
    assert isinstance(outcome.event, HouseEvent)
    assert outcome.event.current_state == "present:kitchen"
    serialized = json.dumps(outcome.to_dict())
    assert "Alice Example" not in serialized
    assert "event-bluetooth" not in serialized

    facts = store.query(occupant_ref="Alice Example", at=1_000.0)
    presence = next(fact for fact in facts if fact["predicate"] == "present_in")
    assert presence["evidence_categories"] == ["bluetooth", "motion"]
    assert presence["fresh"] is True
    assert presence["confidence"] == outcome.decision.confidence


def test_stale_evidence_returns_unknown_without_persisting(tmp_path):
    store = _store(tmp_path)
    engine = PresenceInference(store, clock=lambda: 1_000.0, max_evidence_age=120.0)

    outcome = engine.infer("Alice Example", [_evidence("bluetooth", observed_at=800.0)])

    assert outcome.decision.status == "unknown"
    assert outcome.decision.reason == "no_fresh_evidence"
    assert store.query() == []


def test_contradictory_room_evidence_is_ambiguous_instead_of_guessed(tmp_path):
    store = _store(tmp_path)
    engine = PresenceInference(store, clock=lambda: 1_000.0)
    evidence = [
        _evidence("person_tracker", room="kitchen"),
        _evidence("motion", room="kitchen", occupant=""),
        _evidence("bluetooth", room="office"),
        _evidence("voice", room="office"),
    ]

    outcome = engine.infer("Alice Example", evidence)

    assert outcome.decision.status == "ambiguous"
    assert outcome.decision.room_id == ""
    assert outcome.decision.reason == "contradictory_rooms"
    assert store.query() == []


def test_anonymous_motion_cannot_invent_an_identity(tmp_path):
    store = _store(tmp_path)
    engine = PresenceInference(store, clock=lambda: 1_000.0)

    outcome = engine.infer("Alice Example", [_evidence("motion", occupant="", confidence=1.0)])

    assert outcome.decision.status == "unknown"
    assert outcome.decision.reason == "identity_unknown"
    assert store.query() == []


def test_consistent_negative_identity_evidence_marks_vacancy(tmp_path):
    store = _store(tmp_path)
    engine = PresenceInference(store, clock=lambda: 1_000.0)
    evidence = [
        _evidence("person_tracker", state="absent", room=""),
        _evidence("bluetooth", state="absent", room=""),
    ]

    outcome = engine.infer("Alice Example", evidence)

    assert outcome.decision.status == "vacant"
    assert outcome.decision.confidence >= 0.5
    assert outcome.event.current_state == "vacant"
    facts = store.query(occupant_ref="Alice Example", at=1_000.0)
    assert [(fact["predicate"], fact["object"]) for fact in facts] == [
        ("presence_status", "vacant")
    ]


def test_room_privacy_mode_withholds_location_and_overrides_presence_storage(tmp_path):
    store = _store(tmp_path)
    engine = PresenceInference(store, clock=lambda: 1_000.0, private_rooms={"kitchen"})

    outcome = engine.infer("Alice Example", _present_evidence())

    assert outcome.decision.status == "present"
    assert outcome.decision.room_id == ""
    assert outcome.decision.privacy_context == "private"
    assert outcome.event.current_state == "present:private"
    facts = store.query(occupant_ref="Alice Example", at=1_000.0)
    assert {fact["predicate"] for fact in facts} == {
        "presence_status",
        "privacy_context",
    }
    assert next(fact for fact in facts if fact["predicate"] == "privacy_context")[
        "object"
    ] == "private"


def test_consent_revocation_suppresses_novel_presence_inference(tmp_path):
    store = _store(tmp_path)
    store.purge_occupant("Alice Example", consent_version="consent-v2", purged_at=900.0)
    engine = PresenceInference(store, clock=lambda: 1_000.0)

    outcome = engine.infer("Alice Example", _present_evidence())

    assert outcome.decision.status == "revoked"
    assert outcome.decision.reason == "consent_revoked"
    assert store.query() == []
    assert store.stats()["identity_refs"] == 0


def test_future_clock_skew_is_ignored_fail_closed(tmp_path):
    store = _store(tmp_path)
    engine = PresenceInference(store, clock=lambda: 1_000.0, max_future_skew=5.0)

    outcome = engine.infer("Alice Example", [_evidence("bluetooth", observed_at=1_100.0)])

    assert outcome.decision.status == "unknown"
    assert outcome.decision.reason == "clock_skew"
    assert store.query() == []


def test_restart_recovers_presence_confidence_freshness_and_privacy(tmp_path):
    path = tmp_path / "house" / "private_graph.enc"
    store = _store(tmp_path)
    PresenceInference(store, clock=lambda: 1_000.0).infer("Alice Example", _present_evidence())
    broker = SecretBroker()
    broker.put("house_private_key", _SECRET)
    restarted_store = PrivateHouseStore(path=path, secret_broker=broker, clock=lambda: 1_010.0)

    recovered = PresenceInference(restarted_store, clock=lambda: 1_010.0).current_presence(
        "Alice Example"
    )

    assert recovered.status == "present"
    assert recovered.room_id == "kitchen"
    assert recovered.evidence_categories == ("bluetooth", "motion")
    assert recovered.freshness_seconds == 15.0
    assert recovered.privacy_context == "normal"


def test_vacancy_supersedes_prior_presence_across_restart(tmp_path):
    path = tmp_path / "house" / "private_graph.enc"
    store = _store(tmp_path)
    PresenceInference(store, clock=lambda: 1_000.0).infer("Alice Example", _present_evidence())
    vacancy = PresenceInference(store, clock=lambda: 1_050.0).infer(
        "Alice Example",
        [
            _evidence(
                "person_tracker",
                state="absent",
                room="",
                observed_at=1_045.0,
                event_id="vacant-person",
            ),
            _evidence(
                "bluetooth",
                state="absent",
                room="",
                observed_at=1_045.0,
                event_id="vacant-bluetooth",
            ),
        ],
    )
    assert vacancy.decision.status == "vacant"

    broker = SecretBroker()
    broker.put("house_private_key", _SECRET)
    restarted = PrivateHouseStore(path=path, secret_broker=broker, clock=lambda: 1_060.0)
    recovered = PresenceInference(restarted, clock=lambda: 1_060.0).current_presence(
        "Alice Example"
    )

    assert recovered.status == "vacant"
    assert recovered.evidence_categories == ("bluetooth", "person_tracker")


def test_expired_persisted_presence_recovers_as_unknown(tmp_path):
    store = _store(tmp_path)
    PresenceInference(store, clock=lambda: 1_000.0, max_evidence_age=120.0).infer(
        "Alice Example", _present_evidence()
    )

    recovered = PresenceInference(
        store, clock=lambda: 1_200.0, max_evidence_age=120.0
    ).current_presence("Alice Example")

    assert recovered.status == "unknown"
    assert recovered.reason == "persisted_presence_stale"


@pytest.mark.asyncio
async def test_optional_explanation_uses_only_local_backend_and_sanitized_payload(tmp_path):
    class Backend:
        async def generate(self, model, prompt, **_kwargs):
            assert model == "local-model"
            assert "Alice Example" not in prompt
            assert "event-bluetooth" not in prompt
            return "Local-only explanation"

    class Router:
        active_model = "local-model"

        @property
        def local_backend(self):
            return Backend()

        @property
        def backend(self):
            raise AssertionError("cloud-capable backend accessor must not be touched")

    EGRESS_MONITOR.reset()
    outcome = PresenceInference(_store(tmp_path), clock=lambda: 1_000.0).infer(
        "Alice Example", _present_evidence()
    )
    explainer = LocalPresenceExplainer.from_router(Router())

    assert await explainer.explain(outcome.decision) == "Local-only explanation"
    assert EGRESS_MONITOR.snapshot()["external_egress_total"] == 0
    assert EGRESS_MONITOR.snapshot()["recent"] == []
