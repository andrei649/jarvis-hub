"""Convert GeoJSON geometries to WKT for the envelope's geom_wkt field (Layer E).

Coordinates originate in untrusted OSINT feeds, so every vertex is routed through
``wkt_guard`` (AUD-12/F12): float-coerced, bounds-checked against WGS84, and the
vertex count capped — before anything is formatted into the WKT string. A bad
value raises ``WktBoundsError`` for the caller to drop; it can never reach the
query string.
"""

from __future__ import annotations

from typing import Any

from worldview_ingest.wkt_guard import (
    WktBoundsError,
    check_vertex_count,
    coerce_coord,
    format_coord,
)


def _fmt_point(pt: Any) -> str:
    """Validate + format a single ``[lon, lat]`` pair as ``"lon lat"``."""
    try:
        lon, lat = pt[0], pt[1]
    except (TypeError, IndexError, KeyError) as exc:
        raise WktBoundsError(f"malformed coordinate pair: {pt!r}") from exc
    flon, flat = coerce_coord(lon, lat)
    return f"{format_coord(flon)} {format_coord(flat)}"


def _ring(coords: list[list[float]]) -> str:
    check_vertex_count(len(coords))
    return "(" + ", ".join(_fmt_point(pt) for pt in coords) + ")"


def geojson_geometry_to_wkt(geometry: dict[str, Any]) -> str:
    """Convert a GeoJSON Point / Polygon / MultiPolygon geometry to a WKT string.

    Raises ``WktBoundsError`` if any coordinate is non-numeric, non-finite,
    outside WGS84 bounds, or if the geometry exceeds the vertex cap.
    """
    gtype = geometry["type"]
    coords = geometry["coordinates"]
    if gtype == "Point":
        return f"POINT({_fmt_point(coords)})"
    if gtype == "Polygon":
        check_vertex_count(sum(len(ring) for ring in coords))
        return "POLYGON(" + ", ".join(_ring(ring) for ring in coords) + ")"
    if gtype == "MultiPolygon":
        check_vertex_count(sum(len(ring) for poly in coords for ring in poly))
        polys = ", ".join("(" + ", ".join(_ring(ring) for ring in poly) + ")" for poly in coords)
        return f"MULTIPOLYGON({polys})"
    raise ValueError(f"unsupported geometry type: {gtype}")
