"""Contextual intel worker (Layer E): fetch NOTAMs / events, normalize, publish to osint.context.

Consumes a GeoJSON FeatureCollection of geopolitical events and a NOTAM feed, emitting context
envelopes that the history-writer routes to geopolitical_events / notams. Source endpoints are
deployment-specific (FAA NOTAM API, OSINT event feeds); the fetch helpers return [] by default.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from worldview_ingest.config import settings
from worldview_ingest.context.normalize import normalize_event, normalize_notam
from worldview_ingest.kafka_io import TelemetryProducer

logger = logging.getLogger(__name__)


async def run(producer: TelemetryProducer, poll_seconds: int | None = None) -> None:
    """Poll the context sources, normalize, and publish envelopes."""
    interval = poll_seconds if poll_seconds is not None else settings.context_poll_seconds
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
            await asyncio.sleep(interval)


async def _fetch_events(client: httpx.AsyncClient) -> list[dict]:
    """Fetch a GeoJSON FeatureCollection of events (CONTEXT_EVENTS_URL), or [] if unset."""
    if not settings.context_events_url:
        return []
    try:
        resp = await client.get(settings.context_events_url)
        resp.raise_for_status()
        return resp.json().get("features", [])
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.warning("context events fetch failed: %s", exc)
        return []


async def _fetch_notams(client: httpx.AsyncClient) -> list[dict]:
    """Fetch NOTAM records (CONTEXT_NOTAM_URL: a JSON list or {notams:[...]}), or [] if unset."""
    if not settings.context_notam_url:
        return []
    try:
        resp = await client.get(settings.context_notam_url)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("notams", [])
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.warning("context NOTAM fetch failed: %s", exc)
        return []
