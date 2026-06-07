"""Contextual intel worker (Layer E): fetch NOTAMs / events, normalize, publish to osint.context.

Consumes a GeoJSON FeatureCollection of geopolitical events and a NOTAM feed, emitting context
envelopes that the history-writer routes to geopolitical_events / notams. Source endpoints are
deployment-specific (FAA NOTAM API, OSINT event feeds); the fetch helpers return [] by default.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from worldview_ingest.context.normalize import normalize_event, normalize_notam
from worldview_ingest.kafka_io import TelemetryProducer

logger = logging.getLogger(__name__)

POLL_SECONDS = 300


async def run(producer: TelemetryProducer, poll_seconds: int = POLL_SECONDS) -> None:
    """Poll the context sources, normalize, and publish envelopes."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            published = 0
            for feature in await _fetch_events(client):
                env = normalize_event(feature)
                if env is not None:
                    await producer.publish(env)
                    published += 1
            for record in await _fetch_notams(client):
                env = normalize_notam(record)
                if env is not None:
                    await producer.publish(env)
                    published += 1
            logger.info("context: published %d intel features", published)
            await asyncio.sleep(poll_seconds)


async def _fetch_events(client: httpx.AsyncClient) -> list[dict]:
    """Return GeoJSON event features. Source wiring is deployment-specific."""
    del client
    return []


async def _fetch_notams(client: httpx.AsyncClient) -> list[dict]:
    """Return NOTAM records. Source wiring is deployment-specific."""
    del client
    return []
