"""Task-bound provenance for one original, owner-authored Telegram command.

Only the Telegram adapter creates a candidate. Gateway seals it after pairing and
an inbox write; command dispatch checks the current principal again. None of
these values is authority when supplied as a route keyword or message text.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

# Keep language routing small and deterministic. The adapter only uses this for
# text in an owner private DM; these pure checks never grant source authority.
_RESTART_PHRASE = re.compile(
    r"(?:please[ \t]+)?restart[ \t]+(?:"
    r"(?:the[ \t]+)?(?:nerva[ \t]+)?gateway|nerva"
    r")[.!? \t]*\Z",
    re.ASCII | re.IGNORECASE,
)


def plaintext_restart(text: object) -> bool:
    """Recognize only the bounded, explicit English restart request families."""
    return (type(text) is str and 1 <= len(text) <= 128
            and _RESTART_PHRASE.fullmatch(text) is not None)


def restart_command_text(text: object) -> bool:
    """Recognize a literal slash command or one bounded plain-text phrase."""
    return type(text) is str and (text == "/restart" or plaintext_restart(text))


@dataclass(frozen=True)
class TelegramCommandSeed:
    adapter: Any
    generation: str
    bot_id: int
    update_id: int
    message_id: int
    chat_id: int
    sender_id: int
    text: str


@dataclass(frozen=True)
class TelegramCommandCandidate(TelegramCommandSeed):
    task: asyncio.Task

    @property
    def provider_id(self) -> str:
        return f"telegram:{self.bot_id}:{self.update_id}"


@dataclass(frozen=True)
class InboundCommandSource:
    candidate: TelegramCommandCandidate
    inbox_id: str
    gateway: Any

    @property
    def provider_id(self) -> str:
        return self.candidate.provider_id

    @property
    def bot_id(self) -> int:
        return self.candidate.bot_id

    @property
    def update_id(self) -> int:
        return self.candidate.update_id

    @property
    def message_id(self) -> int:
        return self.candidate.message_id

    @property
    def chat_id(self) -> int:
        return self.candidate.chat_id

    @property
    def sender_id(self) -> int:
        return self.candidate.sender_id


_CANDIDATE: contextvars.ContextVar[TelegramCommandCandidate | None] = contextvars.ContextVar(
    "telegram_command_candidate", default=None)
_SOURCE: contextvars.ContextVar[InboundCommandSource | None] = contextvars.ContextVar(
    "inbound_command_source", default=None)


def candidate_live(candidate: TelegramCommandCandidate, *, adapter: Any, text: str,
                   sender: Any, chat_id: Any) -> bool:
    return (
        type(candidate) is TelegramCommandCandidate
        and candidate.adapter is adapter
        and candidate.task is asyncio.current_task()
        and getattr(adapter, "_running", False) is True
        and getattr(adapter, "_owner_once_generation", None) == candidate.generation
        and getattr(adapter, "_verified_bot_generation", None) == candidate.generation
        and getattr(adapter, "_bot_id", None) == candidate.bot_id
        and type(candidate.bot_id) is int and candidate.bot_id > 0
        and text == candidate.text and restart_command_text(candidate.text)
        and str(sender) == str(candidate.sender_id)
        and type(chat_id) is int and chat_id == candidate.chat_id == candidate.sender_id
    )


@contextlib.contextmanager
def bind_candidate(candidate: TelegramCommandCandidate) -> Iterator[None]:
    token = _CANDIDATE.set(candidate)
    try:
        yield
    finally:
        _CANDIDATE.reset(token)


def current_candidate() -> TelegramCommandCandidate | None:
    candidate = _CANDIDATE.get()
    return candidate if candidate is not None and candidate.task is asyncio.current_task() else None


@contextlib.contextmanager
def bind_source(source: InboundCommandSource | None) -> Iterator[None]:
    token = _SOURCE.set(source)
    try:
        yield
    finally:
        _SOURCE.reset(token)


def source_for_dispatch(*, text: str, principal: Any, orch: Any) -> InboundCommandSource | None:
    source = _SOURCE.get()
    if type(source) is not InboundCommandSource or not source.inbox_id:
        return None
    candidate = source.candidate
    if text != candidate.text and text != "/restart":
        return None
    adapter = (getattr(orch, "channels", None) or {}).get("telegram")
    try:
        current_adapter = source.gateway.command_source_adapter()
        paired = source.gateway.pairing.is_allowed("telegram", str(candidate.sender_id)) is True
    except Exception:
        return None
    if current_adapter is not adapter or not paired:
        return None
    if not candidate_live(candidate, adapter=adapter, text=candidate.text,
                          sender=getattr(principal, "sender", None),
                          chat_id=candidate.chat_id):
        return None
    if (getattr(principal, "channel", None) != "telegram"
            or getattr(principal, "admin", None) is not True
            or getattr(principal, "scope", None) != "dm"
            or getattr(principal, "chat", None) != str(candidate.chat_id)):
        return None
    # Owner settings or pairing may have changed since the principal was bound.
    try:
        current = orch._channel_principal("telegram", str(candidate.sender_id), candidate.chat_id,
                                          "private")
    except Exception:
        return None
    return source if current.admin is True and current.scope == "dm" else None


__all__ = ["InboundCommandSource", "TelegramCommandCandidate", "TelegramCommandSeed", "bind_candidate",
           "bind_source", "candidate_live", "current_candidate", "plaintext_restart",
           "restart_command_text", "source_for_dispatch"]
