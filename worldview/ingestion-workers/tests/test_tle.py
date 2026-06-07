"""Tests for TLE parsing, SGP4 propagation, and footprint geometry."""

from datetime import UTC, datetime

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
