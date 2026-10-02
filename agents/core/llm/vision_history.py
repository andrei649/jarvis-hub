"""Bounded, process-local image parts for explicitly reviewed follow-up turns.

This store is not an authorization source. A handle can select active bytes only
after a fresh owner review binds those exact bytes to the current model route.
Nothing here is serialized into conversation snapshots or logs.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field


class ActiveImageUnavailable(ValueError):
    def __init__(self):
        super().__init__("active image unavailable")


@dataclass(frozen=True)
class _Entry:
    session_id: str
    instance: str
    agent_id: str
    question: str
    images: tuple[bytes, ...] = field(repr=False)
    expires_at: float = field(repr=False)


class ActiveImageHistory:
    """Per-conversation-memory cache with fixed production upper bounds."""

    MAX_BYTES = 16 * 1024 * 1024
    MAX_HANDLES = 32
    MAX_IMAGE_BYTES = 4 * 1024 * 1024
    TTL_SECONDS = 1800

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 ttl_seconds: float = TTL_SECONDS, max_bytes: int = MAX_BYTES,
                 max_handles: int = MAX_HANDLES,
                 max_image_bytes: int = MAX_IMAGE_BYTES):
        if (not callable(clock) or not 0 < ttl_seconds <= self.TTL_SECONDS
                or type(max_bytes) is not int or not 0 < max_bytes <= self.MAX_BYTES
                or type(max_handles) is not int or not 0 < max_handles <= self.MAX_HANDLES
                or type(max_image_bytes) is not int
                or not 0 < max_image_bytes <= self.MAX_IMAGE_BYTES):
            raise ValueError("invalid active image history limits")
        self._clock = clock
        self._ttl = ttl_seconds
        self._max_bytes = max_bytes
        self._max_handles = max_handles
        self._max_image_bytes = max_image_bytes
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._resident_bytes = 0
        self._lock = threading.Lock()

    @staticmethod
    def _identity(session_id: str, instance: str, agent_id: str) -> bool:
        return all(type(value) is str and 0 < len(value) <= 128
                   for value in (session_id, instance, agent_id))

    def _remove(self, handle: str) -> None:
        entry = self._entries.pop(handle)
        self._resident_bytes -= sum(map(len, entry.images))

    def _expire(self, now: float) -> None:
        for handle, entry in tuple(self._entries.items()):
            if entry.expires_at <= now:
                self._remove(handle)

    def remember(self, session_id: str, instance: str, agent_id: str,
                 question: str, images: list[bytes] | tuple[bytes, ...]) -> str | None:
        """Copy a validated selected turn after commit; None means not retained."""
        if not self._identity(session_id, instance, agent_id):
            raise ActiveImageUnavailable()
        if type(question) is not str or not question.strip():
            raise ActiveImageUnavailable()
        if type(images) not in (list, tuple) or not 1 <= len(images) <= 8:
            raise ActiveImageUnavailable()
        if any(type(item) not in (bytes, bytearray, memoryview) or not item
               for item in images):
            raise ActiveImageUnavailable()
        if any(len(item) > self._max_image_bytes for item in images):
            return None
        size = sum(map(len, images))
        if size > self._max_bytes:
            return None
        copied = tuple(bytes(item) for item in images)
        label = " ".join(question.split())[:120]
        with self._lock:
            now = self._clock()
            self._expire(now)
            while (len(self._entries) >= self._max_handles
                   or self._resident_bytes + size > self._max_bytes):
                self._remove(next(iter(self._entries)))
            handle = secrets.token_urlsafe(24)
            while handle in self._entries:
                handle = secrets.token_urlsafe(24)
            self._entries[handle] = _Entry(
                session_id, instance, agent_id, label, copied, now + self._ttl)
            self._resident_bytes += size
            return handle

    def list(self, session_id: str, instance: str, agent_id: str) -> list[dict]:
        if not self._identity(session_id, instance, agent_id):
            return []
        with self._lock:
            self._expire(self._clock())
            return [
                {"handle": handle, "count": len(entry.images), "question": entry.question}
                for handle, entry in self._entries.items()
                if (entry.session_id, entry.instance, entry.agent_id)
                == (session_id, instance, agent_id)
            ]

    def resolve(self, session_id: str, instance: str, agent_id: str,
                handles: list[str] | tuple[str, ...]) -> tuple[bytes, ...]:
        if (not self._identity(session_id, instance, agent_id)
                or type(handles) not in (list, tuple) or not 1 <= len(handles) <= 8
                or any(type(handle) is not str for handle in handles)
                or len(set(handles)) != len(handles)):
            raise ActiveImageUnavailable()
        with self._lock:
            self._expire(self._clock())
            selected = []
            for handle in handles:
                entry = self._entries.get(handle)
                if (entry is None or
                        (entry.session_id, entry.instance, entry.agent_id)
                        != (session_id, instance, agent_id)):
                    raise ActiveImageUnavailable()
                selected.extend(entry.images)
            if len(selected) > 8:
                raise ActiveImageUnavailable()
            return tuple(selected)

    def clear(self, session_id: str | None = None) -> None:
        with self._lock:
            if session_id is None:
                self._entries.clear()
                self._resident_bytes = 0
            else:
                for handle, entry in tuple(self._entries.items()):
                    if entry.session_id == session_id:
                        self._remove(handle)
