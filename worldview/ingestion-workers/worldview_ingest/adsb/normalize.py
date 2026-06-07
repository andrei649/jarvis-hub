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


_FT_TO_M = 0.3048


def normalize_adsbfi_aircraft(
    ac: dict[str, Any], src_time: float, source: str = "adsbfi"
) -> TelemetryEnvelope | None:
    """Map one ADSB.fi aircraft object to a TelemetryEnvelope, or None if it has no position.

    ADSB.fi reports altitude in feet (or the literal "ground"), speed in knots, and a `dbFlags`
    bitfield whose bit 0 marks military aircraft — a real military tag we surface.
    """
    lat = ac.get("lat")
    lon = ac.get("lon")
    if lat is None or lon is None:
        return None
    icao24 = str(ac.get("hex") or "").strip().lower()
    if not icao24:
        return None

    ts = src_time - float(ac.get("seen_pos") or 0.0)
    alt_raw = ac.get("alt_baro")
    on_ground = alt_raw == "ground"
    if on_ground:
        alt_m: float | None = 0.0
    elif isinstance(alt_raw, (int, float)):
        alt_m = float(alt_raw) * _FT_TO_M
    else:
        alt_m = None

    flight = ac.get("flight")
    db_flags = ac.get("dbFlags")
    payload = {
        "callsign": flight.strip() if isinstance(flight, str) and flight.strip() else None,
        "gs_kt": ac.get("gs"),
        "track_deg": ac.get("track"),
        "vert_rate_fpm": ac.get("baro_rate"),
        "squawk": ac.get("squawk"),
        "on_ground": on_ground,
        "is_military": bool(db_flags & 1) if isinstance(db_flags, int) else False,
    }
    return TelemetryEnvelope(
        domain="adsb",
        source=source,
        entity_id=icao24,
        ts=ts,
        lon=float(lon),
        lat=float(lat),
        alt_m=alt_m,
        payload=payload,
    )
