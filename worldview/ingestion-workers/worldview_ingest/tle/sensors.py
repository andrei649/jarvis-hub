"""Per-satellite sensor type + footprint parameters (Layer C).

A curated *starter* registry keyed by NORAD id — illustrative, not exhaustive. In deployment
this is loaded/overridden from the satellites + sensors_footprint_params tables (01_reference.sql);
satellites absent from the registry fall back to a generic optical footprint.
"""

from __future__ import annotations

from typing import Any

SensorSpec = tuple[str, dict[str, Any]]
DEFAULT_SENSOR: SensorSpec = ("optical", {})

# norad_id -> (sensor_type, footprint params). Optical → narrow ground cone (fov);
# SAR → side-look swath (width + offset). Extend with your tasked constellation.
SENSOR_REGISTRY: dict[int, SensorSpec] = {
    40115: ("optical", {"fov_deg": 1.0}),  # WORLDVIEW-3 (Maxar), high-res EO — a real anchor
    # Example SAR entries (replace NORAD ids with your set):
    # 46266: ("sar", {"swath_width_km": 30, "swath_offset_km": 20}),  # CAPELLA-class
    # 43800: ("sar", {"swath_width_km": 25, "swath_offset_km": 18}),  # ICEYE-class
}


def sensor_for(norad_id: int) -> SensorSpec:
    """Return the (sensor_type, params) for a satellite, defaulting to optical."""
    return SENSOR_REGISTRY.get(norad_id, DEFAULT_SENSOR)
