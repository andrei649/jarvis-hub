"""Entry point: `python -m worldview_ingest <worker>`.

Workers: adsb | ais | tle | ew | context | recon | cep | capture. Each fetches its source,
normalizes to the canonical envelope, and publishes to its Kafka topic. The dark-vessel detector
runs as part of the AIS pipeline (see worldview_ingest.darkwatch). The recon worker is the Layer-C
insight predictor — it owns its OWN producer/topic (osint.recon), so it gets no shared producer.
The cep worker is the insight engine — it owns BOTH its consumer (osint.recon) and producer
(osint.events). The capture worker is the governed OSINT capture swarm — it owns its OWN
producer/topic (osint.capture), so it too gets no shared producer.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging

from worldview_ingest.config import settings
from worldview_ingest.kafka_io import DOMAIN_TOPICS, TelemetryProducer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("worldview_ingest")

WORKERS = ("adsb", "ais", "tle", "ew", "context", "recon", "cep", "capture")

# Workers that own their own Kafka client(s)/topic, so they get no shared producer.
# (recon: own producer -> osint.recon; cep: own consumer+producer -> osint.events;
#  capture: own producer -> osint.capture.)
_SELF_OWNED = ("recon", "cep", "capture")


async def _run(worker: str) -> None:
    module = importlib.import_module(f"worldview_ingest.{worker}.worker")
    if worker in _SELF_OWNED:
        await module.run()
        return
    producer = TelemetryProducer()
    await producer.start()
    try:
        await module.run(producer)
    finally:
        await producer.stop()


def main() -> None:
    parser = argparse.ArgumentParser(prog="worldview_ingest")
    parser.add_argument("worker", choices=WORKERS, help="which ingestion worker to run")
    args = parser.parse_args()
    if args.worker == "recon":
        topic = settings.recon_topic
    elif args.worker == "cep":
        topic = settings.cep_output_topic
    elif args.worker == "capture":
        topic = settings.capture_topic
    else:
        topic = DOMAIN_TOPICS[args.worker]
    logger.info("starting %s worker -> topic %s", args.worker, topic)
    asyncio.run(_run(args.worker))


if __name__ == "__main__":
    main()
