"""Normalize OpenSky ADS-B state vectors to the canonical envelope (Layer A)."""

from __future__ import annotations

from typing import Any

from worldview_ingest.envelope import TelemetryEnvelope

# OpenSky /states/all "state vector" array indices.
_ICAO24 = 0
_CALLSIGN = 1
_TIME_POSITION = 3
_LAST_CONTACT = 4
_LONGITUDE = 5
_LATITUDE = 6
_BARO_ALTITUDE = 7
_ON_GROUND = 8
_VELOCITY = 9
_TRUE_TRACK = 10
_VERTICAL_RATE = 11
_GEO_ALTITUDE = 13
_SQUAWK = 14


def normalize_opensky_state(
    state: list[Any], src_time: float, source: str = "opensky"
) -> TelemetryEnvelope | None:
    """Map one OpenSky state vector to a TelemetryEnvelope, or None if it has no position."""
    lon = state[_LONGITUDE]
    lat = state[_LATITUDE]
    if lon is None or lat is None:
        return None

    icao24 = str(state[_ICAO24]).strip()
    ts = state[_TIME_POSITION] or state[_LAST_CONTACT] or src_time
    alt_m = state[_GEO_ALTITUDE]
    if alt_m is None:
        alt_m = state[_BARO_ALTITUDE]

    callsign = state[_CALLSIGN]
    payload = {
        "callsign": callsign.strip() if callsign else None,
        "gs_kt": _mps_to_knots(state[_VELOCITY]),
        "track_deg": state[_TRUE_TRACK],
        "vert_rate_fpm": _mps_to_fpm(state[_VERTICAL_RATE]),
        "squawk": state[_SQUAWK],
        "on_ground": bool(state[_ON_GROUND]),
    }
    return TelemetryEnvelope(
        domain="adsb",
        source=source,
        entity_id=icao24,
        ts=float(ts),
        lon=float(lon),
        lat=float(lat),
        alt_m=float(alt_m) if alt_m is not None else None,
        payload=payload,
    )


def _mps_to_knots(v: float | None) -> float | None:
    return round(v * 1.943844, 2) if v is not None else None


def _mps_to_fpm(v: float | None) -> float | None:
    return round(v * 196.850394, 1) if v is not None else None
