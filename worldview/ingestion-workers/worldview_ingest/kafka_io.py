"""Thin async Kafka producer for the canonical envelope (design doc §4)."""

from __future__ import annotations

import json

from aiokafka import AIOKafkaProducer

from worldview_ingest.config import settings
from worldview_ingest.envelope import Domain, TelemetryEnvelope

# Topic per domain (§4.1). Partition key is entity_id, preserving per-track ordering (§4.2).
DOMAIN_TOPICS: dict[Domain, str] = {
    "adsb": "osint.adsb",
    "ais": "osint.ais",
    "tle": "osint.tle",
    "ew": "osint.ew",
    "context": "osint.context",
}


class TelemetryProducer:
    """Publishes envelopes to the per-domain topic, keyed by entity_id."""

    def __init__(self) -> None:
        self._producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_brokers)

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, envelope: TelemetryEnvelope) -> None:
        topic = DOMAIN_TOPICS[envelope.domain]
        value = json.dumps(envelope.model_dump(by_alias=True)).encode()
        key = envelope.entity_id.encode()
        await self._producer.send_and_wait(topic, value=value, key=key)
