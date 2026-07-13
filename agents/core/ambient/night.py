"""Owner-timezone night windows and verified ambient outcome accounting."""

from __future__ import annotations

import math
import sqlite3
import threading
import time
from collections import Counter
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .policy import DecisionRung


def _timestamp(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("night timestamp must be finite")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("night timestamp must be finite")
    return result


def _hour(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 23:
        raise ValueError(f"{label} must be an hour from 0 through 23")
    return value


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(name))
    except (TypeError, ZoneInfoNotFoundError) as exc:
        raise ValueError("owner timezone must be a valid IANA timezone") from exc


def resolve_owner_time(local_time: datetime, timezone: ZoneInfo) -> datetime:
    """Resolve a wall time deterministically across DST folds and gaps.

    The first occurrence wins for ambiguous times. A nonexistent wall time is
    advanced to the first real owner-local minute, preventing a skipped job
    while preserving a stable night-window identity.
    """

    if not isinstance(local_time, datetime) or not isinstance(timezone, ZoneInfo):
        raise ValueError("owner-local datetime and IANA timezone are required")
    naive = (
        local_time.astimezone(timezone).replace(tzinfo=None)
        if local_time.tzinfo is not None
        else local_time
    )
    for minute in range(181):
        candidate_naive = naive + timedelta(minutes=minute)
        candidates: list[datetime] = []
        for fold in (0, 1):
            candidate = candidate_naive.replace(tzinfo=timezone, fold=fold)
            roundtrip = candidate.astimezone(UTC).astimezone(timezone)
            if roundtrip.replace(tzinfo=None) == candidate_naive:
                candidates.append(candidate)
        if candidates:
            return min(candidates, key=lambda item: item.astimezone(UTC))
    raise ValueError("owner-local time could not be resolved")


@dataclass(frozen=True, slots=True)
class NightClaim:
    admitted: bool
    reason: str
    window_id: str
    action_id: str
    rung: str
    tracked: bool
    scheduled_at: float


class AmbientNightLedger:
    """Persist one execution claim and terminal result per owner night."""

    def __init__(
        self,
        path: str | Path,
        *,
        timezone_name: str,
        start_hour: int = 23,
        end_hour: int = 6,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not callable(clock):
            raise ValueError("night clock must be callable")
        self.path = Path(path)
        self.timezone_name = str(timezone_name)
        self.timezone = _timezone(self.timezone_name)
        self.start_hour = _hour(start_hour, "night start")
        self.end_hour = _hour(end_hour, "night end")
        self._clock = clock
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        self._reason = ""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db: sqlite3.Connection | None = None
        try:
            db = sqlite3.connect(str(self.path), timeout=5.0, check_same_thread=False)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute("PRAGMA busy_timeout=5000")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS night_window (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    anchor_day TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    window_id TEXT NOT NULL UNIQUE,
                    max_seen_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS night_actions (
                    window_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    rung TEXT NOT NULL,
                    result TEXT NOT NULL DEFAULT 'claimed',
                    claimed_at REAL NOT NULL,
                    completed_at REAL,
                    PRIMARY KEY(window_id, action_id)
                );
                """
            )
            db.execute("SELECT window_id FROM night_actions LIMIT 1").fetchall()
            self._db = db
        except (OSError, sqlite3.DatabaseError):
            if db is not None:
                with suppress(sqlite3.Error):
                    db.close()
            self._reason = "night_ledger_unavailable"

    @staticmethod
    def _safe_id(value: object) -> str:
        output = str(value or "").strip()
        if not output or len(output) > 128 or any(ord(char) < 32 for char in output):
            raise ValueError("night action id is invalid")
        return output

    def _require(self) -> sqlite3.Connection:
        if self._db is None:
            raise RuntimeError(self._reason or "night_ledger_unavailable")
        return self._db

    def _anchor(self, timestamp: float) -> date | None:
        local = datetime.fromtimestamp(timestamp, tz=UTC).astimezone(self.timezone)
        hour = local.hour
        if self.start_hour == self.end_hour:
            return None
        if self.start_hour < self.end_hour:
            return local.date() if self.start_hour <= hour < self.end_hour else None
        if hour >= self.start_hour:
            return local.date()
        if hour < self.end_hour:
            return local.date() - timedelta(days=1)
        return None

    def claim(
        self,
        action_id: str,
        *,
        rung: str = DecisionRung.ACT_SILENTLY.value,
        at: float | None = None,
    ) -> NightClaim:
        action_id = self._safe_id(action_id)
        rung = str(rung)
        if rung not in {item.value for item in DecisionRung}:
            raise ValueError("night action rung is invalid")
        scheduled_at = _timestamp(self._clock() if at is None else at)
        anchor = self._anchor(scheduled_at)
        if anchor is None:
            return NightClaim(True, "outside_night", "", action_id, rung, False, scheduled_at)
        if self._db is None:
            return NightClaim(
                False,
                "night_ledger_unavailable",
                "",
                action_id,
                rung,
                False,
                scheduled_at,
            )
        anchor_text = anchor.isoformat()
        with self._lock:
            db = self._require()
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM night_window WHERE singleton=1").fetchone()
                if row is None:
                    sequence = 1
                    window_id = f"{anchor_text}:{sequence}"
                    db.execute(
                        "INSERT INTO night_window VALUES(1, ?, ?, ?, ?)",
                        (anchor_text, sequence, window_id, scheduled_at),
                    )
                elif anchor_text < str(row["anchor_day"]):
                    db.commit()
                    return NightClaim(
                        False,
                        "clock_rollback",
                        str(row["window_id"]),
                        action_id,
                        rung,
                        False,
                        scheduled_at,
                    )
                else:
                    sequence = int(row["sequence"])
                    window_id = str(row["window_id"])
                    if anchor_text > str(row["anchor_day"]):
                        sequence += 1
                        window_id = f"{anchor_text}:{sequence}"
                    db.execute(
                        """UPDATE night_window SET anchor_day=?, sequence=?, window_id=?,
                           max_seen_at=? WHERE singleton=1""",
                        (
                            anchor_text,
                            sequence,
                            window_id,
                            max(float(row["max_seen_at"]), scheduled_at),
                        ),
                    )
                try:
                    db.execute(
                        """INSERT INTO night_actions(
                               window_id, action_id, rung, claimed_at
                           ) VALUES(?, ?, ?, ?)""",
                        (window_id, action_id, rung, scheduled_at),
                    )
                except sqlite3.IntegrityError:
                    db.rollback()
                    return NightClaim(
                        False,
                        "night_action_duplicate",
                        window_id,
                        action_id,
                        rung,
                        True,
                        scheduled_at,
                    )
                db.commit()
                return NightClaim(
                    True, "claimed", window_id, action_id, rung, True, scheduled_at
                )
            except sqlite3.Error:
                db.rollback()
                self._reason = "night_ledger_unavailable"
                return NightClaim(
                    False,
                    self._reason,
                    "",
                    action_id,
                    rung,
                    False,
                    scheduled_at,
                )

    def claim_scheduled(
        self,
        action_id: str,
        owner_local_time: datetime,
        *,
        rung: str = DecisionRung.ACT_SILENTLY.value,
    ) -> NightClaim:
        resolved = resolve_owner_time(owner_local_time, self.timezone)
        return self.claim(action_id, rung=rung, at=resolved.timestamp())

    @staticmethod
    def _result(result: dict[str, Any]) -> str:
        status = str(result.get("status") or "").lower()
        if status == "noop":
            return "noop"
        if result.get("verified") is True:
            return "verified"
        compensation = result.get("compensation")
        if compensation == "verified" or (
            isinstance(compensation, dict) and compensation.get("verified") is True
        ):
            return "rolled_back"
        return "failed"

    def complete(self, claim: NightClaim, result: dict[str, Any]) -> None:
        if not isinstance(claim, NightClaim) or not claim.admitted or not claim.tracked:
            return
        if not isinstance(result, dict):
            raise ValueError("night action result must be a mapping")
        terminal = self._result(result)
        with self._lock:
            db = self._require()
            db.execute(
                """UPDATE night_actions SET result=?, completed_at=?
                   WHERE window_id=? AND action_id=? AND result='claimed'""",
                (terminal, _timestamp(self._clock()), claim.window_id, claim.action_id),
            )
            db.commit()

    def records(self, *, cutoff: float = 0.0, limit: int = 1_000) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 1_000))
        cutoff = _timestamp(cutoff)
        with self._lock:
            rows = self._require().execute(
                """SELECT window_id, action_id, rung, result, claimed_at, completed_at
                   FROM night_actions WHERE claimed_at>=?
                   ORDER BY claimed_at, action_id LIMIT ?""",
                (cutoff, bounded),
            ).fetchall()
        return [dict(row) for row in rows]

    def health(self) -> dict[str, str]:
        return {
            "status": "ready" if self._db is not None and not self._reason else "degraded",
            "reason": self._reason,
        }

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None


def _is_night(
    timestamp: float,
    *,
    timezone: ZoneInfo,
    start_hour: int,
    end_hour: int,
) -> bool:
    hour = datetime.fromtimestamp(timestamp, tz=UTC).astimezone(timezone).hour
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def ambient_night_report(
    *,
    ambient_store: object,
    night_ledger: AmbientNightLedger,
    timezone_name: str,
    start_hour: int,
    end_hour: int,
    cutoff: float,
) -> dict[str, Any]:
    """Report decisions and terminal outcomes without inflating productive work."""

    timezone = _timezone(timezone_name)
    start_hour = _hour(start_hour, "night start")
    end_hour = _hour(end_hour, "night end")
    cutoff = _timestamp(cutoff)
    rung_counts: Counter[str] = Counter()
    try:
        decisions = ambient_store.journal(limit=1_000)
    except Exception:
        decisions = []
    for decision in decisions:
        decided_at = decision.get("decided_at")
        rung = str(decision.get("rung") or "")
        if (
            isinstance(decided_at, (int, float))
            and float(decided_at) >= cutoff
            and rung in {item.value for item in DecisionRung}
            and _is_night(
                float(decided_at),
                timezone=timezone,
                start_hour=start_hour,
                end_hour=end_hour,
            )
        ):
            rung_counts[rung] += 1
    result_counts: Counter[str] = Counter()
    try:
        outcomes = night_ledger.records(cutoff=cutoff)
    except Exception:
        outcomes = []
    for outcome in outcomes:
        result = str(outcome.get("result") or "")
        if result in {"verified", "noop", "rolled_back", "failed"}:
            result_counts[result] += 1
    rungs = {
        rung: rung_counts[rung]
        for rung in (
            "ignore",
            "remember",
            "monitor",
            "act_silently",
            "ask",
            "interrupt",
        )
    }
    results = {
        result: result_counts[result]
        for result in ("verified", "noop", "rolled_back", "failed")
    }
    return {
        "timezone": timezone_name,
        "window": [start_hour, end_hour],
        "rungs": rungs,
        "results": results,
        "completed_work": results["verified"],
        "excluded_non_work": rungs["ignore"] + rungs["monitor"] + results["noop"],
        "decision_samples": sum(rungs.values()),
        "action_samples": sum(results.values()),
    }


__all__ = [
    "AmbientNightLedger",
    "NightClaim",
    "ambient_night_report",
    "resolve_owner_time",
]
