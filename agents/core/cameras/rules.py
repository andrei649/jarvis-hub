"""Deterministic, bounded camera-zone and line-crossing rules for H31.3."""

from __future__ import annotations

import math
import re
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, replace

from .models import CameraEvent, PrivacyMask

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
_CAMERA_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_DIRECTIONS = frozenset({"any", "positive", "negative"})
_EPSILON = 1e-12


def _name(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or _NAME_RE.fullmatch(value.strip()) is None:
        raise ValueError(f"{field_name} contains unsafe characters")
    return value.strip()


def _camera_id(value: str) -> str:
    if not isinstance(value, str) or _CAMERA_ID_RE.fullmatch(value.strip()) is None:
        raise ValueError("rule camera_id contains unsafe characters")
    return value.strip()


def _point(value: tuple[float, float], *, field_name: str) -> tuple[float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError(f"{field_name} must be a normalized x/y pair")
    coordinates: list[float] = []
    for coordinate in value:
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            raise ValueError(f"{field_name} must contain finite numbers")
        number = float(coordinate)
        if not math.isfinite(number):
            raise ValueError(f"{field_name} must contain finite numbers")
        if not 0.0 <= number <= 1.0:
            raise ValueError(f"{field_name} must be normalized between 0 and 1")
        coordinates.append(number)
    return coordinates[0], coordinates[1]


@dataclass(frozen=True, slots=True)
class CameraZone:
    """A named normalized polygon used only for deterministic point membership."""

    camera_id: str
    name: str
    points: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "camera_id", _camera_id(self.camera_id))
        object.__setattr__(self, "name", _name(self.name, field_name="zone name"))
        polygon = PrivacyMask(points=self.points)
        object.__setattr__(self, "points", polygon.points)


@dataclass(frozen=True, slots=True)
class LineRule:
    """A named directed line segment in normalized camera coordinates."""

    camera_id: str
    name: str
    start: tuple[float, float]
    end: tuple[float, float]
    direction: str = "any"

    def __post_init__(self) -> None:
        object.__setattr__(self, "camera_id", _camera_id(self.camera_id))
        object.__setattr__(self, "name", _name(self.name, field_name="line name"))
        start = _point(self.start, field_name="line start")
        end = _point(self.end, field_name="line end")
        if start == end:
            raise ValueError("line endpoints must be distinct")
        direction = str(self.direction).strip().lower()
        if direction not in _DIRECTIONS:
            raise ValueError("line direction must be any, positive, or negative")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "direction", direction)


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    """Metadata-only result of evaluating one detection sample."""

    event: CameraEvent
    zones: tuple[str, ...]
    line_crossings: tuple[str, ...]
    duplicate: bool
    qualifies: bool


def _inside(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
    """Return stable point-in-polygon membership, treating the boundary as inside."""

    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) <= _EPSILON and (
            min(x1, x2) - _EPSILON <= x <= max(x1, x2) + _EPSILON
            and min(y1, y2) - _EPSILON <= y <= max(y1, y2) + _EPSILON
        ):
            return True
        if (y1 > y) != (y2 > y):
            intersection = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection:
                inside = not inside
        previous = current
    return inside


def _side(line: LineRule, point: tuple[float, float]) -> float:
    return (line.end[0] - line.start[0]) * (point[1] - line.start[1]) - (
        line.end[1] - line.start[1]
    ) * (point[0] - line.start[0])


def _crosses(
    line: LineRule,
    previous: tuple[float, float],
    current: tuple[float, float],
) -> bool:
    before = _side(line, previous)
    after = _side(line, current)
    if before * after >= -_EPSILON:
        return False
    fraction = before / (before - after)
    intersection = (
        previous[0] + fraction * (current[0] - previous[0]),
        previous[1] + fraction * (current[1] - previous[1]),
    )
    if not (
        min(line.start[0], line.end[0]) - _EPSILON
        <= intersection[0]
        <= max(line.start[0], line.end[0]) + _EPSILON
        and min(line.start[1], line.end[1]) - _EPSILON
        <= intersection[1]
        <= max(line.start[1], line.end[1]) + _EPSILON
    ):
        return False
    if line.direction == "positive":
        return before < 0.0 < after
    if line.direction == "negative":
        return before > 0.0 > after
    return True


class CameraRuleEngine:
    """Stateful but bounded rule evaluation with exact-sample idempotency."""

    def __init__(
        self,
        *,
        zones: tuple[CameraZone, ...] = (),
        lines: tuple[LineRule, ...] = (),
        history_limit: int = 1024,
    ) -> None:
        if not isinstance(zones, (tuple, list)) or len(zones) > 64:
            raise ValueError("camera zones must be a bounded collection")
        if not isinstance(lines, (tuple, list)) or len(lines) > 64:
            raise ValueError("camera lines must be a bounded collection")
        if any(not isinstance(zone, CameraZone) for zone in zones):
            raise ValueError("camera zones must contain CameraZone values")
        if any(not isinstance(line, LineRule) for line in lines):
            raise ValueError("camera lines must contain LineRule values")
        names = [(item.camera_id, item.name) for item in (*zones, *lines)]
        if len(names) != len(set(names)):
            raise ValueError("camera rule names must be unique")
        if isinstance(history_limit, bool) or not isinstance(history_limit, int):
            raise ValueError("history limit must be an integer")
        if not 1 <= history_limit <= 100_000:
            raise ValueError("history limit must be between 1 and 100000")
        self._zones = tuple(zones)
        self._lines = tuple(lines)
        self._history_limit = history_limit
        self._history: deque[tuple[object, ...]] = deque()
        self._seen: set[tuple[object, ...]] = set()
        self._positions: OrderedDict[tuple[str, str], tuple[float, float]] = OrderedDict()
        self._lock = threading.RLock()

    @property
    def history_size(self) -> int:
        with self._lock:
            return len(self._history)

    def evaluate(
        self,
        event: CameraEvent,
        *,
        point: tuple[float, float] | None = None,
    ) -> RuleOutcome:
        if not isinstance(event, CameraEvent):
            raise ValueError("camera rule input must be a CameraEvent")
        normalized_point = None if point is None else _point(point, field_name="detection point")
        signature = (
            event.event_id,
            event.camera_id,
            event.label,
            event.occurred_at,
            event.confidence,
            event.zone,
            normalized_point,
        )
        with self._lock:
            if signature in self._seen:
                return RuleOutcome(event, (), (), True, False)
            self._remember(signature)

            zone_names = self._matching_zones(event, normalized_point)
            crossing_names: tuple[str, ...] = ()
            if normalized_point is not None:
                key = (event.camera_id, event.event_id)
                previous = self._positions.get(key)
                relevant_lines = tuple(
                    line for line in self._lines if line.camera_id == event.camera_id
                )
                if previous is not None:
                    crossing_names = tuple(
                        line.name
                        for line in relevant_lines
                        if _crosses(line, previous, normalized_point)
                    )
                self._positions[key] = normalized_point
                self._positions.move_to_end(key)
                while len(self._positions) > self._history_limit:
                    self._positions.popitem(last=False)

            enriched = event
            if zone_names and event.zone is None:
                enriched = replace(event, zone=zone_names[0])
            constrained = any(
                item.camera_id == event.camera_id for item in (*self._zones, *self._lines)
            )
            qualifies = not constrained or bool(zone_names or crossing_names)
            return RuleOutcome(enriched, zone_names, crossing_names, False, qualifies)

    def _matching_zones(
        self,
        event: CameraEvent,
        point: tuple[float, float] | None,
    ) -> tuple[str, ...]:
        if point is not None:
            return tuple(
                zone.name
                for zone in self._zones
                if zone.camera_id == event.camera_id and _inside(point, zone.points)
            )
        if event.zone is not None and any(
            zone.camera_id == event.camera_id and zone.name == event.zone for zone in self._zones
        ):
            return (event.zone,)
        return ()

    def _remember(self, signature: tuple[object, ...]) -> None:
        if len(self._history) == self._history_limit:
            self._seen.discard(self._history.popleft())
        self._history.append(signature)
        self._seen.add(signature)


__all__ = ["CameraRuleEngine", "CameraZone", "LineRule", "RuleOutcome"]
