"""
calendar/main.py — Pepper's Google Calendar skill (H2.1).

Loader-pattern skill wrapping GoogleCalendarPlugin. Reads today's agenda and
creates simple events. Degrades gracefully without an access token.

Commands (see get_commands):
  today                          — list today's events
  add_event <title>|<start>|<end>  — create an event (ISO datetimes)
"""

import logging
import os

logger = logging.getLogger("jarvis.skills.calendar")

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
    return ["today", "add_event"]


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


async def handle(cmd: str, args: str, context: dict = None) -> str:
    dispatch = {"today": today, "add_event": add_event}
    fn = dispatch.get(cmd)
    if fn:
        return await fn(args, context)
    return f"[calendar] comandă necunoscută: {cmd}"
