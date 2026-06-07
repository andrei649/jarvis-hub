"""ADS-B ingestion worker (Layer A): poll OpenSky, normalize, publish to osint.adsb."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from worldview_ingest.adsb.normalize import normalize_opensky_state
from worldview_ingest.kafka_io import TelemetryProducer

logger = logging.getLogger(__name__)

OPENSKY_STATES_URL = "https://opensky-network.org/api/states/all"
POLL_SECONDS = 10


async def run(producer: TelemetryProducer, poll_seconds: int = POLL_SECONDS) -> None:
    """Poll OpenSky's global state vectors on an interval and publish normalized envelopes."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            published = await _poll_once(client, producer)
            logger.info("ADS-B: published %d positions", published)
            await asyncio.sleep(poll_seconds)


async def _poll_once(client: httpx.AsyncClient, producer: TelemetryProducer) -> int:
    try:
        resp = await client.get(OPENSKY_STATES_URL)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("ADS-B poll failed: %s", exc)
        return 0

    src_time = float(data.get("time") or time.time())
    count = 0
    for state in data.get("states") or []:
        envelope = normalize_opensky_state(state, src_time)
        if envelope is not None:
            await producer.publish(envelope)
            count += 1
    return count
