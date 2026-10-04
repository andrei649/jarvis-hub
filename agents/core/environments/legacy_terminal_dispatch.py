"""Private, one-use physical fence for a manually approved Docker terminal call.

The scope grants nothing: its current check must revalidate durable approval,
the exact request and Action Kernel at the spawn boundary.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(eq=False)
class LegacyTerminalDispatchScope:
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


_SCOPE: ContextVar[LegacyTerminalDispatchScope | None] = ContextVar(
    'legacy_terminal_physical_dispatch', default=None,
)


@contextmanager
def bind_legacy_terminal_dispatch(scope: LegacyTerminalDispatchScope) -> Iterator[None]:
    scope.originating_task = asyncio.current_task()
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        scope.active = False
        _SCOPE.reset(token)


def legacy_terminal_scope_present() -> bool:
    """A copied closed scope must still forbid an unguarded host fallback."""
    return _SCOPE.get() is not None


def physical_gate(
    transport: object, *, backend: str, argv: tuple[str, ...], cwd: str, timeout: int,
) -> bool | None:
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
            or scope.request.get('target') != scope.target):
        return False
    try:
        return scope.check() is True
    except Exception:
        return False


__all__ = [
    'LegacyTerminalDispatchScope', 'bind_legacy_terminal_dispatch',
    'legacy_terminal_scope_present', 'physical_gate',
]
