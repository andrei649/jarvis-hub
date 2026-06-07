"""Sensor footprint geometry per satellite type (design doc §9.2).

Data-driven from sensors_footprint_params: optical -> ground circle from FOV; SAR -> offset
swath; sigint/other -> broad coverage circle. Returns a WKT POLYGON for the geom_wkt field.
"""

from __future__ import annotations

import math
from typing import Any

from worldview_ingest.geo import circle_polygon_wkt, destination_point


def footprint_wkt(
    lat: float, lon: float, alt_km: float, sensor_type: str, params: dict[str, Any]
) -> str:
    """Build the ground-footprint WKT polygon for a satellite at (lat, lon, alt_km)."""
    if sensor_type == "optical":
        fov_deg = float(params.get("fov_deg") or 4.0)
        radius = alt_km * math.tan(math.radians(fov_deg / 2.0))
        return circle_polygon_wkt(lat, lon, max(radius, 1.0))

    if sensor_type == "sar":
        swath = float(params.get("swath_width_km") or 10.0)
        offset = float(params.get("swath_offset_km") or 20.0)
        clat, clon = destination_point(lat, lon, 90.0, offset)  # side-look, offset east
        return circle_polygon_wkt(clat, clon, max(swath / 2.0, 1.0))

    radius = float(params.get("coverage_radius_km") or 500.0)
    return circle_polygon_wkt(lat, lon, radius)
