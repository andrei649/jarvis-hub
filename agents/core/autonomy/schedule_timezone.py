"""Validated application timezone for schedule adapters.

The natural-language parser remains pure; callers supply this zone explicitly.
Owner-job runners pin the result on first use so a live settings change cannot
quietly move existing cron triggers. Restart the runner to adopt the new zone.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agents.core import settings_db

APP_TIMEZONE_DEFAULT = "Europe/Bucharest"
_ZONE_ALIASES = {"US/Eastern": "America/New_York"}


def app_schedule_timezone() -> ZoneInfo:
    """Read and validate the saved app zone; never substitute the host's zone."""
    try:
        # Unlike get_value(), read_setting does not recover an unreadable store
        # from stale last-good data. It also seeds a missing declared row.
        found, value = settings_db.read_setting("general", "timezone")
    except settings_db.SettingsUnreadable as exc:
        raise ValueError("app timezone is unavailable; repair the settings store") from exc

    name = value if found else APP_TIMEZONE_DEFAULT
    if not isinstance(name, str) or not name.strip():
        raise ValueError("configured app timezone is invalid; choose a valid general.timezone")
    try:
        # Some minimal Unix zoneinfo installations omit the historical US/Eastern
        # link even though it is a shipped Settings option.
        return ZoneInfo(_ZONE_ALIASES.get(name, name))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("configured app timezone is invalid; choose a valid general.timezone") from exc
