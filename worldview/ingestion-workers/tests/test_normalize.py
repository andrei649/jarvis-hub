"""Tests for ADS-B and AIS normalizers."""

from datetime import UTC, datetime

from worldview_ingest.adsb.normalize import normalize_opensky_state
from worldview_ingest.ais.normalize import normalize_aisstream


def _opensky_state(lon, lat):
    # OpenSky state vector layout (17 fields).
    return [
        "4ca7b3", "UAE201  ", "Ireland", 1749200400, 1749200401,
        lon, lat, 10000.0, False, 232.0, 118.4, -6.5, None, 10668.0, "2200", False, 0,
    ]


def test_adsb_normalize_maps_fields():
    env = normalize_opensky_state(_opensky_state(56.2, 26.5), src_time=1749200400.0)
    assert env is not None
    assert env.domain == "adsb"
    assert env.entity_id == "4ca7b3"
    assert env.lon == 56.2 and env.lat == 26.5
    assert env.alt_m == 10668.0
    assert env.payload["callsign"] == "UAE201"
    assert env.payload["on_ground"] is False


def test_adsb_normalize_skips_missing_position():
    assert normalize_opensky_state(_opensky_state(None, None), src_time=1.0) is None


def test_ais_normalize_position_report():
    msg = {
        "MessageType": "PositionReport",
        "MetaData": {
            "MMSI": 636092297,
            "latitude": 26.512,
            "longitude": 56.231,
            "time_utc": "2024-06-07 12:00:00.000 +0000 UTC",
            "ShipName": "EVER GIVEN",
        },
        "Message": {"PositionReport": {"Sog": 12.3, "Cog": 118.0, "TrueHeading": 117}},
    }
    env = normalize_aisstream(msg)
    assert env is not None
    assert env.domain == "ais"
    assert env.entity_id == "636092297"
    assert env.payload["sog_kt"] == 12.3
    assert env.payload["ship_name"] == "EVER GIVEN"


def test_ais_normalize_ignores_non_position():
    assert normalize_aisstream({"MessageType": "ShipStaticData"}) is None


def test_ais_time_is_parsed_as_utc():
    # The event time must be interpreted as UTC regardless of the host's local timezone.
    msg = {
        "MessageType": "PositionReport",
        "MetaData": {
            "MMSI": 1,
            "latitude": 0.0,
            "longitude": 0.0,
            "time_utc": "2024-06-07 12:00:00.123456789 +0000 UTC",
        },
        "Message": {"PositionReport": {}},
    }
    env = normalize_aisstream(msg)
    assert env is not None
    expected = datetime(2024, 6, 7, 12, 0, 0, 123456, tzinfo=UTC).timestamp()
    assert abs(env.ts - expected) < 1e-3
