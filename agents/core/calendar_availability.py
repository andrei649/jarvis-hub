"""
calendar_availability.py — provider-neutral "am I free?" availability helper.

Lineage: cal.com's availability-by-subtraction model. We never ask a provider
"when am I free?" — instead we take the working window and *subtract* busy
intervals from it. This keeps the core a set of small, pure, offline-testable
functions over intervals, with provider I/O pushed to the very edge.

Scope (deliberately small):
  * `busy_intervals` — normalize a calendar's events into merged busy intervals.
  * `free_slots`     — subtract busy from working hours, step into candidate slots.
  * `am_i_free`      — thin yes/no convenience over a moment or window.

Explicitly OUT of scope: multi-attendee intersection, booking limits, caching,
recurrence expansion (the provider is expected to expand recurring events —
Google Calendar does this via `singleEvents=True`).

Python 3.10+ stdlib `zoneinfo` is used for timezone handling; no third-party deps.

Contract
--------
An *events provider* is any callable (sync or async) with the shape::

    provider(start: datetime, end: datetime) -> Iterable[RawEvent]

where each ``RawEvent`` is a mapping describing one occurrence. Two shapes are
accepted so both fakes and the real Google plugin plug in cleanly:

  1. Timed event:    {"start": <dt|iso>, "end": <dt|iso>}
  2. All-day event:  {"start": "2026-06-20", "end": "2026-06-21", "all_day": True}
                     or simply a date-only ISO string in start/end.

Datetimes may be naive (interpreted in the query tz) or aware (respected, then
converted to the query tz). All-day events block the whole local day(s) they span.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, time, timedelta
from typing import Awaitable, Callable, Iterable, Mapping, Optional, Union
from zoneinfo import ZoneInfo

# An interval is a half-open [start, end) pair of tz-aware datetimes.
Interval = tuple[datetime, datetime]
RawEvent = Mapping[str, object]
EventsProvider = Callable[
    [datetime, datetime],
    Union[Iterable[RawEvent], Awaitable[Iterable[RawEvent]]],
]


def _as_zone(tz: Union[str, ZoneInfo]) -> ZoneInfo:
    return tz if isinstance(tz, ZoneInfo) else ZoneInfo(tz)


def _coerce_dt(value: object, tz: ZoneInfo) -> datetime:
    """Coerce a datetime / ISO string into a tz-aware datetime in ``tz``.

    Naive inputs are *assumed* to already be in ``tz`` (the query timezone).
    Aware inputs are converted to ``tz`` so all interval math is single-zone.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):  # bare date -> midnight local
        dt = datetime.combine(value, time.min)
    elif isinstance(value, str):
        s = value.strip()
        if "T" not in s and "t" not in s:
            # Date-only string (all-day boundary): midnight local.
            dt = datetime.combine(date.fromisoformat(s), time.min)
        else:
            # `fromisoformat` handles offsets and (3.11+) trailing 'Z'; be lenient.
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    else:
        raise TypeError(f"cannot coerce {value!r} to datetime")

    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _is_all_day(event: RawEvent, raw_start: object, raw_end: object) -> bool:
    if event.get("all_day") or event.get("allDay"):
        return True
    # Date-only ISO strings (no time component) imply an all-day event.
    return (
        isinstance(raw_start, str)
        and "T" not in raw_start
        and "t" not in raw_start
        and isinstance(raw_end, (str, type(None)))
        and (raw_end is None or ("T" not in raw_end and "t" not in raw_end))
    )


def _event_to_interval(event: RawEvent, tz: ZoneInfo) -> Optional[Interval]:
    """Turn one raw event into a tz-aware busy interval, or None to skip it."""
    raw_start = event.get("start")
    raw_end = event.get("end")
    if raw_start is None:
        return None

    if _is_all_day(event, raw_start, raw_end):
        start_day = _coerce_dt(raw_start, tz).date()
        if raw_end is None:
            end_day = start_day + timedelta(days=1)
        else:
            # All-day end is exclusive in calendar conventions (Google emits the
            # day *after* the last day), so it's already the right boundary.
            end_day = _coerce_dt(raw_end, tz).date()
            if end_day <= start_day:
                end_day = start_day + timedelta(days=1)
        start = datetime.combine(start_day, time.min, tzinfo=tz)
        end = datetime.combine(end_day, time.min, tzinfo=tz)
        return (start, end)

    start = _coerce_dt(raw_start, tz)
    if raw_end is None:
        return None
    end = _coerce_dt(raw_end, tz)
    if end <= start:
        return None
    return (start, end)


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    """Sort and merge overlapping/adjacent half-open intervals."""
    ordered = sorted(intervals, key=lambda iv: iv[0])
    merged: list[Interval] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def clip_intervals(
    intervals: Iterable[Interval], start: datetime, end: datetime
) -> list[Interval]:
    """Clip intervals to the [start, end) window, dropping empties."""
    out: list[Interval] = []
    for iv_start, iv_end in intervals:
        lo = max(iv_start, start)
        hi = min(iv_end, end)
        if lo < hi:
            out.append((lo, hi))
    return out


def normalize_events(
    events: Iterable[RawEvent],
    tz: ZoneInfo,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> list[Interval]:
    """Convert raw events into clipped, merged busy intervals (pure helper)."""
    intervals = [
        iv for ev in events if (iv := _event_to_interval(ev, tz)) is not None
    ]
    if start is not None and end is not None:
        intervals = clip_intervals(intervals, start, end)
    return merge_intervals(intervals)


async def busy_intervals(
    start: datetime,
    end: datetime,
    tz: Union[str, ZoneInfo],
    *,
    provider: EventsProvider,
) -> list[Interval]:
    """Normalize a calendar provider's events into merged busy intervals.

    Returns sorted, overlap-merged, tz-aware ``[start, end)`` intervals clipped
    to the query window. The ``provider`` may be sync or async; both are awaited
    correctly so this stays the single async entry point for I/O.
    """
    zone = _as_zone(tz)
    start = _coerce_dt(start, zone)
    end = _coerce_dt(end, zone)

    result = provider(start, end)
    if inspect.isawaitable(result):
        result = await result
    return normalize_events(result or [], zone, start, end)


def free_slots(
    start: datetime,
    end: datetime,
    tz: Union[str, ZoneInfo],
    *,
    working_hours: tuple[int, int] = (9, 18),
    slot_minutes: int = 30,
    busy: Optional[Iterable[Interval]] = None,
) -> list[Interval]:
    """Step working hours minus busy intervals into candidate free slots.

    Pure function over intervals — no I/O. For each day in ``[start, end)`` we
    build the local working window ``[working_hours[0], working_hours[1])``,
    intersect it with the query window, subtract busy time, then walk the
    remaining gaps in fixed ``slot_minutes`` steps. A trailing remainder smaller
    than one slot is dropped (we only emit slots that fully fit).
    """
    zone = _as_zone(tz)
    start = _coerce_dt(start, zone)
    end = _coerce_dt(end, zone)
    if end <= start:
        return []

    work_start_h, work_end_h = working_hours
    busy_merged = merge_intervals(busy or [])
    step = timedelta(minutes=slot_minutes)
    if step <= timedelta(0):
        raise ValueError("slot_minutes must be positive")

    slots: list[Interval] = []
    day = start.date()
    while datetime.combine(day, time.min, tzinfo=zone) < end:
        work_start = datetime.combine(day, time(hour=work_start_h), tzinfo=zone)
        if work_end_h >= 24:
            work_end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
        else:
            work_end = datetime.combine(day, time(hour=work_end_h), tzinfo=zone)

        # Intersect the day's working window with the overall query window.
        win_start = max(work_start, start)
        win_end = min(work_end, end)
        if win_start < win_end:
            free = _subtract(win_start, win_end, busy_merged)
            for gap_start, gap_end in free:
                cursor = gap_start
                while cursor + step <= gap_end:
                    slots.append((cursor, cursor + step))
                    cursor += step
        day += timedelta(days=1)

    return slots


def _subtract(
    win_start: datetime, win_end: datetime, busy: list[Interval]
) -> list[Interval]:
    """Subtract merged busy intervals from a single [win_start, win_end) window."""
    free: list[Interval] = []
    cursor = win_start
    for b_start, b_end in busy:
        if b_end <= cursor or b_start >= win_end:
            continue  # no overlap with the remaining window
        if b_start > cursor:
            free.append((cursor, min(b_start, win_end)))
        cursor = max(cursor, b_end)
        if cursor >= win_end:
            break
    if cursor < win_end:
        free.append((cursor, win_end))
    return free


async def am_i_free(
    when: Union[datetime, Interval],
    tz: Union[str, ZoneInfo],
    *,
    provider: EventsProvider,
    default_window_minutes: int = 30,
) -> bool:
    """Yes/no convenience: is the given moment or window free of busy time?

    ``when`` is either a single ``datetime`` (treated as a
    ``default_window_minutes`` window starting at that moment) or an explicit
    ``(start, end)`` interval. Returns True iff no busy interval overlaps it.
    """
    zone = _as_zone(tz)
    if isinstance(when, datetime):
        start = _coerce_dt(when, zone)
        end = start + timedelta(minutes=default_window_minutes)
    else:
        start, end = _coerce_dt(when[0], zone), _coerce_dt(when[1], zone)
    if end <= start:
        return True

    busy = await busy_intervals(start, end, zone, provider=provider)
    return len(busy) == 0


def google_calendar_provider(plugin) -> EventsProvider:
    """Wrap the real :class:`GoogleCalendarPlugin` as an events provider.

    The plugin's ``list_events`` returns flattened dicts (``ts`` + ``duration_min``)
    rather than raw start/end, so we reconstruct intervals from those. This is the
    only place that knows the plugin's wire shape; everything above is neutral.
    """

    async def _provider(start: datetime, end: datetime) -> list[RawEvent]:
        # `days_ahead` must reach the END of the query window measured from NOW
        # (the plugin fetches forward from today), NOT just the window width —
        # otherwise a query about a future day (e.g. "free tomorrow at 3pm")
        # fetches too few days and misses that day's events, wrongly reporting free.
        ref = datetime.now(end.tzinfo) if end.tzinfo else datetime.now()
        span_days = max(1, (end.date() - ref.date()).days + 1)
        raw = await plugin.list_events(max_results=250, days_ahead=span_days)
        events: list[RawEvent] = []
        for ev in raw:
            if not isinstance(ev, dict) or ev.get("error"):
                continue
            ts = ev.get("ts")
            if not ts:
                continue
            all_day = isinstance(ts, str) and "T" not in ts
            event: dict[str, object] = {"start": ts, "all_day": all_day}
            if all_day:
                event["end"] = None  # one full local day
            else:
                dur = int(ev.get("duration_min") or 0)
                # Reconstruct end from start + duration; min 1 min so it's non-empty.
                start_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                event["end"] = (start_dt + timedelta(minutes=max(dur, 1))).isoformat()
            events.append(event)
        return events

    return _provider
