"""Dark-vessel consumer worker (Layer B): consume osint.ais, run the detector, emit events.

Stateful Kafka consumer that feeds AIS positions into DarkVesselDetector and periodically
sweeps for vessels gone silent inside a geofence. Emitted events are published back as
`context`-domain envelopes (the STEP 4 writer persists them to dark_vessel_events + Redis).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from aiokafka import AIOKafkaConsumer

from worldview_ingest.config import settings
from worldview_ingest.darkwatch.detector import (
    DarkVesselDetector,
    DarkVesselEvent,
    Geofence,
)
from worldview_ingest.envelope import TelemetryEnvelope
from worldview_ingest.kafka_io import TelemetryProducer

logger = logging.getLogger(__name__)

SWEEP_SECONDS = 60


def event_to_envelope(event: DarkVesselEvent, ts: float) -> TelemetryEnvelope:
    """Wrap a dark-vessel event as a context-domain envelope for the persistence writer."""
    return TelemetryEnvelope(
        domain="context",
        source="darkwatch",
        entity_id=f"dark:{event.mmsi}",
        ts=ts,
        lon=event.extrapolated_lon,
        lat=event.extrapolated_lat,
        payload={
            "kind": "dark_vessel",
            "mmsi": event.mmsi,
            "geofence_id": event.geofence_id,
            "last_seen_ts": event.last_seen_ts,
            "last_lon": event.last_lon,
            "last_lat": event.last_lat,
            "gap_seconds": event.gap_seconds,
            "status": event.status,
        },
    )


async def run(geofences: list[Geofence], producer: TelemetryProducer) -> None:
    """Consume AIS, run detection, and publish dark/resumed events."""
    detector = DarkVesselDetector(geofences)
    consumer = AIOKafkaConsumer(
        "osint.ais",
        bootstrap_servers=settings.kafka_brokers,
        group_id="dark-vessel-detector",
        value_deserializer=lambda b: json.loads(b.decode()),
    )
    await consumer.start()
    sweeper = asyncio.create_task(_sweep_loop(detector, producer))
    try:
        async for msg in consumer:
            env = msg.value
            p = env.get("payload") or {}
            resumed = detector.process(
                mmsi=int(env["entity_id"]),
                lon=env["lon"],
                lat=env["lat"],
                ts=env["ts"],
                cog=p.get("cog_deg") or 0.0,
                sog=p.get("sog_kt") or 0.0,
            )
            if resumed is not None:
                await producer.publish(event_to_envelope(resumed, time.time()))
    finally:
        sweeper.cancel()
        await consumer.stop()


async def _sweep_loop(detector: DarkVesselDetector, producer: TelemetryProducer) -> None:
    while True:
        await asyncio.sleep(SWEEP_SECONDS)
        for event in detector.sweep(time.time()):
            logger.info("dark vessel %s in geofence %s", event.mmsi, event.geofence_id)
            await producer.publish(event_to_envelope(event, time.time()))
