"""Tests for the provider-neutral calendar availability helper (H2.2).

Offline, no network: a fake events provider feeds raw events into
``busy_intervals`` / ``free_slots`` / ``am_i_free``. Covers interval merging,
all-day blocking, working-hours subtraction, tz/DST correctness, and the empty
calendar case.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.calendar_availability import (  # noqa: E402
    am_i_free,
    busy_intervals,
    free_slots,
    google_calendar_provider,
    merge_intervals,
    normalize_events,
)

TZ = "Europe/Bucharest"
ZONE = ZoneInfo(TZ)


def _dt(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=ZONE)


def fake_provider(events):
    """Build a sync events provider returning a fixed list (ignores window)."""

    def _provider(start, end):
        return list(events)

    return _provider


def async_fake_provider(events):
    async def _provider(start, end):
        return list(events)

    return _provider


# --------------------------------------------------------------------------- #
# busy_intervals: merging + normalization
# --------------------------------------------------------------------------- #


async def test_overlapping_events_merge():
    events = [
        {"start": _dt(2026, 6, 22, 10), "end": _dt(2026, 6, 22, 11)},
        {"start": _dt(2026, 6, 22, 10, 30), "end": _dt(2026, 6, 22, 12)},
        {"start": _dt(2026, 6, 22, 14), "end": _dt(2026, 6, 22, 15)},
    ]
    busy = await busy_intervals(
        _dt(2026, 6, 22, 0), _dt(2026, 6, 23, 0), TZ, provider=fake_provider(events)
    )
    assert busy == [
        (_dt(2026, 6, 22, 10), _dt(2026, 6, 22, 12)),
        (_dt(2026, 6, 22, 14), _dt(2026, 6, 22, 15)),
    ]


async def test_adjacent_events_merge():
    events = [
        {"start": _dt(2026, 6, 22, 10), "end": _dt(2026, 6, 22, 11)},
        {"start": _dt(2026, 6, 22, 11), "end": _dt(2026, 6, 22, 12)},
    ]
    busy = await busy_intervals(
        _dt(2026, 6, 22, 0), _dt(2026, 6, 23, 0), TZ, provider=fake_provider(events)
    )
    assert busy == [(_dt(2026, 6, 22, 10), _dt(2026, 6, 22, 12))]


async def test_async_provider_supported():
    events = [{"start": _dt(2026, 6, 22, 10), "end": _dt(2026, 6, 22, 11)}]
    busy = await busy_intervals(
        _dt(2026, 6, 22, 0),
        _dt(2026, 6, 23, 0),
        TZ,
        provider=async_fake_provider(events),
    )
    assert busy == [(_dt(2026, 6, 22, 10), _dt(2026, 6, 22, 11))]


async def test_busy_clipped_to_window():
    events = [{"start": _dt(2026, 6, 22, 8), "end": _dt(2026, 6, 22, 20)}]
    busy = await busy_intervals(
        _dt(2026, 6, 22, 9), _dt(2026, 6, 22, 18), TZ, provider=fake_provider(events)
    )
    assert busy == [(_dt(2026, 6, 22, 9), _dt(2026, 6, 22, 18))]


# --------------------------------------------------------------------------- #
# all-day events
# --------------------------------------------------------------------------- #


async def test_all_day_event_blocks_whole_day():
    events = [{"start": "2026-06-22", "end": "2026-06-23", "all_day": True}]
    busy = await busy_intervals(
        _dt(2026, 6, 22, 0), _dt(2026, 6, 23, 0), TZ, provider=fake_provider(events)
    )
    assert busy == [(_dt(2026, 6, 22, 0), _dt(2026, 6, 23, 0))]


async def test_all_day_date_only_no_end():
    events = [{"start": "2026-06-22"}]  # date-only string -> implied all-day
    busy = await busy_intervals(
        _dt(2026, 6, 22, 0), _dt(2026, 6, 23, 0), TZ, provider=fake_provider(events)
    )
    assert busy == [(_dt(2026, 6, 22, 0), _dt(2026, 6, 23, 0))]


async def test_all_day_event_leaves_no_free_slots():
    events = [{"start": "2026-06-22", "end": "2026-06-23", "all_day": True}]
    busy = await busy_intervals(
        _dt(2026, 6, 22, 0), _dt(2026, 6, 23, 0), TZ, provider=fake_provider(events)
    )
    slots = free_slots(_dt(2026, 6, 22, 0), _dt(2026, 6, 23, 0), TZ, busy=busy)
    assert slots == []


# --------------------------------------------------------------------------- #
# free_slots: subtraction + working hours + slot size
# --------------------------------------------------------------------------- #


def test_empty_calendar_whole_working_window_free():
    slots = free_slots(
        _dt(2026, 6, 22, 0),
        _dt(2026, 6, 23, 0),
        TZ,
        working_hours=(9, 18),
        slot_minutes=60,
        busy=[],
    )
    assert slots[0] == (_dt(2026, 6, 22, 9), _dt(2026, 6, 22, 10))
    assert slots[-1] == (_dt(2026, 6, 22, 17), _dt(2026, 6, 22, 18))
    assert len(slots) == 9  # 9..18 in 1h steps


def test_free_slots_subtracts_busy():
    busy = [(_dt(2026, 6, 22, 10), _dt(2026, 6, 22, 11, 30))]
    slots = free_slots(
        _dt(2026, 6, 22, 0),
        _dt(2026, 6, 23, 0),
        TZ,
        working_hours=(9, 12),
        slot_minutes=30,
        busy=busy,
    )
    # 9:00-10:00 -> two 30m slots; 10:00-11:30 busy; 11:30-12:00 -> one slot.
    assert slots == [
        (_dt(2026, 6, 22, 9), _dt(2026, 6, 22, 9, 30)),
        (_dt(2026, 6, 22, 9, 30), _dt(2026, 6, 22, 10)),
        (_dt(2026, 6, 22, 11, 30), _dt(2026, 6, 22, 12)),
    ]


def test_free_slots_respects_working_hours():
    # Busy outside working hours must not affect the working window.
    busy = [(_dt(2026, 6, 22, 6), _dt(2026, 6, 22, 8))]
    slots = free_slots(
        _dt(2026, 6, 22, 0),
        _dt(2026, 6, 23, 0),
        TZ,
        working_hours=(9, 11),
        slot_minutes=60,
        busy=busy,
    )
    assert slots == [
        (_dt(2026, 6, 22, 9), _dt(2026, 6, 22, 10)),
        (_dt(2026, 6, 22, 10), _dt(2026, 6, 22, 11)),
    ]


def test_free_slots_drops_partial_trailing_remainder():
    # 9:00-10:20 free window only fits two 30m slots; the trailing 20m is dropped.
    busy = [(_dt(2026, 6, 22, 10, 20), _dt(2026, 6, 22, 18))]
    slots = free_slots(
        _dt(2026, 6, 22, 0),
        _dt(2026, 6, 23, 0),
        TZ,
        working_hours=(9, 18),
        slot_minutes=30,
        busy=busy,
    )
    assert slots == [
        (_dt(2026, 6, 22, 9), _dt(2026, 6, 22, 9, 30)),
        (_dt(2026, 6, 22, 9, 30), _dt(2026, 6, 22, 10)),
    ]


def test_free_slots_multi_day():
    slots = free_slots(
        _dt(2026, 6, 22, 0),
        _dt(2026, 6, 24, 0),  # two days
        TZ,
        working_hours=(9, 10),
        slot_minutes=60,
        busy=[],
    )
    assert slots == [
        (_dt(2026, 6, 22, 9), _dt(2026, 6, 22, 10)),
        (_dt(2026, 6, 23, 9), _dt(2026, 6, 23, 10)),
    ]


def test_free_slots_window_narrower_than_working_hours():
    # Query window 10:00-11:00 clips the 9-18 working window.
    slots = free_slots(
        _dt(2026, 6, 22, 10),
        _dt(2026, 6, 22, 11),
        TZ,
        working_hours=(9, 18),
        slot_minutes=30,
        busy=[],
    )
    assert slots == [
        (_dt(2026, 6, 22, 10), _dt(2026, 6, 22, 10, 30)),
        (_dt(2026, 6, 22, 10, 30), _dt(2026, 6, 22, 11)),
    ]


# --------------------------------------------------------------------------- #
# timezone / DST correctness
# --------------------------------------------------------------------------- #


async def test_tz_aware_event_converted_to_query_zone():
    # 09:00 UTC == 12:00 Europe/Bucharest (UTC+3 in June, summer time).
    events = [
        {
            "start": datetime(2026, 6, 22, 9, tzinfo=ZoneInfo("UTC")),
            "end": datetime(2026, 6, 22, 10, tzinfo=ZoneInfo("UTC")),
        }
    ]
    busy = await busy_intervals(
        _dt(2026, 6, 22, 0), _dt(2026, 6, 23, 0), TZ, provider=fake_provider(events)
    )
    assert busy == [(_dt(2026, 6, 22, 12), _dt(2026, 6, 22, 13))]


def test_tz_summer_offset_is_plus_three():
    # Sanity: confirm Bucharest is UTC+3 in June (DST active).
    assert _dt(2026, 6, 22, 12).utcoffset() == timedelta(hours=3)


def test_tz_winter_offset_is_plus_two():
    # And UTC+2 in January (DST inactive) — proves zoneinfo handles the switch.
    assert _dt(2026, 1, 22, 12).utcoffset() == timedelta(hours=2)


def test_free_slots_iso_string_window():
    # Naive ISO strings are interpreted in the query tz.
    slots = free_slots(
        "2026-06-22T09:00:00",
        "2026-06-22T11:00:00",
        TZ,
        working_hours=(9, 18),
        slot_minutes=60,
        busy=[],
    )
    assert slots == [
        (_dt(2026, 6, 22, 9), _dt(2026, 6, 22, 10)),
        (_dt(2026, 6, 22, 10), _dt(2026, 6, 22, 11)),
    ]


# --------------------------------------------------------------------------- #
# am_i_free convenience
# --------------------------------------------------------------------------- #


async def test_am_i_free_moment_true_when_clear():
    events = [{"start": _dt(2026, 6, 22, 14), "end": _dt(2026, 6, 22, 15)}]
    free = await am_i_free(
        _dt(2026, 6, 22, 10), TZ, provider=fake_provider(events)
    )
    assert free is True


async def test_am_i_free_moment_false_when_busy():
    events = [{"start": _dt(2026, 6, 22, 10), "end": _dt(2026, 6, 22, 11)}]
    free = await am_i_free(
        _dt(2026, 6, 22, 10, 15), TZ, provider=fake_provider(events)
    )
    assert free is False


async def test_am_i_free_window():
    events = [{"start": _dt(2026, 6, 22, 11), "end": _dt(2026, 6, 22, 12)}]
    free = await am_i_free(
        (_dt(2026, 6, 22, 9), _dt(2026, 6, 22, 10)),
        TZ,
        provider=fake_provider(events),
    )
    assert free is True


async def test_am_i_free_empty_calendar():
    free = await am_i_free(
        _dt(2026, 6, 22, 10), TZ, provider=fake_provider([])
    )
    assert free is True


# --------------------------------------------------------------------------- #
# pure helpers + real-plugin adapter shape
# --------------------------------------------------------------------------- #


def test_merge_intervals_pure():
    a = (_dt(2026, 6, 22, 9), _dt(2026, 6, 22, 10))
    b = (_dt(2026, 6, 22, 9, 30), _dt(2026, 6, 22, 11))
    assert merge_intervals([b, a]) == [(_dt(2026, 6, 22, 9), _dt(2026, 6, 22, 11))]


def test_normalize_skips_malformed_events():
    events = [
        {"start": None},  # missing start
        {"start": _dt(2026, 6, 22, 10)},  # missing end (timed) -> skip
        {"start": _dt(2026, 6, 22, 14), "end": _dt(2026, 6, 22, 13)},  # end<=start
        {"start": _dt(2026, 6, 22, 16), "end": _dt(2026, 6, 22, 17)},  # valid
    ]
    busy = normalize_events(events, ZONE)
    assert busy == [(_dt(2026, 6, 22, 16), _dt(2026, 6, 22, 17))]


async def test_google_calendar_provider_adapts_plugin_shape():
    class _FakePlugin:
        async def list_events(self, max_results=10, days_ahead=1):
            return [
                # Flattened shape emitted by GoogleCalendarPlugin.list_events.
                {"ts": "2026-06-22T10:00:00+03:00", "duration_min": 60},
                {"ts": "2026-06-22", "duration_min": 0},  # all-day
                {"error": "boom"},  # error sentinel -> ignored
            ]

    provider = google_calendar_provider(_FakePlugin())
    busy = await busy_intervals(
        _dt(2026, 6, 22, 0), _dt(2026, 6, 23, 0), TZ, provider=provider
    )
    # Timed 10:00-11:00 merged with the all-day block (whole day) -> full day.
    assert busy == [(_dt(2026, 6, 22, 0), _dt(2026, 6, 23, 0))]
