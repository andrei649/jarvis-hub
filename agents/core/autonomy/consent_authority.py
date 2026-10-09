"""Process-local Telegram callback authority for reusable owner consent.

Only trusted transport integrations call the factory with Bot API identity
fields and a predicate bound to the current callback registration. A Python
object is not a sandbox; this prevents request/model fields from being treated
as an issued callback merely because they look like a principal key.
"""

from __future__ import annotations

import json
import weakref
from collections.abc import Callable

from .consent_types import OwnerConsentActor


class _TelegramConsentAuthority:
    __slots__ = ('user_id', 'chat_id', 'principal_key', 'check', '__weakref__')

    def __init__(self, user_id: int, chat_id: int, current: Callable[[], bool]):
        self.user_id = user_id
        self.chat_id = chat_id
        self.principal_key = json.dumps(
            ['telegram', str(user_id), str(chat_id)], separators=(',', ':'),
        )

        def check() -> bool:
            try:
                return current() is True
            except Exception:
                return False

        self.check = check


_ISSUED: weakref.WeakSet[_TelegramConsentAuthority] = weakref.WeakSet()


def make_telegram_consent_actor(*, user_id: int, chat_id: int,
                                current: Callable[[], bool]) -> OwnerConsentActor | None:
    """Bind the actual callback sender/chat to a live server-owned predicate."""
    if (type(user_id) is not int or user_id <= 0 or type(chat_id) is not int
            or chat_id == 0 or not callable(current)):
        return None
    authority = _TelegramConsentAuthority(user_id, chat_id, current)
    _ISSUED.add(authority)
    return OwnerConsentActor('owner', 'telegram', authority.check,
                             authority.principal_key, authority)


def telegram_actor_current(actor: OwnerConsentActor) -> bool:
    """Validate exactly the issued event binding, then recheck transport now."""
    try:
        authority = actor.authority
        return (type(actor) is OwnerConsentActor
                and type(authority) is _TelegramConsentAuthority
                and authority in _ISSUED
                and actor.label == 'owner' and actor.decided_by == 'telegram'
                and actor.principal_key == authority.principal_key
                and actor.live is authority.check
                and actor.live() is True)
    except Exception:
        return False


def valid_telegram_principal(value: object) -> bool:
    """Accept only the factory's canonical event-derived identity encoding."""
    if type(value) is not str:
        return False
    try:
        parts = json.loads(value)
        if (type(parts) is not list or len(parts) != 3 or parts[0] != 'telegram'
                or type(parts[1]) is not str or type(parts[2]) is not str):
            return False
        user_id, chat_id = int(parts[1]), int(parts[2])
        return (user_id > 0 and chat_id != 0
                and parts[1] == str(user_id) and parts[2] == str(chat_id)
                and value == json.dumps(parts, separators=(',', ':')))
    except (TypeError, ValueError):
        return False
