"""Tests for TLE parsing, SGP4 propagation, and footprint geometry."""

from datetime import UTC, datetime

import pytest

from worldview_ingest.tle.catalog import parse_tle_text
from worldview_ingest.tle.footprint import footprint_wkt
from worldview_ingest.tle.propagate import propagate

# A real ISS (ZARYA) TLE.
ISS = (
    "ISS (ZARYA)\n"
    "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9007\n"
    "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49514477 30000\n"
)


def test_parse_tle_text():
    records = list(parse_tle_text(ISS))
    assert len(records) == 1
    assert records[0].norad_id == 25544
    assert records[0].name == "ISS (ZARYA)"


def test_propagate_iss_is_in_leo():
    record = next(iter(parse_tle_text(ISS)))
    when = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    pos = propagate(record.line1, record.line2, when)
    # ISS altitude ~400 km; inclination caps latitude near ±51.6°.
    assert 300.0 < pos.alt_km < 500.0
    assert -52.0 <= pos.lat <= 52.0
    assert -180.0 <= pos.lon <= 180.0
    assert 7.0 < pos.velocity_kms < 8.5


# Independently-vetted sub-satellite point for the ISS TLE above, propagated to
# 2024-01-01T12:00:00Z. Computed with Skyfield 1.54 (wgs84.subpoint of an
# EarthSatellite, which runs the same SGP4 but does its own TEME->ITRF rotation
# and geodetic reduction). This is a *reference* check on propagate.py's GMST
# rotation + ellipsoid math: unlike the plausibility envelope above, a longitude
# sign or epoch/GMST bug would shift lon by tens of degrees and fail here.
#
#   $ python -c "from skyfield.api import load, wgs84, EarthSatellite; ..."
#   -> lat=51.46232  lon=65.67984  alt_km=420.3933
ISS_REF_EPOCH = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
ISS_REF_LAT = 51.46232
ISS_REF_LON = 65.67984
ISS_REF_ALT_KM = 420.3933


def test_propagate_iss_matches_independent_reference():
    """Pin lat/lon/alt against a Skyfield-computed sub-point (or hard-coded copy).

    Tolerances are tight enough that a frame-conversion regression (wrong GMST,
    flipped longitude sign, TEME-vs-ECEF mix-up) cannot pass: ~1 km / ~0.01°.
    """
    record = next(iter(parse_tle_text(ISS)))
    pos = propagate(record.line1, record.line2, ISS_REF_EPOCH)

    ref_lat, ref_lon, ref_alt = ISS_REF_LAT, ISS_REF_LON, ISS_REF_ALT_KM
    try:
        # If Skyfield is installed in the worker env, recompute the reference
        # live so the test stays honest if the TLE/epoch is ever changed.
        from skyfield.api import EarthSatellite, load, wgs84

        ts = load.timescale()
        sat = EarthSatellite(record.line1, record.line2, "ISS", ts)
        sp = wgs84.subpoint(sat.at(ts.from_datetime(ISS_REF_EPOCH)))
        ref_lat = sp.latitude.degrees
        ref_lon = sp.longitude.degrees
        ref_alt = sp.elevation.km
    except ImportError:
        pass  # fall back to the hard-coded, vetted reference triple above.

    assert pos.lat == pytest.approx(ref_lat, abs=0.01)
    assert pos.lon == pytest.approx(ref_lon, abs=0.01)
    assert pos.alt_km == pytest.approx(ref_alt, abs=1.0)


def test_footprint_optical_vs_coverage():
    optical = footprint_wkt(26.5, 56.2, 600.0, "optical", {"fov_deg": 4.0})
    coverage = footprint_wkt(26.5, 56.2, 600.0, "sigint", {"coverage_radius_km": 800.0})
    assert optical.startswith("POLYGON((")
    assert coverage.startswith("POLYGON((")
    # The broad coverage footprint spans more longitude than the narrow optical cone.
    assert _lon_span(coverage) > _lon_span(optical)


def _lon_span(wkt: str) -> float:
    coords = wkt[len("POLYGON((") : -2].split(", ")
    lons = [float(c.split(" ")[0]) for c in coords]
    return max(lons) - min(lons)
