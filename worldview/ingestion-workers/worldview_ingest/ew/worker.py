"""Cyber & EW worker (Layer D). Implemented in STEP 3.

Aggregates GPS-jamming observations and IODA internet-outage signals into Uber H3 cells
(design doc §9.3), publishing per-cell time-bucketed intensity to osint.ew.
"""

from __future__ import annotations

from worldview_ingest.kafka_io import TelemetryProducer

DOMAIN = "ew"


async def run(producer: TelemetryProducer) -> None:
    """Bucket interference/outage observations into H3 cells and publish envelopes.

    STEP 3 implements H3 aggregation and IODA polling. Scaffold only.
    """
    raise NotImplementedError("EW/H3 worker is implemented in STEP 3")
