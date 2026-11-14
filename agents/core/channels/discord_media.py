"""In-process authority for an approved Discord owner-DM attachment reply."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from .media_delivery import DeliverableFile


@dataclass(frozen=True)
class DiscordMediaPermit:
    task: asyncio.Task
    adapter: object
    channel_id: int
    sender_id: int
    reply_task_id: int
    files: tuple[DeliverableFile, ...]
    owner_allowed: Callable[[str, str], bool]
    _life: list[int] = field(default_factory=lambda: [0], repr=False)

    def current(self, adapter: object, channel_id: int, files: object) -> bool:
        return (self._life[0] == 1 and asyncio.current_task() is self.task
                and adapter is self.adapter
                and channel_id == self.channel_id and files is self.files)


_CURRENT: ContextVar[DiscordMediaPermit | None] = ContextVar(
    "discord_approved_media_permit", default=None)


def current_permit() -> DiscordMediaPermit | None:
    return _CURRENT.get()


@contextmanager
def bind_permit(permit: DiscordMediaPermit):
    if permit._life[0] != 0:
        raise RuntimeError("Discord media permit already used")
    permit._life[0] = 1
    token = _CURRENT.set(permit)
    try:
        yield
    finally:
        permit._life[0] = 2
        _CURRENT.reset(token)
