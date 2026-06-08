"""Ephemeral OSINT capture snapshot (WorldView ticket H19.5.7).

A :class:`Snapshot` is the unit captured by the governed capture swarm: a frozen,
TTL'd record of an *ephemeral* OSINT signal (a transient ADS-B squawk, an AIS gap,
a short-lived RF/jamming spike, a NOTAM about to expire) stamped with PROVENANCE so
it is not lost when the underlying signal disappears.

Wire contract (value JSON), emitted by :meth:`Snapshot.to_dict`::

    { "schema": "worldview.capture.v1", "key": <str>, "source": <str>,
      "entity_id": <str>, "captured_at": <float UNIX s UTC>, "ttl_s": <float>,
      "trigger": <str>, "payload": <dict>,
      "provenance": { "source": <str>, "captured_at": <float>,
                      "trigger": <str>, "run_id": <str> } }

Hard rules honoured here: timestamps are UTC UNIX-seconds floats (the caller injects
``captured_at`` from a pinned clock — the dataclass never reads the wall clock);
the dataclass is frozen; provenance is *always* present (it is derived, not optional);
``payload`` is shallow-copied so a captured snapshot cannot be mutated after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

SCHEMA = "worldview.capture.v1"


def snapshot_key(source: str, entity_id: str, trigger: str) -> str:
    """Stable identity for a signal: ``"{source}:{entity_id}:{trigger}"``.

    The same ephemeral signal (same source, entity and trigger) collapses to one
    key so the swarm can dedup and skip already-cached/active captures. Kept as a
    free function so callers can compute the key *before* building a Snapshot.
    """
    return f"{source}:{entity_id}:{trigger}"


@dataclass(frozen=True)
class Snapshot:
    """A frozen, TTL'd snapshot of an ephemeral OSINT signal, with provenance.

    ``captured_at`` and ``ttl_s`` are UTC UNIX-seconds floats; the snapshot is
    *active* while ``captured_at <= now < captured_at + ttl_s``. ``provenance`` is
    derived in :meth:`create` and is guaranteed present on every instance.
    """

    source: str
    entity_id: str
    captured_at: float
    ttl_s: float
    trigger: str
    payload: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""

    @classmethod
    def create(
        cls,
        *,
        source: str,
        entity_id: str,
        captured_at: float,
        ttl_s: float,
        trigger: str,
        payload: dict[str, Any] | None = None,
        run_id: str = "",
    ) -> Snapshot:
        """Build a Snapshot, shallow-copying ``payload`` so it cannot be mutated later.

        ``captured_at`` must be supplied by the caller from a pinned UTC clock — the
        dataclass never reads the wall clock, keeping it deterministic/testable.
        """
        return cls(
            source=str(source),
            entity_id=str(entity_id),
            captured_at=float(captured_at),
            ttl_s=float(ttl_s),
            trigger=str(trigger),
            payload=dict(payload or {}),
            run_id=str(run_id),
        )

    def key(self) -> str:
        """Stable dedup/cache key: ``"{source}:{entity_id}:{trigger}"``."""
        return snapshot_key(self.source, self.entity_id, self.trigger)

    @property
    def expires_at(self) -> float:
        """The UTC UNIX-second instant the snapshot stops being active."""
        return self.captured_at + self.ttl_s

    def is_active(self, now: float) -> bool:
        """True while ``captured_at <= now < captured_at + ttl_s`` (UTC seconds)."""
        return self.captured_at <= now < self.expires_at

    def is_expired(self, now: float) -> bool:
        """True once the TTL has elapsed: ``now >= captured_at + ttl_s`` (UTC seconds).

        Distinct from ``not is_active``: a not-yet-started snapshot (``now`` before
        ``captured_at``) is NOT expired, so eviction never drops a future-dated entry.
        """
        return now >= self.expires_at

    @property
    def provenance(self) -> dict[str, Any]:
        """The always-present provenance stamp (read-only view).

        Shape: ``{source, captured_at, trigger, run_id}`` — who captured this signal,
        when (UTC seconds), what trigger fired the capture, and which run it belonged
        to. Returned as a read-only mapping so it cannot be mutated in place.
        """
        return MappingProxyType(
            {
                "source": self.source,
                "captured_at": self.captured_at,
                "trigger": self.trigger,
                "run_id": self.run_id,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        """Produce the ``worldview.capture.v1`` contract dict (with provenance)."""
        return {
            "schema": SCHEMA,
            "key": self.key(),
            "source": self.source,
            "entity_id": self.entity_id,
            "captured_at": float(self.captured_at),
            "ttl_s": float(self.ttl_s),
            "trigger": self.trigger,
            "payload": dict(self.payload),
            "provenance": dict(self.provenance),
        }
