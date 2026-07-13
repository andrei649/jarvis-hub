"""Deterministic strict-local presence and room-privacy inference."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Iterable
from dataclasses import dataclass

from .contracts import HouseEvent
from .private_store import PrivateHouseStore

_MAX_EVIDENCE = 128
_MAX_ID = 128
_MAX_ROOM = 128
_WEIGHTS = {
    "person_tracker": 0.45,
    "bluetooth": 0.35,
    "voice": 0.30,
    "motion": 0.25,
    "door": 0.20,
    "manual": 1.00,
    "privacy": 0.00,
}
_IDENTITY_CATEGORIES = frozenset({"person_tracker", "bluetooth", "voice", "manual"})
_POSITIVE_STATES = frozenset({"present", "active", "entered", "detected", "on"})
_NEGATIVE_STATES = frozenset({"absent", "inactive", "exited", "clear", "off"})


def _text(value: object, *, label: str, limit: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    result = value.strip()
    if required and not result:
        raise ValueError(f"{label} is required")
    if len(result) > limit:
        raise ValueError(f"{label} exceeds its size limit")
    return result


def _timestamp(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite timestamp")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be a finite timestamp")
    return result


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("confidence must be between zero and one")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError("confidence must be between zero and one")
    return result


@dataclass(frozen=True)
class PresenceEvidence:
    source_event_id: str
    category: str
    state: str
    observed_at: float
    confidence: float
    room_id: str = ""
    occupant_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_event_id",
            _text(self.source_event_id, label="source_event_id", limit=_MAX_ID),
        )
        category = _text(self.category, label="category", limit=64).lower()
        state = _text(self.state, label="state", limit=32).lower()
        if category not in _WEIGHTS:
            raise ValueError("presence evidence category is unsupported")
        if state not in _POSITIVE_STATES | _NEGATIVE_STATES:
            raise ValueError("presence evidence state is unsupported")
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "state", state)
        object.__setattr__(
            self,
            "room_id",
            _text(self.room_id, label="room_id", limit=_MAX_ROOM, required=False),
        )
        object.__setattr__(
            self,
            "occupant_ref",
            _text(
                self.occupant_ref,
                label="occupant_ref",
                limit=256,
                required=False,
            ),
        )
        object.__setattr__(self, "observed_at", _timestamp(self.observed_at, label="observed_at"))
        object.__setattr__(self, "confidence", _confidence(self.confidence))


@dataclass(frozen=True)
class PresenceDecision:
    status: str
    occupant_id: str
    room_id: str
    confidence: float
    observed_at: float
    freshness_seconds: float | None
    evidence_categories: tuple[str, ...]
    privacy_context: str
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "occupant_id": self.occupant_id,
            "room_id": self.room_id,
            "confidence": self.confidence,
            "observed_at": self.observed_at,
            "freshness_seconds": self.freshness_seconds,
            "evidence_categories": list(self.evidence_categories),
            "privacy_context": self.privacy_context,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PresenceOutcome:
    decision: PresenceDecision
    event: HouseEvent

    def to_dict(self) -> dict:
        return {"decision": self.decision.to_dict(), "event": self.event.to_dict()}


class LocalPresenceExplainer:
    """Optional post-hoc explanation seam that can only bind a local backend."""

    def __init__(self, backend, model: str) -> None:
        self._backend = backend
        self._model = _text(model or "local", label="model", limit=256)

    @classmethod
    def from_router(cls, router) -> LocalPresenceExplainer:
        backend = router.local_backend
        return cls(backend, getattr(router, "active_model", None) or "local")

    async def explain(self, decision: PresenceDecision) -> str:
        payload = decision.to_dict()
        payload.pop("occupant_id", None)
        prompt = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        result = await self._backend.generate(
            self._model,
            prompt,
            system=(
                "Explain this deterministic presence decision briefly. Do not infer identity, "
                "change the decision, or add facts."
            ),
            max_tokens=128,
            temperature=0.0,
        )
        return str(result)[:1_000]


class PresenceInference:
    """Bounded deterministic inference; occupant payloads never enter a cloud router."""

    def __init__(
        self,
        store: PrivateHouseStore,
        *,
        clock=None,
        max_evidence_age: float = 120.0,
        max_future_skew: float = 5.0,
        private_rooms: Iterable[str] = (),
        presence_threshold: float = 0.5,
        ambiguity_margin: float = 0.15,
    ) -> None:
        if not isinstance(store, PrivateHouseStore):
            raise ValueError("store must be a PrivateHouseStore")
        self._store = store
        self._clock = clock or time.time
        self._max_age = _timestamp(max_evidence_age, label="max_evidence_age")
        self._future_skew = _timestamp(max_future_skew, label="max_future_skew")
        self._threshold = _confidence(presence_threshold)
        self._ambiguity_margin = _confidence(ambiguity_margin)
        rooms = list(private_rooms)
        if len(rooms) > 512:
            raise ValueError("private room count exceeds its limit")
        self._private_rooms = {_text(room, label="room_id", limit=_MAX_ROOM) for room in rooms}

    def set_room_privacy(self, room_id: str, *, enabled: bool) -> None:
        room = _text(room_id, label="room_id", limit=_MAX_ROOM)
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        if enabled:
            if room not in self._private_rooms and len(self._private_rooms) >= 512:
                raise ValueError("private room count exceeds its limit")
            self._private_rooms.add(room)
        else:
            self._private_rooms.discard(room)

    def _decision(
        self,
        *,
        status: str,
        occupant_id: str,
        now: float,
        evidence: list[PresenceEvidence],
        room_id: str = "",
        confidence: float = 0.0,
        privacy_context: str = "unknown",
        reason: str = "",
    ) -> PresenceDecision:
        latest = min(now, max((item.observed_at for item in evidence), default=now))
        categories = tuple(sorted({item.category for item in evidence}))
        return PresenceDecision(
            status=status,
            occupant_id=occupant_id,
            room_id=room_id,
            confidence=round(min(1.0, max(0.0, confidence)), 3),
            observed_at=latest,
            freshness_seconds=round(max(0.0, now - latest), 3) if evidence else None,
            evidence_categories=categories,
            privacy_context=privacy_context,
            reason=reason,
        )

    @staticmethod
    def _room_scores(evidence: list[PresenceEvidence]) -> dict[str, float]:
        by_room_category: dict[tuple[str, str], float] = {}
        for item in evidence:
            if not item.room_id or item.state not in _POSITIVE_STATES:
                continue
            key = (item.room_id, item.category)
            by_room_category[key] = max(
                by_room_category.get(key, 0.0), _WEIGHTS[item.category] * item.confidence
            )
        scores: dict[str, float] = {}
        for (room, _category), score in by_room_category.items():
            scores[room] = min(1.0, scores.get(room, 0.0) + score)
        return scores

    def _classify(
        self,
        occupant_ref: str,
        occupant_id: str,
        evidence: list[PresenceEvidence],
        now: float,
    ) -> PresenceDecision:
        relevant = [
            item
            for item in evidence
            if not item.occupant_ref or item.occupant_ref == occupant_ref
        ]
        future = [item for item in relevant if item.observed_at > now + self._future_skew]
        fresh = [
            item
            for item in relevant
            if item.observed_at <= now + self._future_skew
            and now - item.observed_at <= self._max_age
        ]
        for item in fresh:
            if item.category == "privacy" and item.room_id:
                self.set_room_privacy(item.room_id, enabled=item.state in _POSITIVE_STATES)
        scored = [item for item in fresh if item.category != "privacy"]
        if not scored:
            reason = "clock_skew" if future else "no_fresh_evidence"
            return self._decision(
                status="unknown",
                occupant_id=occupant_id,
                now=now,
                evidence=[],
                reason=reason,
            )

        identity = [
            item
            for item in scored
            if item.occupant_ref == occupant_ref and item.category in _IDENTITY_CATEGORIES
        ]
        negative_score = min(
            1.0,
            sum(
                _WEIGHTS[item.category] * item.confidence
                for item in identity
                if item.state in _NEGATIVE_STATES
            ),
        )
        room_scores = self._room_scores(scored)
        best_room_score = max(room_scores.values(), default=0.0)
        if negative_score >= self._threshold and best_room_score < self._threshold:
            return self._decision(
                status="vacant",
                occupant_id=occupant_id,
                now=now,
                evidence=identity,
                confidence=negative_score,
                privacy_context="normal",
            )
        positive_identity = [item for item in identity if item.state in _POSITIVE_STATES]
        if not positive_identity:
            return self._decision(
                status="unknown",
                occupant_id=occupant_id,
                now=now,
                evidence=scored,
                reason="identity_unknown",
            )
        ranked = sorted(room_scores.items(), key=lambda item: (-item[1], item[0]))
        if not ranked or ranked[0][1] < self._threshold:
            return self._decision(
                status="unknown",
                occupant_id=occupant_id,
                now=now,
                evidence=scored,
                confidence=best_room_score,
                reason="insufficient_confidence",
            )
        if len(ranked) > 1 and ranked[0][1] - ranked[1][1] <= self._ambiguity_margin:
            return self._decision(
                status="ambiguous",
                occupant_id=occupant_id,
                now=now,
                evidence=scored,
                confidence=ranked[0][1],
                reason="contradictory_rooms",
            )
        room_id, score = ranked[0]
        private = room_id in self._private_rooms
        return self._decision(
            status="present",
            occupant_id=occupant_id,
            now=now,
            evidence=scored,
            room_id="" if private else room_id,
            confidence=score,
            privacy_context="private" if private else "normal",
        )

    @staticmethod
    def _source_digest(evidence: list[PresenceEvidence]) -> str:
        joined = "\0".join(sorted({item.source_event_id for item in evidence}))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]

    def _persist(
        self,
        occupant_ref: str,
        decision: PresenceDecision,
        evidence: list[PresenceEvidence],
        *,
        consent_version: str,
    ) -> str:
        if decision.status not in {"present", "vacant"}:
            return "not_applicable"
        digest = self._source_digest(evidence)
        metadata = {
            "valid_from": decision.observed_at,
            "observed_at": decision.observed_at,
            "confidence": decision.confidence,
            "fresh_until": decision.observed_at + self._max_age,
            "consent_version": consent_version,
            "evidence_categories": decision.evidence_categories,
        }
        state = self._store.record_presence_state(
            occupant_ref=occupant_ref,
            state=decision.status,
            source_event_id=f"presence-status-{digest}",
            **metadata,
        )
        if state.get("status") == "suppressed":
            return str(state.get("reason") or "suppressed")
        if decision.status == "vacant":
            return "stored"
        privacy = self._store.record_privacy_context(
            occupant_ref=occupant_ref,
            context=decision.privacy_context,
            source_event_id=f"presence-privacy-{digest}",
            **metadata,
        )
        if privacy.get("status") == "suppressed":
            return str(privacy.get("reason") or "suppressed")
        if decision.privacy_context == "private":
            return "stored"
        presence = self._store.record_presence(
            occupant_ref=occupant_ref,
            room_id=decision.room_id,
            source_event_id=f"presence-location-{digest}",
            **metadata,
        )
        occupancy = self._store.record_occupancy(
            occupant_ref=occupant_ref,
            room_id=decision.room_id,
            source_event_id=f"presence-occupancy-{digest}",
            **metadata,
        )
        if any(result.get("status") == "suppressed" for result in (presence, occupancy)):
            return "consent_revoked"
        return "stored"

    @staticmethod
    def _state_label(decision: PresenceDecision) -> str:
        if decision.status == "present":
            return f"present:{decision.room_id or 'private'}"
        return decision.status

    def _event(
        self,
        decision: PresenceDecision,
        evidence: list[PresenceEvidence],
        *,
        previous_state: str,
        now: float,
    ) -> HouseEvent:
        digest = hashlib.sha256(
            (
                self._source_digest(evidence)
                + decision.occupant_id
                + decision.status
                + decision.room_id
            ).encode("utf-8")
        ).hexdigest()[:24]
        return HouseEvent(
            event_id=f"presence-{digest}",
            source_event_id=f"presence-source-{digest}",
            entity_id=decision.occupant_id,
            event_type="presence_inferred",
            previous_state=previous_state,
            current_state=self._state_label(decision),
            occurred_at=decision.observed_at,
            observed_at=now,
            dedupe_key=f"presence:{digest}",
            provenance="house.presence.deterministic",
            privacy_class="household_sensitive",
        )

    def infer(
        self,
        occupant_ref: str,
        evidence: Iterable[PresenceEvidence],
        *,
        consent_version: str = "consent-v1",
    ) -> PresenceOutcome:
        occupant = _text(occupant_ref, label="occupant_ref", limit=256)
        items = list(evidence)
        if len(items) > _MAX_EVIDENCE or any(
            not isinstance(item, PresenceEvidence) for item in items
        ):
            raise ValueError("presence evidence must be bounded PresenceEvidence values")
        now = _timestamp(self._clock(), label="clock")
        occupant_id = self._store.pseudonym_for(occupant)
        previous = self.current_presence(occupant)
        decision = self._classify(occupant, occupant_id, items, now)
        persisted = self._persist(
            occupant,
            decision,
            items,
            consent_version=_text(consent_version, label="consent_version", limit=64),
        )
        if persisted == "consent_revoked":
            decision = self._decision(
                status="revoked",
                occupant_id=occupant_id,
                now=now,
                evidence=items,
                reason="consent_revoked",
            )
        event = self._event(
            decision,
            items,
            previous_state=self._state_label(previous),
            now=now,
        )
        return PresenceOutcome(decision=decision, event=event)

    def current_presence(self, occupant_ref: str) -> PresenceDecision:
        occupant = _text(occupant_ref, label="occupant_ref", limit=256)
        now = _timestamp(self._clock(), label="clock")
        occupant_id = self._store.pseudonym_for(occupant)
        facts = self._store.query(occupant_ref=occupant, at=now)
        state = next(
            (fact for fact in facts if fact.get("predicate") == "presence_status"),
            None,
        )
        privacy = next((fact for fact in facts if fact.get("predicate") == "privacy_context"), None)
        presence = next((fact for fact in facts if fact.get("predicate") == "present_in"), None)
        freshness_source = state or presence or privacy
        if freshness_source and now > float(freshness_source["fresh_until"]):
            return PresenceDecision(
                status="unknown",
                occupant_id=occupant_id,
                room_id="",
                confidence=0.0,
                observed_at=float(freshness_source["observed_at"]),
                freshness_seconds=max(0.0, now - float(freshness_source["observed_at"])),
                evidence_categories=tuple(freshness_source.get("evidence_categories", ())),
                privacy_context="unknown",
                reason="persisted_presence_stale",
            )
        if state and state.get("object") == "vacant":
            return PresenceDecision(
                status="vacant",
                occupant_id=occupant_id,
                room_id="",
                confidence=float(state["confidence"]),
                observed_at=float(state["observed_at"]),
                freshness_seconds=max(0.0, now - float(state["observed_at"])),
                evidence_categories=tuple(state.get("evidence_categories", ())),
                privacy_context="normal",
            )
        if privacy and privacy.get("object") == "private":
            source = privacy
            return PresenceDecision(
                status="present",
                occupant_id=occupant_id,
                room_id="",
                confidence=float(source["confidence"]),
                observed_at=float(source["observed_at"]),
                freshness_seconds=max(0.0, now - float(source["observed_at"])),
                evidence_categories=tuple(source.get("evidence_categories", ())),
                privacy_context="private",
            )
        if presence:
            return PresenceDecision(
                status="present",
                occupant_id=occupant_id,
                room_id=str(presence["object"]),
                confidence=float(presence["confidence"]),
                observed_at=float(presence["observed_at"]),
                freshness_seconds=max(0.0, now - float(presence["observed_at"])),
                evidence_categories=tuple(presence.get("evidence_categories", ())),
                privacy_context=str(privacy["object"]) if privacy else "normal",
            )
        return PresenceDecision(
            status="unknown",
            occupant_id=occupant_id,
            room_id="",
            confidence=0.0,
            observed_at=now,
            freshness_seconds=None,
            evidence_categories=(),
            privacy_context="unknown",
            reason="no_persisted_presence",
        )
