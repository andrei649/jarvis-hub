"""H30 consumer for anonymous, metadata-only camera sensor events."""

from __future__ import annotations

import threading
from collections import deque

from agents.core.cameras.feeds import CameraFeedEvent

from .contracts import HouseEvent


class HouseCameraFeedConsumer:
    """Maintain a bounded anonymous sensor projection without touching the shared KG."""

    def __init__(self, *, max_events: int = 2_048) -> None:
        if isinstance(max_events, bool) or not isinstance(max_events, int) or not 1 <= max_events <= 10_000:
            raise ValueError("max_events must be between 1 and 10000")
        self._events: deque[HouseEvent] = deque(maxlen=max_events)
        self._dedupe: deque[str] = deque(maxlen=max_events)
        self._dedupe_set: set[str] = set()
        self._sensors: dict[str, dict[str, object]] = {}
        self._duplicates = 0
        self._lock = threading.RLock()

    async def consume(self, event: CameraFeedEvent) -> None:
        if not isinstance(event, CameraFeedEvent):
            raise ValueError("house camera feed requires CameraFeedEvent")
        house_event = event.to_house_event()
        with self._lock:
            if event.dedupe_key in self._dedupe_set:
                self._duplicates += 1
                return
            if len(self._dedupe) == self._dedupe.maxlen:
                expired = self._dedupe.popleft()
                self._dedupe_set.discard(expired)
            self._dedupe.append(event.dedupe_key)
            self._dedupe_set.add(event.dedupe_key)
            self._events.append(house_event)
            self._sensors[event.camera_id] = {
                "camera_id": event.camera_id,
                "state": house_event.current_state,
                "room_id": event.room_id,
                "zone": event.zone,
                "confidence": event.confidence,
                "occurred_at": event.occurred_at,
                "anonymous": True,
            }

    def events(self, *, limit: int = 100) -> tuple[HouseEvent, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise ValueError("event limit must be between 1 and 1000")
        with self._lock:
            return tuple(list(self._events)[-limit:])

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            sensors = [dict(value) for _, value in sorted(self._sensors.items())]
            event_count = len(self._events)
            duplicate_count = self._duplicates
        return {
            "status": "live" if event_count else "empty",
            "events": event_count,
            "duplicates": duplicate_count,
            "sensors": sensors,
        }


__all__ = ["HouseCameraFeedConsumer"]
