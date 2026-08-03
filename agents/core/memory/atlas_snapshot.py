"""Typed, read-only Atlas projections over the existing bi-temporal store.

This module is the bounded E2.0 compatibility seam. It does not introduce a
new database, mutate the source store, merge identities, or promote inferred
content to fact. Legacy facts are projected with explicit provenance,
confidence and privacy defaults. A trusted authorizer grants an effective
privacy scope before the source store is read, then immutable snapshot values
are returned.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

PrivacyClass = Literal["public", "personal", "private_local", "restricted"]
TemporalAxis = Literal["valid", "known"]
ConfidenceStatus = Literal["measured", "unknown"]

_ALLOWED_PRIVACY_CLASSES = {
    "public",
    "personal",
    "private_local",
    "restricted",
}
_ALLOWED_TEMPORAL_AXES = {"valid", "known"}
_SHA256_HEX_LENGTH = 64


@dataclass(frozen=True)
class AtlasConfidence:
    """Qualified confidence that never turns missing evidence into a number."""

    status: ConfidenceStatus
    value: float | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if self.status == "unknown":
            if self.value is not None or self.source is not None:
                raise ValueError("unknown Atlas confidence cannot carry evidence")
            return
        if self.status != "measured":
            raise ValueError("unsupported Atlas confidence status")
        if self.value is None or not math.isfinite(float(self.value)):
            raise ValueError("measured Atlas confidence requires a finite value")
        if not 0.0 <= float(self.value) <= 1.0:
            raise ValueError("Atlas confidence must be between 0 and 1")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("measured Atlas confidence requires a source")


@dataclass(frozen=True)
class AtlasSourceRef:
    """Stable pointer to the canonical source record."""

    source_id: str
    record_id: str
    source_kind: str

    def __post_init__(self) -> None:
        _require_non_empty(self.source_id, "source_id")
        _require_non_empty(self.record_id, "record_id")
        _require_non_empty(self.source_kind, "source_kind")


@dataclass(frozen=True)
class AtlasDeletionLineage:
    """Deletion/export traversal contract for a derived Atlas projection."""

    source_record_id: str
    derived_record_ids: tuple[str, ...]
    propagates_to: tuple[str, ...] = ("atlas_snapshot_projection",)
    tombstoned: bool = False
    deleted_at: float | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.source_record_id, "source_record_id")
        if not isinstance(self.derived_record_ids, tuple):
            raise ValueError("Atlas derived_record_ids must be an immutable tuple")
        if not isinstance(self.propagates_to, tuple):
            raise ValueError("Atlas propagates_to must be an immutable tuple")
        if not self.derived_record_ids:
            raise ValueError("Atlas lineage requires at least one derived record")
        for value in (*self.derived_record_ids, *self.propagates_to):
            _require_non_empty(value, "lineage identifier")
        if self.deleted_at is not None:
            _validate_time(self.deleted_at, "deleted_at")
            if not self.tombstoned:
                raise ValueError("deleted_at requires an explicit tombstone")


@dataclass(frozen=True)
class AtlasObservation:
    """Immutable ``nerva.observation.v1`` projection of one source fact."""

    observation_id: str
    entity_id: str
    subject: str
    predicate: str
    value: str
    valid_from: float
    valid_to: float | None
    ingested_at: float
    invalidated_at: float | None
    source: AtlasSourceRef
    confidence: AtlasConfidence
    privacy_class: PrivacyClass
    lineage: AtlasDeletionLineage
    integrity_sha256: str
    schema: str = field(default="nerva.observation.v1", init=False)

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "entity_id",
            "subject",
            "predicate",
            "value",
            "integrity_sha256",
        ):
            _require_non_empty(getattr(self, name), name)
        if not isinstance(self.source, AtlasSourceRef):
            raise ValueError("Atlas observation source must be AtlasSourceRef")
        if not isinstance(self.confidence, AtlasConfidence):
            raise ValueError("Atlas observation confidence must be AtlasConfidence")
        if not isinstance(self.lineage, AtlasDeletionLineage):
            raise ValueError("Atlas observation lineage must be AtlasDeletionLineage")
        _validate_privacy_class(self.privacy_class)
        _validate_time(self.valid_from, "valid_from")
        _validate_time(self.ingested_at, "ingested_at")
        if self.valid_to is not None:
            _validate_time(self.valid_to, "valid_to")
            if self.valid_to < self.valid_from:
                raise ValueError("valid_to cannot precede valid_from")
        if self.invalidated_at is not None:
            _validate_time(self.invalidated_at, "invalidated_at")
        _validate_sha256_hex(self.integrity_sha256, "integrity_sha256")

    def canonical_payload(
        self,
        *,
        include_integrity: bool = True,
    ) -> dict[str, Any]:
        payload = asdict(self)
        if not include_integrity:
            payload.pop("integrity_sha256", None)
        return payload

    def verify_integrity(self) -> bool:
        payload = self.canonical_payload(include_integrity=False)
        return self.integrity_sha256 == _sha256(payload)


@dataclass(frozen=True)
class AtlasQuery:
    """Requested temporal and privacy scope for one bounded snapshot."""

    temporal_axis: TemporalAxis
    at: float
    requested_privacy_classes: tuple[PrivacyClass, ...]
    subject: str = ""
    predicate: str = ""
    limit: int = 100

    def __post_init__(self) -> None:
        if self.temporal_axis not in _ALLOWED_TEMPORAL_AXES:
            raise ValueError("Atlas temporal_axis must be valid or known")
        _validate_time(self.at, "query at")
        normalized_scope = _validated_privacy_scope(
            self.requested_privacy_classes,
            "requested privacy scope",
        )
        object.__setattr__(self, "requested_privacy_classes", normalized_scope)
        if not isinstance(self.subject, str) or not isinstance(self.predicate, str):
            raise ValueError("Atlas subject and predicate filters must be strings")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool):
            raise ValueError("Atlas query limit must be an integer")
        if not 1 <= self.limit <= 1000:
            raise ValueError("Atlas query limit must be between 1 and 1000")

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AtlasAccessGrant:
    """Trusted authorizer result for one principal and requested scope."""

    grant_id: str
    principal_id: str
    granted_privacy_classes: tuple[PrivacyClass, ...]
    issued_by: str
    schema: str = field(default="nerva.atlas.access_grant.v1", init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.grant_id, "grant_id")
        _require_non_empty(self.principal_id, "principal_id")
        _require_non_empty(self.issued_by, "issued_by")
        normalized_scope = _validated_privacy_scope(
            self.granted_privacy_classes,
            "granted privacy scope",
        )
        object.__setattr__(self, "granted_privacy_classes", normalized_scope)

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


class AtlasAccessAuthorizer(Protocol):
    """Trusted composition seam that grants or denies Atlas read scope."""

    def authorize(
        self,
        principal_id: str,
        requested_privacy_classes: tuple[PrivacyClass, ...],
    ) -> AtlasAccessGrant: ...


@dataclass(frozen=True)
class AtlasSnapshot:
    """Immutable, bounded ``nerva.atlas.snapshot.v1`` query result."""

    snapshot_id: str
    query: AtlasQuery
    access_grant: AtlasAccessGrant
    observations: tuple[AtlasObservation, ...]
    eligible_count: int
    truncated_count: int
    schema: str = field(default="nerva.atlas.snapshot.v1", init=False)
    authority: str = field(default="read_only", init=False)
    can_mutate: bool = field(default=False, init=False)
    can_authorize: bool = field(default=False, init=False)
    can_execute: bool = field(default=False, init=False)
    can_mark_complete: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_non_empty(self.snapshot_id, "snapshot_id")
        if not isinstance(self.query, AtlasQuery):
            raise ValueError("Atlas snapshot query must be AtlasQuery")
        if not isinstance(self.access_grant, AtlasAccessGrant):
            raise ValueError("Atlas snapshot access_grant must be AtlasAccessGrant")
        if not isinstance(self.observations, tuple):
            raise ValueError("Atlas snapshot observations must be an immutable tuple")

        requested = set(self.query.requested_privacy_classes)
        granted = set(self.access_grant.granted_privacy_classes)
        if not requested.issubset(granted):
            raise ValueError("Atlas snapshot query exceeds its trusted access grant")

        observation_ids: set[str] = set()
        for observation in self.observations:
            if not isinstance(observation, AtlasObservation):
                raise ValueError("Atlas snapshot values must be AtlasObservation")
            if observation.observation_id in observation_ids:
                raise ValueError(
                    "Atlas snapshot cannot contain duplicate observation IDs"
                )
            observation_ids.add(observation.observation_id)
            if observation.privacy_class not in requested:
                raise ValueError(
                    "Atlas observation is outside the requested privacy scope"
                )
            if observation.privacy_class not in granted:
                raise ValueError(
                    "Atlas observation is outside the granted privacy scope"
                )
            if not observation.verify_integrity():
                raise ValueError("Atlas observation integrity verification failed")
            if not _observation_matches_query(observation, self.query):
                raise ValueError("Atlas observation is outside the snapshot query")

        expected_order = tuple(sorted(self.observations, key=_observation_sort_key))
        if self.observations != expected_order:
            raise ValueError(
                "Atlas snapshot observations are not deterministically ordered"
            )

        for value, name in (
            (self.eligible_count, "eligible_count"),
            (self.truncated_count, "truncated_count"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"Atlas {name} must be a non-negative integer")
        if len(self.observations) > self.query.limit:
            raise ValueError("Atlas snapshot exceeds the query limit")
        if len(self.observations) + self.truncated_count != self.eligible_count:
            raise ValueError("Atlas snapshot counts do not match eligible records")

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def replay_fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LegacyProjectionPolicy:
    """Explicit defaults for facts that predate Atlas metadata."""

    source_id: str = "legacy.bitemporal"
    default_privacy_class: PrivacyClass = "private_local"
    default_confidence: AtlasConfidence = field(
        default_factory=lambda: AtlasConfidence("unknown")
    )

    def __post_init__(self) -> None:
        _require_non_empty(self.source_id, "source_id")
        _validate_privacy_class(self.default_privacy_class)


PrivacyResolver = Callable[[Mapping[str, Any]], PrivacyClass]
ConfidenceResolver = Callable[[Mapping[str, Any]], AtlasConfidence]


class LegacyBiTemporalAdapter:
    """Project current BiTemporalKG dictionaries without modifying them."""

    def __init__(
        self,
        policy: LegacyProjectionPolicy | None = None,
        *,
        privacy_resolver: PrivacyResolver | None = None,
        confidence_resolver: ConfidenceResolver | None = None,
    ) -> None:
        self._policy = policy or LegacyProjectionPolicy()
        self._privacy_resolver = privacy_resolver
        self._confidence_resolver = confidence_resolver

    def project(self, fact: Mapping[str, Any]) -> AtlasObservation:
        fact_id = _fact_identifier(fact)
        subject = _fact_string(fact, "subject")
        predicate = _fact_string(fact, "predicate")
        value = _fact_string(fact, "object")
        valid_from = _fact_time(fact, "valid_from")
        ingested_at = _fact_time(fact, "ingested_at")
        valid_to = _optional_fact_time(fact, "valid_to")
        invalidated_at = _optional_fact_time(fact, "invalidated_at")

        privacy_class = (
            self._privacy_resolver(fact)
            if self._privacy_resolver is not None
            else self._policy.default_privacy_class
        )
        _validate_privacy_class(privacy_class)
        confidence = (
            self._confidence_resolver(fact)
            if self._confidence_resolver is not None
            else self._policy.default_confidence
        )
        if not isinstance(confidence, AtlasConfidence):
            raise ValueError("Atlas confidence resolver must return AtlasConfidence")

        source_record_id = f"{self._policy.source_id}:{fact_id}"
        observation_id = "atlas:observation:" + _sha256(source_record_id)[:24]
        entity_material = {
            "source_id": self._policy.source_id,
            "subject": _normalize_identifier(subject),
        }
        entity_id = "atlas:entity:" + _sha256(entity_material)[:24]
        source = AtlasSourceRef(
            source_id=self._policy.source_id,
            record_id=source_record_id,
            source_kind="bitemporal_fact",
        )
        lineage = AtlasDeletionLineage(
            source_record_id=source_record_id,
            derived_record_ids=(observation_id,),
        )
        material = {
            "observation_id": observation_id,
            "entity_id": entity_id,
            "subject": subject,
            "predicate": predicate,
            "value": value,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "ingested_at": ingested_at,
            "invalidated_at": invalidated_at,
            "source": asdict(source),
            "confidence": asdict(confidence),
            "privacy_class": privacy_class,
            "lineage": asdict(lineage),
            "schema": "nerva.observation.v1",
        }
        return AtlasObservation(
            observation_id=observation_id,
            entity_id=entity_id,
            subject=subject,
            predicate=predicate,
            value=value,
            valid_from=valid_from,
            valid_to=valid_to,
            ingested_at=ingested_at,
            invalidated_at=invalidated_at,
            source=source,
            confidence=confidence,
            privacy_class=privacy_class,
            lineage=lineage,
            integrity_sha256=_sha256(material),
        )


class BiTemporalReadProtocol(Protocol):
    def as_of(
        self,
        at: float | None = None,
        subject: str = "",
        predicate: str = "",
    ) -> list[dict[str, Any]]: ...

    def known_as_of(
        self,
        at: float,
        subject: str = "",
        predicate: str = "",
    ) -> list[dict[str, Any]]: ...


class AtlasSnapshotReader:
    """Read-only adapter that returns values, never a writable store handle."""

    __slots__ = ("__read_store", "__adapter", "__authorizer")

    def __init__(
        self,
        read_store: BiTemporalReadProtocol,
        authorizer: AtlasAccessAuthorizer,
        adapter: LegacyBiTemporalAdapter | None = None,
    ) -> None:
        if not callable(getattr(read_store, "as_of", None)):
            raise ValueError("Atlas read store must provide as_of")
        if not callable(getattr(read_store, "known_as_of", None)):
            raise ValueError("Atlas read store must provide known_as_of")
        if not callable(getattr(authorizer, "authorize", None)):
            raise ValueError("Atlas reader requires a trusted access authorizer")
        self.__read_store = read_store
        self.__adapter = adapter or LegacyBiTemporalAdapter()
        self.__authorizer = authorizer

    def snapshot(self, query: AtlasQuery, *, principal_id: str) -> AtlasSnapshot:
        if not isinstance(query, AtlasQuery):
            raise ValueError("Atlas snapshot requires an AtlasQuery")
        _require_non_empty(principal_id, "principal_id")

        access_grant = self.__authorizer.authorize(
            principal_id,
            query.requested_privacy_classes,
        )
        if not isinstance(access_grant, AtlasAccessGrant):
            raise PermissionError(
                "Atlas authorizer did not return a trusted access grant"
            )
        if access_grant.principal_id != principal_id:
            raise PermissionError(
                "Atlas access grant principal does not match the caller"
            )
        requested = set(query.requested_privacy_classes)
        granted = set(access_grant.granted_privacy_classes)
        if not requested.issubset(granted):
            raise PermissionError("Atlas requested privacy scope is not granted")

        if query.temporal_axis == "valid":
            facts = self.__read_store.as_of(
                query.at,
                subject=query.subject,
                predicate=query.predicate,
            )
        else:
            facts = self.__read_store.known_as_of(
                query.at,
                subject=query.subject,
                predicate=query.predicate,
            )
        if not isinstance(facts, Sequence):
            raise ValueError("Atlas read store must return a sequence")

        projected: list[AtlasObservation] = []
        for fact in facts:
            if not isinstance(fact, Mapping):
                raise ValueError("Atlas source records must be mappings")
            observation = self.__adapter.project(fact)
            if observation.privacy_class in requested:
                projected.append(observation)

        projected.sort(key=_observation_sort_key)
        eligible_count = len(projected)
        truncated_count = max(0, eligible_count - query.limit)
        observations = tuple(projected[: query.limit])
        snapshot_material = {
            "query": query.canonical_payload(),
            "access_grant": access_grant.canonical_payload(),
            "observation_integrity": tuple(
                observation.integrity_sha256 for observation in observations
            ),
            "eligible_count": eligible_count,
            "truncated_count": truncated_count,
            "schema": "nerva.atlas.snapshot.v1",
        }
        snapshot_id = "atlas:snapshot:" + _sha256(snapshot_material)[:24]
        return AtlasSnapshot(
            snapshot_id=snapshot_id,
            query=query,
            access_grant=access_grant,
            observations=observations,
            eligible_count=eligible_count,
            truncated_count=truncated_count,
        )


def _observation_sort_key(observation: AtlasObservation) -> tuple[float, float, str]:
    return (
        observation.valid_from,
        observation.ingested_at,
        observation.observation_id,
    )


def _observation_matches_query(
    observation: AtlasObservation,
    query: AtlasQuery,
) -> bool:
    if query.subject and observation.subject != query.subject:
        return False
    if query.predicate and observation.predicate != query.predicate:
        return False
    if query.temporal_axis == "valid":
        return observation.valid_from <= query.at and (
            observation.valid_to is None or query.at < observation.valid_to
        )
    return observation.ingested_at <= query.at


def _fact_identifier(fact: Mapping[str, Any]) -> str:
    value = fact.get("id")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("legacy bi-temporal fact id must be an integer or string")
    return str(value)


def _fact_string(fact: Mapping[str, Any], key: str) -> str:
    value = fact.get(key)
    _require_non_empty(value, f"legacy fact {key}")
    return value


def _fact_time(fact: Mapping[str, Any], key: str) -> float:
    value = fact.get(key)
    _validate_time(value, f"legacy fact {key}")
    return float(value)


def _optional_fact_time(fact: Mapping[str, Any], key: str) -> float | None:
    value = fact.get(key)
    if value is None:
        return None
    _validate_time(value, f"legacy fact {key}")
    return float(value)


def _require_non_empty(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Atlas {name} must be a non-empty string")


def _validated_privacy_scope(
    value: Any,
    name: str,
) -> tuple[PrivacyClass, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"Atlas {name} must be an immutable tuple")
    if not value:
        raise ValueError(f"Atlas {name} cannot be empty")
    if len(set(value)) != len(value):
        raise ValueError(f"Atlas {name} cannot contain duplicates")
    for privacy_class in value:
        _validate_privacy_class(privacy_class)
    return tuple(sorted(value))


def _validate_privacy_class(value: Any) -> None:
    if value not in _ALLOWED_PRIVACY_CLASSES:
        raise ValueError("Atlas privacy class is not recognized")


def _validate_sha256_hex(value: Any, name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"Atlas {name} must be a SHA-256 hex digest")
    if len(value) != _SHA256_HEX_LENGTH:
        raise ValueError(f"Atlas {name} must be a SHA-256 hex digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"Atlas {name} must be a SHA-256 hex digest")


def _validate_time(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Atlas {name} must be numeric")
    if not math.isfinite(float(value)):
        raise ValueError(f"Atlas {name} must be finite")


def _normalize_identifier(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _sha256(value: Any) -> str:
    if not isinstance(value, str):
        value = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
