"""AIS ingestion worker (Layer B): stream AISStream, normalize, publish to osint.ais.

Reconnects with exponential backoff on stream drops; subscription + frame handling live in
stream.py (testable, network-free).
"""

from __future__ import annotations

import asyncio
import json
import logging

import websockets

from worldview_ingest.ais.stream import AISSTREAM_URL, build_subscription, handle_frame
from worldview_ingest.config import settings
from worldview_ingest.kafka_io import TelemetryProducer

logger = logging.getLogger(__name__)


async def run(producer: TelemetryProducer, api_key: str | None = None) -> None:
    """Connect to AISStream, subscribe, and publish normalized position reports (reconnecting)."""
    subscription = build_subscription(settings, api_key)
    backoff = 1
    while True:
        try:
            async with websockets.connect(AISSTREAM_URL) as ws:
                await ws.send(json.dumps(subscription))
                logger.info(
                    "AIS: subscribed (%d bbox)", len(subscription["BoundingBoxes"])
                )
                backoff = 1
                async for raw in ws:
                    envelope = handle_frame(raw)
                    if envelope is not None:
                        await producer.publish(envelope)
        except (TimeoutError, websockets.WebSocketException, OSError) as exc:
            logger.warning("AIS stream dropped: %s; reconnecting in %ss", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, settings.ais_reconnect_max_seconds)
