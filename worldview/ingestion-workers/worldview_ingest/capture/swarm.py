"""Capture-swarm governance core (ticket H19.5.7).

Pure and deterministic: given a batch of candidate ephemeral signals, a
:class:`RateLimiter` and a :class:`SnapshotCache`, decide which signals to capture
and produce provenance-stamped :class:`Snapshot`s. No I/O — the signals are passed
in (the async worker is the only thing that fetches them), so the whole governance
decision is unit-testable with injected ``now``/``run_id``.

Governance applied to each candidate, in order:

1. **TTL upkeep** — expired cache entries are evicted up front (counted as
   ``expired_evicted``) so capacity/active checks see a fresh view.
2. **Dedup** — duplicate keys *within the same batch* are collapsed (``deduped``);
   only the first wins.
3. **Skip already-active** — a signal already live in the cache is not re-captured
   (also ``deduped`` — it's a duplicate of a still-cached snapshot).
4. **Rate-limit** — :meth:`RateLimiter.acquire` must grant a token for the signal's
   source (per-source AND global); a denied signal is skipped (``rate_limited``).
5. **Capture** — survivors become Snapshots stamped with provenance
   (``source, captured_at, trigger, run_id``) and are ``put`` into the cache.

The ``now``/``run_id`` come from the caller so nothing here touches the wall clock,
and the swarm NEVER fabricates a signal — every Snapshot traces to an input candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from worldview_ingest.capture.cache import SnapshotCache
from worldview_ingest.capture.ratelimit import RateLimiter
from worldview_ingest.capture.snapshot import Snapshot, snapshot_key


@dataclass(frozen=True)
class CandidateSignal:
    """An ephemeral OSINT signal offered to the swarm for capture.

    Carries everything needed to build a Snapshot: which ``source`` saw it, the
    ``entity_id`` it concerns, the ``trigger`` that flagged it as worth capturing,
    and an opaque ``payload``. ``ttl_s`` is optional — when None the cache default
    is used so the snapshot's lifetime matches the cache's.
    """

    source: str
    entity_id: str
    trigger: str
    payload: dict[str, Any] = field(default_factory=dict)
    ttl_s: float | None = None

    def key(self) -> str:
        """Same identity scheme as :func:`snapshot.snapshot_key`."""
        return snapshot_key(self.source, self.entity_id, self.trigger)


@dataclass(frozen=True)
class RunSummary:
    """Outcome counts for one governed capture run."""

    captured: int = 0
    rate_limited: int = 0
    deduped: int = 0
    expired_evicted: int = 0

    def to_dict(self) -> dict[str, int]:
        """Plain-dict form for logging / the worker run log."""
        return {
            "captured": self.captured,
            "rate_limited": self.rate_limited,
            "deduped": self.deduped,
            "expired_evicted": self.expired_evicted,
        }


@dataclass(frozen=True)
class RunResult:
    """A governed run's captured snapshots plus its summary counts."""

    snapshots: list[Snapshot]
    summary: RunSummary


def run_capture(
    candidates: list[CandidateSignal],
    *,
    limiter: RateLimiter,
    cache: SnapshotCache,
    now: float,
    run_id: str,
) -> RunResult:
    """Govern one capture batch; return captured snapshots + a :class:`RunSummary`.

    Pure/deterministic for fixed inputs: ``now`` and ``run_id`` are injected, the
    cache/limiter carry the only mutable state, and every emitted Snapshot is stamped
    with provenance (asserted by the tests). Candidates are processed in order so the
    dedup "first wins" and drop-oldest behaviour is stable.
    """
    expired_evicted = cache.evict_expired(now)

    captured: list[Snapshot] = []
    rate_limited = 0
    deduped = 0
    seen_in_batch: set[str] = set()

    for candidate in candidates:
        key = candidate.key()

        # (2) intra-batch dedup: only the first candidate for a key is considered.
        if key in seen_in_batch:
            deduped += 1
            continue
        seen_in_batch.add(key)

        # (3) skip signals already live in the cache (post-TTL-eviction view).
        if cache.has_active(key, now):
            deduped += 1
            continue

        # (4) rate-limit per-source AND global; a denied signal is skipped.
        if not limiter.acquire(candidate.source, now):
            rate_limited += 1
            continue

        # (5) capture: stamp provenance and cache it.
        ttl_s = candidate.ttl_s if candidate.ttl_s is not None else cache.default_ttl_s
        snapshot = Snapshot.create(
            source=candidate.source,
            entity_id=candidate.entity_id,
            captured_at=now,
            ttl_s=ttl_s,
            trigger=candidate.trigger,
            payload=candidate.payload,
            run_id=run_id,
        )
        cache.put(snapshot, now)
        captured.append(snapshot)

    summary = RunSummary(
        captured=len(captured),
        rate_limited=rate_limited,
        deduped=deduped,
        expired_evicted=expired_evicted,
    )
    return RunResult(snapshots=captured, summary=summary)
