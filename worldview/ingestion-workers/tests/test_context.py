"""Tests for contextual-intel normalization (Layer E)."""

from worldview_ingest.context.normalize import normalize_event, normalize_notam
from worldview_ingest.timeutil import parse_iso_utc
from worldview_ingest.wkt import geojson_geometry_to_wkt


def test_geojson_point_to_wkt():
    assert geojson_geometry_to_wkt({"type": "Point", "coordinates": [56.2, 26.5]}) == "POINT(56.2 26.5)"


def test_geojson_polygon_to_wkt():
    wkt = geojson_geometry_to_wkt(
        {"type": "Polygon", "coordinates": [[[55, 25], [57, 25], [57, 27], [55, 25]]]}
    )
    assert wkt == "POLYGON((55 25, 57 25, 57 27, 55 25))"


def test_parse_iso_utc_handles_z_and_naive():
    # 'Z' suffix and a naive timestamp both resolve to the same UTC epoch.
    assert parse_iso_utc("2024-06-07T12:00:00Z") == 1717761600.0
    assert parse_iso_utc("2024-06-07 12:00:00") == 1717761600.0
    assert parse_iso_utc("garbage") is None
    assert parse_iso_utc(None) is None


def test_normalize_event_point():
    env = normalize_event(
        {
            "geometry": {"type": "Point", "coordinates": [56.3, 26.4]},
            "properties": {"id": "evt-1", "category": "strike", "severity": 3, "time": "2024-06-07T12:00:00Z"},
        }
    )
    assert env is not None
    assert env.domain == "context"
    assert env.entity_id == "evt-1"
    assert env.lon == 56.3 and env.lat == 26.4
    assert env.payload["kind"] == "event"
    assert env.payload["category"] == "strike"
    assert env.ts == 1717761600.0


def test_normalize_event_polygon_uses_wkt():
    env = normalize_event(
        {
            "geometry": {"type": "Polygon", "coordinates": [[[55, 25], [57, 25], [57, 27], [55, 25]]]},
            "properties": {"id": "zone-9"},
        }
    )
    assert env is not None
    assert env.lon is None and env.lat is None
    assert env.geom_wkt.startswith("POLYGON((")


def test_normalize_notam():
    env = normalize_notam(
        {
            "id": "A1/26",
            "type": "airspace_closure",
            "effective_from": "2024-06-07T00:00:00Z",
            "effective_to": "2024-06-08T00:00:00Z",
            "geometry": {"type": "Polygon", "coordinates": [[[55, 25], [57, 25], [57, 27], [55, 25]]]},
        }
    )
    assert env is not None
    assert env.entity_id == "A1/26"
    assert env.payload["kind"] == "notam"
    assert env.payload["notam_type"] == "airspace_closure"
    assert env.geom_wkt.startswith("POLYGON((")
