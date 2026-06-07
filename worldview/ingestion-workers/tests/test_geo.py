"""Tests for shared geodesy helpers."""

from worldview_ingest.geo import (
    circle_polygon_wkt,
    destination_point,
    point_in_polygon,
)


def test_destination_point_north():
    lat, lon = destination_point(0.0, 0.0, 0.0, 111.195)  # ~1 degree north
    assert abs(lat - 1.0) < 0.02
    assert abs(lon) < 0.001


def test_circle_polygon_is_closed_ring():
    wkt = circle_polygon_wkt(26.5, 56.2, 50.0, segments=12)
    assert wkt.startswith("POLYGON((") and wkt.endswith("))")
    coords = wkt[len("POLYGON((") : -2].split(", ")
    assert len(coords) == 13  # 12 segments + closing vertex
    assert coords[0] == coords[-1]  # ring closed


def test_point_in_polygon():
    square = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]
    assert point_in_polygon(5.0, 5.0, square) is True
    assert point_in_polygon(15.0, 5.0, square) is False
