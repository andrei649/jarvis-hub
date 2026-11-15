"""Turn-scoped proof of a successfully completed explicit /new command."""
from __future__ import annotations

import contextvars
import re

_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def _valid(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


class SessionTransition:
    def __init__(self) -> None:
        self.session_id: str | None = None
        self.closed = False

    def finish(self, actual_session: object) -> dict[str, str] | None:
        if self.closed:
            return None
        self.closed = True
        if _valid(self.session_id) and self.session_id == actual_session:
            return {"command": "new", "session_id": self.session_id}
        return None


_current: contextvars.ContextVar[SessionTransition | None] = contextvars.ContextVar(
    "nerva_session_transition", default=None)


def open_session_transition():
    sink = SessionTransition()
    return sink, _current.set(sink)


def reset_session_transition(token) -> None:
    sink = _current.get()
    if sink is not None:
        sink.closed = True
    _current.reset(token)


def record_new_session(previous: object, created: object) -> None:
    """Called only after the governed /new operation has fully succeeded."""
    sink = _current.get()
    if sink is not None and not sink.closed and _valid(previous) and _valid(created) and previous != created:
        sink.session_id = created
