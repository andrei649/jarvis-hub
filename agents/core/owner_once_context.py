"""Short-lived, transport-owned proof that a Telegram turn can receive a reply.

This is deliberately not an owner identity or approval token. The coordinator
must still validate the sender, the pending task, and the exact decision.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass, field


@dataclass(eq=False)
class OwnerReplySource:
    channel: object
    generation: str
    chat_id: int
    user_id: int
    originating_task: asyncio.Task
    _closed: bool = field(default=False, init=False, repr=False)

    def live(self) -> bool:
        task = self.originating_task
        poller = getattr(self.channel, "_poll_task", None)
        return (
            not self._closed
            and type(self.generation) is str
            and bool(self.generation)
            and type(self.chat_id) is int
            and type(self.user_id) is int
            and isinstance(task, asyncio.Task)
            and not task.done()
            and not task.cancelling()
            and getattr(self.channel, "_running", False) is True
            and getattr(self.channel, "_owner_once_generation", None) == self.generation
            and isinstance(poller, asyncio.Task)
            and not poller.done()
            and not poller.cancelling()
        )


_OWNER_REPLY_SOURCE: ContextVar[OwnerReplySource | None] = ContextVar(
    "owner_reply_source", default=None,
)


def bind_owner_reply_source(source: OwnerReplySource) -> Token:
    if not isinstance(source, OwnerReplySource):
        raise TypeError("owner reply source required")
    return _OWNER_REPLY_SOURCE.set(source)


def close_owner_reply_source(source: OwnerReplySource, token: Token) -> None:
    source._closed = True
    _OWNER_REPLY_SOURCE.reset(token)


def current_owner_reply_source() -> OwnerReplySource | None:
    source = _OWNER_REPLY_SOURCE.get()
    return source if source is not None and source.live() else None
