"""
calendar/main.py — Pepper's Google Calendar skill (H2.1 / H2.2).

Loader-pattern skill wrapping GoogleCalendarPlugin. Reads today's agenda,
creates simple events, and answers availability ("am I free?") questions via
the provider-neutral `calendar_availability` helper. Degrades gracefully
without an access token.

Commands (see get_commands):
  today                            — list today's events
  add_event <title>|<start>|<end>  — create an event (ISO datetimes)
  free [time expression]           — "am I free [tomorrow at 3pm]?" / list free slots
"""

import logging
import os
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger("jarvis.skills.calendar")

# Andrei's home zone — interprets naive time expressions and frames slots.
DEFAULT_TZ = os.environ.get("JARVIS_TZ", "Europe/Bucharest")

_plugin = None


def _get_plugin():
    global _plugin
    if _plugin is not None:
        return _plugin
    try:
        from agents.core.plugins.google_calendar import GoogleCalendarPlugin
    except ImportError:
        from core.plugins.google_calendar import GoogleCalendarPlugin
    _plugin = GoogleCalendarPlugin(
        access_token=os.environ.get("GOOGLE_CALENDAR_TOKEN", ""),
    )
    return _plugin


def get_commands() -> list[str]:
    return ["today", "add_event", "free"]


def _no_token() -> str:
    return "Google Calendar nu e conectat — lipsește GOOGLE_CALENDAR_TOKEN (credentials)."


async def today(args: str = "", context: dict = None) -> str:
    plugin = _get_plugin()
    if not getattr(plugin, "access_token", ""):
        return _no_token()
    try:
        events = await plugin.get_today_events()
    except Exception as e:
        logger.warning(f"Calendar list failed: {e}")
        return "Google Calendar nu răspunde acum."
    if not events or (len(events) == 1 and "error" in events[0]):
        return "Nimic în agenda de azi."
    lines = []
    for ev in events[:10]:
        when = ev.get("start", ev.get("when", ""))
        title = ev.get("summary", ev.get("title", "(fără titlu)"))
        lines.append(f"- {when} {title}".rstrip())
    return f"Agenda de azi ({len(events)}):\n" + "\n".join(lines)


async def add_event(args: str, context: dict = None) -> str:
    """`add_event <title>|<start>|<end>` — ISO datetimes."""
    parts = [p.strip() for p in (args or "").split("|")]
    if len(parts) < 3 or not parts[0]:
        return "Folosire: add_event <titlu>|<start ISO>|<end ISO>"
    plugin = _get_plugin()
    if not getattr(plugin, "access_token", ""):
        return _no_token()
    title, start, end = parts[0], parts[1], parts[2]
    try:
        result = await plugin.create_event(summary=title, start_dt=start, end_dt=end)
    except Exception as e:
        logger.warning(f"Calendar create failed: {e}")
        return "Nu am putut crea evenimentul — Calendar indisponibil."
    if result:
        eid = result.get("id", result.get("event_id", "?")) if isinstance(result, dict) else "?"
        return f"Eveniment creat: „{title}” ({start} – {end}). [{eid}]"
    return "Nu am putut crea evenimentul."


# --------------------------------------------------------------------------- #
# Availability ("am I free?") — H2.2
# --------------------------------------------------------------------------- #

# Day-word → offset from today. Bilingual RO/EN, diacritic-free (input is folded).
_DAY_WORDS = {
    "today": 0, "azi": 0, "astazi": 0,
    "tomorrow": 1, "maine": 1,
    "tonight": 0, "diseara": 0,  # evening today; the hour regex narrows it
}

# Matches an hour: "3pm", "3 pm", "15", "15:30", "9:00", "la 3", "at 3pm".
_HOUR_RE = re.compile(
    r"\b(?:la|at)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    """Lowercase + strip RO diacritics so 'mâine'/'astăzi' match the tables."""
    import unicodedata

    folded = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in folded if not unicodedata.combining(c))


def parse_when(expr: str, *, now: datetime, tz: ZoneInfo):
    """Parse a basic time expression into an aware datetime, or None.

    Deliberately tiny (no real NLP): recognises a day word (today/tomorrow/azi/
    mâine, optional) plus an optional hour ("3pm", "15:30", "la 3"). Returns the
    resolved moment, or None when no concrete hour is present — the caller then
    falls back to listing the day's free slots.
    """
    folded = _fold(expr)
    if not folded:
        return None

    day_offset = None
    for word, off in _DAY_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", folded):
            day_offset = off
            break

    hour = minute = None
    for m in _HOUR_RE.finditer(folded):
        h = int(m.group(1))
        mi = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= mi <= 59:
            hour, minute = h, mi
            break

    if hour is None:
        return None  # no concrete time → caller lists free slots for the day

    base = now + timedelta(days=day_offset or 0)
    return datetime.combine(base.date(), time(hour=hour, minute=minute), tzinfo=tz)


def parse_day_offset(expr: str) -> int:
    """Day offset for the free-slots fallback (today=0, tomorrow=1)."""
    folded = _fold(expr)
    for word, off in _DAY_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", folded):
            return off
    return 0


async def free(args: str = "", context: dict = None) -> str:
    """`free [time expression]` — "am I free [tomorrow at 3pm]?" / list free slots.

    With a concrete time → yes/no answer via `am_i_free`. Without one → lists the
    remaining free slots for the chosen day (today by default). No calendar token
    → a graceful "connect your calendar" message, never an error.
    """
    try:
        from agents.core.calendar_availability import (
            am_i_free,
            free_slots,
            google_calendar_provider,
        )
    except ImportError:
        from core.calendar_availability import (
            am_i_free,
            free_slots,
            google_calendar_provider,
        )

    plugin = _get_plugin()
    if not getattr(plugin, "access_token", ""):
        return _no_token()

    tz = ZoneInfo(DEFAULT_TZ)
    now = datetime.now(tz)
    provider = google_calendar_provider(plugin)

    when = parse_when(args or "", now=now, tz=tz)

    try:
        if when is not None:
            ok = await am_i_free(when, tz, provider=provider)
            stamp = when.strftime("%d %b %H:%M")
            if ok:
                return f"Da, ești liber pe {stamp}."
            return f"Nu, ai ceva în calendar pe {stamp}."

        # No concrete time → list remaining free slots for the requested day.
        offset = parse_day_offset(args or "")
        day = (now + timedelta(days=offset)).date()
        win_start = now if offset == 0 else datetime.combine(day, time.min, tzinfo=tz)
        win_end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)

        try:
            from agents.core.calendar_availability import busy_intervals
        except ImportError:
            from core.calendar_availability import busy_intervals
        busy = await busy_intervals(win_start, win_end, tz, provider=provider)
        slots = free_slots(win_start, win_end, tz, busy=busy)
    except Exception as e:
        logger.warning(f"Calendar availability failed: {e}")
        return "Google Calendar nu răspunde acum."

    if not slots:
        label = "azi" if offset == 0 else "atunci"
        return f"Nu mai ai sloturi libere {label} (în orele de lucru)."

    label = "azi" if offset == 0 else day.strftime("%d %b")
    lines = [f"- {s.strftime('%H:%M')}–{e.strftime('%H:%M')}" for s, e in slots[:8]]
    return f"Sloturi libere {label} ({len(slots)}):\n" + "\n".join(lines)


async def handle(cmd: str, args: str, context: dict = None) -> str:
    dispatch = {"today": today, "add_event": add_event, "free": free}
    fn = dispatch.get(cmd)
    if fn:
        return await fn(args, context)
    return f"[calendar] comandă necunoscută: {cmd}"
