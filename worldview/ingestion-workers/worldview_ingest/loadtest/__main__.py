"""Entry point: ``python -m worldview_ingest.loadtest`` (ticket H19.1.6).

A standalone TOOL (NOT an ingestion worker — deliberately absent from
``worldview_ingest.__main__.WORKERS``): it pumps synthetic telemetry at the configured
target rate to the per-domain Kafka topics and fires as-of-T ``/history`` queries
against a live backend, then prints the latency SLO report (p50/p95/p99) and exits
non-zero iff the SLO was breached (so CI can gate on it).

Everything load-bearing (generation, pacing, latency recording, percentile math, SLO
verdict) lives in the pure cores and is unit-tested; this module is the thin live
wiring (a real ``TelemetryProducer`` + an ``httpx.AsyncClient`` + a ``perf_counter``
clock) plus a wall-clock pacer so the produce phase actually runs at the target rate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import UTC, datetime
from random import Random

from worldview_ingest.config import settings
from worldview_ingest.envelope import Domain
from worldview_ingest.loadtest.generator import DEFAULT_BBOX, Bbox
from worldview_ingest.loadtest.rate import RateSchedule
from worldview_ingest.loadtest.runner import run_loadtest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("worldview_ingest.loadtest")

_VALID_LAYERS = ("adsb", "ais", "tle", "ew", "context")


def _parse_layers(raw: str) -> list[Domain]:
    layers: list[Domain] = []
    for token in raw.split(","):
        name = token.strip()
        if not name:
            continue
        if name not in _VALID_LAYERS:
            raise ValueError(f"unknown layer {name!r}; valid: {_VALID_LAYERS}")
        layers.append(name)  # type: ignore[arg-type]
    if not layers:
        raise ValueError("at least one layer is required")
    return layers


async def _main_async(args: argparse.Namespace) -> int:
    # Imported lazily so a unit-test import of the module never needs aiokafka/httpx.
    import httpx

    from worldview_ingest.kafka_io import TelemetryProducer

    layers = _parse_layers(args.layers)
    bbox = Bbox.from_tuple(DEFAULT_BBOX)
    schedule = RateSchedule(target_rate=args.target_rate, duration_s=args.duration_s, tick_s=1.0)
    thresholds = {"p95": args.slo_p95_s}
    t0 = datetime.now(UTC).timestamp()
    rng = Random(args.seed)

    producer = TelemetryProducer()
    await producer.start()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            report = await run_loadtest(
                producer=producer,
                client=client,
                api_url=args.api_url,
                layers=layers,
                schedule=schedule,
                entities=args.entities,
                probe_count=args.probe_count,
                bbox=bbox,
                thresholds=thresholds,
                t0=t0,
                rng=rng,
                clock=time.perf_counter,
            )
    finally:
        await producer.stop()

    print(json.dumps(report.to_dict(), indent=2))
    if report.slo.passed:
        logger.info("SLO PASSED")
        return 0
    logger.warning("SLO BREACHED: %s", [b.to_dict() for b in report.slo.breaches])
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="worldview_ingest.loadtest",
        description="Drive synthetic telemetry and measure the as-of-T /history SLO.",
    )
    parser.add_argument("--target-rate", type=float, default=settings.loadtest_target_rate)
    parser.add_argument("--duration-s", type=float, default=settings.loadtest_duration_s)
    parser.add_argument("--entities", type=int, default=settings.loadtest_entities)
    parser.add_argument("--layers", default=settings.loadtest_layers)
    parser.add_argument("--probe-count", type=int, default=settings.loadtest_probe_count)
    parser.add_argument("--slo-p95-s", type=float, default=settings.loadtest_slo_p95_s)
    parser.add_argument("--api-url", default=settings.loadtest_api_url)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    logger.info(
        "loadtest: rate=%.1f/s duration=%.0fs entities=%d layers=%s api=%s slo_p95=%.3fs",
        args.target_rate,
        args.duration_s,
        args.entities,
        args.layers,
        args.api_url,
        args.slo_p95_s,
    )
    sys.exit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
