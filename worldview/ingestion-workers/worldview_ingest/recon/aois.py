"""AOI (Area of Interest) loading for the recon worker (Layer C insight).

Parses the ``AOIS`` setting into :class:`worldview_ingest.recon.windows.Aoi`
objects. The wire format is a ``;``-separated list of ``id:lon,lat,radius_km``
entries — longitude first, then latitude (matching the GeoJSON/x,y convention),
then the ground radius in km::

    "hormuz:56.4,26.6,250;bab-el-mandeb:43.3,12.6,150"

When ``AOIS`` is empty the worker defaults to a single Strait-of-Hormuz AOI.
Pure (no I/O) so it can be unit-tested without Kafka or the network.
"""

from __future__ import annotations

from worldview_ingest.config import Settings
from worldview_ingest.recon.windows import Aoi

# Default AOI when AOIS is unset: the Strait of Hormuz (center lon=56.4, lat=26.6).
DEFAULT_AOI = Aoi(id="hormuz", lat=26.6, lon=56.4, radius_km=250.0)


def parse_aoi(entry: str) -> Aoi:
    """Parse a single ``id:lon,lat,radius_km`` entry into an :class:`Aoi`."""
    head, _, coords = entry.partition(":")
    aoi_id = head.strip()
    if not aoi_id or not coords:
        raise ValueError(f"AOI must be 'id:lon,lat,radius_km', got {entry!r}")
    parts = [p.strip() for p in coords.split(",")]
    if len(parts) != 3:
        raise ValueError(f"AOI coords must be 'lon,lat,radius_km', got {coords!r}")
    lon, lat, radius_km = (float(p) for p in parts)
    return Aoi(id=aoi_id, lat=lat, lon=lon, radius_km=radius_km)


def load_aois(settings: Settings) -> list[Aoi]:
    """Parse ``settings.aois`` into a list of AOIs, defaulting to Hormuz when empty."""
    raw = settings.aois.strip()
    if not raw:
        return [DEFAULT_AOI]
    return [parse_aoi(entry) for entry in raw.split(";") if entry.strip()]
