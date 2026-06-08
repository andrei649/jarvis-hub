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


def test_solar_elevation_matches_reference_value():
    """Pin one solar elevation against an independent reference.

    Reference: NOAA ESRL Solar Position Calculator (https://gml.noaa.gov/grad/solcalc/)
    for 2024-06-21 (summer solstice) 12:00 UTC at 45.0°N, 0.0°E — near local solar
    noon, so elevation ~= 90 - (lat - declination) = 90 - (45 - 23.44) ~= 68.4°.
    A declination/equation-of-time or hour-angle sign regression would miss this
    by several degrees. We allow 0.5° (the NOAA approximation's stated accuracy).
    """
    el = solar_elevation(45.0, 0.0, datetime(2024, 6, 21, 12, 0, 0, tzinfo=UTC))
    assert abs(el - 68.44) < 0.5
