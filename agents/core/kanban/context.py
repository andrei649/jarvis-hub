"""Nerva-owned authority and storage scope for the private Kanban state port."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KanbanContext:
    home: Path
    profile: str
    board: str = "default"
    task_id: str | None = None
    run_id: int | None = None
    session_id: str | None = None
    can_mutate: bool = False
    delegated: bool = False


@dataclass(eq=False)
class _BoundScope:
    context: KanbanContext
    closed: bool = False


_CURRENT: ContextVar[_BoundScope | None] = ContextVar("nerva_kanban_scope", default=None)


@contextmanager
def kanban_scope(context: KanbanContext | None) -> Iterator[KanbanContext | None]:
    """Bind a scope whose authority expires even in inherited context copies."""
    if context is not None and not isinstance(context, KanbanContext):
        raise TypeError("KanbanContext required")
    bound = _BoundScope(context) if context is not None else None
    token = _CURRENT.set(bound)
    try:
        yield context
    finally:
        if bound is not None:
            bound.closed = True
        _CURRENT.reset(token)


def current_context() -> KanbanContext | None:
    bound = _CURRENT.get()
    if bound is None or bound.closed:
        return None
    return bound.context


def scope_is_bound() -> bool:
    """Tell callers if a scope object exists, even after its lifetime closed."""
    return _CURRENT.get() is not None


def require_context() -> KanbanContext:
    context = current_context()
    if context is None:
        raise PermissionError("Kanban requires an active Nerva scope")
    return context


def require_mutation() -> KanbanContext:
    context = require_context()
    if not context.can_mutate or context.delegated:
        raise PermissionError("Kanban mutation requires a non-delegated mutating Nerva scope")
    return context
