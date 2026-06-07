"""Cyber & EW worker (Layer D): aggregate jamming observations into H3, publish to osint.ew.

Fetches GPS-interference observations (e.g. GPSJam daily GeoJSON), bins them into H3 cells,
and publishes one envelope per cell with the boundary polygon in geom_wkt. IODA internet-
outage polling shares this worker and is added alongside in deployment.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from worldview_ingest.config import settings
from worldview_ingest.envelope import TelemetryEnvelope
from worldview_ingest.ew.gpsjam import gpsjam_url, parse_gpsjam
from worldview_ingest.ew.h3grid import DEFAULT_RESOLUTION, aggregate_to_h3
from worldview_ingest.kafka_io import TelemetryProducer

logger = logging.getLogger(__name__)


def build_envelopes(
    observations: list[tuple[float, float, float]],
    ts: float,
    resolution: int = DEFAULT_RESOLUTION,
) -> list[TelemetryEnvelope]:
    """Aggregate (lat, lon, intensity) observations into per-H3-cell envelopes."""
    envelopes: list[TelemetryEnvelope] = []
    for cell in aggregate_to_h3(observations, resolution):
        envelopes.append(
            TelemetryEnvelope(
                domain="ew",
                source="gpsjam",
                entity_id=cell.h3_index,
                ts=ts,
                geom_wkt=cell.boundary_wkt,
                payload={
                    "intensity": round(cell.intensity, 4),
                    "sample_count": cell.sample_count,
                    "h3_resolution": cell.resolution,
                },
            )
        )
    return envelopes


async def run(producer: TelemetryProducer, poll_seconds: int | None = None) -> None:
    """Poll the EW source (GPSJam by default), build per-cell envelopes, and publish."""
    interval = poll_seconds if poll_seconds is not None else settings.ew_poll_seconds
    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            envelopes = await _fetch_ew(client)
            for envelope in envelopes:
                await producer.publish(envelope)
            logger.info("EW[%s]: published %d H3 cells", settings.ew_source, len(envelopes))
            await asyncio.sleep(interval)


async def _fetch_ew(client: httpx.AsyncClient) -> list[TelemetryEnvelope]:
    """Fetch + parse the configured EW source. GPSJam ships pre-binned H3 hexagons."""
    if settings.ew_source != "gpsjam":
        return []
    url = gpsjam_url(settings.gpsjam_base_url)
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return parse_gpsjam(resp.json(), time.time())
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("GPSJam fetch failed: %s", exc)
        return []
