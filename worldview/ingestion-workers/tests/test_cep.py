"""Tests for the complex-event-processing detectors (worldview_ingest.cep)."""

from __future__ import annotations

import math

from worldview_ingest.cep.anomaly import (
    HoldingPattern,
    JammingOnset,
    Position,
    detect_holding_pattern,
    detect_jamming_onset,
    haversine_km,
)
from worldview_ingest.cep.tipping import TippingEvent, detect_tipping
from worldview_ingest.geo import destination_point
from worldview_ingest.recon.windows import ReconWindow


def _window(norad_id: int, aoi_id: str, t_ingress: float) -> ReconWindow:
    """A minimal ReconWindow; only norad_id/aoi_id/t_ingress matter for tipping."""
    return ReconWindow(
        norad_id=norad_id,
        aoi_id=aoi_id,
        sensor_type="optical",
        t_ingress=t_ingress,
        t_peak=t_ingress + 30.0,
        t_egress=t_ingress + 60.0,
        min_distance_km=10.0,
        sunlit_at_peak=True,
        quality=0.9,
    )


# --------------------------------------------------------------------------- #
# tipping-and-cueing
# --------------------------------------------------------------------------- #


def test_tipping_clustered_passes_emit_one_event() -> None:
    base = 1_700_000_000.0
    windows = [
        _window(100, "aoi-1", base + 0.0),
        _window(200, "aoi-1", base + 120.0),
        _window(300, "aoi-1", base + 250.0),
    ]
    events = detect_tipping(windows, delta_s=600.0, min_count=3)
    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, TippingEvent)
    assert ev.aoi_id == "aoi-1"
    assert ev.window_count == 3
    assert ev.norad_ids == (100, 200, 300)
    assert ev.t_start == base + 0.0
    assert ev.t_end == base + 250.0


def test_tipping_spread_out_passes_yield_none() -> None:
    base = 1_700_000_000.0
    windows = [
        _window(100, "aoi-1", base + 0.0),
        _window(200, "aoi-1", base + 5_000.0),
        _window(300, "aoi-1", base + 10_000.0),
    ]
    assert detect_tipping(windows, delta_s=600.0, min_count=3) == []


def test_tipping_second_aoi_is_independent() -> None:
    base = 1_700_000_000.0
    windows = [
        # aoi-1: three stacked passes -> qualifies.
        _window(100, "aoi-1", base + 0.0),
        _window(200, "aoi-1", base + 100.0),
        _window(300, "aoi-1", base + 200.0),
        # aoi-2: only two passes, same delta -> does not reach min_count=3.
        _window(400, "aoi-2", base + 50.0),
        _window(500, "aoi-2", base + 150.0),
    ]
    events = detect_tipping(windows, delta_s=600.0, min_count=3)
    assert len(events) == 1
    assert events[0].aoi_id == "aoi-1"
    assert events[0].norad_ids == (100, 200, 300)


# --------------------------------------------------------------------------- #
# holding pattern
# --------------------------------------------------------------------------- #


def test_holding_pattern_circular_track_detected() -> None:
    """A closed loop: ~zero net drift, ~360 deg of cumulative turning."""
    center_lat, center_lon = 40.0, -74.0
    radius_km = 2.0
    n = 24
    track: list[Position] = []
    t0 = 1_700_000_000.0
    for i in range(n + 1):  # close the loop back to the start point
        bearing = 360.0 * i / n
        lat, lon = destination_point(center_lat, center_lon, bearing, radius_km)
        # Heading along a CCW circle is tangent ~ (bearing - 90) mod 360.
        heading = (bearing - 90.0) % 360.0
        track.append(Position(lon=lon, lat=lat, ts=t0 + i * 60.0, track_deg=heading))

    hp = detect_holding_pattern(
        "ENTITY-1", track, window_s=10_000.0, max_drift_km=1.0, min_turn_deg=300.0
    )
    assert isinstance(hp, HoldingPattern)
    assert hp.entity_id == "ENTITY-1"
    assert hp.net_drift_km <= 1.0
    assert hp.turn_total_deg >= 300.0
    # Roughly one full revolution.
    assert abs(hp.turn_total_deg - 360.0) < 30.0


def test_holding_pattern_straight_line_returns_none() -> None:
    """A constant-heading straight leg: large drift, ~zero turning."""
    t0 = 1_700_000_000.0
    lat, lon = 40.0, -74.0
    track: list[Position] = []
    for i in range(20):
        # March due east; heading stays 90 deg.
        lat, lon = destination_point(lat, lon, 90.0, 5.0)
        track.append(Position(lon=lon, lat=lat, ts=t0 + i * 60.0, track_deg=90.0))

    hp = detect_holding_pattern(
        "ENTITY-2", track, window_s=10_000.0, max_drift_km=1.0, min_turn_deg=300.0
    )
    assert hp is None


def test_haversine_one_degree_latitude() -> None:
    d = haversine_km(0.0, 0.0, 1.0, 0.0)
    assert abs(d - 111.0) / 111.0 < 0.01
    assert math.isclose(haversine_km(10.0, 20.0, 10.0, 20.0), 0.0, abs_tol=1e-9)


# --------------------------------------------------------------------------- #
# jamming onset
# --------------------------------------------------------------------------- #


def test_jamming_onset_rising_edge_detected() -> None:
    t0 = 1_700_000_000.0
    series = [
        (t0 + 0.0, 1, 0.1),
        (t0 + 60.0, 2, 0.2),
        (t0 + 120.0, 8, 0.7),  # rising edge: clears both thresholds
        (t0 + 180.0, 9, 0.8),
    ]
    onset = detect_jamming_onset(series, min_cells=5, min_intensity=0.5)
    assert isinstance(onset, JammingOnset)
    assert onset.t == t0 + 120.0
    assert onset.cells == 8
    assert onset.mean_intensity == 0.7


def test_jamming_onset_all_quiet_returns_none() -> None:
    t0 = 1_700_000_000.0
    series = [
        (t0 + 0.0, 1, 0.1),
        (t0 + 60.0, 2, 0.15),
        (t0 + 120.0, 1, 0.2),
    ]
    assert detect_jamming_onset(series, min_cells=5, min_intensity=0.5) is None


def test_jamming_onset_already_active_first_sample_not_reported() -> None:
    """An opening sample that is already active is not a rising edge."""
    t0 = 1_700_000_000.0
    series = [
        (t0 + 0.0, 9, 0.9),
        (t0 + 60.0, 9, 0.9),
    ]
    assert detect_jamming_onset(series, min_cells=5, min_intensity=0.5) is None
