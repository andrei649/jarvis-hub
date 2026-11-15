"""The bounded owner setting for inbound image and voice bytes (H070)."""

from __future__ import annotations

DEFAULT_BYTES = 8 * 1024 * 1024
MAX_BYTES = 20 * 1024 * 1024
CATEGORY = "channels"
KEY = "max_inbound_media_bytes"


def configuration_problem(value) -> str | None:
    """Why an owner setting write is invalid; zero never disables the safety cap."""
    if type(value) is not int or not 1 <= value <= MAX_BYTES:
        return f"{KEY}: expected a whole number of bytes between 1 and {MAX_BYTES}"
    return None


def current_max_bytes() -> int:
    """Live effective cap, falling back to the bounded 8 MiB default on bad storage."""
    from agents.core import settings_db

    try:
        value = settings_db.get_value(CATEGORY, KEY, DEFAULT_BYTES)
    except Exception:
        return DEFAULT_BYTES
    return value if configuration_problem(value) is None else DEFAULT_BYTES
