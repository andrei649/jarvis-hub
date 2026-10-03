"""Private worker authority for an exact reusable-consent execution.

The queue owns the signed proof and single-use physical transition. This scope
only binds those checks to the original worker task and its live lifetime.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from .consent_types import ConsentClaim

if TYPE_CHECKING:
    from .queue import TaskQueue


class _ConsentExecution:
    def __init__(self, queue: TaskQueue, claim: ConsentClaim,
                 worker_task: asyncio.Task, live_check: Callable[[], bool],
                 dispatch_check: Callable[[], bool],
                 trusted_executor: Callable | None) -> None:
        self.queue = queue
        self.claim = claim
        self.worker_task = worker_task
        self.live_check = live_check
        self.dispatch_check = dispatch_check
        self.trusted_executor = trusted_executor
        self.handler_task: asyncio.Task | None = None
        self._handler_bound = False
        self._handler_active = False
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

    def authorized_task(self) -> bool:
        try:
            current = asyncio.current_task()
        except RuntimeError:
            return False
        if current is self.worker_task:
            return True
        return (self._handler_active and current is self.handler_task
                and current is not None and not current.done() and not current.cancelling())

    def authorize_handler(self, executor: object, dispatch_task: object,
                          handler_task: asyncio.Task) -> bool:
        """One trusted TaskExecutor may bind its exact guarded wait_for child."""
        if (self._handler_bound or not self.live() or asyncio.current_task() is not self.worker_task
                or self.trusted_executor is None
                or getattr(self.trusted_executor, "__self__", None) is not executor
                or getattr(self.trusted_executor, "__func__", None)
                is not getattr(type(executor), "execute", None)
                or getattr(executor, "execution_guard", None) is None
                or type(handler_task) is not asyncio.Task
                or handler_task.done() or handler_task.cancelling()
                or type(getattr(dispatch_task, "id", None)) is not int
                or dispatch_task.id != self.claim.task_id):
            return False
        try:
            from .queue import TaskQueue, TaskStatus

            persisted = self.queue.get(dispatch_task.id)
            fingerprint = TaskQueue.execution_fingerprint(dispatch_task)
            if (persisted is None or persisted.status != TaskStatus.RUNNING.value
                    or fingerprint is None
                    or fingerprint != TaskQueue.execution_fingerprint(persisted)
                    or self.queue.verify_consent_execution(
                        dispatch_task.id, self.claim, live_check=self.live,
                    ) is not True):
                return False
        except Exception:
            return False
        self.handler_task = handler_task
        self._handler_bound = True
        self._handler_active = True
        handler_task.add_done_callback(self._handler_done)
        return True

    def _handler_done(self, task: asyncio.Task) -> None:
        if task is self.handler_task:
            self._handler_active = False

    def dispatch_ready(self) -> bool:
        if not self.live() or not self.authorized_task():
            return False
        try:
            return self.dispatch_check() is True
        except Exception:
            return False

    def close(self) -> None:
        with self._lock:
            self._active = False
            self._handler_active = False


_current: ContextVar[_ConsentExecution | None] = ContextVar(
    "consent_worker_execution", default=None,
)


@contextmanager
def _worker_scope(queue: TaskQueue, claim: ConsentClaim,
                  live_check: Callable[[], bool], *,
                  dispatch_check: Callable[[], bool],
                  trusted_executor: Callable | None = None) -> Iterator[_ConsentExecution]:
    worker_task = asyncio.current_task()
    if worker_task is None:
        raise RuntimeError("consent execution requires an asyncio task")
    scope = _ConsentExecution(queue, claim, worker_task, live_check, dispatch_check,
                              trusted_executor)
    token = _current.set(scope)
    try:
        yield scope
    finally:
        scope.close()
        _current.reset(token)


def consent_scope_present() -> bool:
    """Include copied or stale scopes so they cannot become ordinary requests."""
    return _current.get() is not None


def authorize_consent_handler(executor: object, dispatch_task: object,
                              handler_task: asyncio.Task) -> bool | None:
    """None is an ordinary execution; False is an untrusted consent handoff."""
    scope = _current.get()
    if scope is None:
        return None
    return scope.authorize_handler(executor, dispatch_task, handler_task)


def consent_current(task_id: int) -> bool:
    scope = _current.get()
    if (type(task_id) is not int or task_id <= 0 or scope is None
            or scope.claim.task_id != task_id or not scope.authorized_task()
            or not scope.live()):
        return False
    try:
        return scope.queue.verify_consent_execution(
            task_id, scope.claim, live_check=scope.live,
        ) is True
    except Exception:
        return False


def consent_dispatch(task_id: int) -> bool:
    scope = _current.get()
    if (type(task_id) is not int or task_id <= 0 or scope is None
            or scope.claim.task_id != task_id or not scope.dispatch_ready()):
        return False
    try:
        return scope.queue.consent_dispatch_current(
            task_id, scope.claim, live_check=scope.dispatch_ready,
        ) is True
    except Exception:
        return False


__all__ = ["consent_current", "consent_dispatch", "consent_scope_present"]
