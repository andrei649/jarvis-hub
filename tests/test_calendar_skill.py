"""Tests for the calendar skill's availability command (H2.2).

Offline, no network: a fake GoogleCalendarPlugin is injected into the skill's
module-level `_plugin` slot. The fake's `list_events` returns the real plugin
wire shape (`ts` + `duration_min`), so these tests exercise the genuine
`google_calendar_provider` wrapper end to end through the skill.

Covers:
  * "am I free at <time>" with a clashing event   → busy
  * "am I free at <time>" with a free time         → free
  * no calendar token                              → graceful "connect" message
  * free-slots listing (no concrete time)          → lists remaining slots
  * the basic time-expression parser
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import importlib.util

# Load the skill module directly (skills/ is not a package on sys.path).
_spec = importlib.util.spec_from_file_location(
    "calendar_skill_main", repo_root / "skills" / "calendar" / "main.py"
)
cal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cal)

TZ = "Europe/Bucharest"
ZONE = ZoneInfo(TZ)


class FakePlugin:
    """Stand-in for GoogleCalendarPlugin in the wire shape the provider expects."""

    def __init__(self, events, access_token="fake-token"):
        self.access_token = access_token
        self._events = events
        self.calls = []

    async def list_events(self, max_results=10, days_ahead=1, include_today=True):
        self.calls.append((max_results, days_ahead))
        return list(self._events)


def _wire_event(start: datetime, duration_min: int) -> dict:
    """One event in the plugin's flattened wire shape (ts + duration_min)."""
    return {
        "ts": start.isoformat(),
        "title": "Busy",
        "duration_min": duration_min,
        "state": "upcoming",
    }


def _inject(events, token="fake-token"):
    cal._plugin = FakePlugin(events, access_token=token)


def _restore():
    cal._plugin = None


@pytest.fixture(autouse=True)
def _clean_plugin():
    _restore()
    yield
    _restore()


# --------------------------------------------------------------------------- #
# parse_when — the basic time-expression parser
# --------------------------------------------------------------------------- #


def test_parse_when_tomorrow_3pm():
    now = datetime(2026, 6, 20, 9, 0, tzinfo=ZONE)
    got = cal.parse_when("am I free tomorrow at 3pm?", now=now, tz=ZONE)
    assert got == datetime(2026, 6, 21, 15, 0, tzinfo=ZONE)


def test_parse_when_romanian_maine_la_15():
    now = datetime(2026, 6, 20, 9, 0, tzinfo=ZONE)
    got = cal.parse_when("sunt liber maine la 15?", now=now, tz=ZONE)
    assert got == datetime(2026, 6, 21, 15, 0, tzinfo=ZONE)


def test_parse_when_today_default_when_no_day_word():
    now = datetime(2026, 6, 20, 9, 0, tzinfo=ZONE)
    got = cal.parse_when("la 18:30", now=now, tz=ZONE)
    assert got == datetime(2026, 6, 20, 18, 30, tzinfo=ZONE)


def test_parse_when_no_hour_returns_none():
    now = datetime(2026, 6, 20, 9, 0, tzinfo=ZONE)
    assert cal.parse_when("cand sunt liber maine?", now=now, tz=ZONE) is None
    assert cal.parse_when("", now=now, tz=ZONE) is None


def test_parse_day_offset():
    assert cal.parse_day_offset("cand sunt liber maine?") == 1
    assert cal.parse_day_offset("free slots today") == 0
    assert cal.parse_day_offset("") == 0


# --------------------------------------------------------------------------- #
# free command — am I free at <time>
# --------------------------------------------------------------------------- #


def _tomorrow_at(hour: int, minute: int = 0) -> datetime:
    """A datetime on the skill's real 'tomorrow' (now+1d), so these tests stay
    deterministic regardless of the wall-clock date they run on."""
    day = (datetime.now(ZONE) + timedelta(days=1)).date()
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZONE)


def _tomorrow_stamp(hour: int, minute: int = 0) -> str:
    return _tomorrow_at(hour, minute).strftime("%d %b %H:%M")


async def test_am_i_free_with_clashing_event_is_busy():
    # An event 14:30–15:30 clashes with a "3pm" (15:00) query.
    clash = _tomorrow_at(14, 30)
    _inject([_wire_event(clash, 60)])
    out = await cal.free("am I free tomorrow at 3pm?")
    assert "Nu" in out  # busy
    assert _tomorrow_stamp(15, 0) in out


async def test_am_i_free_with_free_time_is_free():
    # Event 10:00–11:00; a 15:00 query is well clear of it.
    other = _tomorrow_at(10, 0)
    _inject([_wire_event(other, 60)])
    out = await cal.free("am I free tomorrow at 3pm?")
    assert "Da" in out  # free
    assert _tomorrow_stamp(15, 0) in out


async def test_am_i_free_empty_calendar_is_free():
    _inject([])
    out = await cal.free("free tomorrow at 3pm?")
    assert out.startswith("Da")


# --------------------------------------------------------------------------- #
# free command — no token → graceful
# --------------------------------------------------------------------------- #


async def test_no_token_is_graceful():
    _inject([], token="")
    out = await cal.free("am I free tomorrow at 3pm?")
    assert "conectat" in out  # "Google Calendar nu e conectat — ..."
    assert "error" not in out.lower()


# --------------------------------------------------------------------------- #
# free command — free-slots listing (no concrete time)
# --------------------------------------------------------------------------- #


async def test_free_slots_listing_tomorrow():
    # Tomorrow: one event 10:00–12:00 inside 9–18 working hours.
    busy = _tomorrow_at(10, 0)
    _inject([_wire_event(busy, 120)])
    out = await cal.free("cand sunt liber maine?")
    assert out.startswith("Sloturi libere")
    # 9:00–10:00 free before the event; 12:00 onward free after it.
    assert "09:00" in out
    # The 10:00–12:00 block is busy, so no 10:30 slot should appear.
    assert "10:30" not in out


async def test_free_slots_listing_handles_full_day():
    # A wall-to-wall all-day style block leaves no slots tomorrow.
    busy = _tomorrow_at(9, 0)
    _inject([_wire_event(busy, 9 * 60)])  # 09:00–18:00
    out = await cal.free("free slots tomorrow")
    assert "Nu mai ai sloturi libere" in out


# --------------------------------------------------------------------------- #
# handle() dispatch
# --------------------------------------------------------------------------- #


async def test_handle_dispatches_free():
    _inject([])
    out = await cal.handle("free", "tomorrow at 3pm")
    assert out.startswith("Da")


def test_free_is_registered_command():
    assert "free" in cal.get_commands()
