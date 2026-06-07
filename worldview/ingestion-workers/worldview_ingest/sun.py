"""Solar position — is the sub-satellite ground point in daylight?

Optical reconnaissance needs the target sunlit; this drives the `is_sunlit` flag on satellite
ephemeris. Uses the NOAA solar-position approximation (accurate to ~0.5°), which is ample for
flagging recon windows.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime


def solar_elevation(lat_deg: float, lon_deg: float, when: datetime) -> float:
    """Solar elevation angle (degrees) above the horizon at (lat, lon) and UTC time `when`."""
    when = when.astimezone(UTC)
    day_of_year = when.timetuple().tm_yday
    hour = when.hour + when.minute / 60.0 + when.second / 3600.0

    # Fractional year (radians).
    gamma = 2.0 * math.pi / 365.0 * (day_of_year - 1 + (hour - 12.0) / 24.0)

    # Equation of time (minutes) and solar declination (radians) — NOAA series.
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )

    # True solar time -> hour angle.
    time_offset = eqtime + 4.0 * lon_deg  # minutes (east longitude positive)
    true_solar_time = hour * 60.0 + time_offset
    hour_angle = math.radians(true_solar_time / 4.0 - 180.0)

    lat = math.radians(lat_deg)
    cos_zenith = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(
        hour_angle
    )
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    return 90.0 - math.degrees(math.acos(cos_zenith))


def is_daylight(lat_deg: float, lon_deg: float, when: datetime) -> bool:
    """True when the sun is above the horizon at the given ground point and time."""
    return solar_elevation(lat_deg, lon_deg, when) > 0.0
