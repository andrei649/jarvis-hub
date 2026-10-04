"""Credit only live, delivered native human waits to one tool-runtime run.

The prompt adapter owns proof of delivery and the exact request binding. This
module only accounts time: it cannot authorize an action. A scope is inherited
by child tasks, then closed when its run ends so detached work cannot revive it.
"""

from __future__ import annotations

import asyncio
import contextvars
import math
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

_MAX_ACTIVE_WINDOWS = 64
_MAX_CREDIT_SECONDS = 1_000_000_000.0


@dataclass(eq=False)
class _Window:
    task: asyncio.Task[object]
    current: Callable[[], bool]
    expiry: float


class RuntimeHumanWaitScope:
    """A bounded union of actual native waits for a single runtime call."""

    def __init__(self) -> None:
        initial = _now()
        self._last = initial if initial is not None else 0.0
        self._credit = 0.0
        self._windows: set[_Window] = set()
        self._closed = False

    def _advance(self) -> None:
        if self._closed:
            return
        sampled = _now()
        if sampled is None:
            return
        now = max(self._last, sampled)
        latest = self._last
        for window in tuple(self._windows):
            if window.task.done() or window.task.cancelling() or not _is_current(window.current):
                self._windows.discard(window)
                continue
            latest = max(latest, min(now, window.expiry))
            if now >= window.expiry:
                self._windows.discard(window)
        self._credit = min(_MAX_CREDIT_SECONDS, self._credit + max(0.0, latest - self._last))
        self._last = now

    def seconds(self) -> float:
        """Return the union accrued so far; a dead binding adds no new credit."""
        self._advance()
        return self._credit

    def _open(self, task: asyncio.Task[object], current: Callable[[], bool], expiry: float) -> _Window | None:
        self._advance()
        if self._closed or len(self._windows) >= _MAX_ACTIVE_WINDOWS:
            return None
        window = _Window(task, current, expiry)
        self._windows.add(window)
        return window

    def _close_window(self, window: _Window) -> None:
        self._advance()
        self._windows.discard(window)

    def _close(self) -> None:
        self._advance()
        self._windows.clear()
        self._closed = True


_CURRENT: contextvars.ContextVar[RuntimeHumanWaitScope | None] = contextvars.ContextVar(
    "runtime_native_human_wait_scope", default=None,
)


def _now() -> float | None:
    value = time.monotonic()
    return value if math.isfinite(value) else None


def _is_current(predicate: Callable[[], bool]) -> bool:
    try:
        return predicate() is True
    except Exception:
        return False


def current_human_wait_scope() -> RuntimeHumanWaitScope | None:
    scope = _CURRENT.get()
    return scope if scope is not None and not scope._closed else None


@contextmanager
def runtime_human_wait_scope() -> Iterator[RuntimeHumanWaitScope]:
    """Establish a fresh account, even inside or parallel to another run."""
    scope = RuntimeHumanWaitScope()
    token = _CURRENT.set(scope)
    try:
        yield scope
    finally:
        scope._close()
        _CURRENT.reset(token)


@contextmanager
def native_human_wait_window(*, deadline: float, current: Callable[[], bool]) -> Iterator[None]:
    """Account a verified delivered prompt until exit, expiry or binding loss.

    ``deadline`` is an absolute monotonic expiry declared by the native prompt.
    Its hard clamp is tighter than a declared-wait-plus-60-second defense: even a
    wedged context can never accrue credit after that expiry. The caller supplies
    a live exact-request predicate; false or errors retire the window permanently.
    """
    scope = current_human_wait_scope()
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    now = _now()
    try:
        expiry = (float(deadline) if isinstance(deadline, (int, float))
                  and not isinstance(deadline, bool) else float("nan"))
    except (OverflowError, ValueError):
        expiry = float("nan")
    valid_deadline = (
        now is not None and math.isfinite(expiry) and expiry > now
    )
    window = None
    if (scope is not None and task is not None and valid_deadline and callable(current)
            and not task.done() and not task.cancelling() and _is_current(current)):
        window = scope._open(task, current, expiry)
    try:
        yield
    finally:
        if scope is not None and window is not None:
            scope._close_window(window)
