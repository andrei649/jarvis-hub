"""Privacy-rechecked, bounded camera event fan-out for local consumers."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import os
import re
import sqlite3
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agents.core.house.contracts import HouseEvent

from .models import CameraEvent
from .pipeline import CameraPipelineResult
from .privacy import CameraPrivacyPolicy
from .source import CameraEventPage

_SINK_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_MAX_QUEUE = 1_024
_MAX_LEDGER_ROWS = 100_000


def _finite_time(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite timestamp")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be a finite timestamp")
    return result


def _bounded_optional(value: object, *, label: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    result = value.strip()
    if len(result) > limit:
        raise ValueError(f"{label} exceeds its size limit")
    return result


def _dedupe_key(camera_id: str, event_id: str) -> str:
    literal = f"camera:{camera_id}:{event_id}"
    if len(literal) <= 128:
        return literal
    digest = hashlib.sha256(literal.encode("utf-8")).hexdigest()
    return f"camera:{digest}"


@dataclass(frozen=True, slots=True)
class CameraFeedEvent:
    """Description-free camera fact safe for House Brain and monitor consumers."""

    event_id: str
    camera_id: str
    label: str
    occurred_at: float
    observed_at: float
    confidence: float
    consent_generation: int
    dedupe_key: str
    zone: str = ""
    room_id: str = ""

    def __post_init__(self) -> None:
        # Reuse the canonical camera contract to validate all public fields and labels.
        validated = CameraEvent(
            event_id=self.event_id,
            camera_id=self.camera_id,
            label=self.label,
            occurred_at=self.occurred_at,
            confidence=self.confidence,
            zone=self.zone or None,
            room_id=self.room_id or None,
        )
        for name in ("event_id", "camera_id", "label", "occurred_at", "confidence"):
            object.__setattr__(self, name, getattr(validated, name))
        object.__setattr__(self, "observed_at", _finite_time(self.observed_at, label="observed_at"))
        if (
            isinstance(self.consent_generation, bool)
            or not isinstance(self.consent_generation, int)
            or self.consent_generation < 0
        ):
            raise ValueError("consent_generation must be a non-negative integer")
        expected_key = _dedupe_key(validated.camera_id, validated.event_id)
        if self.dedupe_key != expected_key:
            raise ValueError("camera feed dedupe key is invalid")
        object.__setattr__(self, "zone", _bounded_optional(self.zone, label="zone", limit=64))
        object.__setattr__(
            self,
            "room_id",
            _bounded_optional(self.room_id, label="room_id", limit=64),
        )

    @classmethod
    def from_camera_event(
        cls,
        event: CameraEvent,
        *,
        observed_at: float,
        consent_generation: int,
    ) -> CameraFeedEvent:
        if not isinstance(event, CameraEvent):
            raise ValueError("camera feed input must be a CameraEvent")
        return cls(
            event_id=event.event_id,
            camera_id=event.camera_id,
            label=event.label,
            occurred_at=event.occurred_at,
            observed_at=observed_at,
            confidence=event.confidence,
            consent_generation=consent_generation,
            dedupe_key=_dedupe_key(event.camera_id, event.event_id),
            zone=event.zone or "",
            room_id=event.room_id or "",
        )

    def to_house_event(self) -> HouseEvent:
        from agents.core.house.contracts import HouseEvent

        occupancy = self.label == "person"
        return HouseEvent(
            event_id=self.event_id,
            source_event_id=self.event_id,
            entity_id=f"camera.{self.camera_id}",
            event_type=(
                "camera_anonymous_occupancy" if occupancy else "camera_sensor_observation"
            ),
            previous_state="",
            current_state="occupied" if occupancy else self.label,
            occurred_at=self.occurred_at,
            observed_at=self.observed_at,
            dedupe_key=self.dedupe_key,
            provenance="camera.feed.metadata_only",
            privacy_class="household",
        )

    def to_public(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "camera_id": self.camera_id,
            "label": self.label,
            "occurred_at": self.occurred_at,
            "observed_at": self.observed_at,
            "confidence": self.confidence,
            "anonymous": True,
            "zone": self.zone,
            "room_id": self.room_id,
            "dedupe_key": self.dedupe_key,
        }


class CameraFeedSink(Protocol):
    async def consume(self, event: CameraFeedEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class CameraFeedPublishResult:
    status: str
    delivered: int = 0
    duplicates: int = 0
    failed: int = 0
    dropped: int = 0
    reason: str = ""


@dataclass(slots=True)
class _SinkState:
    name: str
    consumer: CameraFeedSink
    queue: asyncio.Queue
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    delivered: int = 0
    duplicates: int = 0
    failed: int = 0
    dropped: int = 0
    last_status: str = "idle"


class CameraFeedPublisher:
    """Fan out safe events with per-sink backpressure and persisted dedupe receipts."""

    def __init__(
        self,
        *,
        privacy_policy: CameraPrivacyPolicy,
        ledger_path: str | Path,
        clock=None,
        delivery_timeout: float = 1.0,
        max_ledger_rows: int = _MAX_LEDGER_ROWS,
    ) -> None:
        if not isinstance(privacy_policy, CameraPrivacyPolicy):
            raise ValueError("camera privacy policy is required")
        if (
            isinstance(delivery_timeout, bool)
            or not isinstance(delivery_timeout, (int, float))
            or not math.isfinite(float(delivery_timeout))
            or float(delivery_timeout) <= 0
            or float(delivery_timeout) > 30
        ):
            raise ValueError("delivery_timeout must be between zero and 30 seconds")
        if (
            isinstance(max_ledger_rows, bool)
            or not isinstance(max_ledger_rows, int)
            or not 1 <= max_ledger_rows <= _MAX_LEDGER_ROWS
        ):
            raise ValueError("max_ledger_rows is invalid")
        path = Path(ledger_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._privacy = privacy_policy
        self._clock = clock or time.time
        self._timeout = float(delivery_timeout)
        self._max_ledger_rows = max_ledger_rows
        self._sinks: dict[str, _SinkState] = {}
        self._db = sqlite3.connect(str(path))
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS camera_feed_deliveries (
                sink TEXT NOT NULL,
                dedupe_key TEXT NOT NULL,
                delivered_at REAL NOT NULL,
                PRIMARY KEY (sink, dedupe_key)
            )
            """
        )
        self._db.commit()
        self._closed = False

    def subscribe(self, name: str, consumer: CameraFeedSink, *, max_queue: int = 64) -> None:
        normalized = str(name).strip().lower()
        if _SINK_RE.fullmatch(normalized) is None:
            raise ValueError("camera feed sink name is invalid")
        if normalized in self._sinks:
            raise ValueError("camera feed sink name already exists")
        consume = getattr(consumer, "consume", None)
        if not callable(consume) or not inspect.iscoroutinefunction(consume):
            raise ValueError("camera feed sink must provide async consume")
        if (
            isinstance(max_queue, bool)
            or not isinstance(max_queue, int)
            or not 1 <= max_queue <= _MAX_QUEUE
        ):
            raise ValueError("camera feed queue size is invalid")
        self._sinks[normalized] = _SinkState(
            name=normalized,
            consumer=consumer,
            queue=asyncio.Queue(maxsize=max_queue),
        )

    async def publish(self, event: CameraEvent) -> CameraFeedPublishResult:
        if self._closed:
            raise RuntimeError("camera feed publisher is closed")
        if not isinstance(event, CameraEvent):
            raise ValueError("camera feed input must be a CameraEvent")
        lease = self._privacy.begin(event.camera_id)
        self._privacy.recheck(lease, "publish")
        record = CameraFeedEvent.from_camera_event(
            event,
            observed_at=_finite_time(self._clock(), label="clock"),
            consent_generation=lease.generation,
        )
        if not self._sinks:
            return CameraFeedPublishResult(status="degraded", reason="no_subscribers")

        dropped = 0
        drainers = []
        for state in self._sinks.values():
            try:
                state.queue.put_nowait((record, lease))
            except asyncio.QueueFull:
                state.dropped += 1
                state.last_status = "backpressure"
                dropped += 1
            else:
                drainers.append(self._drain(state))
        batches = await asyncio.gather(*drainers) if drainers else []
        delivered = sum(batch[0] for batch in batches)
        duplicates = sum(batch[1] for batch in batches)
        failed = sum(batch[2] for batch in batches)
        dropped += sum(batch[3] for batch in batches)
        if failed or dropped:
            status = "degraded"
        elif delivered:
            status = "delivered"
        else:
            status = "duplicate"
        return CameraFeedPublishResult(
            status=status,
            delivered=delivered,
            duplicates=duplicates,
            failed=failed,
            dropped=dropped,
            reason="delivery_degraded" if status == "degraded" else "",
        )

    async def _drain(self, state: _SinkState) -> tuple[int, int, int, int]:
        delivered = duplicates = failed = 0
        async with state.lock:
            while True:
                try:
                    record, lease = state.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    if self._was_delivered(state.name, record.dedupe_key):
                        state.duplicates += 1
                        state.last_status = "duplicate"
                        duplicates += 1
                        continue
                    self._privacy.recheck(lease, "publish")
                    outcome = state.consumer.consume(record)
                    if not inspect.isawaitable(outcome):
                        raise TypeError("camera feed sink must be asynchronous")
                    await asyncio.wait_for(outcome, timeout=self._timeout)
                    self._privacy.recheck(lease, "publish")
                    self._mark_delivered(state.name, record.dedupe_key)
                    state.delivered += 1
                    state.last_status = "delivered"
                    delivered += 1
                except Exception:
                    state.failed += 1
                    state.last_status = "failed"
                    failed += 1
                finally:
                    state.queue.task_done()
        return delivered, duplicates, failed, 0

    def _was_delivered(self, sink: str, dedupe_key: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM camera_feed_deliveries WHERE sink = ? AND dedupe_key = ?",
            (sink, dedupe_key),
        ).fetchone()
        return row is not None

    def _mark_delivered(self, sink: str, dedupe_key: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO camera_feed_deliveries(sink, dedupe_key, delivered_at) VALUES(?, ?, ?)",
            (sink, dedupe_key, _finite_time(self._clock(), label="clock")),
        )
        count = int(self._db.execute("SELECT COUNT(*) FROM camera_feed_deliveries").fetchone()[0])
        excess = max(0, count - self._max_ledger_rows)
        if excess:
            self._db.execute(
                """
                DELETE FROM camera_feed_deliveries
                WHERE rowid IN (
                    SELECT rowid FROM camera_feed_deliveries
                    ORDER BY delivered_at ASC, sink ASC, dedupe_key ASC
                    LIMIT ?
                )
                """,
                (excess,),
            )
        self._db.commit()

    def health(self) -> dict[str, object]:
        sinks = {
            name: {
                "status": state.last_status,
                "queued": state.queue.qsize(),
                "queue_capacity": state.queue.maxsize,
                "delivered": state.delivered,
                "duplicates": state.duplicates,
                "failed": state.failed,
                "dropped": state.dropped,
            }
            for name, state in sorted(self._sinks.items())
        }
        return {
            "status": "ready" if sinks else "degraded",
            "reason": "" if sinks else "no_subscribers",
            "sinks": sinks,
        }

    def close(self) -> None:
        if not self._closed:
            self._db.close()
            self._closed = True


@dataclass(frozen=True, slots=True)
class CameraIngestionResult:
    status: str
    polled: int = 0
    processed: int = 0
    stored: int = 0
    delivered: int = 0
    duplicates: int = 0
    filtered: int = 0
    failed: int = 0
    cursor_advanced: bool = False
    reason: str = ""


class CameraIngestionCoordinator:
    """Run one bounded metadata page through pipeline, vault, and durable feeds."""

    _TERMINAL_STATUSES = frozenset(
        {"metadata_only", "described", "description_unavailable"}
    )

    def __init__(
        self,
        *,
        source,
        pipeline,
        vault,
        publisher: CameraFeedPublisher,
        privacy_policy: CameraPrivacyPolicy,
        cursor_path: str | Path,
        describe_selector=None,
    ) -> None:
        for value, method, label in (
            (source, "list_events", "camera event source"),
            (pipeline, "process", "camera pipeline"),
            (vault, "store", "camera vault"),
        ):
            if not callable(getattr(value, method, None)):
                raise ValueError(f"{label} is required")
        if not isinstance(publisher, CameraFeedPublisher):
            raise ValueError("camera feed publisher is required")
        if not isinstance(privacy_policy, CameraPrivacyPolicy):
            raise ValueError("camera privacy policy is required")
        if describe_selector is not None and not callable(describe_selector):
            raise ValueError("describe_selector must be callable")
        self._source = source
        self._pipeline = pipeline
        self._vault = vault
        self._publisher = publisher
        self._privacy = privacy_policy
        self._cursor_path = Path(cursor_path)
        self._cursor_path.parent.mkdir(parents=True, exist_ok=True)
        self._describe_selector = describe_selector or (lambda _event: False)
        self._cursor, cursor_error = self._load_cursor()
        self._retry_events: dict[tuple[str, str], tuple[CameraEvent, bool]] = {}
        self._lock = asyncio.Lock()
        self._last_status = "degraded" if cursor_error else "idle"
        self._last_error = cursor_error
        self._polls = 0

    def _load_cursor(self) -> tuple[str | None, str]:
        if not self._cursor_path.exists():
            return None, ""
        try:
            raw = self._cursor_path.read_text(encoding="utf-8")
            if len(raw) > 4_096:
                raise ValueError("cursor state is too large")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or set(payload) != {"schema", "cursor"}:
                raise ValueError("cursor state shape is invalid")
            if payload["schema"] != 1:
                raise ValueError("cursor state schema is invalid")
            cursor = payload["cursor"]
            if cursor is not None and (
                not isinstance(cursor, str) or not cursor or len(cursor) > 2_048
            ):
                raise ValueError("cursor value is invalid")
            return cursor, ""
        except (OSError, UnicodeError, ValueError):
            return None, "cursor_invalid"

    def _save_cursor(self, cursor: str | None) -> None:
        if cursor is not None and (
            not isinstance(cursor, str) or not cursor or len(cursor) > 2_048
        ):
            raise ValueError("camera source cursor is invalid")
        payload = json.dumps(
            {"schema": 1, "cursor": cursor},
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        temporary = self._cursor_path.with_name(
            f".{self._cursor_path.name}.{os.getpid()}.tmp"
        )
        try:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(self._cursor_path)
        finally:
            temporary.unlink(missing_ok=True)
        self._cursor = cursor

    async def poll(self, *, limit: int = 100) -> CameraIngestionResult:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise ValueError("camera poll limit must be between 1 and 1000")
        async with self._lock:
            self._polls += 1
            try:
                page = await self._source.list_events(self._cursor, limit)
            except Exception:
                self._last_status = "degraded"
                self._last_error = "source_unavailable"
                return CameraIngestionResult(status="degraded", failed=1, reason=self._last_error)
            if (
                not isinstance(page, CameraEventPage)
                or not isinstance(page.events, tuple)
                or len(page.events) > limit
            ):
                self._last_status = "degraded"
                self._last_error = "source_contract_invalid"
                return CameraIngestionResult(status="degraded", failed=1, reason=self._last_error)

            processed = stored = delivered = duplicates = filtered = failed = 0
            for event in page.events:
                if not isinstance(event, CameraEvent):
                    failed += 1
                    self._last_error = "source_contract_invalid"
                    continue
                retry_key = (event.camera_id, event.event_id)
                retry = self._retry_events.get(retry_key)
                candidate: CameraEvent
                stored_already = False
                if retry is None:
                    try:
                        outcome = await self._pipeline.process(
                            event,
                            describe=bool(self._describe_selector(event)),
                        )
                        if not isinstance(outcome, CameraPipelineResult):
                            raise ValueError("camera pipeline contract is invalid")
                        processed += 1
                        if outcome.status in {"filtered", "duplicate"}:
                            filtered += 1
                            continue
                        if outcome.status not in self._TERMINAL_STATUSES:
                            raise ValueError("camera pipeline status is invalid")
                        candidate = outcome.event
                        if len(self._retry_events) >= 1_000:
                            self._retry_events.pop(next(iter(self._retry_events)))
                        self._retry_events[retry_key] = (candidate, False)
                    except Exception:
                        failed += 1
                        self._last_error = "event_processing_failed"
                        continue
                else:
                    candidate, stored_already = retry
                if not stored_already:
                    try:
                        lease = self._privacy.begin(candidate.camera_id)
                        self._privacy.recheck(lease, "store")
                        receipt = self._vault.store(candidate)
                        self._privacy.recheck(lease, "store")
                        stored += int(bool(getattr(receipt, "stored", False)))
                        self._retry_events[retry_key] = (candidate, True)
                    except Exception:
                        failed += 1
                        self._last_error = "event_store_failed"
                        continue
                try:
                    result = await self._publisher.publish(candidate)
                except Exception:
                    failed += 1
                    self._last_error = "feed_delivery_degraded"
                    continue
                delivered += result.delivered
                duplicates += result.duplicates
                if result.failed or result.dropped or result.status == "degraded":
                    failed += max(1, result.failed + result.dropped)
                    self._last_error = "feed_delivery_degraded"

            cursor_advanced = False
            if failed == 0:
                cursor_advanced = page.next_cursor != self._cursor or bool(page.events)
                try:
                    self._save_cursor(page.next_cursor)
                except (OSError, ValueError):
                    failed += 1
                    self._last_error = "cursor_persist_failed"
                else:
                    self._retry_events.clear()
            status = "degraded" if failed else ("ok" if page.events else "idle")
            self._last_status = status
            if not failed:
                self._last_error = ""
            return CameraIngestionResult(
                status=status,
                polled=len(page.events),
                processed=processed,
                stored=stored,
                delivered=delivered,
                duplicates=duplicates,
                filtered=filtered,
                failed=failed,
                cursor_advanced=cursor_advanced,
                reason=self._last_error,
            )

    def health(self) -> dict[str, object]:
        return {
            "status": self._last_status,
            "last_error": self._last_error,
            "polls": self._polls,
            "cursor_present": self._cursor is not None,
            "retry_events": len(self._retry_events),
            "feed": self._publisher.health(),
        }


class CameraIngestionService:
    """Lifecycle-owned polling loop; it is inert until ``start`` is called."""

    def __init__(
        self,
        *,
        coordinator: CameraIngestionCoordinator,
        retention_scheduler=None,
        poll_interval: float = 5.0,
        poll_limit: int = 100,
    ) -> None:
        if not isinstance(coordinator, CameraIngestionCoordinator):
            raise ValueError("camera ingestion coordinator is required")
        if retention_scheduler is not None and not callable(
            getattr(retention_scheduler, "run_due", None)
        ):
            raise ValueError("camera retention scheduler must provide run_due")
        if (
            isinstance(poll_interval, bool)
            or not isinstance(poll_interval, (int, float))
            or not math.isfinite(float(poll_interval))
            or not 0.01 <= float(poll_interval) <= 900
        ):
            raise ValueError("camera poll interval must be between 0.01 and 900 seconds")
        if (
            isinstance(poll_limit, bool)
            or not isinstance(poll_limit, int)
            or not 1 <= poll_limit <= 1_000
        ):
            raise ValueError("camera poll limit must be between 1 and 1000")
        self._coordinator = coordinator
        self._retention = retention_scheduler
        self._interval = float(poll_interval)
        self._limit = poll_limit
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._ticks = 0
        self._last_status = "stopped"
        self._last_error = ""

    def start(self) -> bool:
        if self._task is not None and not self._task.done():
            return False
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="camera-ingestion")
        self._last_status = "starting"
        return True

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=min(5.0, self._interval + 1.0))
            except TimeoutError:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        self._task = None
        self._last_status = "stopped"

    def request_stop(self) -> None:
        """Signal the loop from synchronous privacy-revocation callbacks."""

        self._stop.set()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = await self._coordinator.poll(limit=self._limit)
                self._ticks += 1
                self._last_status = result.status
                self._last_error = result.reason
                if self._retention is not None:
                    self._retention.run_due()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._last_status = "degraded"
                self._last_error = "ingestion_loop_failed"
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                continue

    def health(self) -> dict[str, object]:
        task = self._task
        return {
            "status": self._last_status,
            "last_error": self._last_error,
            "running": task is not None and not task.done(),
            "ticks": self._ticks,
            "coordinator": self._coordinator.health(),
        }


__all__ = [
    "CameraFeedEvent",
    "CameraFeedPublishResult",
    "CameraFeedPublisher",
    "CameraFeedSink",
    "CameraIngestionCoordinator",
    "CameraIngestionResult",
    "CameraIngestionService",
]
