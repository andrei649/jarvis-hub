"""Immutable typed values for the bounded Nerva Episodes E3.0 contract."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from agents.core.memory.atlas_snapshot import (
    AtlasConfidence,
    AtlasObservation,
    PrivacyClass,
)

EpisodeState = Literal["open", "settled", "consolidated", "superseded"]
EpisodeReferenceRole = Literal["source", "decision", "action", "outcome"]
EpisodeAssertionKind = Literal["direct", "inference"]
EpisodeOperation = Literal[
    "open",
    "settle",
    "consolidate",
    "correct",
    "merge",
    "split",
    "tombstone",
    "migrate",
]

_ALLOWED_STATES = {"open", "settled", "consolidated", "superseded"}
_ALLOWED_REFERENCE_ROLES = {"source", "decision", "action", "outcome"}
_ALLOWED_ASSERTION_KINDS = {"direct", "inference"}
_ALLOWED_PRIVACY_CLASSES = {"public", "personal", "private_local", "restricted"}
_SETTLEMENT_CONFIDENCE_FLOOR = 0.75
_MAX_ASSERTION_TEXT_CHARS = 4096
_SHA256_HEX_LENGTH = 64
_FORBIDDEN_RAW_KEYS = {
    "content",
    "messages",
    "raw",
    "raw_text",
    "raw_transcript",
    "transcript",
    "turns",
}


@dataclass(frozen=True)
class EpisodeReference:
    """Content-free pointer to one canonical source or lifecycle record."""

    reference_id: str
    role: EpisodeReferenceRole
    source_id: str
    record_id: str
    source_kind: str
    source_schema: str
    privacy_class: PrivacyClass
    integrity_sha256: str
    occurred_at: float
    deletion_root_id: str
    confidence: AtlasConfidence
    projection_id: str | None = None
    tombstoned: bool = False
    deleted_at: float | None = None
    schema: str = field(default="nerva.episode.reference.v1", init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.reference_id, "reference_id"),
            (self.source_id, "source_id"),
            (self.record_id, "record_id"),
            (self.source_kind, "source_kind"),
            (self.source_schema, "source_schema"),
            (self.deletion_root_id, "deletion_root_id"),
        ):
            _require_non_empty(value, name)
        if self.role not in _ALLOWED_REFERENCE_ROLES:
            raise ValueError("Episode reference role is not recognized")
        _validate_privacy_class(self.privacy_class)
        _validate_sha256_hex(self.integrity_sha256, "integrity_sha256")
        _validate_time(self.occurred_at, "occurred_at")
        if not isinstance(self.confidence, AtlasConfidence):
            raise ValueError("Episode reference confidence must be AtlasConfidence")
        if self.projection_id is not None:
            _require_non_empty(self.projection_id, "projection_id")
        if self.deleted_at is not None:
            _validate_time(self.deleted_at, "deleted_at")
            if self.deleted_at < self.occurred_at:
                raise ValueError("Episode deleted_at cannot precede source occurrence")
            if not self.tombstoned:
                raise ValueError("Episode deleted_at requires an explicit tombstone")
        if self.tombstoned and self.deleted_at is None:
            raise ValueError("Episode tombstoned reference requires deleted_at")
        if self.reference_id != self.expected_reference_id:
            raise ValueError("Episode reference_id does not match canonical metadata")

    @classmethod
    def build(
        cls,
        *,
        role: EpisodeReferenceRole,
        source_id: str,
        record_id: str,
        source_kind: str,
        source_schema: str,
        privacy_class: PrivacyClass,
        integrity_sha256: str,
        occurred_at: float,
        deletion_root_id: str,
        confidence: AtlasConfidence,
        projection_id: str | None = None,
        tombstoned: bool = False,
        deleted_at: float | None = None,
    ) -> EpisodeReference:
        material = {
            "role": role,
            "source_id": source_id,
            "record_id": record_id,
            "source_kind": source_kind,
            "source_schema": source_schema,
            "projection_id": projection_id,
        }
        reference_id = "episode:ref:" + _sha256(material)[:24]
        return cls(
            reference_id=reference_id,
            role=role,
            source_id=source_id,
            record_id=record_id,
            source_kind=source_kind,
            source_schema=source_schema,
            privacy_class=privacy_class,
            integrity_sha256=integrity_sha256,
            occurred_at=occurred_at,
            deletion_root_id=deletion_root_id,
            confidence=confidence,
            projection_id=projection_id,
            tombstoned=tombstoned,
            deleted_at=deleted_at,
        )

    @classmethod
    def from_atlas(
        cls,
        observation: AtlasObservation,
        *,
        role: EpisodeReferenceRole = "source",
    ) -> EpisodeReference:
        if not isinstance(observation, AtlasObservation):
            raise ValueError("Episode Atlas reference requires AtlasObservation")
        if not observation.verify_integrity():
            raise ValueError("Episode Atlas observation integrity verification failed")
        return cls.build(
            role=role,
            source_id=observation.source.source_id,
            record_id=observation.source.record_id,
            source_kind=observation.source.source_kind,
            source_schema=observation.schema,
            privacy_class=observation.privacy_class,
            integrity_sha256=observation.integrity_sha256,
            occurred_at=observation.valid_from,
            deletion_root_id=observation.lineage.source_record_id,
            confidence=observation.confidence,
            projection_id=observation.observation_id,
        )

    @property
    def expected_reference_id(self) -> str:
        material = {
            "role": self.role,
            "source_id": self.source_id,
            "record_id": self.record_id,
            "source_kind": self.source_kind,
            "source_schema": self.source_schema,
            "projection_id": self.projection_id,
        }
        return "episode:ref:" + _sha256(material)[:24]

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EpisodeAssertion:
    """Derived episode text with explicit evidence and inference status."""

    assertion_id: str
    kind: EpisodeAssertionKind
    text: str
    evidence_reference_ids: tuple[str, ...]
    confidence: AtlasConfidence
    schema: str = field(default="nerva.episode.assertion.v1", init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.assertion_id, "assertion_id")
        _require_non_empty(self.text, "assertion text")
        if len(self.text) > _MAX_ASSERTION_TEXT_CHARS:
            raise ValueError("Episode assertion text exceeds 4096 characters")
        if self.kind not in _ALLOWED_ASSERTION_KINDS:
            raise ValueError("Episode assertion kind is not recognized")
        refs = _validated_string_tuple(
            self.evidence_reference_ids,
            "assertion evidence references",
            allow_empty=False,
        )
        object.__setattr__(self, "evidence_reference_ids", refs)
        if not isinstance(self.confidence, AtlasConfidence):
            raise ValueError("Episode assertion confidence must be AtlasConfidence")
        if self.kind == "inference" and self.confidence.status != "measured":
            raise ValueError("Episode inference requires measured confidence")
        if self.assertion_id != self.expected_assertion_id:
            raise ValueError("Episode assertion_id does not match canonical content")

    @classmethod
    def build(
        cls,
        *,
        kind: EpisodeAssertionKind,
        text: str,
        evidence_reference_ids: tuple[str, ...],
        confidence: AtlasConfidence,
    ) -> EpisodeAssertion:
        refs = _validated_string_tuple(
            evidence_reference_ids,
            "assertion evidence references",
            allow_empty=False,
        )
        material = {
            "kind": kind,
            "text": text,
            "evidence_reference_ids": refs,
            "confidence": asdict(confidence),
        }
        assertion_id = "episode:assertion:" + _sha256(material)[:24]
        return cls(
            assertion_id=assertion_id,
            kind=kind,
            text=text,
            evidence_reference_ids=refs,
            confidence=confidence,
        )

    @property
    def expected_assertion_id(self) -> str:
        material = {
            "kind": self.kind,
            "text": self.text,
            "evidence_reference_ids": self.evidence_reference_ids,
            "confidence": asdict(self.confidence),
        }
        return "episode:assertion:" + _sha256(material)[:24]

    def eligible_for_settlement(
        self,
        floor: float = _SETTLEMENT_CONFIDENCE_FLOOR,
    ) -> bool:
        if self.kind == "direct":
            return True
        return (
            self.confidence.status == "measured"
            and self.confidence.value is not None
            and float(self.confidence.value) >= floor
        )

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EpisodeRecord:
    """Immutable revision of one logical ``nerva.episode.v1`` episode."""

    episode_id: str
    record_id: str
    revision: int
    state: EpisodeState
    participants: tuple[str, ...]
    started_at: float
    ended_at: float | None
    references: tuple[EpisodeReference, ...]
    goal: EpisodeAssertion | None
    summary: EpisodeAssertion | None
    significance: EpisodeAssertion | None
    parent_episode_ids: tuple[str, ...]
    supersedes_record_id: str | None
    superseded_by_episode_ids: tuple[str, ...]
    created_at: float
    updated_at: float
    integrity_sha256: str
    schema: str = field(default="nerva.episode.v1", init=False)
    authority: str = field(default="memory_record_only", init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.episode_id, "episode_id")
        _require_non_empty(self.record_id, "record_id")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool):
            raise ValueError("Episode revision must be an integer")
        if self.revision < 1:
            raise ValueError("Episode revision must be positive")
        if self.state not in _ALLOWED_STATES:
            raise ValueError("Episode state is not recognized")
        participants = _validated_string_tuple(
            self.participants,
            "participants",
            allow_empty=False,
        )
        object.__setattr__(self, "participants", participants)
        _validate_time(self.started_at, "started_at")
        _validate_time(self.created_at, "created_at")
        _validate_time(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("Episode updated_at cannot precede created_at")
        if self.ended_at is not None:
            _validate_time(self.ended_at, "ended_at")
            if self.ended_at < self.started_at:
                raise ValueError("Episode ended_at cannot precede started_at")
            if self.ended_at > self.updated_at:
                raise ValueError("Episode ended_at cannot follow updated_at")
        if self.state == "open" and self.ended_at is not None:
            raise ValueError("Open episode cannot have ended_at")
        if self.state in {"settled", "consolidated"} and self.ended_at is None:
            raise ValueError("Settled or consolidated episode requires ended_at")
        if not isinstance(self.references, tuple):
            raise ValueError("Episode references must be an immutable tuple")
        reference_ids: set[str] = set()
        for reference in self.references:
            if not isinstance(reference, EpisodeReference):
                raise ValueError("Episode references must contain EpisodeReference")
            if reference.reference_id in reference_ids:
                raise ValueError("Episode references cannot contain duplicate IDs")
            reference_ids.add(reference.reference_id)
        expected_references = tuple(sorted(self.references, key=_reference_sort_key))
        if self.references != expected_references:
            raise ValueError("Episode references are not deterministically ordered")
        if not any(reference.role == "source" for reference in self.references):
            raise ValueError("Episode requires at least one source reference")
        tombstoned_ids = {
            reference.reference_id
            for reference in self.references
            if reference.tombstoned
        }
        for assertion in (self.goal, self.summary, self.significance):
            if assertion is None:
                continue
            if not isinstance(assertion, EpisodeAssertion):
                raise ValueError("Episode statements must be EpisodeAssertion")
            missing = set(assertion.evidence_reference_ids) - reference_ids
            if missing:
                raise ValueError("Episode assertion references unknown evidence")
            if set(assertion.evidence_reference_ids) & tombstoned_ids:
                raise ValueError("Episode assertion retains tombstoned evidence")
            if self.state in {"settled", "consolidated"} and not assertion.eligible_for_settlement():
                raise ValueError(
                    "Low-confidence inference cannot be promoted to settled history"
                )
        parents = _validated_string_tuple(
            self.parent_episode_ids,
            "parent_episode_ids",
            allow_empty=True,
        )
        object.__setattr__(self, "parent_episode_ids", parents)
        successors = _validated_string_tuple(
            self.superseded_by_episode_ids,
            "superseded_by_episode_ids",
            allow_empty=True,
        )
        object.__setattr__(self, "superseded_by_episode_ids", successors)
        if self.supersedes_record_id is not None:
            _require_non_empty(self.supersedes_record_id, "supersedes_record_id")
        if self.revision == 1 and self.supersedes_record_id is not None:
            raise ValueError("First episode revision cannot supersede another record")
        if self.revision > 1 and self.supersedes_record_id is None:
            raise ValueError("Later episode revision must name superseded record")
        if self.state == "superseded" and not self.superseded_by_episode_ids:
            raise ValueError("Superseded episode requires successor episode IDs")
        if self.state != "superseded" and self.superseded_by_episode_ids:
            raise ValueError("Only superseded episodes can name successor episodes")
        _validate_sha256_hex(self.integrity_sha256, "integrity_sha256")
        if self.record_id != self.expected_record_id:
            raise ValueError("Episode record_id does not match canonical record")
        if not self.verify_integrity():
            raise ValueError("Episode record integrity verification failed")

    @classmethod
    def build(
        cls,
        *,
        state: EpisodeState,
        participants: tuple[str, ...],
        started_at: float,
        ended_at: float | None,
        references: tuple[EpisodeReference, ...],
        goal: EpisodeAssertion | None,
        summary: EpisodeAssertion | None,
        significance: EpisodeAssertion | None,
        created_at: float,
        updated_at: float,
        episode_id: str | None = None,
        revision: int = 1,
        parent_episode_ids: tuple[str, ...] = (),
        supersedes_record_id: str | None = None,
        superseded_by_episode_ids: tuple[str, ...] = (),
    ) -> EpisodeRecord:
        participants = _validated_string_tuple(
            participants,
            "participants",
            allow_empty=False,
        )
        references = tuple(sorted(references, key=_reference_sort_key))
        parent_episode_ids = _validated_string_tuple(
            parent_episode_ids,
            "parent_episode_ids",
            allow_empty=True,
        )
        superseded_by_episode_ids = _validated_string_tuple(
            superseded_by_episode_ids,
            "superseded_by_episode_ids",
            allow_empty=True,
        )
        if episode_id is None:
            identity_material = {
                "participants": participants,
                "started_at": float(started_at),
                "reference_ids": tuple(
                    reference.reference_id for reference in references
                ),
                "parent_episode_ids": parent_episode_ids,
            }
            episode_id = "episode:" + _sha256(identity_material)[:24]
        material = _record_material(
            episode_id=episode_id,
            revision=revision,
            state=state,
            participants=participants,
            started_at=float(started_at),
            ended_at=None if ended_at is None else float(ended_at),
            references=references,
            goal=goal,
            summary=summary,
            significance=significance,
            parent_episode_ids=parent_episode_ids,
            supersedes_record_id=supersedes_record_id,
            superseded_by_episode_ids=superseded_by_episode_ids,
            created_at=float(created_at),
            updated_at=float(updated_at),
        )
        record_id = "episode:record:" + _sha256(material)[:24]
        integrity_sha256 = _sha256({**material, "record_id": record_id})
        return cls(
            episode_id=episode_id,
            record_id=record_id,
            revision=revision,
            state=state,
            participants=participants,
            started_at=float(started_at),
            ended_at=None if ended_at is None else float(ended_at),
            references=references,
            goal=goal,
            summary=summary,
            significance=significance,
            parent_episode_ids=parent_episode_ids,
            supersedes_record_id=supersedes_record_id,
            superseded_by_episode_ids=superseded_by_episode_ids,
            created_at=float(created_at),
            updated_at=float(updated_at),
            integrity_sha256=integrity_sha256,
        )

    @property
    def expected_record_id(self) -> str:
        return "episode:record:" + _sha256(self.record_material())[:24]

    def record_material(self) -> dict[str, Any]:
        return _record_material(
            episode_id=self.episode_id,
            revision=self.revision,
            state=self.state,
            participants=self.participants,
            started_at=self.started_at,
            ended_at=self.ended_at,
            references=self.references,
            goal=self.goal,
            summary=self.summary,
            significance=self.significance,
            parent_episode_ids=self.parent_episode_ids,
            supersedes_record_id=self.supersedes_record_id,
            superseded_by_episode_ids=self.superseded_by_episode_ids,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    def canonical_payload(self, *, include_integrity: bool = True) -> dict[str, Any]:
        payload = {**self.record_material(), "record_id": self.record_id}
        payload.update(
            {
                "schema": self.schema,
                "authority": self.authority,
                "can_authorize": self.can_authorize,
                "can_execute": self.can_execute,
                "can_mark_complete": self.can_mark_complete,
            }
        )
        if include_integrity:
            payload["integrity_sha256"] = self.integrity_sha256
        return payload

    def verify_integrity(self) -> bool:
        return self.integrity_sha256 == _sha256(
            {**self.record_material(), "record_id": self.record_id}
        )

    def to_json(self) -> str:
        return json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, value: str) -> EpisodeRecord:
        if not isinstance(value, str):
            raise ValueError("Episode JSON must be a string")
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Episode JSON is invalid") from exc
        return cls.from_payload(payload)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> EpisodeRecord:
        if not isinstance(payload, dict):
            raise ValueError("Episode payload must be an object")
        if payload.get("schema") != "nerva.episode.v1":
            raise ValueError("Unsupported episode schema")
        if payload.get("authority") != "memory_record_only":
            raise ValueError("Episode payload authority is not memory_record_only")
        for flag in ("can_authorize", "can_execute", "can_mark_complete"):
            if payload.get(flag) is not False:
                raise ValueError("Episode payload attempts to expand authority")
        try:
            references = tuple(
                _reference_from_payload(item) for item in payload["references"]
            )
            goal = _assertion_from_payload(payload.get("goal"))
            summary = _assertion_from_payload(payload.get("summary"))
            significance = _assertion_from_payload(payload.get("significance"))
            return cls(
                episode_id=payload["episode_id"],
                record_id=payload["record_id"],
                revision=payload["revision"],
                state=payload["state"],
                participants=tuple(payload["participants"]),
                started_at=payload["started_at"],
                ended_at=payload.get("ended_at"),
                references=references,
                goal=goal,
                summary=summary,
                significance=significance,
                parent_episode_ids=tuple(payload.get("parent_episode_ids", ())),
                supersedes_record_id=payload.get("supersedes_record_id"),
                superseded_by_episode_ids=tuple(
                    payload.get("superseded_by_episode_ids", ())
                ),
                created_at=payload["created_at"],
                updated_at=payload["updated_at"],
                integrity_sha256=payload["integrity_sha256"],
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("Episode payload is malformed") from exc

    @property
    def source_references(self) -> tuple[EpisodeReference, ...]:
        return tuple(ref for ref in self.references if ref.role == "source")

    @property
    def decision_references(self) -> tuple[EpisodeReference, ...]:
        return tuple(ref for ref in self.references if ref.role == "decision")

    @property
    def action_references(self) -> tuple[EpisodeReference, ...]:
        return tuple(ref for ref in self.references if ref.role == "action")

    @property
    def outcome_references(self) -> tuple[EpisodeReference, ...]:
        return tuple(ref for ref in self.references if ref.role == "outcome")

    @property
    def replay_fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


def _record_material(
    *,
    episode_id: str,
    revision: int,
    state: EpisodeState,
    participants: tuple[str, ...],
    started_at: float,
    ended_at: float | None,
    references: tuple[EpisodeReference, ...],
    goal: EpisodeAssertion | None,
    summary: EpisodeAssertion | None,
    significance: EpisodeAssertion | None,
    parent_episode_ids: tuple[str, ...],
    supersedes_record_id: str | None,
    superseded_by_episode_ids: tuple[str, ...],
    created_at: float,
    updated_at: float,
) -> dict[str, Any]:
    return {
        "episode_id": episode_id,
        "revision": revision,
        "state": state,
        "participants": participants,
        "started_at": started_at,
        "ended_at": ended_at,
        "references": tuple(reference.canonical_payload() for reference in references),
        "goal": None if goal is None else goal.canonical_payload(),
        "summary": None if summary is None else summary.canonical_payload(),
        "significance": None
        if significance is None
        else significance.canonical_payload(),
        "parent_episode_ids": parent_episode_ids,
        "supersedes_record_id": supersedes_record_id,
        "superseded_by_episode_ids": superseded_by_episode_ids,
        "created_at": created_at,
        "updated_at": updated_at,
        "schema": "nerva.episode.v1",
        "authority": "memory_record_only",
        "can_authorize": False,
        "can_execute": False,
        "can_mark_complete": False,
    }


def _reference_from_payload(payload: dict[str, Any]) -> EpisodeReference:
    if not isinstance(payload, dict):
        raise ValueError("Episode reference payload must be an object")
    if payload.get("schema") != "nerva.episode.reference.v1":
        raise ValueError("Unsupported episode reference schema")
    confidence = payload["confidence"]
    return EpisodeReference(
        reference_id=payload["reference_id"],
        role=payload["role"],
        source_id=payload["source_id"],
        record_id=payload["record_id"],
        source_kind=payload["source_kind"],
        source_schema=payload["source_schema"],
        privacy_class=payload["privacy_class"],
        integrity_sha256=payload["integrity_sha256"],
        occurred_at=payload["occurred_at"],
        deletion_root_id=payload["deletion_root_id"],
        confidence=AtlasConfidence(
            confidence["status"],
            confidence.get("value"),
            confidence.get("source"),
        ),
        projection_id=payload.get("projection_id"),
        tombstoned=payload.get("tombstoned", False),
        deleted_at=payload.get("deleted_at"),
    )


def _assertion_from_payload(
    payload: dict[str, Any] | None,
) -> EpisodeAssertion | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("Episode assertion payload must be an object")
    if payload.get("schema") != "nerva.episode.assertion.v1":
        raise ValueError("Unsupported episode assertion schema")
    confidence = payload["confidence"]
    return EpisodeAssertion(
        assertion_id=payload["assertion_id"],
        kind=payload["kind"],
        text=payload["text"],
        evidence_reference_ids=tuple(payload["evidence_reference_ids"]),
        confidence=AtlasConfidence(
            confidence["status"],
            confidence.get("value"),
            confidence.get("source"),
        ),
    )


def _legacy_reference_from_payload(payload: dict[str, Any]) -> EpisodeReference:
    confidence = payload["confidence"]
    return EpisodeReference.build(
        role=payload["role"],
        source_id=payload["source_id"],
        record_id=payload["record_id"],
        source_kind=payload["source_kind"],
        source_schema=payload["source_schema"],
        privacy_class=payload["privacy_class"],
        integrity_sha256=payload["integrity_sha256"],
        occurred_at=payload["occurred_at"],
        deletion_root_id=payload["deletion_root_id"],
        confidence=AtlasConfidence(
            confidence["status"],
            confidence.get("value"),
            confidence.get("source"),
        ),
        projection_id=payload.get("projection_id"),
    )


def _legacy_assertion_from_payload(
    payload: dict[str, Any] | None,
    *,
    reference_aliases: dict[str, str],
) -> EpisodeAssertion | None:
    if payload is None:
        return None
    confidence = payload["confidence"]
    try:
        evidence_reference_ids = tuple(
            reference_aliases[value] for value in payload["evidence_reference_ids"]
        )
    except KeyError as exc:
        raise ValueError("Legacy assertion references unknown evidence alias") from exc
    return EpisodeAssertion.build(
        kind=payload["kind"],
        text=payload["text"],
        evidence_reference_ids=evidence_reference_ids,
        confidence=AtlasConfidence(
            confidence["status"],
            confidence.get("value"),
            confidence.get("source"),
        ),
    )


def _merge_references(
    existing: tuple[EpisodeReference, ...],
    additional: tuple[EpisodeReference, ...],
) -> tuple[EpisodeReference, ...]:
    merged: dict[str, EpisodeReference] = {}
    for reference in (*existing, *additional):
        if not isinstance(reference, EpisodeReference):
            raise ValueError("Episode references must contain EpisodeReference")
        prior = merged.get(reference.reference_id)
        if prior is not None and prior != reference:
            raise ValueError("Episode reference ID collision")
        merged[reference.reference_id] = reference
    return tuple(sorted(merged.values(), key=_reference_sort_key))


def _reference_sort_key(reference: EpisodeReference) -> tuple[str, float, str]:
    return (reference.role, reference.occurred_at, reference.reference_id)


def _require_current_state(
    record: EpisodeRecord,
    allowed: set[str],
    operation: str,
) -> None:
    if not isinstance(record, EpisodeRecord):
        raise ValueError(f"Episode {operation} requires EpisodeRecord")
    if record.state not in allowed:
        raise ValueError(f"Episode {operation} is invalid from state {record.state}")


def _validated_string_tuple(
    value: Any,
    name: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"Episode {name} must be an immutable tuple")
    if not value and not allow_empty:
        raise ValueError(f"Episode {name} cannot be empty")
    normalized: list[str] = []
    for item in value:
        _require_non_empty(item, name)
        normalized.append(item.strip())
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"Episode {name} cannot contain duplicates")
    return tuple(sorted(normalized))


def _require_non_empty(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Episode {name} must be a non-empty string")


def _validate_privacy_class(value: Any) -> None:
    if value not in _ALLOWED_PRIVACY_CLASSES:
        raise ValueError("Episode privacy class is not recognized")


def _validate_sha256_hex(value: Any, name: str) -> None:
    if not isinstance(value, str) or len(value) != _SHA256_HEX_LENGTH:
        raise ValueError(f"Episode {name} must be a SHA-256 hex digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"Episode {name} must be a SHA-256 hex digest")


def _validate_time(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Episode {name} must be numeric")
    if not math.isfinite(float(value)):
        raise ValueError(f"Episode {name} must be finite")


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _reject_raw_content(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in _FORBIDDEN_RAW_KEYS:
                raise ValueError(
                    f"Legacy episode migration rejects raw content at {path}.{key}"
                )
            _reject_raw_content(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_raw_content(item, f"{path}[{index}]")


def _sha256(value: Any) -> str:
    if not isinstance(value, str):
        value = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
