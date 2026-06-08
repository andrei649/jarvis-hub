"""Async load-test harness wiring (ticket H19.1.6).

Thin glue around the deterministic pure cores
(:mod:`~worldview_ingest.loadtest.generator`,
:mod:`~worldview_ingest.loadtest.rate`,
:mod:`~worldview_ingest.loadtest.metrics`):

* :func:`produce` — drives the rate scheduler, generates synthetic envelopes per tick
  and publishes them to the per-domain Kafka topics via an *injectable* producer (the
  real :class:`~worldview_ingest.kafka_io.TelemetryProducer` in prod, a fake in tests).
* :func:`probe` — fires as-of-T ``GET {api}/history/:layer?t=&bbox=`` queries at random
  ``t`` within the loaded window via an *injectable* async http client (``httpx`` in
  prod, a fake in tests), timing each request and recording the REAL latency into a
  :class:`~worldview_ingest.loadtest.metrics.LatencyRecorder`. It never inspects /
  fabricates the query RESULTS — it measures how long the backend took.
* :func:`run_loadtest` — wires both and returns an SLO report.

Graceful degradation (project hard rule): :func:`produce` with no producer and
:func:`probe` with no client are clean no-ops (they return having done nothing), so a
misconfigured rig measures nothing rather than crashing or fabricating.

Determinism: the message COUNTS, the synthetic envelopes (seeded RNG), the chosen
probe ``t`` values (seeded RNG) and the percentile math are all pure and injected — a
fixed seed + a fake clock + a fake client reproduce a run exactly. Only the live wall
clock used to *time real requests* is non-deterministic, and tests inject that too.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from random import Random
from typing import Any, Protocol

from worldview_ingest.envelope import Domain, TelemetryEnvelope
from worldview_ingest.loadtest.generator import Bbox, generate_tick
from worldview_ingest.loadtest.metrics import LatencyRecorder, SloResult, Stats, slo_check
from worldview_ingest.loadtest.rate import RateSchedule

logger = logging.getLogger(__name__)


class EnvelopeProducer(Protocol):
    """Minimal producer interface the rig needs (satisfied by ``TelemetryProducer``)."""

    async def publish(self, envelope: TelemetryEnvelope) -> None: ...


class HistoryClient(Protocol):
    """Minimal async http interface the probe needs (satisfied by ``httpx.AsyncClient``).

    Only ``get(url, params=...)`` is used; the returned response is NOT inspected for
    content — the rig measures latency, not results.
    """

    async def get(self, url: str, *, params: dict[str, Any] | None = None) -> Any: ...


# A monotonic perf clock yielding seconds (injectable; ``time.perf_counter`` in prod).
ClockFn = Callable[[], float]


@dataclass(frozen=True)
class ProduceResult:
    """Outcome of a :func:`produce` run: how many ticks fired and msgs were published."""

    ticks: int
    published: int
    # Per-topic published counts, so a test can assert the right topics were hit.
    per_topic: dict[str, int]


@dataclass(frozen=True)
class LoadTestReport:
    """The rig's final report: latency stats + the as-of-T SLO verdict, plus context."""

    stats: Stats
    slo: SloResult
    published: int
    probes: int
    window_start: float
    window_end: float

    def to_dict(self) -> dict[str, object]:
        return {
            "published": self.published,
            "probes": self.probes,
            "window": [self.window_start, self.window_end],
            "stats": self.stats.to_dict(),
            "slo": self.slo.to_dict(),
        }


def _domain_topic(layer: Domain) -> str:
    """Resolve a layer to its Kafka topic without importing live Kafka at module load."""
    from worldview_ingest.kafka_io import DOMAIN_TOPICS

    return DOMAIN_TOPICS[layer]


async def produce(
    producer: EnvelopeProducer | None,
    *,
    layers: list[Domain],
    schedule: RateSchedule,
    entities: int,
    t0: float,
    rng: Random,
    bbox: Bbox | None = None,
    per_tick: Callable[[float, int], Awaitable[None]] | None = None,
) -> ProduceResult:
    """Pump synthetic telemetry per the ``schedule``, publishing via ``producer``.

    For each scheduled :class:`~worldview_ingest.loadtest.rate.Tick` and each layer,
    generate ``min(tick.count, entities)`` synthetic envelopes (the tick's per-layer
    share is capped at the simulated fleet size) stamped at ``ts = t0 + tick.t_offset``
    and publish each to its domain topic. Returns a :class:`ProduceResult` with the
    total and per-topic counts.

    Deterministic: counts come from the pure schedule and envelopes from the injected
    ``rng`` (seed it for reproducibility). No wall-clock and no real sleeping happen
    here — pacing is the caller's job (``per_tick`` is an optional async hook the live
    runner uses to sleep until each tick's wall-clock offset; tests pass nothing).

    Graceful degradation: ``producer is None`` -> a clean no-op (zero counts).
    """
    if producer is None:
        logger.info("loadtest produce: no producer configured; no-op")
        return ProduceResult(ticks=0, published=0, per_topic={})

    per_topic: dict[str, int] = {}
    published = 0
    ticks = 0
    for tick in schedule:
        ts = t0 + tick.t_offset
        if per_tick is not None:
            await per_tick(ts, tick.count)
        # The tick's message budget is split across layers; cap each layer's batch at
        # the simulated fleet size so we reuse the same stable tracks (real load tools
        # replay a finite fleet, not unbounded new ids).
        batch = min(tick.count, entities)
        for layer in layers:
            for env in generate_tick(
                count=batch, layer=layer, ts=ts, rng=rng, bbox=bbox, ingested_at=ts
            ):
                await producer.publish(env)
                topic = _domain_topic(layer)
                per_topic[topic] = per_topic.get(topic, 0) + 1
                published += 1
        ticks += 1
    logger.info("loadtest produce: %d ticks -> %d msgs across %s", ticks, published, per_topic)
    return ProduceResult(ticks=ticks, published=published, per_topic=per_topic)


def _history_url(api_url: str, layer: Domain) -> str:
    """Build the ``/history/:layer`` URL for the as-of-T query."""
    return f"{api_url.rstrip('/')}/history/{layer}"


async def probe(
    client: HistoryClient | None,
    *,
    api_url: str,
    layers: list[Domain],
    count: int,
    window_start: float,
    window_end: float,
    bbox: Bbox,
    rng: Random,
    recorder: LatencyRecorder,
    clock: ClockFn,
) -> int:
    """Fire ``count`` as-of-T ``/history`` queries, recording each REAL latency.

    Each probe picks a random ``t`` uniformly within ``[window_start, window_end]``
    (from the injected ``rng`` -> deterministic choice of Ts) and a round-robin layer,
    then issues ``GET {api}/history/:layer?t=&bbox=`` and times it with the injected
    monotonic ``clock`` (``after - before``), recording the elapsed seconds into
    ``recorder``. The response body is intentionally ignored — the rig measures query
    LATENCY, not results, so it can never fabricate an answer. Returns probes recorded.

    Graceful degradation: ``client is None`` -> a clean no-op (records nothing).
    """
    if client is None:
        logger.info("loadtest probe: no http client configured; no-op")
        return 0
    if count <= 0:
        return 0

    bbox_q = bbox.as_query()
    recorded = 0
    for i in range(count):
        t = rng.uniform(window_start, window_end)
        layer = layers[i % len(layers)]
        params = {"t": t, "bbox": bbox_q}
        before = clock()
        await client.get(_history_url(api_url, layer), params=params)
        after = clock()
        recorder.record(max(0.0, after - before))
        recorded += 1
    logger.info("loadtest probe: recorded %d as-of-T latencies", recorded)
    return recorded


async def run_loadtest(
    *,
    producer: EnvelopeProducer | None,
    client: HistoryClient | None,
    api_url: str,
    layers: list[Domain],
    schedule: RateSchedule,
    entities: int,
    probe_count: int,
    bbox: Bbox,
    thresholds: dict[str, float],
    t0: float,
    rng: Random,
    clock: ClockFn,
) -> LoadTestReport:
    """Run the produce phase then the probe phase and return the SLO report.

    The probe phase samples as-of-T queries across the loaded window
    ``[t0, t0 + schedule.duration_s]`` — exactly the window :func:`produce` stamped
    envelopes into — so every probe ``t`` falls inside loaded data. The verdict comes
    from :func:`~worldview_ingest.loadtest.metrics.slo_check` against ``thresholds``.

    Degrades gracefully end-to-end: a missing producer skips the load, a missing client
    skips the probe; with no probes the SLO verdict is a (failing) report with empty
    stats — a load test that measured nothing has not met its SLO.
    """
    produce_result = await produce(
        producer,
        layers=layers,
        schedule=schedule,
        entities=entities,
        t0=t0,
        rng=rng,
        bbox=bbox,
    )
    window_start = t0
    window_end = t0 + schedule.duration_s
    recorder = LatencyRecorder()
    probes = await probe(
        client,
        api_url=api_url,
        layers=layers,
        count=probe_count,
        window_start=window_start,
        window_end=window_end,
        bbox=bbox,
        rng=rng,
        recorder=recorder,
        clock=clock,
    )
    stats = recorder.stats()
    slo = slo_check(stats, thresholds)
    report = LoadTestReport(
        stats=stats,
        slo=slo,
        published=produce_result.published,
        probes=probes,
        window_start=window_start,
        window_end=window_end,
    )
    logger.info("loadtest report: %s", report.to_dict())
    return report
