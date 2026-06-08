"""Parse the GPSJam daily heatmap GeoJSON (already H3-binned hexagons) into EW envelopes.

GPSJam publishes one hexagon per cell with `good`/`bad` aircraft-GPS-confidence counts; the
interference intensity is `bad / (good + bad)`. We derive the H3 id from the hexagon centroid
and carry the hexagon polygon as geom_wkt. (For raw point observations, use `ew/h3grid.py`.)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import h3

from worldview_ingest.envelope import TelemetryEnvelope
from worldview_ingest.wkt import geojson_geometry_to_wkt

GPSJAM_RESOLUTION = 4  # GPSJam's heatmap is binned at H3 resolution 4


def gpsjam_url(base: str, day: datetime | None = None) -> str:
    """Build the GPSJam heatmap URL for a UTC day, e.g. .../2026-06-07-heatmap.geojson."""
    date = (day or datetime.now(UTC)).strftime("%Y-%m-%d")
    return f"{base.rstrip('/')}/{date}-heatmap.geojson"


def parse_gpsjam(
    geojson: dict[str, Any], ts: float, resolution: int = GPSJAM_RESOLUTION
) -> list[TelemetryEnvelope]:
    """Convert a GPSJam heatmap FeatureCollection into per-cell EW envelopes."""
    envelopes: list[TelemetryEnvelope] = []
    for feature in geojson.get("features", []):
        geometry = feature.get("geometry")
        props = feature.get("properties") or {}
        if not geometry:
            continue
        bad = float(props.get("bad") or 0.0)
        good = float(props.get("good") or 0.0)
        total = bad + good
        if total <= 0:
            continue  # no GPS observations contributing to this cell
        lon, lat = _ring_centroid(geometry)
        h3_index = h3.latlng_to_cell(lat, lon, resolution)
        envelopes.append(
            TelemetryEnvelope(
                domain="ew",
                source="gpsjam",
                entity_id=h3_index,
                ts=ts,
                geom_wkt=geojson_geometry_to_wkt(geometry),
                payload={
                    "intensity": round(bad / total, 4),
                    "sample_count": int(total),
                    "h3_resolution": resolution,
                },
            )
        )
    return envelopes


def _ring_centroid(geometry: dict[str, Any]) -> tuple[float, float]:
    """Average of a Polygon's exterior ring (or a ring) → (lon, lat)."""
    coords = geometry["coordinates"]
    ring = coords[0] if geometry.get("type") == "Polygon" else coords
    lons = [pt[0] for pt in ring]
    lats = [pt[1] for pt in ring]
    return sum(lons) / len(lons), sum(lats) / len(lats)
