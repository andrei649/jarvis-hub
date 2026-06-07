"""Recon Kafka message contract (``worldview.recon.v1``).

A :class:`ReconMessage` is the wire form of a predicted :class:`ReconWindow`,
published to the ``osint.recon`` topic so the backend can persist predicted
satellite passes over each AOI. Kept pure (dataclass + plain dict) so the exact
contract is unit-testable without Kafka.

Wire contract (value JSON)::

    { "schema": "worldview.recon.v1", "norad_id": <int>, "aoi_id": <str>,
      "sensor_type": <str>, "t_ingress": <float>, "t_peak": <float>,
      "t_egress": <float>, "min_distance_km": <float>,
      "sunlit_at_peak": <bool>, "quality": <float 0..1> }
"""

from __future__ import annotations

from dataclasses import dataclass

from worldview_ingest.recon.windows import ReconWindow

SCHEMA = "worldview.recon.v1"


@dataclass(frozen=True)
class ReconMessage:
    """Serializable form of a predicted recon window (the 9 contract fields)."""

    norad_id: int
    aoi_id: str
    sensor_type: str
    t_ingress: float
    t_peak: float
    t_egress: float
    min_distance_km: float
    sunlit_at_peak: bool
    quality: float

    @classmethod
    def from_window(cls, w: ReconWindow) -> ReconMessage:
        """Build a :class:`ReconMessage` from a predicted :class:`ReconWindow`."""
        return cls(
            norad_id=w.norad_id,
            aoi_id=w.aoi_id,
            sensor_type=w.sensor_type,
            t_ingress=w.t_ingress,
            t_peak=w.t_peak,
            t_egress=w.t_egress,
            min_distance_km=w.min_distance_km,
            sunlit_at_peak=w.sunlit_at_peak,
            quality=w.quality,
        )

    def key(self) -> str:
        """Kafka partition key: ``"{norad_id}:{aoi_id}"`` (per-pass ordering)."""
        return f"{self.norad_id}:{self.aoi_id}"

    def to_dict(self) -> dict:
        """Produce the ``worldview.recon.v1`` contract dict (with the schema tag)."""
        return {
            "schema": SCHEMA,
            "norad_id": int(self.norad_id),
            "aoi_id": str(self.aoi_id),
            "sensor_type": str(self.sensor_type),
            "t_ingress": float(self.t_ingress),
            "t_peak": float(self.t_peak),
            "t_egress": float(self.t_egress),
            "min_distance_km": float(self.min_distance_km),
            "sunlit_at_peak": bool(self.sunlit_at_peak),
            "quality": float(self.quality),
        }
