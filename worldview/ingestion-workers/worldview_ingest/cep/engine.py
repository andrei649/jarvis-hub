"""Windowed-keyed CEP engine skeleton (WorldView ticket H19.2.3).

A *pure*, framework-agnostic complex-event-processing engine that runs the
existing pure detectors (``cep.tipping`` / ``cep.anomaly``) over a live stream of
``(key, ts, payload)`` events with a bounded watermark / allowed lateness.

The engine is the streaming "driver" — it does NOT know *how* to detect anything;
it only knows *when* to call a rule and over *which* buffered events. Detection
itself stays in the pure ``detect_*`` functions, which a registered
:class:`Rule` adapts.

Design / semantics
------------------
- **Event time.** Every event carries a UNIX-seconds float ``ts`` (UTC). The
  engine never reads the wall clock — progress is driven purely by the event
  times it sees, so it is fully deterministic and replayable.
- **Watermark.** A monotonic estimate of "event time we believe is complete":
  ``watermark = max_event_ts - allowed_lateness_s``. It only ever rises. An
  event whose ``ts < watermark`` is *later than the allowed lateness* and is
  **dropped** (and counted in :attr:`dropped_late`). An out-of-order event whose
  ``ts >= watermark`` is still accepted and routed into its window.
- **Tumbling windows.** Time is partitioned, per key, into contiguous
  fixed-width buckets of ``window_s`` seconds aligned to the epoch:
  ``window_index = floor(ts / window_s)`` covering ``[start, start + window_s)``.
  A window *closes* (its rule fires once over its buffered events) as soon as the
  watermark reaches its right edge: ``watermark >= start + window_s``.
- **Per-key isolation.** Each key owns an independent set of windows; events,
  windows and firings of one key never bleed into another's. (The watermark is
  global, advanced by the max ts across all keys — the usual single-source-of-
  time model; per-key buffers are what stay isolated.)
- **Memory.** Once a window fires it is evicted, freeing its buffered events; a
  key with no remaining windows is dropped from the index entirely.

Pure stdlib only — no Kafka / asyncio imports live here.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

# Payload (P) and rule-output (R) are generic so the engine is reusable across
# detectors (e.g. P=ReconWindow, R=list[TippingEvent]). NOTE: we use the classic
# Generic/TypeVar form (not PEP 695 ``class Event[P]``) because the runtime here
# targets 3.11; ruff's UP046/UP047 (which want the 3.12 syntax) are ignored for
# this module in pyproject.toml.
P = TypeVar("P")  # event payload type
R = TypeVar("R")  # rule output type


@dataclass(frozen=True)
class Event(Generic[P]):  # noqa: UP046 — PEP 695 syntax needs py3.12; runtime here is 3.11
    """One stream event: a partition ``key``, an event-time ``ts``, a ``payload``.

    ``ts`` is a UNIX-seconds float (UTC). ``payload`` is opaque to the engine and
    handed verbatim to the rule (e.g. a decoded recon message dict).
    """

    key: str
    ts: float
    payload: P


@dataclass(frozen=True)
class WindowResult(Generic[R]):  # noqa: UP046 — see Event: classic Generic for 3.11 runtime
    """A rule firing over one closed window, with provenance for the emitter.

    - ``key`` / ``window_start`` / ``window_end``: the closed bucket
      ``[window_start, window_end)`` (UTC UNIX-seconds) and its owning key.
    - ``output``: whatever the rule returned (often a ``list`` of detections).
    """

    key: str
    window_start: float
    window_end: float
    output: R


# A Rule maps a window's buffered events (in arrival order) to an arbitrary
# output. Returning ``None`` (or an empty collection) means "nothing detected";
# the engine still records the firing only when the output is truthy (see below).
Rule = Callable[[str, float, float, list[Event[Any]]], Any]


@dataclass
class _Window(Generic[P]):  # noqa: UP046 — see Event: classic Generic for 3.11 runtime
    """Internal per-key bucket: its half-open ``[start, end)`` and buffered events."""

    start: float
    end: float
    events: list[Event[P]] = field(default_factory=list)


class WindowedKeyedEngine(Generic[P, R]):  # noqa: UP046 — see Event: classic Generic for 3.11
    """A tumbling, keyed, watermark-driven CEP engine running one registered rule.

    Usage::

        engine = WindowedKeyedEngine(window_s=600.0, allowed_lateness_s=120.0, rule=my_rule)
        for key, ts, payload in stream:
            for fired in engine.push(Event(key, ts, payload)):
                emit(fired)
        for fired in engine.flush():   # close any still-open windows at end-of-stream
            emit(fired)

    ``push`` ingests one event and returns the (possibly empty) list of
    :class:`WindowResult` produced by windows that closed as a result. ``flush``
    force-closes every remaining window (e.g. on shutdown) regardless of the
    watermark, so nothing is silently stranded.
    """

    def __init__(
        self,
        window_s: float,
        allowed_lateness_s: float,
        rule: Rule,
    ) -> None:
        if window_s <= 0:
            raise ValueError("window_s must be > 0")
        if allowed_lateness_s < 0:
            raise ValueError("allowed_lateness_s must be >= 0")
        self.window_s = float(window_s)
        self.allowed_lateness_s = float(allowed_lateness_s)
        self._rule = rule

        # Per-key open windows, keyed by window-start time. Fully isolated per key.
        self._windows: dict[str, dict[float, _Window[P]]] = {}
        # Highest event ts seen across ALL keys; drives the (monotonic) watermark.
        self._max_event_ts: float | None = None

        # Observability counters (read-only by convention).
        self.dropped_late = 0  # events later than the allowed lateness (ts < watermark)
        self.fired = 0  # number of windows that closed and fired the rule

    # ------------------------------------------------------------------ #
    # watermark
    # ------------------------------------------------------------------ #
    @property
    def watermark(self) -> float:
        """Current watermark = ``max_event_ts - allowed_lateness_s``.

        Before any event is seen there is no time basis, so the watermark is
        ``-inf`` (nothing is ever "late" against an empty stream).
        """
        if self._max_event_ts is None:
            return -math.inf
        return self._max_event_ts - self.allowed_lateness_s

    def _window_bounds(self, ts: float) -> tuple[float, float]:
        """Tumbling bucket ``[start, end)`` containing ``ts`` (epoch-aligned)."""
        start = math.floor(ts / self.window_s) * self.window_s
        return start, start + self.window_s

    # ------------------------------------------------------------------ #
    # ingest
    # ------------------------------------------------------------------ #
    def push(self, event: Event[P]) -> list[WindowResult[R]]:
        """Ingest one event; return results for any windows that closed.

        Steps:

        1. Advance the watermark from this event's ts (monotonic via the running
           max — an out-of-order, *older* event can never lower it).
        2. If the event is later than the allowed lateness (``ts < watermark``)
           drop it and bump :attr:`dropped_late`; it joins no window.
        3. Otherwise route it into its (per-key) tumbling window, creating the
           bucket on first touch.
        4. Fire and evict every window whose right edge the watermark has now
           reached, across all keys.
        """
        # 1. Watermark only ever rises (running max of event ts).
        if self._max_event_ts is None or event.ts > self._max_event_ts:
            self._max_event_ts = event.ts

        # 2. Too late? Drop and count. NOTE: compute against the *post-advance*
        #    watermark so an event cannot drop itself by raising the bar — only a
        #    later (higher-ts) event can render a subsequent older event late.
        if event.ts < self.watermark:
            self.dropped_late += 1
            return []

        # 3. Route into the owning per-key tumbling window.
        start, end = self._window_bounds(event.ts)
        key_windows = self._windows.setdefault(event.key, {})
        window = key_windows.get(start)
        if window is None:
            window = _Window(start=start, end=end)
            key_windows[start] = window
        window.events.append(event)

        # 4. Close everything the watermark now covers.
        return self._collect_closed()

    # ------------------------------------------------------------------ #
    # close / flush
    # ------------------------------------------------------------------ #
    def _collect_closed(self) -> list[WindowResult[R]]:
        """Fire+evict every window whose ``end <= watermark`` (all keys)."""
        wm = self.watermark
        results: list[WindowResult[R]] = []
        for key in list(self._windows.keys()):
            key_windows = self._windows[key]
            # Deterministic order: close earlier windows before later ones.
            for start in sorted(key_windows.keys()):
                window = key_windows[start]
                if window.end <= wm:
                    fired = self._fire(key, window)
                    if fired is not None:
                        results.append(fired)
            # Drop fired windows; release a key with no windows left.
            self._evict_closed(key, wm)
        return results

    def _evict_closed(self, key: str, wm: float) -> None:
        """Remove every closed window for ``key`` (and the key if it empties)."""
        key_windows = self._windows[key]
        for start in [s for s, w in key_windows.items() if w.end <= wm]:
            del key_windows[start]  # frees the buffered events
        if not key_windows:
            del self._windows[key]

    def _fire(self, key: str, window: _Window[P]) -> WindowResult[R] | None:
        """Run the rule over a closed window; wrap a truthy output as a result.

        A rule returning ``None`` or an empty/falsey output means "nothing
        detected" and produces no :class:`WindowResult` (so empty windows are
        cheap and silent), but the window is still counted as fired/evicted.
        """
        self.fired += 1
        output = self._rule(key, window.start, window.end, window.events)
        if not output:
            return None
        return WindowResult(
            key=key,
            window_start=window.start,
            window_end=window.end,
            output=output,
        )

    def flush(self) -> list[WindowResult[R]]:
        """Force-close EVERY remaining window (end-of-stream / shutdown).

        Ignores the watermark: any still-open window is fired and evicted so no
        buffered events are stranded. After ``flush`` the engine holds no
        windows (counters are preserved).
        """
        results: list[WindowResult[R]] = []
        for key in list(self._windows.keys()):
            key_windows = self._windows[key]
            for start in sorted(key_windows.keys()):
                fired = self._fire(key, key_windows[start])
                if fired is not None:
                    results.append(fired)
            del self._windows[key]
        return results

    # ------------------------------------------------------------------ #
    # introspection (mainly for tests)
    # ------------------------------------------------------------------ #
    def open_window_count(self) -> int:
        """Total number of still-open (un-fired) windows across all keys."""
        return sum(len(w) for w in self._windows.values())

    def key_count(self) -> int:
        """Number of keys that currently hold at least one open window."""
        return len(self._windows)
