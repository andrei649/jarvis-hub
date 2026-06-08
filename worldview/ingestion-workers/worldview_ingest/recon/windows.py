"""Satellite recon-window prediction (WorldView ticket H19.2.1).

Given an Area of Interest (AOI center + radius), a satellite TLE, and a sensor
spec, predict the UTC time windows during which the satellite's sensor footprint
covers the AOI, together with a simple [0, 1] quality score.

Approach
--------
1. Walk time in fixed steps over the horizon, propagating the TLE to each step
   (reusing :func:`worldview_ingest.tle.propagate.propagate`).
2. At each step compute the sensor footprint *ground* circle (center + radius)
   and test coverage as a circle-vs-circle overlap on the sphere:
   ``haversine(fp_center, aoi_center) <= fp_radius + aoi.radius_km``.
3. Group consecutive covered steps into candidate windows. Refine each window's
   ingress/egress to ~1 s with bisection against a continuous ``covered_at(t)``
   helper, find the closest-approach instant (``t_peak``), and score quality.

Pure stdlib + the reused worldview_ingest modules (no shapely / numpy).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from worldview_ingest.geo import EARTH_RADIUS_KM, destination_point
from worldview_ingest.sun import is_daylight
from worldview_ingest.tle.propagate import propagate


@dataclass(frozen=True)
class ReconWindow:
    """A predicted coverage window of an AOI by a satellite sensor.

    All times are UNIX-seconds floats (UTC).
    """

    norad_id: int
    aoi_id: str
    sensor_type: str
    t_ingress: float
    t_peak: float
    t_egress: float
    min_distance_km: float
    sunlit_at_peak: bool
    quality: float


@dataclass(frozen=True)
class Aoi:
    """Area of Interest, modelled as a ground circle (center + radius)."""

    id: str
    lat: float
    lon: float
    radius_km: float


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points in km (spherical earth)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def footprint_ground(
    sensor_type: str,
    params: dict,
    sub_lat: float,
    sub_lon: float,
    alt_km: float,
) -> tuple[float, float, float]:
    """Ground footprint of a sensor as ``(center_lat, center_lon, radius_km)``.

    - ``optical``: nadir circle of radius ``alt_km * tan(fov_deg / 2)`` centered
      on the sub-satellite point (``fov_deg`` default 4.0).
    - ``sar``: side-looking swath of half-width ``swath_width_km / 2`` (default
      30 km) centered ``swath_offset_km`` east of nadir (default 20 km).
    - else (sigint / coverage / default): broad circle of ``coverage_radius_km``
      (default 500 km) centered on the sub-satellite point.
    """
    if sensor_type == "optical":
        fov_deg = float(params.get("fov_deg", 4.0))
        radius = alt_km * math.tan(math.radians(fov_deg / 2.0))
        return sub_lat, sub_lon, radius

    if sensor_type == "sar":
        radius = float(params.get("swath_width_km", 30)) / 2.0
        offset = float(params.get("swath_offset_km", 20))
        clat, clon = destination_point(sub_lat, sub_lon, 90.0, offset)
        return clat, clon, radius

    radius = float(params.get("coverage_radius_km", 500))
    return sub_lat, sub_lon, radius


def predict_windows(
    aoi: Aoi,
    norad_id: int,
    line1: str,
    line2: str,
    sensor_type: str,
    params: dict,
    t0: float,
    horizon_s: float,
    step_s: float = 30.0,
) -> list[ReconWindow]:
    """Predict AOI coverage windows over ``[t0, t0 + horizon_s]``.

    Walks the horizon in ``step_s`` increments, propagating the TLE at each step
    (steps where SGP4 errors are skipped). Consecutive covered steps form a
    window; ingress/egress are bisection-refined to ~1 s, ``t_peak`` is the
    closest-approach instant, and ``quality`` scores the pass.

    Quality formula (in [0, 1])::

        closeness = max(0, 1 - min_distance_km / (fp_radius + aoi.radius_km))
        quality   = closeness * (0.0 if optical and not sunlit else 1.0)

    Higher quality means the AOI passes closer to the footprint center relative
    to the combined footprint+AOI radius. Optical passes require the AOI to be
    sunlit at peak (else quality is 0); SAR and other sensors ignore sunlight.

    Returns the windows sorted by ``t_ingress``.

    Caveat: the coarse ``step_s`` walk can *alias* — a small optical footprint
    (a few-km nadir circle moving at ~7 km/s, i.e. sub-``step_s`` dwell over the
    AOI) may slip entirely between two samples and be missed. The 30 s default is
    tuned for the broad coverage/SAR footprints; TODO(worldview): adapt ``step_s``
    to the footprint radius (or do a finer pre-pass) before relying on this for
    narrow optical tasking.
    """

    def coverage_at(t: float) -> tuple[bool, float, float]:
        """Return (covered, distance_km, fp_radius_km) at UNIX time ``t``.

        On propagation failure returns ``(False, inf, 0.0)`` so the instant is
        treated as uncovered.
        """
        when = datetime.fromtimestamp(t, tz=UTC)
        try:
            sub = propagate(line1, line2, when)
        except ValueError:
            return False, math.inf, 0.0
        fp_lat, fp_lon, fp_radius = footprint_ground(
            sensor_type, params, sub.lat, sub.lon, sub.alt_km
        )
        dist = haversine_km(fp_lat, fp_lon, aoi.lat, aoi.lon)
        covered = dist <= fp_radius + aoi.radius_km
        return covered, dist, fp_radius

    def covered_at(t: float) -> bool:
        return coverage_at(t)[0]

    def bisect_boundary(t_lo: float, t_hi: float, lo_covered: bool) -> float:
        """Refine a covered/uncovered transition between t_lo and t_hi to ~1 s.

        ``lo_covered`` is the coverage state at ``t_lo``; ``t_hi`` has the
        opposite state. Returns the boundary time (first instant on the covered
        side of the transition).
        """
        while t_hi - t_lo > 1.0:
            mid = (t_lo + t_hi) / 2.0
            if covered_at(mid) == lo_covered:
                t_lo = mid
            else:
                t_hi = mid
        return t_lo if lo_covered else t_hi

    # --- Sample the horizon, recording covered steps. ---
    samples: list[tuple[float, bool, float, float]] = []  # (t, covered, dist, fp_r)
    t = t0
    t_end = t0 + horizon_s
    while t <= t_end + 1e-9:
        covered, dist, fp_r = coverage_at(t)
        samples.append((t, covered, dist, fp_r))
        t += step_s

    windows: list[ReconWindow] = []
    i = 0
    n = len(samples)
    while i < n:
        if not samples[i][1]:
            i += 1
            continue

        # Run of consecutive covered samples [start_idx, end_idx].
        start_idx = i
        while i + 1 < n and samples[i + 1][1]:
            i += 1
        end_idx = i
        i += 1  # advance past the run for the outer loop

        # Ingress: refine between the prior uncovered sample and the first
        # covered one (clamp to t0 when the run starts at the horizon edge).
        t_first = samples[start_idx][0]
        if start_idx == 0:
            t_ingress = t_first
        else:
            t_ingress = bisect_boundary(samples[start_idx - 1][0], t_first, False)

        # Egress: refine between the last covered sample and the next uncovered
        # one (clamp to horizon end when the run ends at the edge).
        t_last = samples[end_idx][0]
        if end_idx == n - 1:
            t_egress = min(t_last, t_end)
        else:
            # lo = last covered sample (earlier), hi = first uncovered sample
            # (later), lo_covered=True — mirrors the ingress convention so the
            # transition is actually bisected to ~1 s.
            t_egress = bisect_boundary(t_last, samples[end_idx + 1][0], True)

        # Peak: minimum-distance in-window sample, then a short refinement.
        peak_idx = min(
            range(start_idx, end_idx + 1), key=lambda k: samples[k][2]
        )
        t_peak = samples[peak_idx][0]
        min_dist = samples[peak_idx][2]
        fp_radius = samples[peak_idx][3]

        # Refine the peak within +/- one step via a coarse golden-ish scan.
        lo = max(t_ingress, t_peak - step_s)
        hi = min(t_egress, t_peak + step_s)
        refine_steps = 8
        if hi > lo:
            for k in range(refine_steps + 1):
                tt = lo + (hi - lo) * k / refine_steps
                _, d, fpr = coverage_at(tt)
                if d < min_dist:
                    min_dist = d
                    t_peak = tt
                    fp_radius = fpr

        # Keep t_peak strictly inside (t_ingress, t_egress) for a well-formed window.
        t_peak = min(max(t_peak, t_ingress + 1e-6), t_egress - 1e-6)

        peak_dt = datetime.fromtimestamp(t_peak, tz=UTC)
        sunlit = is_daylight(aoi.lat, aoi.lon, peak_dt)

        denom = fp_radius + aoi.radius_km
        closeness = max(0.0, 1.0 - min_dist / denom) if denom > 0 else 0.0
        sun_factor = 0.0 if (sensor_type == "optical" and not sunlit) else 1.0
        quality = closeness * sun_factor

        windows.append(
            ReconWindow(
                norad_id=norad_id,
                aoi_id=aoi.id,
                sensor_type=sensor_type,
                t_ingress=t_ingress,
                t_peak=t_peak,
                t_egress=t_egress,
                min_distance_km=min_dist,
                sunlit_at_peak=sunlit,
                quality=quality,
            )
        )

    windows.sort(key=lambda w: w.t_ingress)
    return windows
