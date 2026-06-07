"""TLE / SGP4 worker (Layer C): fetch catalog, propagate, emit ephemeris + footprints.

Publishes one envelope per satellite per tick to osint.tle, carrying the sub-satellite point
(lon/lat/alt) and the sensor-footprint polygon in geom_wkt.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from worldview_ingest.envelope import TelemetryEnvelope
from worldview_ingest.kafka_io import TelemetryProducer
from worldview_ingest.sun import is_daylight
from worldview_ingest.tle.catalog import TleRecord, parse_tle_text
from worldview_ingest.tle.footprint import footprint_wkt
from worldview_ingest.tle.propagate import propagate

logger = logging.getLogger(__name__)

CELESTRAK_ACTIVE = "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle"
PROPAGATE_SECONDS = 60

# Per-satellite sensor type + footprint params, keyed by NORAD id. In deployment this is
# loaded from the satellites / sensors_footprint_params tables (design doc §1, 01_reference.sql).
SensorSpec = tuple[str, dict[str, Any]]
DEFAULT_SENSOR: SensorSpec = ("optical", {})


def build_envelope(
    record: TleRecord,
    when: datetime,
    sensor_type: str = "optical",
    params: dict | None = None,
) -> TelemetryEnvelope | None:
    """Propagate one TLE and build its ephemeris envelope, or None on propagation error."""
    try:
        pos = propagate(record.line1, record.line2, when)
    except ValueError as exc:
        logger.debug("propagation failed for %s: %s", record.norad_id, exc)
        return None
    return TelemetryEnvelope(
        domain="tle",
        source="celestrak",
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
    interval_seconds: int = PROPAGATE_SECONDS,
    sensors: dict[int, SensorSpec] | None = None,
) -> None:
    """Fetch the catalog once, then propagate the whole set every interval.

    `sensors` maps NORAD id -> (sensor_type, footprint_params); satellites absent from the
    map fall back to a generic optical footprint.
    """
    sensors = sensors or {}
    async with httpx.AsyncClient(timeout=60.0) as client:
        records = await _fetch_catalog(client)
        logger.info("TLE: loaded %d satellites", len(records))
        while True:
            when = datetime.now(UTC)
            published = 0
            for record in records:
                sensor_type, params = sensors.get(record.norad_id, DEFAULT_SENSOR)
                envelope = build_envelope(record, when, sensor_type, params)
                if envelope is not None:
                    await producer.publish(envelope)
                    published += 1
            logger.info("TLE: published %d ephemeris points", published)
            await asyncio.sleep(interval_seconds)


async def _fetch_catalog(client: httpx.AsyncClient) -> list[TleRecord]:
    try:
        resp = await client.get(CELESTRAK_ACTIVE)
        resp.raise_for_status()
        return list(parse_tle_text(resp.text))
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("TLE catalog fetch failed: %s", exc)
        return []
