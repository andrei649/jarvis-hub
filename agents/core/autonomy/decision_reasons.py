"""Normalize optional human decision text; it is metadata, never authority."""
from __future__ import annotations

import unicodedata

MAX_REASON_CHARS = 280


def normalize_reason(reason: str | None) -> str | None:
    """Strict bounded input; control/format characters become spaces, empty is None."""
    if reason is None:
        return None
    if not isinstance(reason, str) or len(reason) > MAX_REASON_CHARS:
        raise ValueError("reason must be a string of at most 280 characters")
    cleaned = "".join(" " if unicodedata.category(ch) in {"Cc", "Cf"} else ch for ch in reason)
    return cleaned.strip() or None
