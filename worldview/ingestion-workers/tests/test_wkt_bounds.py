"""AUD-12 (F12): bounds + sanity guards for untrusted WKT coordinates.

Coordinates from external OSINT feeds are string-formatted into geom_wkt. These
tests prove a hostile or malformed coordinate is rejected before it reaches the
WKT string, valid geometries round-trip unchanged (format preserved), and the
ingestion callers drop a bad feature with a WARNING rather than fail silently.
"""

import pytest
from pydantic import ValidationError

from worldview_ingest.context.normalize import normalize_event, normalize_notam
from worldview_ingest.envelope import TelemetryEnvelope
from worldview_ingest.wkt import geojson_geometry_to_wkt
from worldview_ingest.wkt_guard import (
    MAX_VERTICES,
    WktBoundsError,
    coerce_coord,
    format_coord,
)

# ── coerce_coord ──────────────────────────────────────────────────────────────

def test_coerce_coord_valid():
    assert coerce_coord(56.2, 26.5) == (56.2, 26.5)
    assert coerce_coord("55", "25") == (55.0, 25.0)        # numeric strings ok
    assert coerce_coord(-180, -90) == (-180.0, -90.0)      # bounds inclusive
    assert coerce_coord(180, 90) == (180.0, 90.0)


@pytest.mark.parametrize("lon,lat", [(181.0, 0.0), (-181.0, 0.0), (0.0, 91.0), (0.0, -91.0)])
def test_coerce_coord_out_of_range(lon, lat):
    with pytest.raises(WktBoundsError):
        coerce_coord(lon, lat)


@pytest.mark.parametrize("lon,lat", [(float("nan"), 0.0), (0.0, float("inf")), (0.0, float("-inf"))])
def test_coerce_coord_non_finite(lon, lat):
    with pytest.raises(WktBoundsError):
        coerce_coord(lon, lat)


@pytest.mark.parametrize("lon,lat", [("12) DROP TABLE", 0.0), (None, 0.0), ({}, 0.0)])
def test_coerce_coord_non_numeric(lon, lat):
    with pytest.raises(WktBoundsError):
        coerce_coord(lon, lat)


def test_format_coord_integral_vs_float():
    assert format_coord(55.0) == "55"
    assert format_coord(56.2) == "56.2"
    assert format_coord(-0.0) == "0"


# ── valid geometries round-trip (existing WKT format preserved) ───────────────

def test_valid_geometries_roundtrip():
    assert geojson_geometry_to_wkt({"type": "Point", "coordinates": [56.2, 26.5]}) == "POINT(56.2 26.5)"
    assert geojson_geometry_to_wkt(
        {"type": "Polygon", "coordinates": [[[55, 25], [57, 25], [57, 27], [55, 25]]]}
    ) == "POLYGON((55 25, 57 25, 57 27, 55 25))"
    assert geojson_geometry_to_wkt(
        {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]]}
    ) == "MULTIPOLYGON(((0 0, 1 0, 1 1, 0 0)))"


# ── hostile / malformed input rejected at the WKT chokepoint ──────────────────

def test_point_out_of_range_rejected():
    with pytest.raises(WktBoundsError):
        geojson_geometry_to_wkt({"type": "Point", "coordinates": [999.0, 0.0]})


def test_polygon_non_numeric_vertex_rejected():
    with pytest.raises(WktBoundsError):
        geojson_geometry_to_wkt(
            {"type": "Polygon", "coordinates": [[[0, 0], ["x) DROP", 0], [1, 1], [0, 0]]]}
        )


def test_nan_vertex_rejected():
    with pytest.raises(WktBoundsError):
        geojson_geometry_to_wkt({"type": "Point", "coordinates": [float("nan"), 0.0]})


def test_too_many_vertices_rejected():
    oversized = [[0.0, 0.0]] * (MAX_VERTICES + 1)
    with pytest.raises(WktBoundsError):
        geojson_geometry_to_wkt({"type": "Polygon", "coordinates": [oversized]})


# ── ingestion callers drop bad features (no silent failure) ───────────────────

def test_normalize_event_point_drops_out_of_bounds(caplog):
    feature = {"geometry": {"type": "Point", "coordinates": [999.0, 0.0]},
               "properties": {"id": "evt-bad"}}
    with caplog.at_level("WARNING"):
        assert normalize_event(feature) is None
    assert any("evt-bad" in r.message for r in caplog.records)


def test_normalize_event_polygon_drops_out_of_bounds(caplog):
    feature = {"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [999, 0], [0, 0]]]},
               "properties": {"id": "zone-bad"}}
    with caplog.at_level("WARNING"):
        assert normalize_event(feature) is None
    assert any("zone-bad" in r.message for r in caplog.records)


def test_normalize_notam_drops_out_of_bounds(caplog):
    record = {"id": "N-bad", "effective_from": "2024-06-07T00:00:00Z",
              "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [200, 0], [0, 0]]]}}
    with caplog.at_level("WARNING"):
        assert normalize_notam(record) is None
    assert any("N-bad" in r.message for r in caplog.records)


def test_normalize_event_valid_still_works():
    feature = {"geometry": {"type": "Point", "coordinates": [56.3, 26.4]},
               "properties": {"id": "evt-ok", "time": "2024-06-07T12:00:00Z"}}
    env = normalize_event(feature)
    assert env is not None and env.lon == 56.3 and env.lat == 26.4


# ── envelope defence-in-depth validator ───────────────────────────────────────

def test_envelope_rejects_non_wkt_geom():
    with pytest.raises(ValidationError):
        TelemetryEnvelope(domain="context", source="x", entity_id="e", ts=1.0,
                          geom_wkt="DROP TABLE telemetry; --")


def test_envelope_accepts_valid_wkt_and_none():
    e1 = TelemetryEnvelope(domain="context", source="x", entity_id="e", ts=1.0,
                           geom_wkt="POLYGON((0 0, 1 0, 1 1, 0 0))")
    assert e1.geom_wkt.startswith("POLYGON((")
    e2 = TelemetryEnvelope(domain="context", source="x", entity_id="e", ts=1.0)
    assert e2.geom_wkt is None
