"""Tests for the async load-test harness (ticket H19.1.6).

No Kafka / HTTP: ``produce`` runs against a FAKE producer (records published
envelopes), and ``probe`` runs against a FAKE async http client (returns canned
responses) with a FAKE monotonic clock that advances by a controlled per-request
latency. Drives async code with ``asyncio.run`` (no pytest-asyncio), mirroring the
other worker tests. Asserts: produce publishes the expected count to the right topics;
probe records the controlled latencies and the SLO verdict is correct; both no-op
without producer/client.
"""

from __future__ import annotations

import asyncio
from random import Random
from typing import Any

from worldview_ingest.envelope import TelemetryEnvelope
from worldview_ingest.kafka_io import DOMAIN_TOPICS
from worldview_ingest.loadtest.generator import DEFAULT_BBOX, Bbox
from worldview_ingest.loadtest.metrics import LatencyRecorder
from worldview_ingest.loadtest.rate import RateSchedule
from worldview_ingest.loadtest.runner import probe, produce, run_loadtest

T0 = 1_700_000_000.0


def _box() -> Bbox:
    return Bbox.from_tuple(DEFAULT_BBOX)


class FakeProducer:
    """Records every published envelope (the real TelemetryProducer.publish shape)."""

    def __init__(self) -> None:
        self.published: list[TelemetryEnvelope] = []

    async def publish(self, envelope: TelemetryEnvelope) -> None:
        self.published.append(envelope)


class FakeResponse:
    """A stand-in /history response; the rig never inspects it (latency-only)."""

    status_code = 200

    def json(self) -> dict[str, Any]:
        return {"type": "FeatureCollection", "features": []}


class FakeHttpClient:
    """A fake async http client returning canned responses and recording requests."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any] | None]] = []

    async def get(self, url: str, *, params: dict[str, Any] | None = None) -> FakeResponse:
        self.requests.append((url, params))
        return FakeResponse()


def _clock_from(latencies: list[float]):
    """A fake perf clock yielding exact per-probe latencies.

    Reads come in pairs (before, after) per probe. ``before`` returns 0.0 and ``after``
    returns the next latency, so ``after - before`` is EXACTLY that latency with no
    float accumulation across probes (the rig only ever subtracts within one probe).
    """
    seq = iter(latencies)
    pending = [False]
    current = [0.0]

    def clock() -> float:
        if not pending[0]:
            pending[0] = True
            current[0] = next(seq, 0.0)
            return 0.0
        pending[0] = False
        return current[0]

    return clock


# ---- produce ---------------------------------------------------------------------


def test_produce_publishes_expected_count_and_topics() -> None:
    """10 msg/s for 3 s, two layers, large fleet -> 10*3 per layer to each topic."""
    producer = FakeProducer()
    schedule = RateSchedule(target_rate=10.0, duration_s=3.0, tick_s=1.0)
    result = asyncio.run(
        produce(
            producer,
            layers=["adsb", "ais"],
            schedule=schedule,
            entities=1000,  # fleet >= per-tick budget so nothing is capped
            t0=T0,
            rng=Random(1),
            bbox=_box(),
        )
    )
    # 30 msgs/layer * 2 layers.
    assert result.published == 60
    assert result.ticks == 3
    assert result.per_topic == {DOMAIN_TOPICS["adsb"]: 30, DOMAIN_TOPICS["ais"]: 30}
    assert len(producer.published) == 60
    # Right domains published.
    assert {e.domain for e in producer.published} == {"adsb", "ais"}


def test_produce_caps_batch_at_fleet_size() -> None:
    """Per-tick batch is capped at `entities` (replays a finite fleet)."""
    producer = FakeProducer()
    schedule = RateSchedule(target_rate=100.0, duration_s=1.0, tick_s=1.0)
    result = asyncio.run(
        produce(
            producer,
            layers=["adsb"],
            schedule=schedule,
            entities=5,  # cap each tick's 100 down to 5
            t0=T0,
            rng=Random(1),
            bbox=_box(),
        )
    )
    assert result.published == 5  # capped


def test_produce_ts_within_window() -> None:
    """Published envelope ts stay within [t0, t0+duration]."""
    producer = FakeProducer()
    schedule = RateSchedule(target_rate=5.0, duration_s=4.0, tick_s=1.0)
    asyncio.run(
        produce(
            producer, layers=["adsb"], schedule=schedule, entities=100,
            t0=T0, rng=Random(1), bbox=_box(),
        )
    )
    for e in producer.published:
        assert T0 < e.ts <= T0 + 4.0


def test_produce_noop_without_producer() -> None:
    """produce(None, ...) is a clean no-op."""
    schedule = RateSchedule(target_rate=10.0, duration_s=3.0, tick_s=1.0)
    result = asyncio.run(
        produce(
            None, layers=["adsb"], schedule=schedule, entities=100,
            t0=T0, rng=Random(1), bbox=_box(),
        )
    )
    assert result.published == 0
    assert result.ticks == 0
    assert result.per_topic == {}


# ---- probe -----------------------------------------------------------------------


def test_probe_records_controlled_latencies() -> None:
    """probe records exactly the clock-derived latencies into the recorder."""
    client = FakeHttpClient()
    rec = LatencyRecorder()
    latencies = [0.1, 0.2, 0.3, 0.4]
    n = asyncio.run(
        probe(
            client,
            api_url="http://api",
            layers=["adsb", "ais"],
            count=4,
            window_start=T0,
            window_end=T0 + 10.0,
            bbox=_box(),
            rng=Random(1),
            recorder=rec,
            clock=_clock_from(latencies),
        )
    )
    assert n == 4
    assert rec.samples == latencies
    assert len(client.requests) == 4


def test_probe_query_shape_as_of_t() -> None:
    """Each probe hits /history/:layer with t (in window) + bbox params."""
    client = FakeHttpClient()
    rec = LatencyRecorder()
    asyncio.run(
        probe(
            client,
            api_url="http://api/",
            layers=["adsb"],
            count=3,
            window_start=T0,
            window_end=T0 + 5.0,
            bbox=_box(),
            rng=Random(7),
            recorder=rec,
            clock=_clock_from([0.05, 0.05, 0.05]),
        )
    )
    for url, params in client.requests:
        assert url == "http://api/history/adsb"
        assert params is not None
        assert T0 <= params["t"] <= T0 + 5.0
        assert params["bbox"] == _box().as_query()


def test_probe_round_robins_layers() -> None:
    """Probe layer cycles round-robin across the configured layers."""
    client = FakeHttpClient()
    rec = LatencyRecorder()
    asyncio.run(
        probe(
            client,
            api_url="http://api",
            layers=["adsb", "ais", "tle"],
            count=6,
            window_start=T0,
            window_end=T0 + 1.0,
            bbox=_box(),
            rng=Random(1),
            recorder=rec,
            clock=_clock_from([0.01] * 6),
        )
    )
    layers_hit = [url.rsplit("/", 1)[-1] for url, _ in client.requests]
    assert layers_hit == ["adsb", "ais", "tle", "adsb", "ais", "tle"]


def test_probe_deterministic_ts_with_seed() -> None:
    """Same seed -> same chosen as-of-T values (deterministic probe selection)."""
    def run_once() -> list[float]:
        client = FakeHttpClient()
        asyncio.run(
            probe(
                client, api_url="http://api", layers=["adsb"], count=5,
                window_start=T0, window_end=T0 + 100.0, bbox=_box(),
                rng=Random(123), recorder=LatencyRecorder(), clock=_clock_from([0.0] * 5),
            )
        )
        return [p["t"] for _, p in client.requests]

    assert run_once() == run_once()


def test_probe_noop_without_client() -> None:
    rec = LatencyRecorder()
    n = asyncio.run(
        probe(
            None, api_url="http://api", layers=["adsb"], count=10,
            window_start=T0, window_end=T0 + 1.0, bbox=_box(),
            rng=Random(1), recorder=rec, clock=_clock_from([]),
        )
    )
    assert n == 0
    assert rec.samples == []


def test_probe_zero_count_records_nothing() -> None:
    client = FakeHttpClient()
    rec = LatencyRecorder()
    n = asyncio.run(
        probe(
            client, api_url="http://api", layers=["adsb"], count=0,
            window_start=T0, window_end=T0 + 1.0, bbox=_box(),
            rng=Random(1), recorder=rec, clock=_clock_from([]),
        )
    )
    assert n == 0
    assert client.requests == []


# ---- run_loadtest end-to-end -----------------------------------------------------


def test_run_loadtest_slo_pass() -> None:
    """Fast canned latencies -> SLO passes; report carries published/probe counts."""
    producer = FakeProducer()
    client = FakeHttpClient()
    schedule = RateSchedule(target_rate=10.0, duration_s=2.0, tick_s=1.0)
    report = asyncio.run(
        run_loadtest(
            producer=producer,
            client=client,
            api_url="http://api",
            layers=["adsb"],
            schedule=schedule,
            entities=100,
            probe_count=4,
            bbox=_box(),
            thresholds={"p95": 0.5},
            t0=T0,
            rng=Random(1),
            clock=_clock_from([0.1, 0.2, 0.1, 0.2]),
        )
    )
    assert report.published == 20  # 10/s * 2s, single layer
    assert report.probes == 4
    assert report.window_start == T0 and report.window_end == T0 + 2.0
    assert report.slo.passed
    assert report.stats.count == 4
    assert report.stats.max == 0.2


def test_run_loadtest_slo_breach() -> None:
    """Slow canned latencies breach the p95 SLO; verdict reflects it."""
    producer = FakeProducer()
    client = FakeHttpClient()
    schedule = RateSchedule(target_rate=5.0, duration_s=1.0, tick_s=1.0)
    report = asyncio.run(
        run_loadtest(
            producer=producer,
            client=client,
            api_url="http://api",
            layers=["adsb"],
            schedule=schedule,
            entities=100,
            probe_count=4,
            bbox=_box(),
            thresholds={"p95": 0.5},
            t0=T0,
            rng=Random(1),
            clock=_clock_from([0.6, 0.7, 0.8, 0.9]),
        )
    )
    assert not report.slo.passed
    assert report.slo.breaches[0].metric == "p95"
    d = report.to_dict()
    assert d["slo"]["passed"] is False
    assert d["published"] == 5


def test_run_loadtest_no_client_reports_breach() -> None:
    """No client -> zero probes -> empty stats -> SLO breach (measured nothing)."""
    producer = FakeProducer()
    schedule = RateSchedule(target_rate=10.0, duration_s=1.0, tick_s=1.0)
    report = asyncio.run(
        run_loadtest(
            producer=producer,
            client=None,
            api_url="http://api",
            layers=["adsb"],
            schedule=schedule,
            entities=100,
            probe_count=10,
            bbox=_box(),
            thresholds={"p95": 0.5},
            t0=T0,
            rng=Random(1),
            clock=_clock_from([]),
        )
    )
    assert report.probes == 0
    assert report.stats.count == 0
    assert not report.slo.passed
    # Load still happened.
    assert report.published == 10


def test_run_loadtest_no_producer_skips_load_but_probes() -> None:
    """No producer -> no load, but probes still measure (against whatever is live)."""
    client = FakeHttpClient()
    schedule = RateSchedule(target_rate=10.0, duration_s=1.0, tick_s=1.0)
    report = asyncio.run(
        run_loadtest(
            producer=None,
            client=client,
            api_url="http://api",
            layers=["adsb"],
            schedule=schedule,
            entities=100,
            probe_count=3,
            bbox=_box(),
            thresholds={"p95": 0.5},
            t0=T0,
            rng=Random(1),
            clock=_clock_from([0.1, 0.1, 0.1]),
        )
    )
    assert report.published == 0
    assert report.probes == 3
    assert report.slo.passed
