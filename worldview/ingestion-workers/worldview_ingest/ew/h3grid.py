"""Aggregate EW point observations into Uber H3 cells (design doc §9.3).

GPS-jamming / interference observations are binned into H3 cells (default resolution ~r5,
~8 km edge); per cell we keep mean intensity, sample count, and the boundary polygon (WKT).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

import h3

DEFAULT_RESOLUTION = 5


@dataclass(frozen=True)
class CellAggregate:
    h3_index: str
    resolution: int
    intensity: float
    sample_count: int
    boundary_wkt: str


def cell_boundary_wkt(h3_index: str) -> str:
    """WKT POLYGON for an H3 cell boundary (h3 v4 returns (lat, lng) vertices)."""
    boundary = h3.cell_to_boundary(h3_index)
    points = [(lng, lat) for lat, lng in boundary]
    points.append(points[0])  # close the ring
    ring = ", ".join(f"{lng:.6f} {lat:.6f}" for lng, lat in points)
    return f"POLYGON(({ring}))"


def aggregate_to_h3(
    observations: Iterable[tuple[float, float, float]],
    resolution: int = DEFAULT_RESOLUTION,
) -> list[CellAggregate]:
    """Bin (lat, lon, intensity) observations into H3 cells with mean intensity per cell."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for lat, lon, intensity in observations:
        cell = h3.latlng_to_cell(lat, lon, resolution)
        buckets[cell].append(intensity)

    return [
        CellAggregate(
            h3_index=cell,
            resolution=resolution,
            intensity=sum(vals) / len(vals),
            sample_count=len(vals),
            boundary_wkt=cell_boundary_wkt(cell),
        )
        for cell, vals in buckets.items()
    ]
