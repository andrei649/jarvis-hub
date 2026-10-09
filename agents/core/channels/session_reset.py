"""H063 reset policy and durable, generation-fenced channel routes."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..validation import is_valid_session_id


class SessionResetError(ValueError):
    """A reset route cannot be evaluated or persisted safely."""


def _zone(name: str) -> ZoneInfo:
    if not isinstance(name, str) or not name:
        raise SessionResetError("Invalid reset timezone")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise SessionResetError("Invalid reset timezone") from exc


@dataclass(frozen=True)
class ResetPolicy:
    mode: str = "none"
    idle_minutes: int = 1440
    daily_hour: int = 4
    timezone: str = "Europe/Bucharest"

    def __post_init__(self) -> None:
        if not isinstance(self.mode, str) or self.mode not in {"none", "idle", "daily", "both"}:
            raise SessionResetError("Invalid reset mode")
        if type(self.idle_minutes) is not int or self.idle_minutes <= 0:
            raise SessionResetError("Invalid reset idle minutes")
        try:
            timedelta(minutes=self.idle_minutes)
        except OverflowError as exc:
            raise SessionResetError("Invalid reset idle minutes") from exc
        if type(self.daily_hour) is not int or not 0 <= self.daily_hour <= 23:
            raise SessionResetError("Invalid reset daily hour")
        _zone(self.timezone)


@dataclass(frozen=True)
class RouteState:
    base: str
    generation: int
    last_activity: datetime | None
    channel: str | None
    kind: str | None
    active: bool


def _token(value: str) -> str:
    if not isinstance(value, str):
        raise SessionResetError("Invalid route metadata")
    normalized = value.strip().lower()
    if not is_valid_session_id(normalized):
        raise SessionResetError("Invalid route metadata")
    return normalized


def _overrides(value: object, *, channel: bool = False) -> dict:
    if not isinstance(value, dict):
        raise SessionResetError("Invalid reset configuration")
    allowed = {"mode", "idle_minutes", "daily_hour"}
    if channel:
        allowed.add("types")
    if any(key not in allowed for key in value):
        raise SessionResetError("Invalid reset configuration")
    ResetPolicy(**{key: item for key, item in value.items() if key != "types"})
    if "types" in value:
        if not isinstance(value["types"], dict):
            raise SessionResetError("Invalid reset configuration")
        for kind, nested in value["types"].items():
            _token(kind)
            _overrides(nested)
    return value


def resolve_policy(get_setting: Callable, channel: str, kind: str) -> ResetPolicy:
    """Apply global, kind, channel, then channel-kind settings in that order."""
    channel, kind = _token(channel), _token(kind)
    try:
        values = {
            "mode": get_setting("sessions.reset_mode", "none"),
            "idle_minutes": get_setting("sessions.idle_minutes", 1440),
            "daily_hour": get_setting("sessions.daily_hour", 4),
            "timezone": get_setting("general.timezone", "Europe/Bucharest"),
        }
        by_type = get_setting("sessions.reset_by_type", {})
        by_channel = get_setting("sessions.reset_by_channel", {})
    except Exception as exc:
        raise SessionResetError("Reset settings unavailable") from exc
    if not isinstance(by_type, dict) or not isinstance(by_channel, dict):
        raise SessionResetError("Invalid reset configuration")
    for name, item in by_type.items():
        _token(name)
        _overrides(item)
    for name, item in by_channel.items():
        _token(name)
        _overrides(item, channel=True)
    values.update(by_type.get(kind, {}))
    selected = by_channel.get(channel, {})
    values.update({key: value for key, value in selected.items() if key != "types"})
    values.update(selected.get("types", {}).get(kind, {}))
    return ResetPolicy(**values)


def _instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SessionResetError("Invalid reset clock")
    try:
        if value.utcoffset() is None:
            raise ValueError
        result = value.astimezone(UTC)
        if not math.isfinite(result.timestamp()):
            raise ValueError
        return result
    except (OverflowError, ValueError) as exc:
        raise SessionResetError("Invalid reset clock") from exc


def _cycle(value: datetime, zone: ZoneInfo, hour: int):
    try:
        local = value.astimezone(zone)
        return local.date() if local.hour >= hour else local.date() - timedelta(days=1)
    except (OverflowError, ValueError) as exc:
        raise SessionResetError("Invalid reset clock") from exc


def should_reset(last_activity: datetime, now: datetime, policy: ResetPolicy) -> bool:
    """Return whether a forward UTC clock crossed the selected reset threshold."""
    last, current = _instant(last_activity), _instant(now)
    if not isinstance(policy, ResetPolicy):
        raise SessionResetError("Invalid reset policy")
    if current <= last or policy.mode == "none":
        return False
    idle = (current - last) >= timedelta(minutes=policy.idle_minutes)
    zone = _zone(policy.timezone)
    daily = _cycle(current, zone, policy.daily_hour) > _cycle(last, zone, policy.daily_hour)
    return (policy.mode in {"idle", "both"} and idle) or (
        policy.mode in {"daily", "both"} and daily
    )


def generation_key(base: str, generation: int) -> str:
    """Preserve generation zero and append a safe suffix for later transcripts."""
    if type(generation) is not int or generation < 0 or not is_valid_session_id(base):
        raise SessionResetError("Invalid route generation")
    key = base if generation == 0 else f"{base}_g{generation}"
    if not is_valid_session_id(key):
        raise SessionResetError("Route generation exceeds session ID limit")
    return key


class SessionResetStore:
    """SQLite route index; every mutation locks, reads, and writes atomically."""

    def __init__(self, path: str | Path, *, max_entries: int = 10_000):
        try:
            self.path = Path(path)
        except (TypeError, ValueError) as exc:
            raise SessionResetError("Invalid reset store path") from exc
        if self.path.is_symlink() or self.path.is_dir() or not self.path.parent.is_dir():
            raise SessionResetError("Invalid reset store path")
        if type(max_entries) is not int or max_entries <= 0 or max_entries > 10_000:
            raise SessionResetError("Invalid reset store capacity")
        self.max_entries = max_entries
        try:
            with closing(self._connect()) as db:
                tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if not tables and version == 0:
                    db.execute("CREATE TABLE routes (base TEXT PRIMARY KEY, generation INTEGER NOT NULL, "
                               "last_activity REAL, channel TEXT, kind TEXT, active INTEGER NOT NULL)")
                    db.execute("PRAGMA user_version=1")
                elif version != 1 or {row[0] for row in tables} != {"routes"}:
                    raise SessionResetError("Invalid reset store schema")
                columns = db.execute("PRAGMA table_info(routes)").fetchall()
                if [(row[1], row[2].upper(), row[3], row[5]) for row in columns] != [
                    ("base", "TEXT", 0, 1),
                    ("generation", "INTEGER", 1, 0),
                    ("last_activity", "REAL", 0, 0),
                    ("channel", "TEXT", 0, 0),
                    ("kind", "TEXT", 0, 0),
                    ("active", "INTEGER", 1, 0),
                ]:
                    raise SessionResetError("Invalid reset store schema")
                for row in db.execute("SELECT * FROM routes"):
                    self._decode(row)
        except (sqlite3.Error, OSError) as exc:
            raise SessionResetError("Reset store unavailable") from exc

    def _connect(self):
        if self.path.is_symlink():
            raise SessionResetError("Invalid reset store path")
        return sqlite3.connect(self.path, timeout=5, isolation_level=None)

    @staticmethod
    def _decode(row) -> RouteState:
        base, generation, stamp, channel, kind, active = row
        if not is_valid_session_id(base) or type(generation) is not int or generation < 0:
            raise SessionResetError("Invalid reset store record")
        generation_key(base, generation)
        if active not in (0, 1) or type(active) is not int:
            raise SessionResetError("Invalid reset store record")
        if active == 0:
            if any(value is not None for value in (stamp, channel, kind)):
                raise SessionResetError("Invalid reset store record")
            return RouteState(base, generation, None, None, None, False)
        if not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
            raise SessionResetError("Invalid reset store record")
        try:
            when = datetime.fromtimestamp(stamp, UTC)
        except (OverflowError, ValueError, OSError) as exc:
            raise SessionResetError("Invalid reset store record") from exc
        if channel != _token(channel) or kind != _token(kind):
            raise SessionResetError("Invalid reset store record")
        return RouteState(base, generation, when, channel, kind, True)

    def _read(self, db, base: str) -> RouteState:
        row = db.execute(
            "SELECT base,generation,last_activity,channel,kind,active FROM routes WHERE base=?", (base,)
        ).fetchone()
        return self._decode(row) if row else RouteState(base, 0, None, None, None, False)

    def state(self, base: str) -> RouteState:
        generation_key(base, 0)
        try:
            with closing(self._connect()) as db:
                return self._read(db, base)
        except (sqlite3.Error, OSError) as exc:
            raise SessionResetError("Reset store unavailable") from exc

    def entries(self) -> list[RouteState]:
        try:
            with closing(self._connect()) as db:
                return [self._decode(row) for row in db.execute(
                    "SELECT base,generation,last_activity,channel,kind,active FROM routes ORDER BY base"
                )]
        except (sqlite3.Error, OSError) as exc:
            raise SessionResetError("Reset store unavailable") from exc

    def _mutate(self, base: str, *, now: datetime | None, channel: str | None,
                kind: str | None, action: str) -> RouteState:
        generation_key(base, 0)
        if action != "retire":
            stamp = _instant(now).timestamp()
            channel, kind = _token(channel), _token(kind)
        else:
            stamp = None
        try:
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                old = self._read(db, base)
                if (stamp is not None and old.last_activity is not None
                        and stamp < old.last_activity.timestamp()):
                    raise SessionResetError("Reset clock moved backwards")
                generation = old.generation + (action != "touch")
                generation_key(base, generation)
                if action == "retire":
                    result = RouteState(base, generation, None, None, None, False)
                else:
                    result = RouteState(base, generation, datetime.fromtimestamp(stamp, UTC),
                                        channel, kind, True)
                if (
                    old.generation == 0
                    and not old.active
                    and db.execute("SELECT 1 FROM routes WHERE base=?", (base,)).fetchone() is None
                    and db.execute("SELECT COUNT(*) FROM routes").fetchone()[0] >= self.max_entries
                ):
                    raise SessionResetError("Reset store capacity reached")
                db.execute("INSERT INTO routes(base,generation,last_activity,channel,kind,active) "
                           "VALUES(?,?,?,?,?,?) ON CONFLICT(base) DO UPDATE SET "
                           "generation=excluded.generation,last_activity=excluded.last_activity,"
                           "channel=excluded.channel,kind=excluded.kind,active=excluded.active",
                           (base, generation, stamp, channel if result.active else None,
                            kind if result.active else None, int(result.active)))
                db.execute("COMMIT")
                return result
        except (sqlite3.Error, OSError) as exc:
            raise SessionResetError("Reset store unavailable") from exc

    def touch(self, base: str, now: datetime, channel: str, kind: str) -> RouteState:
        return self._mutate(base, now=now, channel=channel, kind=kind, action="touch")

    def rotate(self, base: str, now: datetime, channel: str, kind: str) -> RouteState:
        return self._mutate(base, now=now, channel=channel, kind=kind, action="rotate")

    def retire(self, base: str) -> RouteState:
        return self._mutate(base, now=None, channel=None, kind=None, action="retire")
