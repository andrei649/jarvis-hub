"""H222 — whether Nerva is listening, for an indicator outside the main window.

Hermes shows a small always-visible "listening" cue even when its window is hidden.
Nerva's only mic cue lived inside the HUD page and was a static mute flag. Here the
voice paths publish what they are doing, and anything can read or follow it:

- **Sources.** ``hub`` — the host's own voice pipeline: ``armed`` while the wake-word
  detector holds the mic open, ``listening`` while it records an utterance, ``thinking``
  while it transcribes and answers, ``speaking`` while it plays the reply.
  ``satellite:<id>`` — a Wyoming satellite that said it heard its wake word or started
  capturing (``detection`` / ``voice-started``), until its transcript is answered or it
  disconnects. A satellite's own mic is otherwise invisible to the hub.
- **State.** :func:`snapshot` gives each source's state, the loudest of them
  (:data:`ORDER`: listening, then armed — both mean an open mic — then thinking,
  speaking, off) and ``mic_open``. A transient state not refreshed for
  :data:`STALE_SECONDS` is dropped, so a crashed capture never leaves the indicator on.
- **Get / set / on-change.** :func:`set_state` (the voice paths only; there is no route
  that sets it), :func:`snapshot`, :func:`subscribe` / :func:`unsubscribe` for a callback
  on every change, and ``seq``, which moves on every change, for pollers.
- **Read-only surfaces.** ``GET /api/voice/listening`` and ``GET /api/voice/listening/stream``;
  the HUD forwards it to the desktop shell's tray. None of them can open or close a mic.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger("jarvis.voice.listening")

HUB = "hub"
STATES = ("off", "armed", "listening", "thinking", "speaking")
#: Loudest first: an open mic outranks everything else.
ORDER = ("listening", "armed", "thinking", "speaking", "off")
MIC_OPEN = frozenset({"armed", "listening"})
TRANSIENT = frozenset({"listening", "thinking", "speaking"})
STALE_SECONDS = 120.0
MAX_SOURCES = 32
MAX_SOURCE_LEN = 80


class ListeningState:
    """Per-source listening state, thread-safe (the capture runs in a worker thread)."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._sources: dict[str, tuple[str, float]] = {}
        self._seq = 0
        self._subscribers: list[Callable[[dict], None]] = []

    def set_state(self, source: str, state: str) -> bool:
        """Record *source*'s state; ``off`` forgets it. False for a bad name or state."""
        if (not isinstance(source, str) or not source or len(source) > MAX_SOURCE_LEN
                or any(ch.isspace() or not ch.isprintable() for ch in source) or state not in STATES):
            return False
        with self._lock:
            before = self._sources.get(source, ("off", 0.0))[0]
            if state == "off":
                self._sources.pop(source, None)
            else:
                if source not in self._sources and len(self._sources) >= MAX_SOURCES:
                    return False
                self._sources[source] = (state, self._clock())
            changed = before != state
            if changed:
                self._seq += 1
            snap = self._snapshot_locked()
            subscribers = list(self._subscribers)
        if changed:
            for fn in subscribers:
                try:
                    fn(snap)
                except Exception:
                    logger.debug("listening subscriber failed", exc_info=True)
        return True

    def _expire_locked(self) -> None:
        now = self._clock()
        stale = [s for s, (state, at) in self._sources.items()
                 if state in TRANSIENT and now - at > STALE_SECONDS]
        for s in stale:
            del self._sources[s]
        if stale:
            self._seq += 1

    def _snapshot_locked(self) -> dict:
        self._expire_locked()
        sources = {s: state for s, (state, _) in sorted(self._sources.items())}
        present = set(sources.values())
        state = next(s for s in ORDER if s in present or s == "off")
        return {"state": state, "mic_open": bool(present & MIC_OPEN), "sources": sources, "seq": self._seq}

    def snapshot(self) -> dict:
        with self._lock:
            return self._snapshot_locked()

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        with self._lock:
            self._subscribers.append(fn)

    def unsubscribe(self, fn: Callable[[dict], None]) -> None:
        with self._lock:
            if fn in self._subscribers:
                self._subscribers.remove(fn)

    def reset(self) -> None:
        """Tests: forget every source and subscriber."""
        with self._lock:
            self._sources.clear()
            self._subscribers.clear()
            self._seq += 1


STATE = ListeningState()


def set_state(source: str, state: str) -> bool:
    return STATE.set_state(source, state)


def snapshot() -> dict:
    return STATE.snapshot()


def subscribe(fn: Callable[[dict], None]) -> None:
    STATE.subscribe(fn)


def unsubscribe(fn: Callable[[dict], None]) -> None:
    STATE.unsubscribe(fn)


def satellite_source(satellite_id: object) -> str:
    """``satellite:<id>`` for a known satellite, ``satellite`` when the id is unknown."""
    sid = str(satellite_id or "").strip()
    return f"satellite:{sid}" if sid else "satellite"


__all__ = [
    "HUB", "MIC_OPEN", "ORDER", "STALE_SECONDS", "STATE", "STATES", "ListeningState", "satellite_source",
    "set_state", "snapshot", "subscribe", "unsubscribe",
]
