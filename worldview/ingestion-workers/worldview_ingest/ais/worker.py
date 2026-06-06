"""AIS ingestion worker (Layer B). Implemented in STEP 3.

Also feeds the dark-vessel detector: geofenced last-seen tracking for vessels that go
silent inside watched choke points (design doc §9.1).
"""

from __future__ import annotations

from worldview_ingest.kafka_io import TelemetryProducer

DOMAIN = "ais"


async def run(producer: TelemetryProducer) -> None:
    """Stream AIS (AISStream/sat), normalize to the envelope, publish to osint.ais.

    STEP 3 implements the stream parser and the dark-vessel watch state. Scaffold only.
    """
    raise NotImplementedError("AIS worker is implemented in STEP 3")
