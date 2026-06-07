"""Entry point: `python -m worldview_ingest <worker>`.

Workers: adsb | ais | tle | ew | context | recon. Each fetches its source, normalizes to the
canonical envelope, and publishes to its Kafka topic. The dark-vessel detector runs as part of
the AIS pipeline (see worldview_ingest.darkwatch). The recon worker is the Layer-C insight
predictor — it owns its OWN producer/topic (osint.recon), so it gets no shared producer.
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

WORKERS = ("adsb", "ais", "tle", "ew", "context", "recon")


async def _run(worker: str) -> None:
    module = importlib.import_module(f"worldview_ingest.{worker}.worker")
    # recon publishes to its own topic (osint.recon) and builds its own producer.
    if worker == "recon":
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
    topic = settings.recon_topic if args.worker == "recon" else DOMAIN_TOPICS[args.worker]
    logger.info("starting %s worker -> topic %s", args.worker, topic)
    asyncio.run(_run(args.worker))


if __name__ == "__main__":
    main()
