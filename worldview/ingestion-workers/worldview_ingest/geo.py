"""Shared geodesy helpers — pure and dependency-free.

Spherical-earth approximations are fine for footprint/extrapolation rendering; the precise
WGS84 conversion used for satellite sub-points lives in tle/propagate.py.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088
KNOTS_TO_KMH = 1.852


def destination_point(
    lat_deg: float, lon_deg: float, bearing_deg: float, distance_km: float
) -> tuple[float, float]:
    """Great-circle destination from a start point given a bearing and distance.

    Returns (lat, lon) in degrees, longitude normalized to [-180, 180].
    """
    angular = distance_km / EARTH_RADIUS_KM
    bearing = math.radians(bearing_deg)
    lat1 = math.radians(lat_deg)
    lon1 = math.radians(lon_deg)

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular)
        + math.cos(lat1) * math.sin(angular) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), (math.degrees(lon2) + 540.0) % 360.0 - 180.0


def circle_polygon_wkt(
    lat_deg: float, lon_deg: float, radius_km: float, segments: int = 24
) -> str:
    """A closed WKT POLYGON ring approximating a circle of `radius_km` around a point.

    Vertices are emitted counter-clockwise (decreasing bearing) so the exterior
    ring follows the OGC/GeoJSON right-hand-rule convention; sweeping bearings
    0->360 would trace a clockwise ring.
    """
    points: list[tuple[float, float]] = []
    for i in range(segments):
        bearing = -360.0 * i / segments  # CCW: N -> W -> S -> E
        plat, plon = destination_point(lat_deg, lon_deg, bearing, radius_km)
        points.append((plon, plat))
    points.append(points[0])  # close the ring
    ring = ", ".join(f"{lon:.6f} {lat:.6f}" for lon, lat in points)
    return f"POLYGON(({ring}))"


def point_in_polygon(lon: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test. `ring` is a list of (lon, lat) vertices.

    Limitation: ray-casts in raw lon/lat and is NOT antimeridian-safe — geofences
    that cross ±180° (or wrap a pole) will mis-test. The shipped Strait of Hormuz
    fence stays well clear of the antimeridian, so this is fine today.
    TODO(worldview): split/normalize rings crossing ±180° before testing if we
    ever add a Pacific/dateline-spanning geofence.
    """
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside
