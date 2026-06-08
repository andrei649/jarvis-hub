"""Tests for the ephemeral TTL snapshot cache (ticket H19.5.7).

Pure/no-I/O: ``now`` (UTC UNIX seconds) is injected on every call so TTL expiry and
capacity eviction are deterministic. Covers TTL expiry, drop-oldest at capacity,
``active()`` correctness, lazy expiry on ``get``, replace-in-place, and counters.
"""

from __future__ import annotations

import pytest

from worldview_ingest.capture.cache import SnapshotCache
from worldview_ingest.capture.snapshot import Snapshot

T0 = 1_700_000_000.0


def _snap(entity_id: str, captured_at: float, *, ttl_s: float = 100.0, trigger: str = "t") -> Snapshot:
    return Snapshot.create(
        source="adsb",
        entity_id=entity_id,
        captured_at=captured_at,
        ttl_s=ttl_s,
        trigger=trigger,
        payload={"e": entity_id},
        run_id="run-1",
    )


def test_put_and_get_roundtrip() -> None:
    """A freshly put snapshot is retrievable by key while active."""
    cache = SnapshotCache(ttl_s=100.0, capacity=10)
    snap = _snap("a", T0)
    cache.put(snap, T0)
    assert cache.get(snap.key(), T0) is snap
    assert cache.has_active(snap.key(), T0) is True
    assert len(cache) == 1
    assert cache.counters.puts == 1


def test_ttl_expiry_get_returns_none_after_ttl() -> None:
    """``get`` returns None once the snapshot's TTL has elapsed (boundary exclusive)."""
    cache = SnapshotCache(ttl_s=100.0, capacity=10)
    snap = _snap("a", T0, ttl_s=50.0)
    cache.put(snap, T0)
    # Just before expiry: still live. At exactly captured_at+ttl: expired.
    assert cache.get(snap.key(), T0 + 49.999) is snap
    assert cache.get(snap.key(), T0 + 50.0) is None
    # Lazy eviction on the expired get removed it and bumped the counter.
    assert len(cache) == 0
    assert cache.counters.ttl_evicted == 1


def test_evict_expired_reaps_only_dead_entries() -> None:
    """``evict_expired`` drops expired entries and leaves live ones, returning the count."""
    cache = SnapshotCache(ttl_s=100.0, capacity=10)
    cache.put(_snap("short", T0, ttl_s=10.0), T0)
    cache.put(_snap("long", T0, ttl_s=1000.0), T0)
    evicted = cache.evict_expired(T0 + 20.0)
    assert evicted == 1
    assert cache.counters.ttl_evicted == 1
    assert {s.entity_id for s in cache.active(T0 + 20.0)} == {"long"}


def test_capacity_drops_oldest_by_captured_at() -> None:
    """At capacity, inserting a new key evicts the oldest (smallest captured_at)."""
    cache = SnapshotCache(ttl_s=10_000.0, capacity=2)
    cache.put(_snap("old", T0 + 0.0), T0 + 10.0)
    cache.put(_snap("mid", T0 + 5.0), T0 + 10.0)
    # Third insert at capacity -> "old" (smallest captured_at) is dropped.
    cache.put(_snap("new", T0 + 9.0), T0 + 10.0)
    keys = {s.entity_id for s in cache.active(T0 + 10.0)}
    assert keys == {"mid", "new"}
    assert cache.counters.capacity_evicted == 1


def test_expired_freed_before_capacity_eviction() -> None:
    """Expired entries are reaped first, so a live entry isn't evicted unnecessarily."""
    cache = SnapshotCache(ttl_s=10_000.0, capacity=2)
    cache.put(_snap("expiring", T0, ttl_s=5.0), T0)  # will be dead by T0+10
    cache.put(_snap("live", T0 + 1.0, ttl_s=10_000.0), T0)
    # At T0+10 the "expiring" entry is dead; putting a new key reaps it (no capacity drop).
    cache.put(_snap("fresh", T0 + 10.0), T0 + 10.0)
    keys = {s.entity_id for s in cache.active(T0 + 10.0)}
    assert keys == {"live", "fresh"}
    assert cache.counters.ttl_evicted == 1
    assert cache.counters.capacity_evicted == 0


def test_active_excludes_expired_and_sorts_newest_first() -> None:
    """``active`` returns only live snapshots, newest (largest captured_at) first."""
    cache = SnapshotCache(ttl_s=10_000.0, capacity=10)
    cache.put(_snap("a", T0 + 0.0, ttl_s=5.0), T0)  # dead by T0+10
    cache.put(_snap("b", T0 + 2.0), T0)
    cache.put(_snap("c", T0 + 8.0), T0)
    active = cache.active(T0 + 10.0)
    assert [s.entity_id for s in active] == ["c", "b"]


def test_replace_in_place_does_not_evict() -> None:
    """Re-putting the same key replaces the snapshot without a capacity eviction."""
    cache = SnapshotCache(ttl_s=10_000.0, capacity=1)
    first = _snap("a", T0, trigger="squawk")
    cache.put(first, T0)
    second = _snap("a", T0 + 1.0, trigger="squawk")  # same key (source:entity:trigger)
    cache.put(second, T0 + 1.0)
    assert len(cache) == 1
    assert cache.get(second.key(), T0 + 1.0).captured_at == T0 + 1.0
    assert cache.counters.replaced == 1
    assert cache.counters.capacity_evicted == 0
    assert cache.counters.puts == 2


def test_has_active_false_for_missing_or_expired() -> None:
    """``has_active`` is False for an unknown key and for an expired one."""
    cache = SnapshotCache(ttl_s=100.0, capacity=10)
    assert cache.has_active("nope", T0) is False
    snap = _snap("a", T0, ttl_s=5.0)
    cache.put(snap, T0)
    assert cache.has_active(snap.key(), T0 + 4.0) is True
    assert cache.has_active(snap.key(), T0 + 5.0) is False


@pytest.mark.parametrize("ttl_s,capacity", [(0.0, 10), (-1.0, 10), (100.0, 0), (100.0, -3)])
def test_rejects_invalid_config(ttl_s: float, capacity: int) -> None:
    """Non-positive TTL or capacity is a configuration error."""
    with pytest.raises(ValueError):
        SnapshotCache(ttl_s=ttl_s, capacity=capacity)
