"""Deterministic, model-free temporal retrieval over redacted camera metadata."""

from __future__ import annotations

import math
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any, Protocol

from .models import CameraEvent
from .vault import CameraVaultError

_ALLOWED_LABELS = frozenset({"person", "vehicle", "animal", "package"})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_WORDS = re.compile(r"[a-z0-9_-]+")
_RELATIVE = re.compile(
    r"\b(?:last|past|ultimele|ultim(?:a|e|ii))\s+(\d{1,2})\s+"
    r"(minutes?|mins?|ore|hours?|zile|days?)\b"
)
_LABEL_WORDS = {
    "person": frozenset({"person", "people", "someone", "courier", "curier", "curierul"}),
    "vehicle": frozenset({"vehicle", "car", "auto", "masina", "masini"}),
    "animal": frozenset({"animal", "dog", "cat", "caine", "pisica"}),
    "package": frozenset({"package", "packages", "parcel", "delivery", "deliveries", "colet"}),
}
_TODAY = frozenset({"today", "azi"})
_YESTERDAY = frozenset({"yesterday", "ieri"})
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "came",
        "cand",
        "come",
        "did",
        "days",
        "day",
        "din",
        "from",
        "hours",
        "hour",
        "in",
        "last",
        "mins",
        "minutes",
        "minute",
        "past",
        "show",
        "the",
        "venit",
        "when",
        "zile",
        "ore",
    }
)


class CameraSearchError(ValueError):
    """A stable refusal for an invalid or unbounded camera search."""


class _EventIndex(Protocol):
    def list_events(self, *, now: float | None = None, limit: int = 100) -> tuple[CameraEvent, ...]: ...


def _finite(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"camera {field_name} must be a finite timestamp")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"camera {field_name} must be a finite timestamp")
    return result


def _text(value: Any, *, field_name: str, maximum: int, identifier: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"camera {field_name} must be text")
    result = value.strip()
    if not result or len(result) > maximum or any(ord(char) < 32 for char in result):
        raise ValueError(f"camera {field_name} is invalid")
    if identifier and _ID_RE.fullmatch(result) is None:
        raise ValueError(f"camera {field_name} is invalid")
    return result


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(character for character in decomposed if not unicodedata.combining(character)).lower()


@dataclass(frozen=True, slots=True)
class CameraFilter:
    after: float | None = None
    before: float | None = None
    label: str | None = None
    camera_id: str | None = None
    zone: str | None = None
    room_id: str | None = None
    limit: int = 100

    def __post_init__(self) -> None:
        if self.after is not None:
            object.__setattr__(self, "after", _finite(self.after, field_name="after"))
        if self.before is not None:
            object.__setattr__(self, "before", _finite(self.before, field_name="before"))
        if self.after is not None and self.before is not None and self.after >= self.before:
            raise ValueError("camera time range must have after before before")
        if self.label is not None:
            label = _text(self.label, field_name="label", maximum=32).lower()
            if label not in _ALLOWED_LABELS:
                raise ValueError("camera label is not allowed")
            object.__setattr__(self, "label", label)
        if self.camera_id is not None:
            object.__setattr__(
                self,
                "camera_id",
                _text(self.camera_id, field_name="camera_id", maximum=64, identifier=True),
            )
        for name in ("zone", "room_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    _text(value, field_name=name, maximum=64),
                )
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or not 1 <= self.limit <= 100:
            raise ValueError("camera search limit must be between 1 and 100")

    def interpretation(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in ("after", "before", "label", "camera_id", "zone", "room_id")
            if getattr(self, name) is not None
        }


@dataclass(frozen=True, slots=True)
class CameraSearchResult:
    status: str
    events: tuple[CameraEvent, ...]
    reason: str | None
    interpretation: dict[str, Any]

    def to_public(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "interpretation": dict(self.interpretation),
            "events": [event.to_public() for event in self.events],
        }


class CameraEventRetrieval:
    """Search at most the newest 1000 encrypted metadata records without a model."""

    def __init__(
        self,
        *,
        index: _EventIndex,
        clock=time.time,
        timezone: tzinfo = UTC,
    ) -> None:
        if not callable(getattr(index, "list_events", None)):
            raise ValueError("camera retrieval index must provide list_events")
        if not callable(clock):
            raise ValueError("camera retrieval clock must be callable")
        if not isinstance(timezone, tzinfo):
            raise ValueError("camera retrieval timezone must be tzinfo")
        self._index = index
        self._clock = clock
        self._timezone = timezone

    def query(self, filters: CameraFilter, *, terms: tuple[str, ...] = ()) -> CameraSearchResult:
        if not isinstance(filters, CameraFilter):
            raise ValueError("camera retrieval requires CameraFilter")
        current = _finite(self._clock(), field_name="clock")
        try:
            values = self._index.list_events(now=current, limit=1000)
            if not isinstance(values, (tuple, list)) or any(
                not isinstance(event, CameraEvent) for event in values
            ):
                raise CameraVaultError("camera index payload invalid")
        except CameraVaultError:
            return CameraSearchResult(
                status="degraded",
                events=(),
                reason="camera_index_unavailable",
                interpretation=filters.interpretation(),
            )
        matches = [event for event in values if self._matches(event, filters, terms)]
        matches.sort(key=lambda event: (-event.occurred_at, event.event_id))
        selected = tuple(matches[: filters.limit])
        return CameraSearchResult(
            status="ok" if selected else "empty",
            events=selected,
            reason=None if selected else "no_matches",
            interpretation=filters.interpretation(),
        )

    def search(self, query: str, *, limit: int = 100) -> CameraSearchResult:
        if not isinstance(query, str):
            raise CameraSearchError("query_invalid")
        raw = query.strip()
        if not raw:
            return CameraSearchResult("empty", (), "query_empty", {})
        if len(raw) > 256:
            raise CameraSearchError("query_too_long")
        now = _finite(self._clock(), field_name="clock")
        parsed = self._parse(raw, now=now, limit=limit)
        if parsed is None:
            return CameraSearchResult("ambiguous", (), "query_ambiguous", {})
        filters, terms = parsed
        return self.query(filters, terms=terms)

    def _parse(
        self,
        query: str,
        *,
        now: float,
        limit: int,
    ) -> tuple[CameraFilter, tuple[str, ...]] | None:
        normalized = _normalized(query)
        tokens = tuple(_WORDS.findall(normalized))
        token_set = set(tokens)
        today = bool(token_set & _TODAY)
        yesterday = bool(token_set & _YESTERDAY)
        relatives = list(_RELATIVE.finditer(normalized))
        if today + yesterday + bool(relatives) > 1 or len(relatives) > 1:
            return None

        labels = [label for label, words in _LABEL_WORDS.items() if token_set & words]
        if len(labels) > 1:
            return None
        label = labels[0] if labels else None

        after: float | None = None
        before: float | None = None
        moment = datetime.fromtimestamp(now, tz=self._timezone)
        start_today = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        if today:
            after = start_today.timestamp()
            before = (start_today + timedelta(days=1)).timestamp()
        elif yesterday:
            after = (start_today - timedelta(days=1)).timestamp()
            before = start_today.timestamp()
        elif relatives:
            amount = int(relatives[0].group(1))
            unit = relatives[0].group(2)
            if amount < 1:
                return None
            if unit.startswith(("min",)):
                seconds = amount * 60
            elif unit.startswith(("hour", "ore")):
                seconds = amount * 3600
            else:
                seconds = amount * 86_400
            after = max(0.0, now - seconds)
            before = now + 1e-6

        label_tokens = set().union(*_LABEL_WORDS.values())
        ignored = _STOPWORDS | _TODAY | _YESTERDAY | label_tokens
        terms = tuple(
            dict.fromkeys(
                token
                for token in tokens
                if token not in ignored and not token.isdigit() and len(token) >= 2
            )
        )[:8]
        return CameraFilter(after=after, before=before, label=label, limit=limit), terms

    @staticmethod
    def _matches(event: CameraEvent, filters: CameraFilter, terms: tuple[str, ...]) -> bool:
        if filters.after is not None and event.occurred_at < filters.after:
            return False
        if filters.before is not None and event.occurred_at >= filters.before:
            return False
        if filters.label is not None and event.label != filters.label:
            return False
        if filters.camera_id is not None and event.camera_id != filters.camera_id:
            return False
        if filters.zone is not None and event.zone != filters.zone:
            return False
        if filters.room_id is not None and event.room_id != filters.room_id:
            return False
        if terms:
            haystack = set(
                _WORDS.findall(
                    _normalized(
                        " ".join(
                            value
                            for value in (
                                event.camera_id,
                                event.zone,
                                event.room_id,
                                event.description,
                            )
                            if value
                        )
                    )
                )
            )
            return all(term in haystack for term in terms)
        return True


__all__ = [
    "CameraEventRetrieval",
    "CameraFilter",
    "CameraSearchError",
    "CameraSearchResult",
]
