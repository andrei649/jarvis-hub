"""TLE / SGP4 worker (Layer C): fetch catalog, propagate, emit ephemeris + footprints.

Publishes one envelope per satellite per tick to osint.tle, carrying the sub-satellite point
(lon/lat/alt), the sensor-footprint polygon (geom_wkt), and the daylight/recon flag. The
catalog source is selectable (Celestrak / Space-Track) and is periodically re-fetched since
TLEs age.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

import httpx

from worldview_ingest.config import settings
from worldview_ingest.envelope import TelemetryEnvelope
from worldview_ingest.kafka_io import TelemetryProducer
from worldview_ingest.sun import is_daylight
from worldview_ingest.tle.catalog import TleRecord
from worldview_ingest.tle.footprint import footprint_wkt
from worldview_ingest.tle.propagate import propagate
from worldview_ingest.tle.sensors import DEFAULT_SENSOR, SensorSpec, sensor_for
from worldview_ingest.tle.sources import build_source

logger = logging.getLogger(__name__)


def build_envelope(
    record: TleRecord,
    when: datetime,
    sensor_type: str = "optical",
    params: dict | None = None,
    source: str = "celestrak",
) -> TelemetryEnvelope | None:
    """Propagate one TLE and build its ephemeris envelope, or None on propagation error."""
    try:
        pos = propagate(record.line1, record.line2, when)
    except ValueError as exc:
        logger.debug("propagation failed for %s: %s", record.norad_id, exc)
        return None
    return TelemetryEnvelope(
        domain="tle",
        source=source,
        entity_id=str(record.norad_id),
        ts=when.timestamp(),
        lon=pos.lon,
        lat=pos.lat,
        alt_m=pos.alt_km * 1000.0,
        geom_wkt=footprint_wkt(pos.lat, pos.lon, pos.alt_km, sensor_type, params or {}),
        payload={
            "name": record.name,
            "velocity_kms": round(pos.velocity_kms, 4),
            "sensor_type": sensor_type,
            # Optical recon needs the target sunlit; SAR sees through darkness.
            "is_sunlit": is_daylight(pos.lat, pos.lon, when),
        },
    )


async def run(
    producer: TelemetryProducer,
    interval_seconds: int | None = None,
    sensors: dict[int, SensorSpec] | None = None,
) -> None:
    """Fetch the catalog, then propagate the whole set every interval; re-fetch as TLEs age.

    `sensors` overrides the per-NORAD sensor registry; satellites absent from either fall back
    to a generic optical footprint.
    """
    source = build_source(settings)
    interval = interval_seconds if interval_seconds is not None else settings.tle_propagate_seconds
    overrides = sensors or {}
    logger.info("TLE worker using source=%s, interval=%ss", source.name, interval)

    async with httpx.AsyncClient(timeout=60.0) as client:
        records: list[TleRecord] = []
        last_fetch = 0.0
        while True:
            if not records or (time.time() - last_fetch) >= settings.tle_refresh_seconds:
                fetched = await source.fetch(client)
                if fetched:
                    records = fetched
                    last_fetch = time.time()
                    logger.info("TLE[%s]: loaded %d satellites", source.name, len(records))
                elif not records:
                    await asyncio.sleep(min(interval, 30))
                    continue

            when = datetime.now(UTC)
            published = 0
            for record in records:
                sensor_type, params = overrides.get(record.norad_id) or sensor_for(record.norad_id)
                envelope = build_envelope(record, when, sensor_type, params, source.name)
                if envelope is not None:
                    await producer.publish(envelope)
                    published += 1
            logger.info("TLE[%s]: published %d ephemeris points", source.name, published)
            await asyncio.sleep(interval)


# Re-exported for backward compatibility with earlier imports/tests.
__all__ = ["build_envelope", "run", "DEFAULT_SENSOR", "SensorSpec"]
