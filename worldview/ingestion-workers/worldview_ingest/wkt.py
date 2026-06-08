"""Convert GeoJSON geometries to WKT for the envelope's geom_wkt field (Layer E)."""

from __future__ import annotations

from typing import Any


def _ring(coords: list[list[float]]) -> str:
    return "(" + ", ".join(f"{pt[0]} {pt[1]}" for pt in coords) + ")"


def geojson_geometry_to_wkt(geometry: dict[str, Any]) -> str:
    """Convert a GeoJSON Point / Polygon / MultiPolygon geometry to a WKT string."""
    gtype = geometry["type"]
    coords = geometry["coordinates"]
    if gtype == "Point":
        return f"POINT({coords[0]} {coords[1]})"
    if gtype == "Polygon":
        return "POLYGON(" + ", ".join(_ring(ring) for ring in coords) + ")"
    if gtype == "MultiPolygon":
        polys = ", ".join("(" + ", ".join(_ring(ring) for ring in poly) + ")" for poly in coords)
        return f"MULTIPOLYGON({polys})"
    raise ValueError(f"unsupported geometry type: {gtype}")
