"""Tests for the async capture-swarm worker (worldview_ingest.capture.worker).

No Kafka / network: ``run`` is driven with a FAKE producer (records send_and_wait
calls) and a FAKE gather() (returns canned candidate batches), an injected fake
``clock`` for determinism, and a finite ``max_cycles`` so the loop terminates.
Mirrors the fakes in the other worker tests; async code is driven with asyncio.run
(no pytest-asyncio).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from unittest import mock

from worldview_ingest.capture import worker as capture_worker
from worldview_ingest.capture.swarm import CandidateSignal
from worldview_ingest.config import Settings

T0 = 1_700_000_000.0

# Pin the capture knobs independent of env defaults.
_TEST_SETTINGS = replace(
    Settings(),
    capture_topic="osint.capture",
    capture_interval_seconds=0,
    capture_rate_per_sec=0.0,  # no refill within a cycle's instant
    capture_burst=100.0,
    capture_global_rate_per_sec=0.0,
    capture_global_burst=100.0,
    capture_cache_ttl_seconds=300.0,
    capture_cache_capacity=1000,
)


class FakeProducer:
    """Records every send_and_wait call so the test can assert on output."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.sent: list[tuple[str, bytes, bytes]] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> None:
        self.sent.append((topic, value, key))


def _cand(entity_id: str, *, source: str = "adsb", trigger: str = "squawk") -> CandidateSignal:
    return CandidateSignal(
        source=source, entity_id=entity_id, trigger=trigger, payload={"e": entity_id}
    )


def _make_gather(batches: list[list[CandidateSignal]]):
    """A fake gather() that yields each batch in turn (then empties)."""
    seq = iter(batches)

    async def gather() -> list[CandidateSignal]:
        return next(seq, [])

    return gather


def _make_clock(times: list[float]):
    """A deterministic fake clock yielding successive UTC seconds."""
    seq = iter(times)
    last = times[-1] if times else T0

    def clock() -> float:
        nonlocal last
        last = next(seq, last)
        return last

    return clock


def _run(gather, *, clock=None, max_cycles=1, settings=_TEST_SETTINGS) -> FakeProducer:
    producer = FakeProducer()
    with mock.patch.object(capture_worker, "settings", settings):
        asyncio.run(
            capture_worker.run(
                producer=producer,
                gather=gather,
                clock=clock or _make_clock([T0]),
                max_cycles=max_cycles,
            )
        )
    assert producer.started and producer.stopped
    return producer


def test_captures_publish_to_osint_capture_with_provenance() -> None:
    """Captured snapshots are published to osint.capture, each carrying provenance."""
    gather = _make_gather([[_cand("a"), _cand("b")]])
    producer = _run(gather, clock=_make_clock([T0]), max_cycles=1)

    assert len(producer.sent) == 2
    for topic, value, key in producer.sent:
        assert topic == "osint.capture"
        msg = json.loads(value)
        assert msg["schema"] == "worldview.capture.v1"
        prov = msg["provenance"]
        assert prov.keys() == {"source", "captured_at", "trigger", "run_id"}
        assert prov["captured_at"] == T0
        assert prov["run_id"] == f"capture-{T0:.3f}"
        assert prov["trigger"] == msg["trigger"]
        # Kafka key is the stable snapshot key.
        assert key.decode() == msg["key"] == f"{msg['source']}:{msg['entity_id']}:{msg['trigger']}"


def test_no_candidates_is_a_noop() -> None:
    """A gather() returning [] publishes nothing (graceful degradation)."""
    producer = _run(_make_gather([[]]), max_cycles=1)
    assert producer.sent == []


def test_no_gather_returns_without_touching_producer() -> None:
    """With no gather() configured, run() no-ops before building/starting a producer."""
    # We pass producer=None and no gather -> early return, nothing published.
    with mock.patch.object(capture_worker, "settings", _TEST_SETTINGS):
        asyncio.run(capture_worker.run(producer=None, gather=None))
    # Nothing to assert beyond "did not raise"; the early return precedes any Kafka use.


def test_dedup_across_cycles_via_shared_cache() -> None:
    """The same active signal in a later cycle is not re-published (cache dedup)."""
    gather = _make_gather([[_cand("a")], [_cand("a"), _cand("b")]])
    # Two cycles, both within the TTL window so "a" stays active.
    producer = _run(gather, clock=_make_clock([T0, T0 + 1.0]), max_cycles=2)
    published_keys = [key.decode() for _, _, key in producer.sent]
    # "a" once (cycle 1), "b" once (cycle 2) — "a" in cycle 2 was deduped.
    assert sorted(published_keys) == ["adsb:a:squawk", "adsb:b:squawk"]


def test_rate_limit_caps_publishes_within_cycle() -> None:
    """A tight per-source burst limits how many of a batch get published."""
    tight = replace(_TEST_SETTINGS, capture_burst=2.0, capture_global_burst=100.0)
    gather = _make_gather([[_cand(f"e{i}") for i in range(5)]])
    producer = _run(gather, clock=_make_clock([T0]), max_cycles=1, settings=tight)
    assert len(producer.sent) == 2  # burst of 2; the other 3 rate-limited


def test_poison_gather_results_skipped_but_handled() -> None:
    """An empty-then-populated gather across cycles still publishes the real batch."""
    gather = _make_gather([[], [_cand("a")]])
    producer = _run(gather, clock=_make_clock([T0, T0 + 1.0]), max_cycles=2)
    assert len(producer.sent) == 1
    assert producer.sent[0][2].decode() == "adsb:a:squawk"
