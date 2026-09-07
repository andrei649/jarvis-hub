"""Group-chat gating for chat adapters (Hermes absorption 0.4).

Nerva's only gating vocabulary was one flat ``allowed_user_ids`` list, so a bot placed in a
group answered every message from every permitted member, and every message in the room
became context the agent reasoned and acted on. Being in a room is not being addressed.

This is an authorization boundary, so it fails closed: an unknown chat type is dropped, a
configured chat allowlist is exact, and in a group only an explicit mention of the bot or a
reply to one of its messages counts as being addressed — unless the owner turns that
requirement off for the room. Observe mode is the one middle ground: an unaddressed message
in an allowed group is recorded as context and never answered.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..env_config import is_recognized_bool, truthy

PRIVATE_CHAT_TYPES = frozenset({"private"})
GROUP_CHAT_TYPES = frozenset({"group", "supergroup", "channel"})

ANSWER = "answer"
OBSERVE = "observe"
DROP = "drop"


def _flag(raw: str | None, *, default: bool) -> bool:
    """One boolean convention in the tree (`env_config`); an unrecognised spelling keeps the default."""
    if raw is None or not is_recognized_bool(raw):
        return default
    return truthy(raw, default)


def _csv(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


@dataclass(frozen=True)
class GroupPolicy:
    """What a bot does with a message that arrives in a room rather than a DM."""

    require_mention: bool = True
    allowed_chat_ids: frozenset[str] = frozenset()
    observe_mode: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> GroupPolicy:
        """``TELEGRAM_GROUP_REQUIRE_MENTION`` / ``TELEGRAM_ALLOWED_CHAT_IDS`` / ``TELEGRAM_GROUP_OBSERVE``.

        An allowlist entry is a chat id, or ``chat_id:thread_id`` for one forum topic.
        """
        env = os.environ if environ is None else environ
        return cls(
            require_mention=_flag(env.get("TELEGRAM_GROUP_REQUIRE_MENTION"), default=True),
            allowed_chat_ids=frozenset(_csv(env.get("TELEGRAM_ALLOWED_CHAT_IDS"))),
            observe_mode=_flag(env.get("TELEGRAM_GROUP_OBSERVE"), default=False),
        )

    def chat_allowed(self, chat_id: Any, thread_id: Any = None) -> bool:
        if not self.allowed_chat_ids:
            return True
        chat = str(chat_id)
        if thread_id is not None and f"{chat}:{thread_id}" in self.allowed_chat_ids:
            return True
        return chat in self.allowed_chat_ids


@dataclass(frozen=True)
class GateDecision:
    action: str
    reason: str
    text: str


def gate_message(
    policy: GroupPolicy,
    *,
    chat_type: Any,
    chat_id: Any,
    text: str,
    thread_id: Any = None,
    entities: Iterable[Any] = (),
    reply_to_from_id: Any = None,
    bot_id: Any = None,
    bot_username: str | None = None,
) -> GateDecision:
    """Decide whether a message is answered, observed or dropped, and what text survives.

    The returned text has the bot's own mention removed so the model never sees itself
    being summoned; an unaddressed message keeps its text (observe mode records it as is).
    """
    kind = str(chat_type or "").strip().lower()
    if kind in PRIVATE_CHAT_TYPES:
        return GateDecision(ANSWER, "private_chat", text)
    if kind not in GROUP_CHAT_TYPES:
        return GateDecision(DROP, "unknown_chat_type", text)
    if not policy.chat_allowed(chat_id, thread_id):
        return GateDecision(DROP, "chat_not_allowed", text)
    addressed, stripped = _addressed(
        text,
        entities,
        reply_to_from_id=reply_to_from_id,
        bot_id=bot_id,
        bot_username=bot_username,
    )
    if addressed:
        return GateDecision(ANSWER, "addressed", stripped)
    if not policy.require_mention:
        return GateDecision(ANSWER, "mention_not_required", text)
    if policy.observe_mode:
        return GateDecision(OBSERVE, "observe", text)
    return GateDecision(DROP, "not_addressed", text)


def _addressed(
    text: str,
    entities: Iterable[Any],
    *,
    reply_to_from_id: Any,
    bot_id: Any,
    bot_username: str | None,
) -> tuple[bool, str]:
    addressed = False
    if bot_id is not None and reply_to_from_id is not None and str(reply_to_from_id) == str(bot_id):
        addressed = True
    stripped = text
    username = (bot_username or "").strip().lstrip("@")
    if username:
        # The `/command@bot` form Telegram uses in groups keeps its command …
        command = re.compile(rf"^(/\w+)@{re.escape(username)}\b", re.IGNORECASE)
        if command.match(stripped):
            addressed = True
            stripped = command.sub(r"\1", stripped)
        # … and `@bot` anywhere else is removed; `x@bot` (an address) is not a mention.
        mention = re.compile(rf"(?<![\w@])@{re.escape(username)}\b", re.IGNORECASE)
        if mention.search(stripped):
            addressed = True
            stripped = mention.sub("", stripped)
    if bot_id is not None:
        for entity in entities or ():
            if not isinstance(entity, Mapping) or entity.get("type") != "text_mention":
                continue
            user = entity.get("user")
            if isinstance(user, Mapping) and str(user.get("id")) == str(bot_id):
                addressed = True
    cleaned = " ".join(stripped.split())
    return addressed, cleaned or text
