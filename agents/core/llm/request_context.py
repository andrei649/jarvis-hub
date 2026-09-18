"""Request-local conversation identity shared by provider adapters."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_session: ContextVar[str | None] = ContextVar('llm_session', default=None)


def current_session() -> str | None:
    return _session.get()


@contextmanager
def session_scope(session_id: str | None):
    token = _session.set(str(session_id) if session_id else None)
    try:
        yield
    finally:
        _session.reset(token)


# The canonical override is immutable. Only its lifetime is shared with inherited
# tasks, allowing request completion to revoke an explicit override everywhere.


@dataclass
class _ReasoningLifetime:
    active: bool = True
    parent: '_ReasoningLifetime | None' = None

    def is_active(self):
        return self.active and (self.parent is None or self.parent.is_active())


@dataclass(frozen=True)
class _ReasoningFrame:
    effort: str | None
    lifetime: _ReasoningLifetime


_reasoning: ContextVar[_ReasoningFrame | None] = ContextVar('invocation_reasoning', default=None)


def ensure_reasoning_active():
    from .reasoning_effort import ReasoningEffortRefused
    frame = _reasoning.get()
    if frame is not None and not frame.lifetime.is_active():
        raise ReasoningEffortRefused()


def selected_reasoning(default):
    ensure_reasoning_active()
    frame = _reasoning.get()
    return frame.effort if frame is not None and frame.effort is not None else default


@contextmanager
def reasoning_scope(effort: str | None):
    from .reasoning_effort import LADDER
    if effort is not None and (type(effort) is not str or effort not in LADDER):
        raise ValueError('reasoning must be a canonical effort level')
    ensure_reasoning_active()
    parent = _reasoning.get()
    frame = (_ReasoningFrame(effort, _ReasoningLifetime(parent=parent.lifetime if parent else None))
             if effort is not None or parent is not None else None)
    token = _reasoning.set(frame)
    try:
        yield
    finally:
        if frame is not None:
            frame.lifetime.active = False
        _reasoning.reset(token)
