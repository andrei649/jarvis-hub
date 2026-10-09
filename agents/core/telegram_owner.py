"""Pure Telegram owner-sender check for trusted server-side identity fields."""

from __future__ import annotations

import json

_MAX_USER_ID = 0xffffffffff
_OWNER_COLLECTIONS = (list, tuple, set, frozenset)


def _user_dialog_id(value: object) -> int | None:
    """Parse only canonical positive Bot API user-dialog identifiers."""
    if type(value) is int:
        return value if 1 <= value <= _MAX_USER_ID else None
    if (type(value) is str and 1 <= len(value) <= 13 and value.isascii()
            and value[0] in "123456789" and value.isdigit()):
        parsed = int(value)
        return parsed if parsed <= _MAX_USER_ID else None
    return None


def is_telegram_owner_sender(
    user_id: object, *, chat_id: object, owner_chat_id: object,
    allowed_user_ids: object,
) -> bool:
    """Authorize an owner sender, never a group destination alone.

    A configured sender list takes precedence even if it contains bad entries:
    valid members remain usable, but a nonempty invalid list cannot silently
    become the empty-list private-chat fallback. The caller separately checks
    the destination when the operation requires one particular owner chat.
    """
    sender = _user_dialog_id(user_id)
    if sender is None:
        return False
    if allowed_user_ids is not None:
        if type(allowed_user_ids) not in _OWNER_COLLECTIONS:
            return False
        if allowed_user_ids:
            return any(_user_dialog_id(entry) == sender for entry in allowed_user_ids)
    chat = _user_dialog_id(chat_id)
    owner_chat = _user_dialog_id(owner_chat_id)
    return chat is not None and chat == owner_chat == sender


def telegram_owner_user_ids(configured: object, *, allowed_user_ids: object) -> object:
    """Resolve explicit owner IDs, preserving malformed settings as invalid.

    ``None`` alone means the owner setting is absent and the ingress allowlist
    supplies the legacy identity. An explicitly supplied invalid value must
    never become that fallback or an empty-list private-chat authorization.
    """
    if configured is None:
        return allowed_user_ids
    if type(configured) in _OWNER_COLLECTIONS:
        return configured
    if type(configured) is str:
        try:
            decoded = json.loads(configured)
        except ValueError:
            return configured
        return decoded if type(decoded) is list else configured
    return configured
