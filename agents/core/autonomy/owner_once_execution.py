"""Private, task-scoped worker authority for one owner-approved terminal dispatch.

No Task, request argument, model output or copied ContextVar can manufacture this
scope. The queue independently validates the signed owner receipt and consumes
the one-use physical dispatch transition.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .owner_once import OwnerOnceClaim
from .queue import TaskQueue


class _OwnerOnceExecution:
    def __init__(self, queue: TaskQueue, claim: OwnerOnceClaim,
                 worker_task: asyncio.Task, live_check: Callable[[], bool],
                 dispatch_check: Callable[[], bool]) -> None:
        self.queue = queue
        self.claim = claim
        self.worker_task = worker_task
        self.live_check = live_check
        self.dispatch_check = dispatch_check
        self._active = True
        self._lock = threading.Lock()

    def live(self) -> bool:
        with self._lock:
            active = self._active
        if not active or self.worker_task.done() or self.worker_task.cancelling():
            return False
        try:
            return self.live_check() is True
        except Exception:
            return False

    def close(self) -> None:
        with self._lock:
            self._active = False

    def dispatch_ready(self) -> bool:
        if not self.live():
            return False
        try:
            return self.dispatch_check() is True
        except Exception:
            return False


_current: ContextVar[_OwnerOnceExecution | None] = ContextVar(
    "owner_once_worker_execution", default=None,
)


@contextmanager
def _worker_scope(queue: TaskQueue, claim: OwnerOnceClaim,
                  live_check: Callable[[], bool], *,
                  dispatch_check: Callable[[], bool]) -> Iterator[_OwnerOnceExecution]:
    worker_task = asyncio.current_task()
    if worker_task is None:
        raise RuntimeError("owner-once execution requires an asyncio task")
    scope = _OwnerOnceExecution(queue, claim, worker_task, live_check, dispatch_check)
    token = _current.set(scope)
    try:
        yield scope
    finally:
        scope.close()
        _current.reset(token)


def owner_once_current(task_id: int) -> bool:
    """Recheck the live private worker scope and its exact signed queue receipt."""
    scope = _current.get()
    if (type(task_id) is not int or task_id <= 0 or scope is None
            or scope.claim.task_id != task_id or not scope.live()):
        return False
    return scope.queue.verify_owner_once_terminal_approval(
        task_id, check=lambda _receipt: scope.live(),
    )


def owner_once_dispatch(task_id: int) -> bool:
    """Consume one physical-dispatch CAS at the actual transport spawn seam."""
    scope = _current.get()
    if (type(task_id) is not int or task_id <= 0 or scope is None
            or scope.claim.task_id != task_id or not scope.dispatch_ready()):
        return False
    return scope.queue.owner_once_dispatch_current(
        task_id, scope.claim, live_check=scope.dispatch_ready,
    )


__all__ = ["owner_once_current", "owner_once_dispatch"]
