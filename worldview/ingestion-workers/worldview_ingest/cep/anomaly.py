"""Track and signal anomaly detectors (WorldView ticket H19.2.5).

Two pure detectors over a single entity's ordered observations:

- :func:`detect_holding_pattern` — a vessel/aircraft that loiters: lots of
  turning but little net displacement (a holding stack or racetrack orbit).
- :func:`detect_jamming_onset` — the rising edge of a GPS/RF jamming event over a
  grid of cells.

Pure stdlib only (a local :func:`haversine_km` avoids touching ``geo.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from worldview_ingest.geo import EARTH_RADIUS_KM


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points in km (spherical earth).

    Local copy mirroring ``recon.windows.haversine_km`` so this module stays
    self-contained and does not edit ``geo.py``.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _norm_180(delta: float) -> float:
    """Normalize an angle difference (degrees) into [-180, 180]."""
    return (delta + 180.0) % 360.0 - 180.0


@dataclass(frozen=True)
class Position:
    """One observation of an entity's track.

    ``ts`` is UNIX-seconds (UTC). ``track_deg`` is true heading in [0, 360);
    ``speed`` is informational. Both may be ``None`` when the source omits them.
    """

    lon: float
    lat: float
    ts: float
    track_deg: float | None = None
    speed: float | None = None


@dataclass(frozen=True)
class HoldingPattern:
    """A loiter / holding-stack / orbit detection over a trailing window."""

    entity_id: str
    t_start: float
    t_end: float
    net_drift_km: float
    turn_total_deg: float


def detect_holding_pattern(
    entity_id: str,
    track: list[Position],
    window_s: float,
    max_drift_km: float,
    min_turn_deg: float,
) -> HoldingPattern | None:
    """Detect a holding/orbit pattern over the trailing ``window_s`` of a track.

    The track is taken to be ordered by ``ts``. We look at the trailing window
    ``[last.ts - window_s, last.ts]`` and require **both**:

    - **low net drift** — the haversine distance between the window's first and
      last position is ``≤ max_drift_km``, and
    - **high cumulative turning** — the sum over consecutive points of the
      absolute heading change ``|Δtrack_deg|`` (each Δ normalized to
      ``[-180, 180]``) is ``≥ min_turn_deg``.

    When both hold, return a :class:`HoldingPattern` describing the window; else
    return ``None``. Points whose ``track_deg`` is ``None`` are skipped for the
    turning sum (no contribution) but still bound the window. Fewer than two
    points in the window can never qualify, so ``None`` is returned.
    """
    if not track:
        return None

    t_last = track[-1].ts
    t_floor = t_last - window_s
    window = [p for p in track if t_floor <= p.ts <= t_last]
    if len(window) < 2:
        return None

    net_drift = haversine_km(
        window[0].lat, window[0].lon, window[-1].lat, window[-1].lon
    )

    turn_total = 0.0
    prev_heading: float | None = None
    for p in window:
        if p.track_deg is None:
            continue
        if prev_heading is not None:
            turn_total += abs(_norm_180(p.track_deg - prev_heading))
        prev_heading = p.track_deg

    if net_drift <= max_drift_km and turn_total >= min_turn_deg:
        return HoldingPattern(
            entity_id=entity_id,
            t_start=window[0].ts,
            t_end=window[-1].ts,
            net_drift_km=net_drift,
            turn_total_deg=turn_total,
        )
    return None


@dataclass(frozen=True)
class JammingOnset:
    """The rising-edge sample of a jamming event.

    - ``t``: timestamp of the onset sample.
    - ``cells``: active (jammed) cell count at onset.
    - ``mean_intensity``: mean interference intensity at onset.
    """

    t: float
    cells: int
    mean_intensity: float


def detect_jamming_onset(
    series: list[tuple[float, int, float]],
    min_cells: int,
    min_intensity: float,
) -> JammingOnset | None:
    """Detect the rising edge of a jamming event.

    ``series`` is a list of ``(ts, active_cell_count, mean_intensity)`` samples
    sorted by ``ts``. A sample is *active* when it clears **both** thresholds:
    ``active_cell_count ≥ min_cells`` **and** ``mean_intensity ≥ min_intensity``.

    Rising-edge rule: return the first active sample that is immediately
    preceded by a non-active ("quieter") sample — i.e. the transition
    quiet → active. The very first sample cannot be a rising edge (there is no
    prior quieter sample to rise from), so an already-active opening sample is
    not reported. If no such transition exists, return ``None``.
    """

    def is_active(sample: tuple[float, int, float]) -> bool:
        _, cells, intensity = sample
        return cells >= min_cells and intensity >= min_intensity

    for i in range(1, len(series)):
        if is_active(series[i]) and not is_active(series[i - 1]):
            ts, cells, intensity = series[i]
            return JammingOnset(t=ts, cells=cells, mean_intensity=intensity)
    return None
