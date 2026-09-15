"""Request-local conversation identity shared by provider adapters."""
from contextlib import contextmanager
from contextvars import ContextVar

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
