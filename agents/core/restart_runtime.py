"""Process-local admission and live-work census for a future governed restart.

This module never stops a service or changes persistent job/sub-agent settings. A
closed gate holds new work while previously admitted work settles. The owner of
the gate is one exact orchestrator; a different runtime cannot reopen it.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import inspect
import math
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

KINDS = ("turn", "job", "manual", "script", "held", "subagent", "worker", "control")
MAX_WAIT_SECONDS = 60.0
_BOUND: contextvars.ContextVar[tuple[Lease, tuple[int, object | None]] | None] = (
    contextvars.ContextVar("restart_live_lease", default=None)
)
_CREATE_LOCK = threading.Lock()


def _binder() -> tuple[int, object | None]:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return threading.get_ident(), task


class Lease:
    """One counted operation; releasing it is safe from cleanup callbacks."""

    def __init__(self, runtime: RestartRuntime, kind: str) -> None:
        self.runtime = runtime
        self.kind = kind
        self._live = True

    @contextlib.contextmanager
    def bind(self) -> Iterator[Lease]:
        """Allow this same task/thread to enter trusted nested work while live."""
        with self.runtime._lock:
            if not self._live:
                raise RuntimeError("restart lease already released")
        token = _BOUND.set((self, _binder()))
        try:
            yield self
        finally:
            _BOUND.reset(token)

    def release(self) -> None:
        with self.runtime._lock:
            if not self._live:
                return
            self._live = False
            self.runtime._counts[self.kind] -= 1


class RestartRuntime:
    """One orchestrator's ephemeral admission gate and bounded live counters."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self._lock = threading.RLock()
        self._counts = dict.fromkeys(KINDS, 0)
        self._closed: object | None = None

    def acquire(self, kind: str, *, allow_reentrant: bool = False) -> Lease | None:
        if kind not in KINDS or kind == "control":
            raise ValueError("unknown restart work kind")
        with self._lock:
            if self._closed is not None:
                binding = _BOUND.get()
                parent = binding[0] if binding is not None else None
                if (not allow_reentrant or binding is None or parent is None
                        or parent.runtime is not self or not parent._live
                        or binding[1] != _binder()):
                    return None
            self._counts[kind] += 1
            return Lease(self, kind)

    def acquire_control(self) -> Lease:
        """Count an externally authenticated recovery control during drain."""
        with self._lock:
            self._counts["control"] += 1
            return Lease(self, "control")

    def close_admission(self) -> object | None:
        with self._lock:
            if self._closed is not None:
                return None
            self._closed = object()
            return self._closed

    def reopen(self, token: object) -> bool:
        with self._lock:
            if token is None or self._closed is not token:
                return False
            self._closed = None
            return True

    def snapshot(self) -> dict:
        with self._lock:
            counts = dict(self._counts)
            return {"accepting": self._closed is None, "active": sum(counts.values()),
                    "by_kind": counts}

    def bind_child_operation(self, awaitable: Any) -> Any:
        """Explicitly carry this task's live lease into one trusted awaited child.

        ``asyncio.wait_for`` creates a child Task with a copied ContextVar. That
        copy alone is never authority: only a caller currently bound to a live
        lease may create this wrapper, and the child must bind it explicitly.
        A callable factory is evaluated only after the child starts, so a
        cancelled task cannot leave an unawaited handler coroutine behind.
        """
        binding = _BOUND.get()
        lease = binding[0] if binding is not None else None
        with self._lock:
            authorized = (binding is not None and lease is not None
                          and lease.runtime is self and lease._live
                          and binding[1] == _binder())

        async def run():
            def operation():
                return awaitable() if callable(awaitable) else awaitable

            if authorized:
                try:
                    with lease.bind():
                        return await operation()
                except RuntimeError:
                    if inspect.iscoroutine(awaitable):
                        awaitable.close()
                    raise
            return await operation()

        return run()

    async def wait_idle(self, token: object, timeout: float,
                        extra_probe: Callable[[], Any] | None = None) -> bool:
        """Keep the owned gate closed on success; reopen it on refusal/cancel.

        ``extra_probe`` returns True when external work remains, False when
        idle, and non-bool when unreadable. The caller must reopen after a
        successful wait if it decides not to perform its later guarded action.
        """
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout < 0):
            self.reopen(token)
            return False
        deadline = time.monotonic() + min(float(timeout), MAX_WAIT_SECONDS)
        try:
            while True:
                with self._lock:
                    if self._closed is not token or token is None:
                        return False
                    local_idle = not any(self._counts.values())
                if local_idle:
                    pending = False
                    if extra_probe is not None:
                        pending = extra_probe()
                        if inspect.isawaitable(pending):
                            pending = await asyncio.wait_for(
                                pending, timeout=max(0.0, deadline - time.monotonic()))
                    if type(pending) is not bool:
                        self.reopen(token)
                        return False
                    if not pending:
                        with self._lock:
                            if self._closed is token and not any(self._counts.values()):
                                return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.reopen(token)
                    return False
                await asyncio.sleep(min(0.025, remaining))
        except asyncio.CancelledError:
            self.reopen(token)
            raise
        except Exception:
            self.reopen(token)
            return False


def runtime_for(orch: Any) -> RestartRuntime:
    """Return the single runtime bound to this exact orchestrator instance."""
    if orch is None:
        raise ValueError("restart runtime requires an orchestrator")
    with _CREATE_LOCK:
        current = getattr(orch, "_restart_runtime", None)
        if current is None:
            current = RestartRuntime(orch)
            orch._restart_runtime = current
        if type(current) is not RestartRuntime or current.owner is not orch:
            raise RuntimeError("restart runtime owner changed")
        return current


__all__ = ["KINDS", "Lease", "MAX_WAIT_SECONDS", "RestartRuntime", "runtime_for"]
