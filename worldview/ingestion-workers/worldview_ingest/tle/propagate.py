"""SGP4 propagation: TLE + time -> WGS84 sub-satellite point (design doc §9.2).

Converts the SGP4 TEME position to ECEF via GMST rotation, then to geodetic lat/lon/alt.
Polar motion / UT1-UTC corrections are omitted (negligible for visualization-grade tracks).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from sgp4.api import Satrec, jday

WGS84_A = 6378.137  # equatorial radius, km
WGS84_F = 1.0 / 298.257223563


@dataclass(frozen=True)
class SubSatellite:
    lat: float
    lon: float
    alt_km: float
    velocity_kms: float


def _gmst_rad(jd: float, fr: float) -> float:
    """Greenwich Mean Sidereal Time (IAU-82), radians."""
    tut1 = ((jd - 2451545.0) + fr) / 36525.0
    gmst_sec = (
        67310.54841
        + (876600.0 * 3600.0 + 8640184.812866) * tut1
        + 0.093104 * tut1 * tut1
        - 6.2e-6 * tut1 * tut1 * tut1
    )
    return math.radians((gmst_sec / 240.0) % 360.0)


def _ecef_to_geodetic(x: float, y: float, z: float) -> tuple[float, float, float]:
    """ECEF (km) -> (lat_deg, lon_deg, alt_km) on the WGS84 ellipsoid."""
    e2 = WGS84_F * (2.0 - WGS84_F)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1.0 - e2))
    alt = 0.0
    for _ in range(6):  # converges in a few iterations
        s = math.sin(lat)
        n = WGS84_A / math.sqrt(1.0 - e2 * s * s)
        alt = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1.0 - e2 * n / (n + alt)))
    return math.degrees(lat), math.degrees(lon), alt


def propagate(line1: str, line2: str, when: datetime) -> SubSatellite:
    """Propagate a TLE to `when` (UTC) and return the geodetic sub-satellite point."""
    sat = Satrec.twoline2rv(line1, line2)
    jd, fr = jday(
        when.year,
        when.month,
        when.day,
        when.hour,
        when.minute,
        when.second + when.microsecond * 1e-6,
    )
    err, r, v = sat.sgp4(jd, fr)
    if err != 0:
        raise ValueError(f"SGP4 propagation error code {err}")

    theta = _gmst_rad(jd, fr)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    x, y, z = r
    xe = x * cos_t + y * sin_t
    ye = -x * sin_t + y * cos_t
    lat, lon, alt = _ecef_to_geodetic(xe, ye, z)
    speed = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return SubSatellite(lat=lat, lon=lon, alt_km=alt, velocity_kms=speed)
