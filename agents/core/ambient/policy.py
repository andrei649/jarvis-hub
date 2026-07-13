"""H33 decision ladder and the one durable unsolicited-attention choke point."""

from __future__ import annotations

import inspect
import math
import sqlite3
import threading
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class DecisionRung(StrEnum):
    IGNORE = "ignore"
    REMEMBER = "remember"
    MONITOR = "monitor"
    ACT_SILENTLY = "act_silently"
    ASK = "ask"
    INTERRUPT = "interrupt"


_ATTENTION_MODE = {
    DecisionRung.IGNORE: "none",
    DecisionRung.REMEMBER: "none",
    DecisionRung.MONITOR: "none",
    DecisionRung.ACT_SILENTLY: "none",
    DecisionRung.ASK: "digest",
    DecisionRung.INTERRUPT: "interrupt",
}
_HARD_FLOOR_PREFIXES = (
    "call.",
    "house.security",
    "media.",
    "message.",
    "money.",
    "notify.",
    "payment.",
)


@dataclass(frozen=True, slots=True)
class LadderContext:
    requested_rung: str | DecisionRung
    confidence: float = 1.0
    tainted: bool = False
    critical: bool = False
    quiet_hours: bool = False
    capability_id: str = ""
    silent_eligible: bool = False
    rollbackable: bool = False
    postcondition_bound: bool = False

    def __post_init__(self) -> None:
        try:
            rung = DecisionRung(self.requested_rung)
        except (TypeError, ValueError) as exc:
            raise ValueError("ambient decision rung is invalid") from exc
        object.__setattr__(self, "requested_rung", rung)
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(float(self.confidence))
            or not 0 <= float(self.confidence) <= 1
        ):
            raise ValueError("ambient confidence must be between zero and one")
        object.__setattr__(self, "confidence", float(self.confidence))
        for name in (
            "tainted",
            "critical",
            "quiet_hours",
            "silent_eligible",
            "rollbackable",
            "postcondition_bound",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        capability = str(self.capability_id or "").strip().lower()
        if len(capability) > 128:
            raise ValueError("ambient capability id is too long")
        object.__setattr__(self, "capability_id", capability)


@dataclass(frozen=True, slots=True)
class LadderDecision:
    rung: DecisionRung
    reason: str
    attention_mode: str


class LadderPolicy:
    """Finite, fail-closed selection policy; it never performs an action."""

    def __init__(self, *, min_confidence: float = 0.75) -> None:
        if (
            isinstance(min_confidence, bool)
            or not isinstance(min_confidence, (int, float))
            or not 0 <= float(min_confidence) <= 1
        ):
            raise ValueError("ambient confidence threshold is invalid")
        self.min_confidence = float(min_confidence)

    def decide(self, context: LadderContext) -> LadderDecision:
        if not isinstance(context, LadderContext):
            raise ValueError("ambient ladder context is required")
        requested = context.requested_rung
        rung = requested
        reason = "policy_selected"
        needs_trust = requested in {DecisionRung.ACT_SILENTLY, DecisionRung.INTERRUPT}
        if needs_trust and context.tainted:
            rung, reason = DecisionRung.ASK, "tainted_downgrade"
        elif needs_trust and context.confidence < self.min_confidence:
            rung, reason = DecisionRung.ASK, "low_confidence_downgrade"
        elif requested is DecisionRung.ACT_SILENTLY:
            hard_floor = any(context.capability_id.startswith(item) for item in _HARD_FLOOR_PREFIXES)
            if hard_floor:
                rung, reason = DecisionRung.ASK, "capability_hard_floor"
            elif not (
                context.silent_eligible
                and context.rollbackable
                and context.postcondition_bound
            ):
                rung, reason = DecisionRung.ASK, "silent_proof_missing"
        elif requested is DecisionRung.INTERRUPT and context.quiet_hours and not context.critical:
            rung, reason = DecisionRung.ASK, "quiet_hours_downgrade"
        return LadderDecision(rung=rung, reason=reason, attention_mode=_ATTENTION_MODE[rung])


@dataclass(frozen=True, slots=True)
class AttentionReservation:
    admitted: bool
    reason: str
    state: str
    window_id: str


class AttentionLedger:
    """Atomic SQLite allowance for every unsolicited delivery channel.

    Only opaque ids and delivery lifecycle metadata are stored. Reservations are
    immediately spent; a failure releases the slot only when dispatch provably
    never began.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        timezone_name: str,
        per_day: int = 4,
        clock: Callable[[], float] = time.time,
        k3: object | None = None,
    ) -> None:
        if isinstance(per_day, bool) or not isinstance(per_day, int) or not 0 <= per_day <= 4:
            raise ValueError("attention allowance must be between zero and four")
        if not callable(clock):
            raise ValueError("attention clock must be callable")
        try:
            owner_tz = ZoneInfo(str(timezone_name))
        except (TypeError, ZoneInfoNotFoundError) as exc:
            raise ValueError("owner timezone must be an IANA timezone") from exc
        self.path = str(path)
        self.timezone_name = str(timezone_name)
        self._timezone = owner_tz
        self._per_day = per_day
        self._clock = clock
        self._k3 = k3
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        self._reason = ""
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        db: sqlite3.Connection | None = None
        try:
            db = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS attention_window (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    local_day TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    window_id TEXT NOT NULL,
                    max_seen_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attention_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    channel_class TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('reserved','dispatching','delivered','failed')),
                    window_id TEXT NOT NULL,
                    reserved_at REAL NOT NULL,
                    dispatching_at REAL,
                    delivered_at REAL,
                    failed_at REAL,
                    failure_category TEXT NOT NULL DEFAULT '',
                    spent INTEGER NOT NULL CHECK(spent IN (0,1))
                );
                CREATE INDEX IF NOT EXISTS idx_attention_window_spent
                    ON attention_deliveries(window_id, spent);
                """
            )
            db.execute("SELECT delivery_id FROM attention_deliveries LIMIT 1").fetchall()
            db.commit()
            self._db = db
            self._sync_k3()
        except (OSError, sqlite3.DatabaseError):
            if db is not None:
                with suppress(sqlite3.Error):
                    db.close()
            self._db = None
            self._reason = "attention_ledger_unavailable"

    @property
    def per_day(self) -> int:
        return self._per_day

    @per_day.setter
    def per_day(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 4:
            raise ValueError("attention allowance must be between zero and four")
        self._per_day = value
        self._sync_k3()

    def _now(self) -> float:
        value = self._clock()
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValueError("attention clock returned an invalid timestamp")
        return float(value)

    def _require(self) -> sqlite3.Connection:
        if self._db is None:
            raise sqlite3.DatabaseError(self._reason or "attention_ledger_unavailable")
        return self._db

    def _window(self, db: sqlite3.Connection, now: float) -> str:
        local_day = datetime.fromtimestamp(now, tz=UTC).astimezone(self._timezone).date()
        day_text = local_day.isoformat()
        row = db.execute("SELECT * FROM attention_window WHERE singleton=1").fetchone()
        if row is None:
            sequence = 1
            window_id = f"{day_text}:{sequence}"
            db.execute(
                "INSERT INTO attention_window VALUES(1, ?, ?, ?, ?)",
                (day_text, sequence, window_id, now),
            )
            return window_id
        stored_day = str(row["local_day"])
        sequence = int(row["sequence"])
        window_id = str(row["window_id"])
        # A clock rollback never returns to an older allowance. Only a strictly
        # newer owner-local day advances the monotonically sequenced window.
        if day_text > stored_day:
            sequence += 1
            window_id = f"{day_text}:{sequence}"
            stored_day = day_text
        db.execute(
            """UPDATE attention_window
               SET local_day=?, sequence=?, window_id=?, max_seen_at=? WHERE singleton=1""",
            (stored_day, sequence, window_id, max(float(row["max_seen_at"]), now)),
        )
        return window_id

    @staticmethod
    def _validate_id(value: object, label: str) -> str:
        result = str(value or "").strip()
        if not result or len(result) > 128 or any(ord(char) < 32 for char in result):
            raise ValueError(f"{label} is invalid")
        return result

    def reserve(self, delivery_id: str, channel_class: str) -> AttentionReservation:
        delivery_id = self._validate_id(delivery_id, "delivery id")
        channel_class = self._validate_id(channel_class, "channel class")
        if self._db is None:
            return AttentionReservation(False, "attention_ledger_unavailable", "failed", "")
        with self._lock:
            db = self._require()
            try:
                db.execute("BEGIN IMMEDIATE")
                now = self._now()
                row = db.execute(
                    "SELECT state, window_id, spent, failure_category FROM attention_deliveries WHERE delivery_id=?",
                    (delivery_id,),
                ).fetchone()
                if row is not None:
                    db.commit()
                    admitted = bool(row["spent"]) or row["state"] != "failed"
                    reason = str(row["failure_category"] or "idempotent")
                    return AttentionReservation(admitted, reason, str(row["state"]), str(row["window_id"]))
                window_id = self._window(db, now)
                used = int(
                    db.execute(
                        "SELECT COUNT(*) FROM attention_deliveries WHERE window_id=? AND spent=1",
                        (window_id,),
                    ).fetchone()[0]
                )
                if used >= self._per_day:
                    db.commit()
                    self._sync_k3(window_id=window_id, used=used)
                    return AttentionReservation(
                        False, "attention_budget_exhausted", "failed", window_id
                    )
                db.execute(
                    """INSERT INTO attention_deliveries(
                           delivery_id, channel_class, state, window_id, reserved_at, spent
                       ) VALUES(?, ?, 'reserved', ?, ?, 1)""",
                    (delivery_id, channel_class, window_id, now),
                )
                db.commit()
                self._sync_k3(window_id=window_id, used=used + 1)
                return AttentionReservation(True, "reserved", "reserved", window_id)
            except sqlite3.Error:
                db.rollback()
                self._reason = "attention_ledger_unavailable"
                return AttentionReservation(False, self._reason, "failed", "")

    def start_dispatch(self, delivery_id: str) -> None:
        self._transition(delivery_id, "dispatching")

    def delivered(self, delivery_id: str) -> None:
        self._transition(delivery_id, "delivered")

    def _transition(self, delivery_id: str, state: str) -> None:
        delivery_id = self._validate_id(delivery_id, "delivery id")
        column = "dispatching_at" if state == "dispatching" else "delivered_at"
        with self._lock:
            db = self._require()
            row = db.execute(
                "SELECT state FROM attention_deliveries WHERE delivery_id=?", (delivery_id,)
            ).fetchone()
            if row is None:
                raise ValueError("attention delivery does not exist")
            if state == "dispatching" and row["state"] not in {"reserved", "dispatching"}:
                return
            if state == "delivered" and row["state"] not in {"dispatching", "delivered"}:
                raise ValueError("attention delivery was not dispatching")
            db.execute(
                f"UPDATE attention_deliveries SET state=?, {column}=COALESCE({column}, ?) WHERE delivery_id=?",  # nosec B608
                (state, self._now(), delivery_id),
            )
            db.commit()
            self._sync_k3()

    def fail(self, delivery_id: str, *, category: str, before_dispatch: bool) -> None:
        delivery_id = self._validate_id(delivery_id, "delivery id")
        allowed_categories = {
            "ambiguous_timeout",
            "dispatcher_unavailable",
            "not_dispatched",
            "provider_error",
            "provider_rejected",
        }
        safe_category = category if category in allowed_categories else "provider_error"
        with self._lock:
            db = self._require()
            row = db.execute(
                "SELECT state FROM attention_deliveries WHERE delivery_id=?", (delivery_id,)
            ).fetchone()
            if row is None:
                raise ValueError("attention delivery does not exist")
            provably_before = bool(before_dispatch and row["state"] == "reserved")
            db.execute(
                """UPDATE attention_deliveries
                   SET state='failed', failed_at=?, failure_category=?, spent=?
                   WHERE delivery_id=?""",
                (self._now(), safe_category, 0 if provably_before else 1, delivery_id),
            )
            db.commit()
            self._sync_k3()

    def _current_usage(self) -> tuple[str, int]:
        with self._lock:
            db = self._require()
            db.execute("BEGIN IMMEDIATE")
            window_id = self._window(db, self._now())
            used = int(
                db.execute(
                    "SELECT COUNT(*) FROM attention_deliveries WHERE window_id=? AND spent=1",
                    (window_id,),
                ).fetchone()[0]
            )
            db.commit()
            return window_id, used

    def _sync_k3(self, *, window_id: str | None = None, used: int | None = None) -> None:
        setter = getattr(self._k3, "set_dimension_usage", None)
        if not callable(setter) or self._db is None:
            return
        try:
            if window_id is None or used is None:
                window_id, used = self._current_usage()
            setter(
                "interrupts/day",
                used,
                limit=self._per_day,
                unit="interrupts",
                enforced=True,
                metadata={"period": "owner_day", "window_id": window_id},
            )
        except (sqlite3.Error, ValueError):
            return

    def remaining(self) -> int:
        if self._db is None:
            return 0
        try:
            window_id, used = self._current_usage()
            self._sync_k3(window_id=window_id, used=used)
            return max(0, self._per_day - used)
        except (sqlite3.Error, ValueError):
            self._reason = "attention_ledger_unavailable"
            return 0

    def records(self, *, limit: int = 1_000) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 1_000))
        with self._lock:
            db = self._require()
            rows = db.execute(
                """SELECT delivery_id, channel_class, state, window_id, reserved_at,
                          dispatching_at, delivered_at, failed_at, failure_category, spent
                   FROM attention_deliveries ORDER BY reserved_at DESC, delivery_id LIMIT ?""",
                (bounded,),
            ).fetchall()
        return [dict(row) for row in rows]

    def status(self) -> dict[str, Any]:
        if self._db is None:
            return {
                "status": "degraded",
                "reason": self._reason or "attention_ledger_unavailable",
                "limit": self._per_day,
                "used": self._per_day,
                "remaining": 0,
                "window_id": "",
            }
        try:
            window_id, used = self._current_usage()
        except (sqlite3.Error, ValueError):
            return {
                "status": "degraded",
                "reason": "attention_ledger_unavailable",
                "limit": self._per_day,
                "used": self._per_day,
                "remaining": 0,
                "window_id": "",
            }
        return {
            "status": "ready",
            "reason": "",
            "limit": self._per_day,
            "used": used,
            "remaining": max(0, self._per_day - used),
            "window_id": window_id,
        }

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


class AttentionDeliveryBroker:
    """Only service allowed to admit and dispatch an unsolicited delivery."""

    def __init__(self, ledger: AttentionLedger) -> None:
        if not isinstance(ledger, AttentionLedger):
            raise ValueError("attention ledger is required")
        self.ledger = ledger

    async def dispatch(
        self,
        delivery_id: str,
        channel_class: str,
        dispatcher: Callable[[], Awaitable[object]] | None,
    ) -> dict[str, str]:
        reservation = self.ledger.reserve(delivery_id, channel_class)
        if not reservation.admitted:
            return {"status": "downgraded", "reason": reservation.reason}
        if reservation.state == "delivered":
            return {"status": "delivered", "reason": "idempotent"}
        if reservation.state == "dispatching":
            return {"status": "failed", "reason": "ambiguous_timeout"}
        if reservation.state == "failed":
            return {"status": "failed", "reason": reservation.reason}
        if not callable(dispatcher):
            self.ledger.fail(
                delivery_id, category="dispatcher_unavailable", before_dispatch=True
            )
            return {"status": "failed", "reason": "dispatcher_unavailable"}
        self.ledger.start_dispatch(delivery_id)
        try:
            pending = dispatcher()
            if not inspect.isawaitable(pending):
                raise TypeError("attention dispatcher must be async")
            accepted = await pending
        except TimeoutError:
            self.ledger.fail(delivery_id, category="ambiguous_timeout", before_dispatch=False)
            return {"status": "failed", "reason": "ambiguous_timeout"}
        except Exception:
            self.ledger.fail(delivery_id, category="provider_error", before_dispatch=False)
            return {"status": "failed", "reason": "provider_error"}
        if accepted is not True:
            self.ledger.fail(delivery_id, category="provider_rejected", before_dispatch=False)
            return {"status": "failed", "reason": "provider_rejected"}
        self.ledger.delivered(delivery_id)
        return {"status": "delivered", "reason": "provider_accepted"}


__all__ = [
    "AttentionDeliveryBroker",
    "AttentionLedger",
    "AttentionReservation",
    "DecisionRung",
    "LadderContext",
    "LadderDecision",
    "LadderPolicy",
]
