"""Metadata-only camera event-source contracts."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from .models import CameraEvent


class CameraSourceError(RuntimeError):
    """Stable, non-sensitive camera-source refusal."""


@dataclass(frozen=True, slots=True)
class CameraEventPage:
    """One deterministic metadata page; it can never carry frame or clip bytes."""

    events: tuple[CameraEvent, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class CameraSourceHealth:
    status: str
    camera_count: int
    last_success_at: float | None = None
    last_error: str | None = None

    def to_public(self) -> dict[str, int | float | str | None]:
        return {
            "status": self.status,
            "camera_count": self.camera_count,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
        }


class CameraEventSource(Protocol):
    """The only camera-source interface exposed beyond the privacy pipeline."""

    def list_events(self, after: str | None, limit: int) -> Awaitable[CameraEventPage]: ...

    def health(self) -> CameraSourceHealth: ...
