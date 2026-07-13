"""Immutable, bounded contracts shared by the House Brain producers."""

from __future__ import annotations

import math
from dataclasses import dataclass

_MAX_ID = 128
_MAX_NAME = 160
_MAX_STATE = 256
_MAX_REASON = 256
_MAX_ATTRIBUTES = 16
_MAX_ATTRIBUTE_KEY = 64
_MAX_ATTRIBUTE_VALUE = 256
_MAX_AREAS = 512
_MAX_ENTITIES = 2_000


def _bounded_text(value: object, *, label: str, limit: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    text = value.strip()
    if required and not text:
        raise ValueError(f"{label} is required")
    if len(text) > limit:
        raise ValueError(f"{label} exceeds its size limit")
    return text


def _finite_time(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite timestamp")
    timestamp = float(value)
    if not math.isfinite(timestamp) or timestamp < 0:
        raise ValueError(f"{label} must be a finite timestamp")
    return timestamp


@dataclass(frozen=True)
class HouseArea:
    area_id: str
    name: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "area_id",
            _bounded_text(self.area_id, label="area_id", limit=_MAX_ID, required=True),
        )
        object.__setattr__(
            self,
            "name",
            _bounded_text(self.name, label="area name", limit=_MAX_NAME, required=True),
        )

    def to_dict(self) -> dict:
        return {"area_id": self.area_id, "name": self.name}


@dataclass(frozen=True)
class HouseEntity:
    entity_id: str
    domain: str
    name: str
    state: str
    area_id: str = ""
    updated_at: float = 0.0
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for field, limit, required in (
            ("entity_id", _MAX_ID, True),
            ("domain", 64, True),
            ("name", _MAX_NAME, True),
            ("state", _MAX_STATE, True),
            ("area_id", _MAX_ID, False),
        ):
            object.__setattr__(
                self,
                field,
                _bounded_text(getattr(self, field), label=field, limit=limit, required=required),
            )
        object.__setattr__(self, "updated_at", _finite_time(self.updated_at, label="updated_at"))
        attrs = tuple(self.attributes)
        if len(attrs) > _MAX_ATTRIBUTES:
            raise ValueError("entity attributes exceed their count limit")
        normalized = []
        for pair in attrs:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise ValueError("entity attributes must be key/value pairs")
            key = _bounded_text(
                pair[0], label="attribute key", limit=_MAX_ATTRIBUTE_KEY, required=True
            )
            value = _bounded_text(
                pair[1], label="attribute value", limit=_MAX_ATTRIBUTE_VALUE, required=False
            )
            normalized.append((key, value))
        object.__setattr__(self, "attributes", tuple(normalized))

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "domain": self.domain,
            "name": self.name,
            "state": self.state,
            "area_id": self.area_id,
            "updated_at": self.updated_at,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class HouseEvent:
    event_id: str
    source_event_id: str
    entity_id: str
    event_type: str
    previous_state: str
    current_state: str
    occurred_at: float
    observed_at: float
    dedupe_key: str
    provenance: str = "home_assistant.websocket"
    privacy_class: str = "household"

    def __post_init__(self) -> None:
        for field, limit, required in (
            ("event_id", _MAX_ID, True),
            ("source_event_id", _MAX_ID, True),
            ("entity_id", _MAX_ID, True),
            ("event_type", 64, True),
            ("previous_state", _MAX_STATE, False),
            ("current_state", _MAX_STATE, True),
            ("dedupe_key", _MAX_ID, True),
            ("provenance", _MAX_NAME, True),
            ("privacy_class", 32, True),
        ):
            object.__setattr__(
                self,
                field,
                _bounded_text(getattr(self, field), label=field, limit=limit, required=required),
            )
        object.__setattr__(self, "occurred_at", _finite_time(self.occurred_at, label="occurred_at"))
        object.__setattr__(self, "observed_at", _finite_time(self.observed_at, label="observed_at"))

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "source_event_id": self.source_event_id,
            "entity_id": self.entity_id,
            "event_type": self.event_type,
            "previous_state": self.previous_state,
            "current_state": self.current_state,
            "occurred_at": self.occurred_at,
            "observed_at": self.observed_at,
            "dedupe_key": self.dedupe_key,
            "provenance": self.provenance,
            "privacy_class": self.privacy_class,
        }


@dataclass(frozen=True)
class HouseSnapshot:
    enabled: bool
    status: str
    observed_at: float
    areas: tuple[HouseArea, ...] = ()
    entities: tuple[HouseEntity, ...] = ()
    reason: str = ""
    provenance: str = "home_assistant.rest"

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("snapshot enabled must be boolean")
        if self.status not in {"disabled", "degraded", "live"}:
            raise ValueError("snapshot status is invalid")
        object.__setattr__(self, "observed_at", _finite_time(self.observed_at, label="observed_at"))
        areas = tuple(self.areas)
        entities = tuple(self.entities)
        if len(areas) > _MAX_AREAS:
            raise ValueError("snapshot area count exceeds its limit")
        if len(entities) > _MAX_ENTITIES:
            raise ValueError("snapshot entity count exceeds its limit")
        if any(not isinstance(area, HouseArea) for area in areas):
            raise ValueError("snapshot areas must be HouseArea values")
        if any(not isinstance(entity, HouseEntity) for entity in entities):
            raise ValueError("snapshot entities must be HouseEntity values")
        object.__setattr__(self, "areas", areas)
        object.__setattr__(self, "entities", entities)
        object.__setattr__(
            self, "reason", _bounded_text(self.reason, label="reason", limit=_MAX_REASON)
        )
        object.__setattr__(
            self,
            "provenance",
            _bounded_text(self.provenance, label="provenance", limit=_MAX_NAME, required=True),
        )

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "status": self.status,
            "observed_at": self.observed_at,
            "areas": [area.to_dict() for area in self.areas],
            "entities": [entity.to_dict() for entity in self.entities],
            "reason": self.reason,
            "provenance": self.provenance,
        }
