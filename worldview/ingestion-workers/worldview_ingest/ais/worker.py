"""AIS ingestion worker (Layer B): stream AISStream, normalize, publish to osint.ais."""

from __future__ import annotations

import json
import logging
import os

import websockets

from worldview_ingest.ais.normalize import normalize_aisstream
from worldview_ingest.kafka_io import TelemetryProducer

logger = logging.getLogger(__name__)

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
# Global bounding box; narrow per deployment (e.g. the Strait of Hormuz) to cut volume.
WORLD_BBOX = [[[-90.0, -180.0], [90.0, 180.0]]]


async def run(producer: TelemetryProducer, api_key: str | None = None) -> None:
    """Connect to AISStream, subscribe, and publish normalized position reports."""
    api_key = api_key or os.getenv("AISSTREAM_API_KEY", "")
    if not api_key:
        raise RuntimeError("AISSTREAM_API_KEY is required for the AIS worker")

    subscription = {
        "APIKey": api_key,
        "BoundingBoxes": WORLD_BBOX,
        "FilterMessageTypes": ["PositionReport"],
    }
    async with websockets.connect(AISSTREAM_URL) as ws:
        await ws.send(json.dumps(subscription))
        logger.info("AIS: subscribed to AISStream")
        async for raw in ws:
            envelope = normalize_aisstream(json.loads(raw))
            if envelope is not None:
                await producer.publish(envelope)
