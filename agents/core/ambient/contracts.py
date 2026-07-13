"""Strict bounded contracts for declarative ambient monitoring."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FIELD_RE = re.compile(r"^(?:source|schema|subject_id|age_seconds|attributes\.[a-z][a-z0-9_]{0,63})$")
_ATTRIBUTE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_HASH_RE = re.compile(r"^[a-f0-9]{64}$")
_SOURCES = frozenset({"house", "camera", "digital"})
_PRIVACY = frozenset({"public", "household", "private"})
_OPERATORS = frozenset({"eq", "ne", "lt", "lte", "gt", "gte", "in", "changed", "age"})
_TRANSITIONS = frozenset({"alert", "recovery"})
_RUNGS = frozenset({"ignore", "remember", "monitor", "act_silently", "ask", "interrupt"})
_ATTENTION_MODES = frozenset({"none", "digest", "interrupt"})
_SENSITIVE_ATTRIBUTES = frozenset(
    {
        "body",
        "clip",
        "cmd",
        "content",
        "credential",
        "description",
        "detail",
        "email",
        "face",
        "frame",
        "host",
        "identity",
        "image",
        "name",
        "payload",
        "phone",
        "plate",
        "recipient",
        "rtsp",
        "sender",
        "snapshot",
        "target",
        "template",
        "title",
        "url",
        "vault",
    }
)
_MAX_EVENT_BYTES = 16 * 1024
_MAX_EVENT_AGE = 24 * 60 * 60
_MAX_SECONDS = 7 * 24 * 60 * 60


def _text(value: object, *, label: str, maximum: int, pattern=None) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    result = value.strip()
    if not result or len(result) > maximum:
        raise ValueError(f"{label} is invalid")
    if pattern is not None and pattern.fullmatch(result) is None:
        raise ValueError(f"{label} is invalid")
    return result


def _timestamp(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite timestamp")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be a finite timestamp")
    return result


def _seconds(value: object, *, label: str) -> float:
    result = _timestamp(value, label=label)
    if result > _MAX_SECONDS:
        raise ValueError(f"{label} exceeds seven days")
    return result


def _scalar(value: object, *, label: str) -> bool | int | float | str:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{label} must be finite")
        return value
    if isinstance(value, str):
        if len(value) > 512:
            raise ValueError(f"{label} exceeds 512 characters")
        return value
    raise ValueError(f"{label} must be a scalar")


@dataclass(frozen=True, slots=True)
class EventProvenance:
    adapter: str
    version: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "adapter",
            _text(self.adapter, label="provenance adapter", maximum=128, pattern=_ID_RE),
        )
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("provenance version must be positive")

    def to_dict(self) -> dict[str, object]:
        return {"adapter": self.adapter, "version": self.version}


@dataclass(frozen=True, slots=True)
class AmbientEvent:
    source: str
    schema: str
    source_event_id: str
    subject_id: str
    occurred_at: float
    observed_at: float
    dedupe_key: str
    provenance: EventProvenance
    attributes: tuple[tuple[str, bool | int | float | str], ...] = ()
    privacy: str = "household"
    consent_generation: int = 0
    correlation_id: str = ""
    tainted: bool = False
    critical: bool = False

    def __post_init__(self) -> None:
        source = str(self.source).strip().lower()
        if source not in _SOURCES:
            raise ValueError("ambient source is unsupported")
        object.__setattr__(self, "source", source)
        for name in ("schema", "source_event_id", "subject_id", "dedupe_key"):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), label=name, maximum=128, pattern=_ID_RE),
            )
        occurred = _timestamp(self.occurred_at, label="occurred_at")
        observed = _timestamp(self.observed_at, label="observed_at")
        if observed < occurred or observed - occurred > _MAX_EVENT_AGE:
            raise ValueError("ambient event age exceeds 24 hours")
        object.__setattr__(self, "occurred_at", occurred)
        object.__setattr__(self, "observed_at", observed)
        if not isinstance(self.provenance, EventProvenance):
            raise ValueError("ambient event provenance is required")
        privacy = str(self.privacy).strip().lower()
        if privacy not in _PRIVACY:
            raise ValueError("ambient privacy class is unsupported")
        object.__setattr__(self, "privacy", privacy)
        if (
            isinstance(self.consent_generation, bool)
            or not isinstance(self.consent_generation, int)
            or self.consent_generation < 0
        ):
            raise ValueError("consent generation must be non-negative")
        correlation = str(self.correlation_id).strip()
        if correlation:
            correlation = _text(
                correlation,
                label="correlation_id",
                maximum=128,
                pattern=_ID_RE,
            )
        object.__setattr__(self, "correlation_id", correlation)
        if not isinstance(self.tainted, bool) or not isinstance(self.critical, bool):
            raise ValueError("ambient event flags must be boolean")
        pairs = tuple(self.attributes)
        if len(pairs) > 32:
            raise ValueError("ambient attributes exceed their count limit")
        normalized: list[tuple[str, bool | int | float | str]] = []
        seen: set[str] = set()
        for pair in pairs:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise ValueError("ambient attributes must be key/value pairs")
            key = str(pair[0]).strip().lower()
            if (
                _ATTRIBUTE_RE.fullmatch(key) is None
                or key in _SENSITIVE_ATTRIBUTES
                or any(token in key for token in ("secret", "token", "password", "private"))
                or key in seen
            ):
                raise ValueError("ambient attribute key is forbidden")
            seen.add(key)
            normalized.append((key, _scalar(pair[1], label=f"attribute {key}")))
        normalized.sort(key=lambda item: item[0])
        object.__setattr__(self, "attributes", tuple(normalized))
        encoded = json.dumps(
            self.to_dict(),
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_EVENT_BYTES:
            raise ValueError("ambient event exceeds 16 KiB")

    def attribute(self, name: str, default=None):
        return dict(self.attributes).get(name, default)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "schema": self.schema,
            "source_event_id": self.source_event_id,
            "subject_id": self.subject_id,
            "occurred_at": self.occurred_at,
            "observed_at": self.observed_at,
            "dedupe_key": self.dedupe_key,
            "provenance": self.provenance.to_dict(),
            "attributes": dict(self.attributes),
            "privacy": self.privacy,
            "consent_generation": self.consent_generation,
            "correlation_id": self.correlation_id,
            "tainted": self.tainted,
            "critical": self.critical,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AmbientEvent:
        allowed = {
            "source",
            "schema",
            "source_event_id",
            "subject_id",
            "occurred_at",
            "observed_at",
            "dedupe_key",
            "provenance",
            "attributes",
            "privacy",
            "consent_generation",
            "correlation_id",
            "tainted",
            "critical",
        }
        if not isinstance(payload, Mapping) or not set(payload).issubset(allowed):
            raise ValueError("ambient event contains unsupported fields")
        provenance = payload.get("provenance")
        attributes = payload.get("attributes", {})
        if not isinstance(provenance, Mapping) or set(provenance) != {"adapter", "version"}:
            raise ValueError("ambient provenance is invalid")
        if not isinstance(attributes, Mapping):
            raise ValueError("ambient attributes are invalid")
        values = dict(payload)
        values["provenance"] = EventProvenance(**dict(provenance))
        values["attributes"] = tuple(attributes.items())
        return cls(**values)


@dataclass(frozen=True, slots=True)
class MonitorPredicate:
    field: str
    operator: str
    expected: Any = None

    def __post_init__(self) -> None:
        field_name = str(self.field).strip().lower()
        if _FIELD_RE.fullmatch(field_name) is None:
            raise ValueError("monitor predicate field is invalid")
        operator = str(self.operator).strip().lower()
        if operator not in _OPERATORS:
            raise ValueError("monitor predicate operator is unsupported")
        if operator == "changed":
            if self.expected is not None:
                raise ValueError("changed predicate cannot have an expected value")
            expected = None
        elif operator == "in":
            if not isinstance(self.expected, (tuple, list)) or not 1 <= len(self.expected) <= 32:
                raise ValueError("in predicate requires a bounded collection")
            expected = tuple(_scalar(item, label="predicate expected") for item in self.expected)
        else:
            expected = _scalar(self.expected, label="predicate expected")
            if operator == "age" and (
                isinstance(expected, bool) or not isinstance(expected, (int, float)) or expected < 0
            ):
                raise ValueError("age predicate requires non-negative seconds")
        object.__setattr__(self, "field", field_name)
        object.__setattr__(self, "operator", operator)
        object.__setattr__(self, "expected", expected)

    def to_dict(self) -> dict[str, Any]:
        expected = list(self.expected) if isinstance(self.expected, tuple) else self.expected
        return {"field": self.field, "operator": self.operator, "expected": expected}


@dataclass(frozen=True, slots=True)
class MonitorDefinition:
    monitor_id: str
    version: int
    source: str
    schema: str
    predicates: tuple[MonitorPredicate, ...]
    clear_predicates: tuple[MonitorPredicate, ...] = ()
    subject_id: str = ""
    debounce_seconds: float = 0
    hold_seconds: float = 0
    cooldown_seconds: float = 0
    enabled: bool = True
    branch: str = "match"
    alert_rung: str = "monitor"
    recovery_rung: str = "monitor"
    _ALLOWED_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "monitor_id",
            "version",
            "source",
            "schema",
            "predicates",
            "clear_predicates",
            "subject_id",
            "debounce_seconds",
            "hold_seconds",
            "cooldown_seconds",
            "enabled",
            "branch",
            "alert_rung",
            "recovery_rung",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "monitor_id",
            _text(self.monitor_id, label="monitor_id", maximum=128, pattern=_ID_RE),
        )
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("monitor version must be positive")
        source = str(self.source).strip().lower()
        if source not in _SOURCES:
            raise ValueError("monitor source is unsupported")
        object.__setattr__(self, "source", source)
        object.__setattr__(
            self,
            "schema",
            _text(self.schema, label="monitor schema", maximum=128, pattern=_ID_RE),
        )
        subject = str(self.subject_id).strip()
        if subject:
            subject = _text(subject, label="monitor subject_id", maximum=128, pattern=_ID_RE)
        object.__setattr__(self, "subject_id", subject)
        predicates = tuple(self.predicates)
        clears = tuple(self.clear_predicates)
        if not 1 <= len(predicates) <= 20 or len(clears) > 20:
            raise ValueError("monitor predicates exceed their count limit")
        if any(not isinstance(item, MonitorPredicate) for item in predicates + clears):
            raise ValueError("monitor predicates are invalid")
        object.__setattr__(self, "predicates", predicates)
        object.__setattr__(self, "clear_predicates", clears)
        for name in ("debounce_seconds", "hold_seconds", "cooldown_seconds"):
            object.__setattr__(self, name, _seconds(getattr(self, name), label=name))
        if not isinstance(self.enabled, bool):
            raise ValueError("monitor enabled must be boolean")
        if self.branch != "match":
            raise ValueError("monitor branch is unsupported")
        for name in ("alert_rung", "recovery_rung"):
            rung = str(getattr(self, name)).strip().lower()
            if rung not in _RUNGS:
                raise ValueError("monitor decision rung is unsupported")
            object.__setattr__(self, name, rung)

    @property
    def definition_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), allow_nan=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "monitor_id": self.monitor_id,
            "version": self.version,
            "source": self.source,
            "schema": self.schema,
            "predicates": [item.to_dict() for item in self.predicates],
            "clear_predicates": [item.to_dict() for item in self.clear_predicates],
            "subject_id": self.subject_id,
            "debounce_seconds": self.debounce_seconds,
            "hold_seconds": self.hold_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "enabled": self.enabled,
            "branch": self.branch,
            "alert_rung": self.alert_rung,
            "recovery_rung": self.recovery_rung,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> MonitorDefinition:
        if not isinstance(payload, Mapping) or not set(payload).issubset(cls._ALLOWED_FIELDS):
            raise ValueError("monitor definition contains unsupported fields")
        values = dict(payload)
        values["predicates"] = tuple(MonitorPredicate(**item) for item in values.get("predicates", ()))
        values["clear_predicates"] = tuple(
            MonitorPredicate(**item) for item in values.get("clear_predicates", ())
        )
        return cls(**values)


@dataclass(frozen=True, slots=True)
class AmbientDecision:
    decision_id: str
    monitor_id: str
    monitor_version: int
    monitor_hash: str
    event_fingerprint: str
    transition: str
    matched: bool
    reason: str
    decided_at: float
    consent_generation: int
    rung: str = "monitor"
    attention_mode: str = "none"
    policy_reason: str = "policy_selected"

    def __post_init__(self) -> None:
        for name in ("decision_id", "monitor_id"):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), label=name, maximum=128, pattern=_ID_RE),
            )
        if (
            isinstance(self.monitor_version, bool)
            or not isinstance(self.monitor_version, int)
            or self.monitor_version < 1
        ):
            raise ValueError("monitor version must be positive")
        for name in ("monitor_hash", "event_fingerprint"):
            value = str(getattr(self, name))
            if _HASH_RE.fullmatch(value) is None:
                raise ValueError(f"{name} is invalid")
        transition = str(self.transition).strip().lower()
        if transition not in _TRANSITIONS:
            raise ValueError("ambient transition is invalid")
        object.__setattr__(self, "transition", transition)
        if not isinstance(self.matched, bool):
            raise ValueError("ambient decision match flag must be boolean")
        object.__setattr__(
            self,
            "reason",
            _text(self.reason, label="decision reason", maximum=64, pattern=_ID_RE),
        )
        object.__setattr__(self, "decided_at", _timestamp(self.decided_at, label="decided_at"))
        if (
            isinstance(self.consent_generation, bool)
            or not isinstance(self.consent_generation, int)
            or self.consent_generation < 0
        ):
            raise ValueError("consent generation must be non-negative")
        rung = str(self.rung).strip().lower()
        attention_mode = str(self.attention_mode).strip().lower()
        if rung not in _RUNGS or attention_mode not in _ATTENTION_MODES:
            raise ValueError("ambient decision disposition is invalid")
        expected_mode = "digest" if rung == "ask" else ("interrupt" if rung == "interrupt" else "none")
        if attention_mode != expected_mode:
            raise ValueError("ambient decision attention mode does not match its rung")
        object.__setattr__(self, "rung", rung)
        object.__setattr__(self, "attention_mode", attention_mode)
        object.__setattr__(
            self,
            "policy_reason",
            _text(self.policy_reason, label="policy reason", maximum=64, pattern=_ID_RE),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "monitor_id": self.monitor_id,
            "monitor_version": self.monitor_version,
            "monitor_hash": self.monitor_hash,
            "event_fingerprint": self.event_fingerprint,
            "transition": self.transition,
            "matched": self.matched,
            "reason": self.reason,
            "decided_at": self.decided_at,
            "consent_generation": self.consent_generation,
            "rung": self.rung,
            "attention_mode": self.attention_mode,
            "policy_reason": self.policy_reason,
        }


__all__ = [
    "AmbientDecision",
    "AmbientEvent",
    "EventProvenance",
    "MonitorDefinition",
    "MonitorPredicate",
]
