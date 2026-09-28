"""
nl_schedule.py — H10.27 Natural-language scheduling.

Turns phrases like "every weekday at 7am", "în fiecare luni la 9", "daily at
18:30", or "every 15 minutes" into a 5-field cron expression
(`minute hour day-of-month month day-of-week`), so a user can schedule autonomy
jobs without writing cron by hand. English + Romanian, fully offline.

H450 adds what Hermes accepts beyond that:

* **One-shots** — a delay (``in 30m``, ``in 1h30m``, ``peste 2 ore``), an ISO
  timestamp (``2026-10-01 09:00``, anchored to the configured zone unless it carries
  an offset), and a day word with a time (``tomorrow at 9``, ``mâine la 9``,
  ``today at 18:00``, ``once at 9am``). They answer ``{"ok", "at", "description"}``
  with ``at`` in UTC ISO — never a daily cron from the hour, which is what a bare time
  still means.
* **Compact intervals** — ``every 2h``, ``every 30m`` and a bare ``2h`` / ``30m``. An
  interval a cron cannot keep (``every 45 minutes`` would fire at :00 and :45) is
  refused: minutes must divide the hour and hours the day.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Optional

#: How far ahead a one-shot may be armed.
MAX_ONE_SHOT_AHEAD = timedelta(days=366)

_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60}


def _unit(word: str) -> str:
    """days/zile/zi → d, hours/ore/oră → h, minutes/minute → m."""
    return "d" if word[0] in "dz" else "h" if word[0] in "ho" else "m"


_DURATION_TOKEN = re.compile(
    r"(\d+|(?<![a-zăâîșț])(?:an?|one|o|un)\b)\s*(?:de\s+)?"
    r"(days?|zile|zi|d|hours?|hrs?|ore|oră|ora|h|minutes?|minute|minut|mins?|m)(?![a-zăâîșț])"
)
_DELAY = re.compile(r"^(?:in|în|peste)\s+(.+?)\s*$")
_ISO = re.compile(
    r"\b(\d{4})-(\d{2})-(\d{2})(?:[t ]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(z|[+-]\d{2}:?\d{2})?)?(?![\d:])"
)
_TOMORROW = re.compile(r"\b(tomorrow|mâine|maine)\b")
_TODAY = re.compile(r"\b(today|azi|astăzi|astazi)\b")
_ONCE = re.compile(r"\b(once|o dată|o data|one time)\b")

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


def _duration(text: str) -> Optional[timedelta]:
    """``30m``, ``1h30m``, ``2 hours 15 minutes``, ``an hour``, ``30 de minute`` → a
    timedelta, or None unless the whole of *text* is duration tokens."""
    total, pos = 0, 0
    for match in _DURATION_TOKEN.finditer(text):
        if text[pos:match.start()].strip(" ,") not in ("", "and", "și", "si"):
            return None
        count = match.group(1)
        number = int(count) if count.isdigit() else 1
        total += number * _UNIT_SECONDS[_unit(match.group(2))]
        pos = match.end()
    if pos == 0 or text[pos:].strip():
        return None
    return timedelta(seconds=total)


def _one_shot(at: datetime, now: datetime, zone: tzinfo) -> dict:
    if at <= now:
        return {"ok": False, "error": f"{at.astimezone(zone):%Y-%m-%d %H:%M} has already passed"}
    if at - now > MAX_ONE_SHOT_AHEAD:
        return {"ok": False, "error": "a one-shot must be within a year"}
    return {"ok": True, "at": at.astimezone(UTC).isoformat(),
            "description": f"once at {at.astimezone(zone):%Y-%m-%d %H:%M} ({zone})"}


def _offset(raw: str) -> tzinfo:
    from datetime import timezone as fixed

    if raw == "z":
        return UTC
    sign = -1 if raw[0] == "-" else 1
    digits = raw[1:].replace(":", "")
    return fixed(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))


def _parse_one_shot(t: str, now: datetime, zone: tzinfo) -> Optional[dict]:
    """A one-shot said in words, or None when *t* is not one."""
    delay = _DELAY.match(t)
    if delay:
        span = _duration(delay.group(1))
        if span is not None:
            if span < timedelta(minutes=1):
                return {"ok": False, "error": "a delay must be at least one minute"}
            return _one_shot(now + span, now, zone)
        if _DURATION_TOKEN.match(delay.group(1)):
            # "in 2 hours at 9" is neither a delay nor a daily 9 o'clock: say which.
            return {"ok": False, "error": "say the delay alone (e.g. 'in 2h', 'in 1h30m') or a time "
                                          "('tomorrow at 9')"}
    iso = _ISO.search(t)
    if iso:
        year, month, day, hour, minute, second, offset = iso.groups()
        if hour is None:
            rest = _parse_time(t[:iso.start()] + " " + t[iso.end():])
            if rest is None:
                return {"ok": False, "error": "say the time too (e.g. '2026-10-01 09:00')"}
            hour, minute, second = rest[0], rest[1], 0
        hour, minute, second = int(hour), int(minute), int(second or 0)
        if not _valid(hour, minute) or second > 59:
            return {"ok": False, "error": f"invalid time {hour}:{minute:02d}"}
        try:
            local = datetime(int(year), int(month), int(day), hour, minute, second)
        except ValueError:
            return {"ok": False, "error": f"{year}-{month}-{day} is not a real date"}
        return _one_shot(local.replace(tzinfo=_offset(offset) if offset else zone), now, zone)
    days = 1 if _TOMORROW.search(t) else 0 if (_TODAY.search(t) or _ONCE.search(t)) else None
    if days is None:
        return None
    tm = _parse_time(t)
    if tm is None:
        return {"ok": False, "error": "could not find a time (e.g. 'tomorrow at 9')"}
    if not _valid(*tm):
        return {"ok": False, "error": f"invalid time {tm[0]}:{tm[1]:02d}"}
    today = now.astimezone(zone).date()

    def at_on(day: date) -> datetime:
        return datetime(day.year, day.month, day.day, tm[0], tm[1], tzinfo=zone)

    at = at_on(today + timedelta(days=days))
    if _ONCE.search(t) and not _TODAY.search(t) and not _TOMORROW.search(t) and at <= now:
        at = at_on(today + timedelta(days=1))          # "once at 9": the next 9 o'clock
    return _one_shot(at, now, zone)


def _local_zone() -> tzinfo:
    from tzlocal import get_localzone

    return get_localzone()


_COMPACT = r"(\d+)\s*(m|mins?|minutes?|minute|min|h|hrs?|hours?|ore|oră|ora)\b"


def _interval(n: int, unit: str) -> dict:
    """Every *n* minutes or hours as a cron, when a cron can keep that interval."""
    if unit.startswith(("m",)):
        if n < 1:  # GOV-148: `*/0` is not a valid cron field — refuse, don't emit it
            return {"ok": False, "error": "interval must be at least 1 minute"}
        if n % 60 == 0:
            return _interval(n // 60, "h")
        if 60 % n:
            return {"ok": False, "error": f"every {n} minutes cannot be kept by a schedule: the minutes must "
                                          "divide the hour (1, 2, 3, 4, 5, 6, 10, 12, 15, 20 or 30)"}
        return {"ok": True, "cron": f"*/{n} * * * *", "description": f"every {n} minute(s)"}
    if n < 1:
        return {"ok": False, "error": "interval must be at least 1 hour"}
    if 24 % n:
        return {"ok": False, "error": f"every {n} hours cannot be kept by a schedule: the hours must "
                                      "divide the day (1, 2, 3, 4, 6, 8 or 12); say 'every day at …' for longer"}
    return {"ok": True, "cron": f"0 */{n} * * *", "description": f"every {n} hour(s)"}


def parse_schedule(text: str, *, now: Optional[datetime] = None, zone: Optional[tzinfo] = None) -> dict:
    """Parse *text* → {ok, cron, description}, a one-shot {ok, at, description}, or
    {ok: False, error}. *now* and *zone* anchor one-shots (default: the clock and the
    local zone, which is also APScheduler's default)."""
    if not text or not text.strip():
        return {"ok": False, "error": "empty input"}
    t = " ".join(text.lower().split())

    # ── one-shots (H450) ──
    zone = zone or _local_zone()
    now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    once = _parse_one_shot(t, now, zone)
    if once is not None:
        return once

    # ── interval schedules (no time needed) ──
    m = re.search(rf"^{_COMPACT}$", t) or re.search(rf"(?:every|la fiecare|fiecare)\s+{_COMPACT}", t)
    if m:
        return _interval(int(m.group(1)), "m" if m.group(2)[0] == "m" else "h")
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
