"""Live execute_code interruption, scoped to a host-bound conversation session.

Only trusted ingress calls ``interrupt``.  The model cannot name a session or an
execution to cancel, and transport cancellation remains a separate path.
"""

from __future__ import annotations

import asyncio
import contextvars
from dataclasses import dataclass
from time import monotonic

MARKER = "[execution interrupted — user sent a new message]"
_CAPTURE_BYTES = 50_000


class PartialOutput:
    """Bounded output already delivered by the backend's stream readers."""

    def __init__(self) -> None:
        self._stdout = bytearray()
        self._stderr = bytearray()
        self.tool_calls = 0
        self.truncated = False

    def _append(self, target: bytearray, chunk: bytes) -> None:
        old_size = len(target)
        if len(target) < _CAPTURE_BYTES:
            target.extend(chunk[:_CAPTURE_BYTES - len(target)])
        if old_size + len(chunk) > _CAPTURE_BYTES:
            self.truncated = True

    def stdout_sink(self, chunk: bytes) -> None:
        self._append(self._stdout, chunk)

    def stderr_sink(self, chunk: bytes) -> None:
        self._append(self._stderr, chunk)

    def tool_called(self) -> None:
        self.tool_calls += 1

    @property
    def stdout(self) -> str:
        return self._stdout.decode("utf-8", errors="replace")

    @property
    def stderr(self) -> str:
        return self._stderr.decode("utf-8", errors="replace")


_capture = contextvars.ContextVar("nerva-active-code-capture", default=None)
_conversation = contextvars.ContextVar("nerva-code-conversation", default=None)
_admitted_channel = contextvars.ContextVar("nerva-code-admitted-channel", default=None)


def capture_scope(capture: PartialOutput):
    return _capture.set(capture)


def reset_capture(token) -> None:
    _capture.reset(token)


def current_capture() -> PartialOutput | None:
    return _capture.get()


def bind_conversation(session_id: str):
    return _conversation.set(session_id)


def reset_conversation(token) -> None:
    _conversation.reset(token)


def is_conversation(session_id: str) -> bool:
    return bool(session_id) and _conversation.get() == session_id


def bind_admitted_channel(channel: str):
    return _admitted_channel.set(channel)


def reset_admitted_channel(token) -> None:
    _admitted_channel.reset(token)


def is_admitted_channel(channel: str) -> bool:
    return _admitted_channel.get() == channel


@dataclass(eq=False)
class ActiveCode:
    session_id: str
    task: asyncio.Task
    capture: PartialOutput
    started: float
    interrupted: bool = False


_active: dict[str, set[ActiveCode]] = {}


def register(session_id: str, task: asyncio.Task, capture: PartialOutput) -> ActiveCode | None:
    if not session_id:
        return None
    record = ActiveCode(session_id, task, capture, monotonic())
    _active.setdefault(session_id, set()).add(record)
    return record


def unregister(record: ActiveCode | None) -> None:
    if record is not None:
        records = _active.get(record.session_id)
        if records is not None:
            records.discard(record)
            if not records:
                del _active[record.session_id]


def interrupt(session_id: str) -> bool:
    """Signal a live child without cancelling the model turn awaiting it."""
    signalled = False
    for record in tuple(_active.get(session_id, ())):
        if not record.task.done():
            record.interrupted = True
            record.task.cancel()
            signalled = True
    return signalled
