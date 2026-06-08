"""Time parsing helpers shared across workers."""

from __future__ import annotations

from datetime import UTC, datetime


def parse_iso_utc(value: str | None) -> float | None:
    """Parse an ISO-8601 timestamp to a UTC UNIX epoch (float), or None if unparseable.

    Naive timestamps are assumed UTC; a trailing 'Z' is accepted.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()
