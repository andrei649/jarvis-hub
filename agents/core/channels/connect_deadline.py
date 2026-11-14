"""Validated opening budget shared by channel transports.

This value configures Telegram identity, Discord gateway, ntfy, IMAP and Slack opening
attempts. It is not a promise that late transport cleanup finishes within the same budget.
"""

from __future__ import annotations

import math

CONNECT_TIMEOUT_SETTING = "system.channel_connect_timeout_seconds"
DEFAULT_CONNECT_TIMEOUT = 15.0
MIN_CONNECT_TIMEOUT = 1.0
MAX_CONNECT_TIMEOUT = 25.0


def channel_connect_timeout(value: object) -> float:
    """Return a finite enabled budget; malformed settings keep the safe default."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return DEFAULT_CONNECT_TIMEOUT
    try:
        seconds = float(value)
    except (ValueError, OverflowError):
        return DEFAULT_CONNECT_TIMEOUT
    if not math.isfinite(seconds):
        return DEFAULT_CONNECT_TIMEOUT
    return max(MIN_CONNECT_TIMEOUT, min(MAX_CONNECT_TIMEOUT, seconds))
