"""ADS-B ingestion worker (Layer A). Implemented in STEP 3."""

from __future__ import annotations

from worldview_ingest.kafka_io import TelemetryProducer

DOMAIN = "adsb"


async def run(producer: TelemetryProducer) -> None:
    """Poll ADS-B feeds (OpenSky/ADSB.fi), normalize to the envelope, publish to osint.adsb.

    STEP 3 implements source polling, military tagging, and envelope mapping. Scaffold only.
    """
    raise NotImplementedError("ADS-B worker is implemented in STEP 3")
