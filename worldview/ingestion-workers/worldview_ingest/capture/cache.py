"""Ephemeral in-memory snapshot cache with TTL (ticket H19.5.7).

Pure, no I/O: the caller injects ``now`` (UTC UNIX seconds) so expiry is fully
deterministic and unit-testable. The cache holds captured :class:`Snapshot`s only
long enough that an ephemeral signal isn't lost before it's published, then evicts
them — it is NOT a durable store. Two bounds keep growth in check:

* **TTL** — a snapshot is dropped once ``now >= captured_at + ttl_s``.
* **Capacity** — at most ``capacity`` live entries; inserting beyond it evicts the
  OLDEST (smallest ``captured_at``) entry first (drop-oldest).

Counters (puts / ttl_evicted / capacity_evicted / replaced) are exposed for the
run summary and observability.
"""

from __future__ import annotations

from dataclasses import dataclass

from worldview_ingest.capture.snapshot import Snapshot


@dataclass
class CacheCounters:
    """Monotonic counters for cache activity (lifetime of the cache)."""

    puts: int = 0
    ttl_evicted: int = 0
    capacity_evicted: int = 0
    replaced: int = 0


class SnapshotCache:
    """A bounded, TTL'd, in-memory map of ``key -> Snapshot`` (drop-oldest)."""

    def __init__(self, *, ttl_s: float, capacity: int) -> None:
        if ttl_s <= 0:
            raise ValueError(f"ttl_s must be > 0, got {ttl_s}")
        if capacity <= 0:
            raise ValueError(f"capacity must be > 0, got {capacity}")
        self._default_ttl_s = float(ttl_s)
        self._capacity = int(capacity)
        self._entries: dict[str, Snapshot] = {}
        self.counters = CacheCounters()

    @property
    def default_ttl_s(self) -> float:
        """The cache's default TTL (snapshots may carry their own ``ttl_s``)."""
        return self._default_ttl_s

    @property
    def capacity(self) -> int:
        """Maximum number of live entries before drop-oldest eviction kicks in."""
        return self._capacity

    def evict_expired(self, now: float) -> int:
        """Drop every entry whose TTL has elapsed at ``now``; return how many.

        Uses :meth:`Snapshot.is_expired` (``now >= expires_at``), NOT ``not is_active``,
        so a not-yet-started (future-dated) entry is never evicted prematurely.
        """
        expired = [k for k, snap in self._entries.items() if snap.is_expired(now)]
        for k in expired:
            del self._entries[k]
        self.counters.ttl_evicted += len(expired)
        return len(expired)

    def put(self, snapshot: Snapshot, now: float) -> None:
        """Insert ``snapshot``, evicting expired entries then enforcing capacity.

        Order matters: expired entries are reaped first (they free space for free),
        then — if still at capacity for a NEW key — the oldest live entry is dropped
        (by ``captured_at``, ties broken by key for determinism). Re-putting an
        existing key replaces in place and counts as ``replaced``, never evicts.
        """
        self.evict_expired(now)
        key = snapshot.key()
        if key in self._entries:
            self._entries[key] = snapshot
            self.counters.puts += 1
            self.counters.replaced += 1
            return
        while len(self._entries) >= self._capacity:
            oldest_key = min(
                self._entries,
                key=lambda k: (self._entries[k].captured_at, k),
            )
            del self._entries[oldest_key]
            self.counters.capacity_evicted += 1
        self._entries[key] = snapshot
        self.counters.puts += 1

    def get(self, key: str, now: float) -> Snapshot | None:
        """Return the live snapshot for ``key`` at ``now``, or None if absent/expired.

        An expired entry is lazily dropped (and counted) on access so a stale read
        never returns a dead snapshot.
        """
        snap = self._entries.get(key)
        if snap is None:
            return None
        if snap.is_expired(now):
            del self._entries[key]
            self.counters.ttl_evicted += 1
            return None
        if not snap.is_active(now):
            # Stored but not yet started (future-dated): not a hit, but keep it.
            return None
        return snap

    def has_active(self, key: str, now: float) -> bool:
        """Whether ``key`` maps to a non-expired snapshot at ``now``."""
        return self.get(key, now) is not None

    def active(self, now: float) -> list[Snapshot]:
        """All currently-active snapshots at ``now`` (newest first), reaping expired ones."""
        self.evict_expired(now)
        live = [s for s in self._entries.values() if s.is_active(now)]
        return sorted(live, key=lambda s: s.captured_at, reverse=True)

    def __len__(self) -> int:
        """Current entry count (may include not-yet-reaped expired entries)."""
        return len(self._entries)
