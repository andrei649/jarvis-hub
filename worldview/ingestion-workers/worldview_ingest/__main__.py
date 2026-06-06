"""Entry point: `python -m worldview_ingest`.

Scaffold: lists the domain->topic routing. Per-domain worker logic lands in STEP 3.
"""

from __future__ import annotations

import logging

from worldview_ingest.kafka_io import DOMAIN_TOPICS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("worldview_ingest")


def main() -> None:
    logger.info("WorldView ingestion workers (scaffold). Domain -> Kafka topic:")
    for domain, topic in DOMAIN_TOPICS.items():
        logger.info("  %-8s -> %s", domain, topic)
    logger.info("Worker fetch/normalize logic is implemented in STEP 3.")


if __name__ == "__main__":
    main()
