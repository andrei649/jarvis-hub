"""Bind one consented terminal request to its final physical process launch."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(eq=False)
class ConsentDispatchScope:
    task_id: int
    backend: str
    target: str
    argv: tuple[str, ...]
    cwd: str
    timeout: int
    transport: object = field(repr=False)
    request: dict = field(repr=False)
    check: Callable[[], bool] = field(repr=False)
    active: bool = field(default=False, init=False, repr=False)
    used: bool = field(default=False, init=False, repr=False)
    originating_task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _request_snapshot: dict | None = field(default=None, init=False, repr=False)
    _binding_snapshot: tuple | None = field(default=None, init=False, repr=False)


_SCOPE: ContextVar[ConsentDispatchScope | None] = ContextVar(
    "consent_physical_dispatch", default=None,
)


@contextmanager
def bind_consent_dispatch(scope: ConsentDispatchScope) -> Iterator[None]:
    task = asyncio.current_task()
    if task is None or scope.active or scope.used or scope.originating_task is not None:
        raise RuntimeError("consent dispatch requires a fresh asyncio scope")
    scope.originating_task = task
    scope._request_snapshot = dict(scope.request)
    scope._binding_snapshot = (scope.task_id, scope.backend, scope.target,
                               scope.argv, scope.cwd, scope.timeout, scope.transport)
    scope.active = True
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        scope.active = False
        _SCOPE.reset(token)


def consent_dispatch_scope_present() -> bool:
    """Copied and closed contexts remain classified as consent authority."""
    return _SCOPE.get() is not None


def physical_gate(
    transport: object, *, backend: str, argv: tuple[str, ...], cwd: str,
    timeout: int,
) -> bool | None:
    """None means ordinary path; False refuses; True consumes queue dispatch CAS."""
    scope = _SCOPE.get()
    if scope is None:
        return None
    if not scope.active or scope.used:
        return False
    task = scope.originating_task
    if task is None or asyncio.current_task() is not task or task.done() or task.cancelling():
        return False
    # Mark used before any callback, including a failed check, to prevent retries.
    scope.used = True
    from .owner_once_dispatch import owner_once_scope_present

    if (owner_once_scope_present() or scope.transport is not transport
            or (scope.task_id, scope.backend, scope.target, scope.argv, scope.cwd,
                scope.timeout, scope.transport) != scope._binding_snapshot
            or scope.backend != backend or type(scope.task_id) is not int
            or scope.task_id <= 0 or scope.argv != argv or scope.cwd != cwd
            or scope.timeout != timeout or scope.request != scope._request_snapshot
            or scope.request.get("target") != scope.target):
        return False
    try:
        from agents.core.autonomy.consent_execution import consent_current, consent_dispatch

        if scope.check() is not True or consent_current(scope.task_id) is not True:
            return False
        return consent_dispatch(scope.task_id) is True
    except Exception:
        return False


__all__ = [
    "ConsentDispatchScope", "bind_consent_dispatch", "consent_dispatch_scope_present",
    "physical_gate",
]
