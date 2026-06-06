"""TLE / SGP4 propagation worker (Layer C). Implemented in STEP 3.

Fetches TLEs (Celestrak/Space-Track), propagates with SGP4 at a fixed cadence, derives
sensor footprints (optical cone / SAR swath / coverage circle), publishes to osint.tle.
"""

from __future__ import annotations

from worldview_ingest.kafka_io import TelemetryProducer

DOMAIN = "tle"


async def run(producer: TelemetryProducer) -> None:
    """Propagate the satellite catalog and emit ephemeris + footprint envelopes.

    STEP 3 implements SGP4 propagation and footprint geometry. Scaffold only.
    """
    raise NotImplementedError("TLE/SGP4 worker is implemented in STEP 3")
