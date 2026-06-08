"""Governed OSINT capture-swarm worker (ticket H19.5.7).

A thin async runner around the pure governance core. Each cycle it gathers
candidate *ephemeral* signals from a pluggable :data:`gather` callable, runs the
swarm governance (rate-limit + dedup + TTL cache, see
:func:`worldview_ingest.capture.swarm.run_capture`), and publishes each captured,
provenance-stamped :class:`Snapshot` to the ``osint.capture`` topic.

Structure mirrors ``recon/worker.py`` / ``cep/worker.py``: the worker owns its OWN
``AIOKafkaProducer`` (``osint.capture`` is not a ``DOMAIN_TOPICS`` entry), so the
``producer`` handed in by ``__main__`` dispatch is ignored in live mode; the
optional ``producer`` / ``gather`` / ``clock`` parameters exist ONLY so the tests
can drive ``run`` without a live broker or live sources.

Graceful degradation (project hard rule): with no ``gather`` configured, or when
``gather`` returns no candidates, the cycle is a clean no-op — nothing is fabricated
and nothing is published. ``gather`` is the ONLY data source.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from worldview_ingest.capture.cache import SnapshotCache
from worldview_ingest.capture.ratelimit import RateLimiter
from worldview_ingest.capture.snapshot import Snapshot
from worldview_ingest.capture.swarm import CandidateSignal, run_capture
from worldview_ingest.config import settings

logger = logging.getLogger(__name__)

# Backoff bounds for the capture loop on transient errors (mirrors the other workers).
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0

# A gather() yields the current batch of candidate ephemeral signals (async, no-arg).
GatherFn = Callable[[], Awaitable[list[CandidateSignal]]]

# A clock yields UTC UNIX seconds; injectable so the governed core stays deterministic.
ClockFn = Callable[[], float]


def _utc_now() -> float:
    """Wall-clock UTC UNIX seconds (the live default; tests inject a fake clock)."""
    return datetime.now(UTC).timestamp()


def _new_run_id(now: float) -> str:
    """Deterministic per-cycle run id derived from the (UTC) capture instant."""
    return f"capture-{now:.3f}"


def _build_limiter() -> RateLimiter:
    """Construct the rate limiter from settings (per-source + global buckets)."""
    return RateLimiter(
        rate=settings.capture_rate_per_sec,
        burst=settings.capture_burst,
        global_rate=settings.capture_global_rate_per_sec,
        global_burst=settings.capture_global_burst,
    )


def _build_cache() -> SnapshotCache:
    """Construct the ephemeral snapshot cache from settings (TTL + capacity)."""
    return SnapshotCache(
        ttl_s=settings.capture_cache_ttl_seconds,
        capacity=settings.capture_cache_capacity,
    )


async def _publish(producer: AIOKafkaProducer, snapshots: list[Snapshot]) -> int:
    """Publish each captured snapshot to ``osint.capture``, keyed by its cache key.

    Returns the number published. Every snapshot carries provenance by construction
    (see :class:`Snapshot`); the value is the ``worldview.capture.v1`` contract dict.
    """
    published = 0
    for snap in snapshots:
        value = json.dumps(snap.to_dict()).encode()
        key = snap.key().encode()
        await producer.send_and_wait(settings.capture_topic, value=value, key=key)
        published += 1
    return published


async def _cycle(
    producer: AIOKafkaProducer,
    gather: GatherFn,
    limiter: RateLimiter,
    cache: SnapshotCache,
    clock: ClockFn,
) -> int:
    """Run one governed capture cycle; return the number of snapshots published.

    Gathers candidates (no-op when empty), governs them, publishes the survivors.
    The ``now``/``run_id`` are pinned per cycle so the governance is deterministic.
    """
    candidates = await gather()
    now = clock()
    if not candidates:
        # Still reap expired entries so the cache can't grow across idle cycles.
        evicted = cache.evict_expired(now)
        if evicted:
            logger.info("capture: no candidates; evicted %d expired snapshot(s)", evicted)
        return 0

    result = run_capture(
        candidates,
        limiter=limiter,
        cache=cache,
        now=now,
        run_id=_new_run_id(now),
    )
    published = await _publish(producer, result.snapshots)
    logger.info(
        "capture: %d candidate(s) -> %s; published %d",
        len(candidates),
        result.summary.to_dict(),
        published,
    )
    return published


async def run(
    producer: AIOKafkaProducer | None = None,
    *,
    gather: GatherFn | None = None,
    clock: ClockFn | None = None,
    max_cycles: int | None = None,
) -> None:
    """Run the capture swarm: gather, govern, publish to ``osint.capture``, repeat.

    Owns its own ``AIOKafkaProducer`` by default (``osint.capture`` is its own
    topic, not a domain); a ``producer`` handed in by ``__main__`` is ignored in
    live mode. The optional ``producer`` / ``gather`` / ``clock`` / ``max_cycles``
    parameters are used ONLY for tests: an injected producer + finite ``max_cycles``
    let ``run`` terminate without a live broker.

    Degrades gracefully: with no ``gather`` (no configured sources) the worker logs
    once and returns — it never fabricates signals.
    """
    if gather is None:
        # No sources wired yet: nothing to capture. No-op rather than fabricate.
        logger.info("capture worker: no gather() source configured; nothing to capture")
        return

    interval = settings.capture_interval_seconds
    clock = clock or _utc_now
    limiter = _build_limiter()
    cache = _build_cache()
    logger.info(
        "capture worker: topic=%s rate=%.3f/s burst=%.0f global=%.3f/s/%0.f "
        "ttl=%ss cap=%d interval=%ss",
        settings.capture_topic,
        settings.capture_rate_per_sec,
        settings.capture_burst,
        settings.capture_global_rate_per_sec,
        settings.capture_global_burst,
        settings.capture_cache_ttl_seconds,
        settings.capture_cache_capacity,
        interval,
    )

    if producer is None:
        producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_brokers)

    await producer.start()
    try:
        backoff = _BACKOFF_BASE
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            try:
                await _cycle(producer, gather, limiter, cache, clock)
                backoff = _BACKOFF_BASE
            except (TimeoutError, OSError, KafkaError) as exc:
                logger.warning("capture loop error: %s; backing off %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
                cycles += 1
                continue
            cycles += 1
            if max_cycles is None or cycles < max_cycles:
                await asyncio.sleep(interval)
    finally:
        await producer.stop()
