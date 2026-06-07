"""Recon-window prediction worker (Layer C insight, ticket H19.2.3).

Runs the pure :func:`worldview_ingest.recon.windows.predict_windows` algorithm
for each configured AOI against the live satellite catalog, and publishes the
predicted passes to the dedicated ``osint.recon`` Kafka topic so the backend can
persist them.

Unlike the domain workers, recon publishes to its OWN topic (not a
``DOMAIN_TOPICS`` entry), so it builds and owns its own ``AIOKafkaProducer`` and
ignores any ``producer`` handed in by the ``__main__`` dispatch.

Cost note
---------
Prediction is CPU-heavy: it walks the horizon in ``step_s`` increments,
propagating each TLE at every step, for *every* AOI x satellite pair. Operators
should set ``TLE_NORAD_IDS`` to a curated recon set (``build_source`` already
filters the fetched catalog to it) — otherwise the whole ``active`` group is
predicted each cycle. The blocking prediction runs in a thread executor so the
asyncio loop (and the producer heartbeats) stay responsive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

import httpx
from aiokafka import AIOKafkaProducer

from worldview_ingest.config import settings
from worldview_ingest.recon.aois import load_aois
from worldview_ingest.recon.message import ReconMessage
from worldview_ingest.recon.windows import Aoi, ReconWindow, predict_windows
from worldview_ingest.tle.catalog import TleRecord
from worldview_ingest.tle.sensors import sensor_for
from worldview_ingest.tle.sources import build_source

logger = logging.getLogger(__name__)

# Backoff bounds for the fetch/predict loop on transient errors (mirrors the other workers).
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0


def predict_all(aois: list[Aoi], records: list[TleRecord], t0: float) -> list[ReconWindow]:
    """Predict every AOI x satellite pair over the horizon (pure, blocking, CPU-heavy).

    Uses the configured horizon/step and the per-NORAD sensor registry. Runs off
    the event loop (see :func:`run`). Returns the flattened window list.
    """
    horizon_s = float(settings.recon_horizon_seconds)
    step_s = float(settings.recon_step_seconds)
    windows: list[ReconWindow] = []
    for record in records:
        sensor_type, params = sensor_for(record.norad_id)
        for aoi in aois:
            windows.extend(
                predict_windows(
                    aoi,
                    record.norad_id,
                    record.line1,
                    record.line2,
                    sensor_type,
                    params,
                    t0,
                    horizon_s,
                    step_s,
                )
            )
    return windows


async def run(producer=None) -> None:  # noqa: ARG001 — recon owns its own producer (own topic)
    """Predict recon windows for the configured AOIs and publish to ``osint.recon``.

    Builds its own ``AIOKafkaProducer`` (recon is its own topic, not a domain), loads
    the AOIs, fetches + periodically refreshes the TLE catalog, and every
    ``recon_interval_seconds`` predicts and publishes windows with exponential
    backoff on transient errors. The ``producer`` argument is ignored by design.
    """
    aois = load_aois(settings)
    source = build_source(settings)
    interval = settings.recon_interval_seconds
    logger.info(
        "recon worker: %d AOI(s), source=%s, horizon=%ss step=%ss interval=%ss",
        len(aois),
        source.name,
        settings.recon_horizon_seconds,
        settings.recon_step_seconds,
        interval,
    )

    kafka = AIOKafkaProducer(bootstrap_servers=settings.kafka_brokers)
    await kafka.start()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            records: list[TleRecord] = []
            last_fetch = 0.0
            backoff = _BACKOFF_BASE
            while True:
                try:
                    if not records or (time.time() - last_fetch) >= settings.tle_refresh_seconds:
                        fetched = await source.fetch(client)
                        if fetched:
                            records = fetched
                            last_fetch = time.time()
                            logger.info(
                                "recon[%s]: loaded %d satellites", source.name, len(records)
                            )
                        elif not records:
                            await asyncio.sleep(min(interval, 30))
                            continue

                    t0 = datetime.now(UTC).timestamp()
                    # CPU-heavy: run the prediction off the event loop to stay responsive.
                    windows = await asyncio.to_thread(predict_all, aois, records, t0)
                    published = await _publish_windows(kafka, windows)
                    logger.info(
                        "recon[%s]: published %d windows (%d sats x %d AOIs)",
                        source.name,
                        published,
                        len(records),
                        len(aois),
                    )
                    backoff = _BACKOFF_BASE
                    await asyncio.sleep(interval)
                except (httpx.HTTPError, OSError) as exc:
                    logger.warning("recon loop error: %s; backing off %.0fs", exc, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_MAX)
    finally:
        await kafka.stop()


async def _publish_windows(kafka: AIOKafkaProducer, windows: list[ReconWindow]) -> int:
    """Publish each window as a ``worldview.recon.v1`` message; return the count sent."""
    published = 0
    for w in windows:
        msg = ReconMessage.from_window(w)
        value = json.dumps(msg.to_dict()).encode()
        key = msg.key().encode()
        await kafka.send_and_wait(settings.recon_topic, value=value, key=key)
        published += 1
    return published
