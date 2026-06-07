"""Tests for the solar-position helper (satellite daylight / recon windows)."""

from datetime import UTC, datetime

from worldview_ingest.sun import is_daylight, solar_elevation


def test_solar_noon_at_equator_is_near_overhead():
    # Equinox, solar noon at the prime meridian: sun is nearly overhead.
    el = solar_elevation(0.0, 0.0, datetime(2024, 3, 20, 12, 0, 0, tzinfo=UTC))
    assert el > 85.0
    assert is_daylight(0.0, 0.0, datetime(2024, 3, 20, 12, 0, 0, tzinfo=UTC))


def test_local_midnight_is_night():
    # Same place at 00:00 UTC (local midnight) is well below the horizon.
    el = solar_elevation(0.0, 0.0, datetime(2024, 3, 20, 0, 0, 0, tzinfo=UTC))
    assert el < 0.0
    assert not is_daylight(0.0, 0.0, datetime(2024, 3, 20, 0, 0, 0, tzinfo=UTC))


def test_polar_night_in_winter():
    # Northern high latitude in deep winter: the sun never rises.
    assert not is_daylight(80.0, 0.0, datetime(2024, 12, 21, 12, 0, 0, tzinfo=UTC))


def test_elevation_is_bounded():
    el = solar_elevation(45.0, -75.0, datetime(2024, 6, 21, 17, 0, 0, tzinfo=UTC))
    assert -90.0 <= el <= 90.0
