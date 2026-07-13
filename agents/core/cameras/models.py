"""Immutable, bounded camera-domain contracts for H31."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

MAX_SNAPSHOT_TTL_SECONDS = 24 * 60 * 60
MAX_METADATA_TTL_SECONDS = 30 * 24 * 60 * 60

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CAMERA_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_ALLOWED_LABELS = frozenset({"person", "vehicle", "animal", "package"})
_SENSITIVE_EVENT_FIELDS = frozenset(
    {
        "biometric",
        "biometrics",
        "face",
        "face_embedding",
        "face_id",
        "identity",
        "license_plate",
        "name",
        "person_id",
        "person_name",
        "plate",
        "plate_number",
        "sub_label",
    }
)


def _bounded_text(value: Any, *, field_name: str, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    result = value.strip()
    if not allow_empty and not result:
        raise ValueError(f"{field_name} must not be empty")
    if len(result) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")
    return result


def _finite_number(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be a finite number")
    return result


def _safe_id(value: Any, *, field_name: str, camera: bool = False) -> str:
    result = _bounded_text(value, field_name=field_name, maximum=128)
    pattern = _CAMERA_ID_RE if camera else _ID_RE
    if pattern.fullmatch(result) is None:
        raise ValueError(f"{field_name} contains unsafe characters")
    return result


def _orientation(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
) -> float:
    return (second[0] - first[0]) * (third[1] - first[1]) - (
        second[1] - first[1]
    ) * (third[0] - first[0])


def _segments_cross(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
    fourth: tuple[float, float],
) -> bool:
    first_turn = _orientation(first, second, third)
    second_turn = _orientation(first, second, fourth)
    third_turn = _orientation(third, fourth, first)
    fourth_turn = _orientation(third, fourth, second)
    epsilon = 1e-12
    if (
        first_turn * second_turn < -epsilon
        and third_turn * fourth_turn < -epsilon
    ):
        return True

    def _on_segment(
        start: tuple[float, float],
        point: tuple[float, float],
        end: tuple[float, float],
    ) -> bool:
        return (
            min(start[0], end[0]) - epsilon <= point[0] <= max(start[0], end[0]) + epsilon
            and min(start[1], end[1]) - epsilon
            <= point[1]
            <= max(start[1], end[1]) + epsilon
        )

    return (
        (abs(first_turn) <= epsilon and _on_segment(first, third, second))
        or (abs(second_turn) <= epsilon and _on_segment(first, fourth, second))
        or (abs(third_turn) <= epsilon and _on_segment(third, first, fourth))
        or (abs(fourth_turn) <= epsilon and _on_segment(third, second, fourth))
    )


def _is_simple_polygon(points: list[tuple[float, float]]) -> bool:
    if len(set(points)) != len(points):
        return False
    edge_count = len(points)
    for first_index in range(edge_count):
        first = points[first_index]
        second = points[(first_index + 1) % edge_count]
        for second_index in range(first_index + 1, edge_count):
            if second_index in {
                first_index,
                (first_index + 1) % edge_count,
                (first_index - 1) % edge_count,
            }:
                continue
            third = points[second_index]
            fourth = points[(second_index + 1) % edge_count]
            if _segments_cross(first, second, third, fourth):
                return False
    return True


@dataclass(frozen=True, slots=True)
class PrivacyMask:
    """A normalized polygon which must be blacked out before any consumer sees a frame."""

    points: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.points, (tuple, list)) or not 3 <= len(self.points) <= 32:
            raise ValueError("privacy mask needs between 3 and 32 normalized points")
        normalized: list[tuple[float, float]] = []
        for point in self.points:
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                raise ValueError("privacy mask points must be normalized x/y pairs")
            x = _finite_number(point[0], field_name="privacy mask x")
            y = _finite_number(point[1], field_name="privacy mask y")
            if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
                raise ValueError("privacy mask coordinates must be normalized between 0 and 1")
            normalized.append((x, y))

        twice_area = abs(
            sum(
                x1 * y2 - x2 * y1
                for (x1, y1), (x2, y2) in zip(
                    normalized,
                    normalized[1:] + normalized[:1],
                    strict=True,
                )
            )
        )
        if twice_area <= 1e-9:
            raise ValueError("privacy mask polygon area must be non-zero")
        if not _is_simple_polygon(normalized):
            raise ValueError("privacy mask polygon must be simple and non-intersecting")
        object.__setattr__(self, "points", tuple(normalized))


@dataclass(frozen=True, slots=True)
class CameraConfig:
    """Owner-curated camera configuration; safe defaults perform no work."""

    camera_id: str
    name: str
    enabled: bool = False
    required_consent_version: int = 1
    masks: tuple[PrivacyMask, ...] = ()
    snapshot_ttl_seconds: int = MAX_SNAPSHOT_TTL_SECONDS
    metadata_ttl_seconds: int = MAX_METADATA_TTL_SECONDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "camera_id",
            _safe_id(self.camera_id, field_name="camera_id", camera=True),
        )
        object.__setattr__(self, "name", _bounded_text(self.name, field_name="camera name", maximum=128))
        if not isinstance(self.enabled, bool):
            raise ValueError("camera enabled must be a boolean")
        if (
            isinstance(self.required_consent_version, bool)
            or not isinstance(self.required_consent_version, int)
            or self.required_consent_version < 1
        ):
            raise ValueError("required consent version must be a positive integer")
        if not isinstance(self.masks, (tuple, list)) or len(self.masks) > 16:
            raise ValueError("camera masks must be a bounded collection")
        masks = tuple(self.masks)
        if any(not isinstance(mask, PrivacyMask) for mask in masks):
            raise ValueError("camera masks must contain PrivacyMask values")
        object.__setattr__(self, "masks", masks)
        self._validate_retention()

    def _validate_retention(self) -> None:
        if (
            isinstance(self.snapshot_ttl_seconds, bool)
            or not isinstance(self.snapshot_ttl_seconds, int)
            or not 1 <= self.snapshot_ttl_seconds <= MAX_SNAPSHOT_TTL_SECONDS
        ):
            raise ValueError("snapshot retention must be between 1 second and 24 hours")
        if (
            isinstance(self.metadata_ttl_seconds, bool)
            or not isinstance(self.metadata_ttl_seconds, int)
            or not 1 <= self.metadata_ttl_seconds <= MAX_METADATA_TTL_SECONDS
        ):
            raise ValueError("metadata retention must be between 1 second and 30 days")


@dataclass(frozen=True, slots=True)
class HouseholdConsent:
    """Versioned consent snapshot used to mint generation-bound privacy leases."""

    version: int
    generation: int
    granted: bool
    camera_ids: tuple[str, ...]
    accepted_at: float

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("consent version must be a positive integer")
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation < 0
        ):
            raise ValueError("consent generation must be a non-negative integer")
        if not isinstance(self.granted, bool):
            raise ValueError("consent granted must be a boolean")
        if not isinstance(self.camera_ids, (tuple, list)) or len(self.camera_ids) > 128:
            raise ValueError("consented camera ids must be bounded")
        camera_ids = tuple(
            _safe_id(value, field_name="camera_id", camera=True) for value in self.camera_ids
        )
        if len(camera_ids) != len(set(camera_ids)):
            raise ValueError("consented camera ids must be unique")
        object.__setattr__(self, "camera_ids", camera_ids)
        accepted_at = _finite_number(self.accepted_at, field_name="consent accepted_at")
        if accepted_at < 0:
            raise ValueError("consent accepted_at must be non-negative")
        object.__setattr__(self, "accepted_at", accepted_at)


@dataclass(frozen=True, slots=True)
class PrivacyLease:
    """A non-renewable permit for one consent generation and camera."""

    camera_id: str
    consent_version: int
    generation: int


@dataclass(frozen=True, slots=True)
class PrivacyPollingGrant:
    """A generation-bound allowlist for one bounded metadata poll."""

    camera_ids: tuple[str, ...]
    consent_version: int
    generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.camera_ids, (tuple, list)) or not 1 <= len(self.camera_ids) <= 128:
            raise ValueError("polling camera ids must be a non-empty bounded collection")
        camera_ids = tuple(
            _safe_id(value, field_name="camera_id", camera=True) for value in self.camera_ids
        )
        if len(camera_ids) != len(set(camera_ids)):
            raise ValueError("polling camera ids must be unique")
        object.__setattr__(self, "camera_ids", camera_ids)
        if (
            isinstance(self.consent_version, bool)
            or not isinstance(self.consent_version, int)
            or self.consent_version < 1
        ):
            raise ValueError("polling consent version must be positive")
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation < 0
        ):
            raise ValueError("polling generation must be non-negative")


@dataclass(frozen=True, slots=True)
class MaskedFrame:
    """A sanitized, metadata-free frame. Raw source bytes/digests are never retained."""

    data: bytes = field(repr=False)
    format: str = "PNG"
    width: int = 0
    height: int = 0

    def public_metadata(self) -> dict[str, int | str]:
        return {
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "encoded_bytes": len(self.data),
        }


@dataclass(frozen=True, slots=True)
class CameraEvent:
    """Bounded, non-identifying camera event safe for metadata-only consumers."""

    event_id: str
    camera_id: str
    label: str
    occurred_at: float
    confidence: float
    zone: str | None = None
    room_id: str | None = None
    description: str | None = None
    description_provenance: str | None = None

    _PAYLOAD_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "event_id",
            "camera_id",
            "label",
            "occurred_at",
            "confidence",
            "zone",
            "room_id",
            "description",
            "description_provenance",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _safe_id(self.event_id, field_name="event_id"))
        object.__setattr__(
            self,
            "camera_id",
            _safe_id(self.camera_id, field_name="camera_id", camera=True),
        )
        label = _bounded_text(self.label, field_name="event label", maximum=32).lower()
        if label not in _ALLOWED_LABELS:
            raise ValueError("event label is not allowed")
        object.__setattr__(self, "label", label)
        occurred_at = _finite_number(self.occurred_at, field_name="occurred_at")
        if occurred_at < 0:
            raise ValueError("occurred_at must be non-negative")
        object.__setattr__(self, "occurred_at", occurred_at)
        confidence = _finite_number(self.confidence, field_name="confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)
        for field_name, maximum in (
            ("zone", 64),
            ("room_id", 64),
            ("description", 512),
            ("description_provenance", 64),
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _bounded_text(value, field_name=field_name, maximum=maximum),
                )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> CameraEvent:
        if not isinstance(payload, Mapping):
            raise ValueError("camera event payload must be a mapping")
        normalized_keys = {str(key).strip().lower().replace("-", "_") for key in payload}
        if normalized_keys & _SENSITIVE_EVENT_FIELDS:
            raise ValueError("sensitive camera field is forbidden")
        unknown = normalized_keys - cls._PAYLOAD_FIELDS
        if unknown:
            raise ValueError("camera event contains unsupported fields")
        missing = {"event_id", "camera_id", "label", "occurred_at", "confidence"} - set(payload)
        if missing:
            raise ValueError("camera event is missing required fields")
        return cls(**dict(payload))

    def to_public(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "event_id": self.event_id,
            "camera_id": self.camera_id,
            "label": self.label,
            "occurred_at": self.occurred_at,
            "confidence": self.confidence,
            "anonymous": self.label == "person",
        }
        for field_name in ("zone", "room_id", "description", "description_provenance"):
            value = getattr(self, field_name)
            if value is not None:
                result[field_name] = value
        return result
