"""Tests for satellite recon-window prediction (worldview_ingest.recon.windows)."""

from __future__ import annotations

from datetime import UTC, datetime

from worldview_ingest.recon.windows import (
    Aoi,
    footprint_ground,
    haversine_km,
    predict_windows,
)
from worldview_ingest.tle.propagate import propagate

# Real ISS (ZARYA) TLE — inclination ~51.6°, so ground track stays within ~±52°.
ISS_L1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9007"
ISS_L2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49514477 30000"

NORAD = 25544
T0 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).timestamp()
HORIZON = 24 * 3600
COVERAGE_PARAMS = {"coverage_radius_km": 600}


def test_haversine_one_degree_latitude() -> None:
    """1° of latitude at the equator is ~111 km (within 1%)."""
    d = haversine_km(0.0, 0.0, 1.0, 0.0)
    assert abs(d - 111.0) / 111.0 < 0.01


def test_equatorial_aoi_yields_windows() -> None:
    """An equatorial AOI with a generous coverage sensor yields >=1 valid window."""
    aoi = Aoi(id="equator", lat=0.0, lon=0.0, radius_km=300.0)
    windows = predict_windows(
        aoi, NORAD, ISS_L1, ISS_L2, "coverage", COVERAGE_PARAMS, T0, HORIZON
    )
    assert len(windows) >= 1
    for w in windows:
        assert w.t_ingress < w.t_peak < w.t_egress
        assert T0 <= w.t_ingress <= T0 + HORIZON
        assert T0 <= w.t_egress <= T0 + HORIZON
        assert w.min_distance_km >= 0.0
        assert w.norad_id == NORAD
        assert w.aoi_id == "equator"


def test_polar_aoi_yields_no_windows() -> None:
    """A high-latitude AOI is never reachable by the ISS ground track."""
    aoi = Aoi(id="polar", lat=85.0, lon=0.0, radius_km=300.0)
    windows = predict_windows(
        aoi, NORAD, ISS_L1, ISS_L2, "coverage", COVERAGE_PARAMS, T0, HORIZON
    )
    assert windows == []


def test_optical_night_zero_quality_sar_positive() -> None:
    """Same geometry: optical-at-night scores 0, SAR scores > 0.

    Find a coverage window, then re-predict the same AOI/horizon as optical and
    as SAR using a footprint big enough to keep coverage, and find a window whose
    AOI is in darkness at peak. Optical must score 0 there; SAR must score > 0.
    """
    aoi = Aoi(id="dark", lat=0.0, lon=0.0, radius_km=300.0)

    # Wide optical FOV and wide SAR swath so both still cover the AOI like the
    # coverage sensor would, isolating the sunlight factor in the score.
    optical_params = {"fov_deg": 80.0}
    sar_params = {"swath_width_km": 1200.0, "swath_offset_km": 0.0}

    optical = predict_windows(
        aoi, NORAD, ISS_L1, ISS_L2, "optical", optical_params, T0, HORIZON
    )
    sar = predict_windows(
        aoi, NORAD, ISS_L1, ISS_L2, "sar", sar_params, T0, HORIZON
    )

    # There should be some optical window where the AOI is dark -> quality 0.
    dark_optical = [w for w in optical if not w.sunlit_at_peak]
    assert dark_optical, "expected at least one optical window in darkness"
    for w in dark_optical:
        assert w.quality == 0.0

    # And at least one optical window in daylight should score > 0.
    lit_optical = [w for w in optical if w.sunlit_at_peak]
    assert any(w.quality > 0.0 for w in lit_optical)

    # SAR ignores sunlight: every covering SAR window scores > 0.
    assert sar, "expected at least one SAR window"
    assert all(w.quality > 0.0 for w in sar)


def test_footprint_ground_shapes() -> None:
    """Footprint geometry matches the documented per-sensor rules."""
    # optical: nadir-centered, radius from FOV.
    clat, clon, r = footprint_ground("optical", {"fov_deg": 4.0}, 10.0, 20.0, 420.0)
    assert (clat, clon) == (10.0, 20.0)
    assert r > 0.0

    # sar: offset east of nadir, radius = swath/2.
    clat, clon, r = footprint_ground(
        "sar", {"swath_width_km": 30.0, "swath_offset_km": 20.0}, 0.0, 0.0, 500.0
    )
    assert r == 15.0
    assert clon > 0.0  # shifted east

    # default/coverage: nadir-centered broad circle.
    clat, clon, r = footprint_ground("coverage", {"coverage_radius_km": 600.0}, 5.0, 6.0, 500.0)
    assert (clat, clon) == (5.0, 6.0)
    assert r == 600.0


def _covered_at(aoi: Aoi, params: dict, t: float) -> bool:
    """Replicate windows.coverage_at's covered test for a coverage sensor."""
    sub = propagate(ISS_L1, ISS_L2, datetime.fromtimestamp(t, tz=UTC))
    dist = haversine_km(sub.lat, sub.lon, aoi.lat, aoi.lon)
    return dist <= float(params["coverage_radius_km"]) + aoi.radius_km


def test_egress_is_refined_to_one_second() -> None:
    """Egress must bisect to ~1 s, not snap to the 30 s coarse grid.

    With the old (lo>hi) argument order the egress guard was immediately false and
    egress snapped to the last covered coarse sample, leaving coverage still true
    for up to ~step_s afterwards. After the fix, coverage flips from True to False
    within ~1-2 s of t_egress.
    """
    aoi = Aoi(id="equator", lat=0.0, lon=0.0, radius_km=300.0)
    windows = predict_windows(
        aoi, NORAD, ISS_L1, ISS_L2, "coverage", COVERAGE_PARAMS, T0, HORIZON
    )
    assert windows, "expected at least one ISS pass over the equatorial AOI"

    # Use an interior window (not clamped to the horizon edge) so egress is a real
    # covered->uncovered transition that bisection refines.
    interior = [w for w in windows if w.t_egress < T0 + HORIZON - 1.0]
    assert interior, "expected an interior window with a real egress transition"

    for w in interior:
        # Just inside egress is covered; ~2 s past it is not -> boundary pinned to ~1 s.
        assert _covered_at(aoi, COVERAGE_PARAMS, w.t_egress - 0.5)
        assert not _covered_at(aoi, COVERAGE_PARAMS, w.t_egress + 2.0)
