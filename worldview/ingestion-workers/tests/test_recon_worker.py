"""Tests for the recon worker's pure pieces (AOIs + Kafka message contract).

No Kafka / network: exercises ``load_aois`` parsing, the ``worldview.recon.v1``
message round-trip, and an end-to-end-ish path that feeds a real ISS TLE + an
equatorial AOI through :func:`predict_windows` and serializes each window with
:meth:`ReconMessage.to_dict`, asserting the wire contract shape.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from worldview_ingest.config import Settings
from worldview_ingest.recon.aois import DEFAULT_AOI, load_aois
from worldview_ingest.recon.message import SCHEMA, ReconMessage
from worldview_ingest.recon.windows import Aoi, ReconWindow, predict_windows

# Real ISS (ZARYA) TLE — inclination ~51.6°, so its ground track reaches the equator.
ISS_L1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9007"
ISS_L2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49514477 30000"
NORAD = 25544
T0 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).timestamp()
HORIZON = 24 * 3600
COVERAGE_PARAMS = {"coverage_radius_km": 600}

# The 9 contract fields plus the schema tag.
CONTRACT_KEYS = {
    "schema",
    "norad_id",
    "aoi_id",
    "sensor_type",
    "t_ingress",
    "t_peak",
    "t_egress",
    "min_distance_km",
    "sunlit_at_peak",
    "quality",
}


def _settings(aois: str = "") -> Settings:
    """A Settings instance with only ``aois`` overridden (frozen dataclass)."""
    return replace(Settings(), aois=aois)


def test_load_aois_default_hormuz() -> None:
    """Empty/whitespace AOIS yields the single default Strait-of-Hormuz AOI."""
    for raw in ("", "   "):
        aois = load_aois(_settings(raw))
        assert aois == [DEFAULT_AOI]
        (hormuz,) = aois
        assert hormuz.id == "hormuz"
        assert hormuz.lon == 56.4
        assert hormuz.lat == 26.6
        assert hormuz.radius_km == 250.0


def test_load_aois_custom_string_parse() -> None:
    """Custom AOIS string parses lon-first coords into multiple AOIs."""
    raw = "hormuz:56.4,26.6,250; bab:43.3,12.6,150 ;malacca:100.5,2.5,120"
    aois = load_aois(_settings(raw))
    assert [a.id for a in aois] == ["hormuz", "bab", "malacca"]

    bab = aois[1]
    # Format is id:lon,lat,radius_km — longitude first.
    assert bab.lon == 43.3
    assert bab.lat == 12.6
    assert bab.radius_km == 150.0


def test_load_aois_skips_blank_segments() -> None:
    """Trailing/empty ``;`` segments are ignored, not parsed as empty AOIs."""
    aois = load_aois(_settings("hormuz:56.4,26.6,250;;"))
    assert len(aois) == 1
    assert aois[0].id == "hormuz"


def _sample_window() -> ReconWindow:
    return ReconWindow(
        norad_id=25544,
        aoi_id="hormuz",
        sensor_type="optical",
        t_ingress=1700000000.0,
        t_peak=1700000123.5,
        t_egress=1700000250.0,
        min_distance_km=42.5,
        sunlit_at_peak=True,
        quality=0.83,
    )


def test_message_from_window_preserves_fields() -> None:
    """from_window copies all 9 fields verbatim."""
    w = _sample_window()
    msg = ReconMessage.from_window(w)
    assert msg.norad_id == w.norad_id
    assert msg.aoi_id == w.aoi_id
    assert msg.sensor_type == w.sensor_type
    assert msg.t_ingress == w.t_ingress
    assert msg.t_peak == w.t_peak
    assert msg.t_egress == w.t_egress
    assert msg.min_distance_km == w.min_distance_km
    assert msg.sunlit_at_peak == w.sunlit_at_peak
    assert msg.quality == w.quality


def test_message_to_dict_contract_and_roundtrip() -> None:
    """to_dict emits the worldview.recon.v1 contract with the schema tag + 9 fields."""
    w = _sample_window()
    d = ReconMessage.from_window(w).to_dict()

    assert set(d) == CONTRACT_KEYS
    assert d["schema"] == SCHEMA == "worldview.recon.v1"

    # Types match the contract.
    assert isinstance(d["norad_id"], int)
    assert isinstance(d["aoi_id"], str)
    assert isinstance(d["sensor_type"], str)
    assert isinstance(d["t_ingress"], float)
    assert isinstance(d["t_peak"], float)
    assert isinstance(d["t_egress"], float)
    assert isinstance(d["min_distance_km"], float)
    assert isinstance(d["sunlit_at_peak"], bool)
    assert isinstance(d["quality"], float)

    # Values round-trip from the window.
    assert d["norad_id"] == w.norad_id
    assert d["aoi_id"] == w.aoi_id
    assert d["sensor_type"] == w.sensor_type
    assert d["t_ingress"] == w.t_ingress
    assert d["t_peak"] == w.t_peak
    assert d["t_egress"] == w.t_egress
    assert d["min_distance_km"] == w.min_distance_km
    assert d["sunlit_at_peak"] == w.sunlit_at_peak
    assert d["quality"] == w.quality


def test_message_key_format() -> None:
    """The Kafka key is ``"{norad_id}:{aoi_id}"``."""
    assert ReconMessage.from_window(_sample_window()).key() == "25544:hormuz"


def test_end_to_end_predict_to_contract_dict() -> None:
    """Feed a real ISS TLE + equatorial AOI through predict_windows -> to_dict.

    Each predicted window must serialize to a contract-shaped dict with the
    schema tag, the right key set, and the right field types.
    """
    aoi = Aoi(id="equator", lat=0.0, lon=0.0, radius_km=300.0)
    windows = predict_windows(
        aoi, NORAD, ISS_L1, ISS_L2, "coverage", COVERAGE_PARAMS, T0, HORIZON
    )
    assert windows, "expected at least one ISS pass over the equatorial AOI"

    for w in windows:
        d = ReconMessage.from_window(w).to_dict()
        assert set(d) == CONTRACT_KEYS
        assert d["schema"] == "worldview.recon.v1"
        assert d["norad_id"] == NORAD
        assert d["aoi_id"] == "equator"
        assert d["sensor_type"] == "coverage"
        assert isinstance(d["sunlit_at_peak"], bool)
        assert 0.0 <= d["quality"] <= 1.0
        assert d["t_ingress"] < d["t_peak"] < d["t_egress"]
        assert d["min_distance_km"] >= 0.0
