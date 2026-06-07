"""ADS-B ingestion worker (Layer A): poll the configured source, normalize, publish to osint.adsb.

Source is selectable (OpenSky / ADSB.fi, see sources.py). The loop adapts to rate limits and
transient errors with exponential backoff, and resets on success.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from worldview_ingest.adsb.sources import RateLimited, build_source
from worldview_ingest.config import settings
from worldview_ingest.kafka_io import TelemetryProducer

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 300


async def run(producer: TelemetryProducer, poll_seconds: int | None = None) -> None:
    """Poll the configured ADS-B source on an interval and publish normalized envelopes."""
    source = build_source(settings)
    interval = poll_seconds if poll_seconds is not None else settings.adsb_poll_seconds
    backoff = interval
    logger.info("ADS-B worker using source=%s, interval=%ss", source.name, interval)

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                result = await source.fetch(client)
                for envelope in result.envelopes:
                    await producer.publish(envelope)
                logger.info(
                    "ADS-B[%s]: published %d positions (credits=%s)",
                    source.name,
                    len(result.envelopes),
                    result.credits_remaining,
                )
                backoff = interval
                await asyncio.sleep(interval)
            except RateLimited as exc:
                wait = exc.retry_after or min(backoff * 2, MAX_BACKOFF_SECONDS)
                logger.warning("ADS-B[%s] rate-limited; backing off %.0fs", source.name, wait)
                await asyncio.sleep(wait)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning(
                    "ADS-B[%s] fetch failed: %s; backing off %.0fs", source.name, exc, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
