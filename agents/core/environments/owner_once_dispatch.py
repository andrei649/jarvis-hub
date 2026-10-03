"""One private owner decision bound to the final physical terminal spawn.

The runner installs this short-lived scope only after target, contract and kernel
checks. It is not an authority by itself: the worker's private current check and
single-use queue dispatch CAS must both pass at the actual transport boundary.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(eq=False)
class OwnerOnceDispatchScope:
    task_id: int
    backend: str
    target: str
    argv: tuple[str, ...]
    cwd: str
    timeout: int
    transport: object = field(repr=False)
    request: dict = field(repr=False)
    check: Callable[[], bool] = field(repr=False)
    active: bool = field(default=True, init=False, repr=False)
    used: bool = field(default=False, init=False, repr=False)
    originating_task: asyncio.Task | None = field(default=None, init=False, repr=False)


_SCOPE: ContextVar[OwnerOnceDispatchScope | None] = ContextVar(
    "owner_once_physical_dispatch", default=None,
)


@contextmanager
def bind_owner_once_dispatch(scope: OwnerOnceDispatchScope) -> Iterator[None]:
    scope.originating_task = asyncio.current_task()
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        scope.active = False
        _SCOPE.reset(token)


def owner_once_scope_present() -> bool:
    """A copied, closed scope still forbids Docker's host fallback."""
    return _SCOPE.get() is not None


def _owner_current(task_id: int) -> bool:
    try:
        from agents.core.autonomy.owner_once_execution import owner_once_current

        return owner_once_current(task_id) is True
    except Exception:
        return False


def _owner_dispatch(task_id: int) -> bool:
    try:
        from agents.core.autonomy.owner_once_execution import owner_once_dispatch

        return owner_once_dispatch(task_id) is True
    except Exception:
        return False


def physical_gate(
    transport: object, *, backend: str, argv: tuple[str, ...], cwd: str,
    timeout: int,
) -> bool | None:
    """None means ordinary path; False refuses; True consumed the one-use CAS."""
    scope = _SCOPE.get()
    if scope is None:
        return None
    if not scope.active or scope.used:
        return False
    task = scope.originating_task
    if task is None or asyncio.current_task() is not task or task.done() or task.cancelling():
        return False
    scope.used = True
    if (scope.transport is not transport or scope.backend != backend
            or type(scope.task_id) is not int or scope.task_id <= 0
            or scope.argv != argv or scope.cwd != cwd or scope.timeout != timeout
            or scope.request.get("target") != scope.target):
        return False
    try:
        if scope.check() is not True or not _owner_current(scope.task_id):
            return False
        return _owner_dispatch(scope.task_id) is True
    except Exception:
        return False


__all__ = [
    "OwnerOnceDispatchScope", "bind_owner_once_dispatch", "owner_once_scope_present",
    "physical_gate",
]
