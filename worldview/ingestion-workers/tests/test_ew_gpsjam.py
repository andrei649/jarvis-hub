"""Tests for the GPSJam heatmap parser (Layer D)."""

from datetime import UTC, datetime

from worldview_ingest.ew.gpsjam import _ring_centroid, gpsjam_url, parse_gpsjam

# A real-shaped GPSJam heatmap: an interference hexagon + a "no observations" one (skipped).
GPSJAM = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"good": 6, "bad": 18},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[56.0, 26.0], [56.2, 26.0], [56.3, 26.1],
                                 [56.2, 26.2], [56.0, 26.2], [55.9, 26.1], [56.0, 26.0]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"good": 0, "bad": 0},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        },
    ],
}


def test_gpsjam_url_format():
    url = gpsjam_url("https://gpsjam.org/data/", day=datetime(2026, 6, 7, tzinfo=UTC))
    assert url == "https://gpsjam.org/data/2026-06-07-heatmap.geojson"


def test_parse_gpsjam_intensity_and_skip_empty():
    envs = parse_gpsjam(GPSJAM, ts=1749200400.0)
    assert len(envs) == 1  # the zero-observation cell is skipped
    env = envs[0]
    assert env.domain == "ew"
    assert env.source == "gpsjam"
    assert env.payload["intensity"] == 0.75  # bad 18 / total 24
    assert env.payload["sample_count"] == 24
    assert env.payload["h3_resolution"] == 4
    assert env.geom_wkt.startswith("POLYGON((")
    assert env.entity_id  # an H3 cell id derived from the hexagon centroid


def test_ring_centroid_drops_duplicate_closing_vertex():
    """The closing vertex (first == last) must not be double-counted in the average."""
    # Closed square ring: vertices average to (0.5, 0.5); the repeated first/last
    # vertex would pull the mean toward (0,0) if not dropped.
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
    }
    lon, lat = _ring_centroid(geometry)
    assert lon == 0.5
    assert lat == 0.5
