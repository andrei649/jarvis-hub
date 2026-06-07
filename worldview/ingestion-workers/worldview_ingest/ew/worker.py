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

from worldview_ingest.envelope import TelemetryEnvelope
from worldview_ingest.ew.h3grid import DEFAULT_RESOLUTION, aggregate_to_h3
from worldview_ingest.kafka_io import TelemetryProducer

logger = logging.getLogger(__name__)

POLL_SECONDS = 300


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


async def run(producer: TelemetryProducer, poll_seconds: int = POLL_SECONDS) -> None:
    """Poll the interference source, aggregate to H3, and publish per-cell envelopes."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            observations = await _fetch_observations(client)
            envelopes = build_envelopes(observations, time.time())
            for envelope in envelopes:
                await producer.publish(envelope)
            logger.info("EW: published %d H3 cells", len(envelopes))
            await asyncio.sleep(poll_seconds)


async def _fetch_observations(client: httpx.AsyncClient) -> list[tuple[float, float, float]]:
    """Return (lat, lon, intensity) observations. Source wiring is deployment-specific."""
    # Placeholder: deployments point this at GPSJam/IODA. Returning [] keeps the loop safe.
    del client
    return []
