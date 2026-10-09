"""Request-local output for the pinned CLI rendering helpers."""

from __future__ import annotations

import io
import sys
from contextlib import contextmanager
from contextvars import ContextVar

_SINK: ContextVar[tuple[io.StringIO, io.StringIO] | None] = ContextVar("kanban_cli_sink", default=None)


@contextmanager
def capture():
    pair = (io.StringIO(), io.StringIO())
    token = _SINK.set(pair)
    try:
        yield pair
    finally:
        _SINK.reset(token)


def emit(*values, sep=" ", end="\n", file=None, flush=False):
    pair = _SINK.get()
    if pair is None:
        raise RuntimeError("Kanban CLI output requires a request sink")
    stream = pair[1] if file is sys.stderr else pair[0]
    stream.write(sep.join(str(value) for value in values) + end)


def write(value):
    pair = _SINK.get()
    if pair is None:
        raise RuntimeError("Kanban CLI output requires a request sink")
    return pair[0].write(value)
