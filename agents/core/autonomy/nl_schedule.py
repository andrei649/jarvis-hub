"""
nl_schedule.py — H10.27 Natural-language scheduling.

Turns phrases like "every weekday at 7am", "în fiecare luni la 9", "daily at
18:30", or "every 15 minutes" into a 5-field cron expression
(`minute hour day-of-month month day-of-week`), so a user can schedule autonomy
jobs without writing cron by hand. English + Romanian, fully offline.
"""

from __future__ import annotations

import re
from typing import Optional

# Romanian + English day names → cron day-of-week (0/7=Sun … 6=Sat).
_DAYS = {
    "sunday": 0, "sun": 0, "duminica": 0, "duminică": 0,
    "monday": 1, "mon": 1, "luni": 1,
    "tuesday": 2, "tue": 2, "marti": 2, "marți": 2,
    "wednesday": 3, "wed": 3, "miercuri": 3,
    "thursday": 4, "thu": 4, "joi": 4,
    "friday": 5, "fri": 5, "vineri": 5,
    "saturday": 6, "sat": 6, "sambata": 6, "sâmbătă": 6,
}
_DAY_LABEL = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}


def _parse_time(text: str) -> Optional[tuple[int, int]]:
    """Find a time → (hour, minute). Supports 7am, 7:30pm, 19:00, 'la 9', 'at 9'."""
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text)
    if m:
        hour = int(m.group(1)) % 12
        if m.group(3) == "pm":
            hour += 12
        return hour, int(m.group(2) or 0)
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", text)          # 24h HH:MM
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"\b(?:at|la|ora)\s+(\d{1,2})\b", text)  # "at 9" / "la 9"
    if m:
        return int(m.group(1)), 0
    return None


def _valid(hour: int, minute: int) -> bool:
    return 0 <= hour <= 23 and 0 <= minute <= 59


def parse_schedule(text: str) -> dict:
    """Parse *text* → {ok, cron, description} or {ok: False, error}."""
    if not text or not text.strip():
        return {"ok": False, "error": "empty input"}
    t = text.lower().strip()

    # ── interval schedules (no time needed) ──
    m = re.search(r"every\s+(\d+)\s*(?:minutes?|mins?|min)\b", t) or \
        re.search(r"(?:la fiecare|fiecare)\s+(\d+)\s*(?:minute|min)\b", t)
    if m:
        n = int(m.group(1))
        if n < 1:  # GOV-148: `*/0` is not a valid cron field — refuse, don't emit it
            return {"ok": False, "error": "interval must be at least 1 minute"}
        return {"ok": True, "cron": f"*/{n} * * * *", "description": f"every {n} minute(s)"}
    m = re.search(r"every\s+(\d+)\s*(?:hours?|hrs?)\b", t) or \
        re.search(r"(?:la fiecare|fiecare)\s+(\d+)\s*(?:ore|oră|ora)\b", t)
    if m:
        n = int(m.group(1))
        if n < 1:
            return {"ok": False, "error": "interval must be at least 1 hour"}
        return {"ok": True, "cron": f"0 */{n} * * *", "description": f"every {n} hour(s)"}
    if re.search(r"\b(hourly|în fiecare oră|in fiecare ora|orar)\b", t):
        return {"ok": True, "cron": "0 * * * *", "description": "hourly"}
    if re.search(r"\bevery minute\b", t):
        return {"ok": True, "cron": "* * * * *", "description": "every minute"}

    # ── time-of-day schedules ──
    tm = _parse_time(t)
    if tm is None:
        return {"ok": False, "error": "could not find a time (e.g. 'at 7am', 'la 9')"}
    hour, minute = tm
    if not _valid(hour, minute):
        return {"ok": False, "error": f"invalid time {hour}:{minute:02d}"}

    # day-of-week selection
    if re.search(r"\b(weekday|weekdays|zi lucr|zile lucr)\w*", t):
        dow, label = "1-5", "weekdays"
    elif re.search(r"\b(weekends?|weekenduri)\b", t):  # GOV-147: the English plural
        dow, label = "0,6", "weekends"
    else:
        days = sorted({v for name, v in _DAYS.items() if re.search(rf"\b{name}\b", t)})
        if days:
            dow = ",".join(str(d) for d in days)
            label = ", ".join(_DAY_LABEL[d] for d in days)
        elif re.search(r"\b(every day|daily|fiecare zi|în fiecare zi|in fiecare zi|zilnic)\b", t):
            dow, label = "*", "every day"
        else:
            # a bare time with no day qualifier → treat as daily
            dow, label = "*", "every day"

    return {
        "ok": True,
        "cron": f"{minute} {hour} * * {dow}",
        "description": f"{label} at {hour:02d}:{minute:02d}",
    }
