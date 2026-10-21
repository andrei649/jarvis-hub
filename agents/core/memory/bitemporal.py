"""
bitemporal.py — H14.1 Bi-temporal Knowledge Graph (Graphiti/Zep-style).

Facts are (subject, predicate, object) triples carrying two timelines:

* **valid-time** (`valid_from` / `valid_to`) — when the fact is true in the world;
* **transaction-time** (`ingested_at`) — when we learned it.

A contradicting fact does **not delete** the prior one: for a single-valued
predicate the old fact is *invalidated* (its `valid_to` is closed at the new
fact's `valid_from`, and `invalidated_at` is stamped), preserving history. Recall
is "as-of": ``as_of(at)`` returns what was true in the world at time *at*, and
``known_as_of(at)`` returns everything ingested by *at*. ``believed_as_of(at)`` is
the stricter transaction-time question the memory explorer's scrubber asks, "what did
the store believe at *at*": a fact ingested by then and not yet superseded or
retracted by then, shown as the store held it at that moment.

Times are plain numbers (epoch seconds) so the store is deterministic and
offline-testable. Persistence is a single JSON file (atomic writes).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

from ..persistence import JsonStore

DEFAULT_PATH = data_path("bitemporal_kg.json")


class BiTemporalKG(JsonStore):
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return {"facts": self._facts, "seq": self._seq}

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._facts = raw.get("facts", [])
        self._seq = raw.get("seq", len(self._facts))


    # ── write ──────────────────────────────────────────────────────────────

    def add_fact(
        self,
        subject: str,
        predicate: str,
        obj: str,
        valid_from: Optional[float] = None,
        ingested_at: Optional[float] = None,
        multi: bool = False,
    ) -> dict:
        """Add a fact. For single-valued predicates (default), an existing valid
        fact for the same (subject, predicate) with a *different* object is
        invalidated (closed) at ``valid_from`` rather than deleted.
        """
        now = time.time()
        valid_from = now if valid_from is None else float(valid_from)
        ingested_at = now if ingested_at is None else float(ingested_at)
        with self._lock:
            if not multi:
                for f in self._facts:
                    if (f["subject"] == subject and f["predicate"] == predicate
                            and f["object"] != obj and f["valid_to"] is None
                            and f["invalidated_at"] is None):
                        f["valid_to"] = valid_from
                        f["invalidated_at"] = valid_from
                        # Transaction time of the supersession: when WE learned the
                        # newer fact (``invalidated_at`` above is valid time).
                        f["invalidated_tx"] = ingested_at
            self._seq += 1
            fact = {
                "id": self._seq,
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "valid_from": valid_from,
                "valid_to": None,
                "ingested_at": ingested_at,
                "invalidated_at": None,
            }
            self._facts.append(fact)
            self._save()
            return dict(fact)

    def invalidate(self, subject: str, predicate: str, obj: str, at: Optional[float] = None,
                   ingested_at: Optional[float] = None) -> bool:
        """Explicitly retract a currently-valid fact (close it, keep history).

        ``at`` is the valid-time end; ``ingested_at`` is the transaction time of the
        retraction (default: ``at``)."""
        at = time.time() if at is None else float(at)
        tx = at if ingested_at is None else float(ingested_at)
        with self._lock:
            for f in self._facts:
                if (f["subject"] == subject and f["predicate"] == predicate
                        and f["object"] == obj and f["valid_to"] is None):
                    f["valid_to"] = at
                    f["invalidated_at"] = at
                    f["invalidated_tx"] = tx
                    self._save()
                    return True
        return False

    def retract_entity(self, name: str, at: Optional[float] = None,
                       ingested_at: Optional[float] = None) -> int:
        """Close every still-believed fact naming *name* as subject or object.

        Backs "delete memory" in the explorer: the graph entity is gone, so the
        timeline must stop asserting its facts from now on. History before *at* is
        kept (``believed_as_of`` an earlier time still returns them). Returns how
        many facts were closed."""
        at = time.time() if at is None else float(at)
        tx = at if ingested_at is None else float(ingested_at)
        closed = 0
        with self._lock:
            ends = self._tx_ends(self._facts)
            for f in self._facts:
                if (f["subject"] == name or f["object"] == name) and ends[f["id"]] is None:
                    if f["valid_to"] is None:
                        f["valid_to"] = at
                    f["invalidated_at"] = at
                    f["invalidated_tx"] = tx
                    closed += 1
            if closed:
                self._save()
        return closed

    # ── read ───────────────────────────────────────────────────────────────

    @staticmethod
    def _valid_at(f: dict, at: float) -> bool:
        return f["valid_from"] <= at and (f["valid_to"] is None or at < f["valid_to"])

    def as_of(self, at: Optional[float] = None, subject: str = "", predicate: str = "") -> list[dict]:
        """Valid-time recall: facts true in the world at time *at*."""
        at = time.time() if at is None else float(at)
        with self._lock:
            facts = list(self._facts)
        out = [
            dict(f) for f in facts
            if self._valid_at(f, at)
            and (not subject or f["subject"] == subject)
            and (not predicate or f["predicate"] == predicate)
        ]
        return out

    def known_as_of(self, at: float, subject: str = "", predicate: str = "") -> list[dict]:
        """Transaction-time recall: what we had ingested by time *at*."""
        at = float(at)
        with self._lock:
            facts = list(self._facts)
        return [
            dict(f) for f in facts
            if f["ingested_at"] <= at
            and (not subject or f["subject"] == subject)
            and (not predicate or f["predicate"] == predicate)
        ]

    @staticmethod
    def _tx_ends(facts: list[dict]) -> dict:
        """fact id -> transaction time the store stopped believing it (None = still).

        Rows written by this version carry ``invalidated_tx``. Older rows only have
        the valid-time ``invalidated_at``; for those the end is when the superseding
        fact (same subject/predicate, opening where this one closed) was ingested,
        falling back to ``invalidated_at``."""
        ends: dict = {}
        by_start: Optional[dict] = None
        for f in facts:
            tx = f.get("invalidated_tx")
            if tx is not None:
                ends[f["id"]] = tx
                continue
            if f.get("invalidated_at") is None and f.get("valid_to") is None:
                ends[f["id"]] = None
                continue
            if by_start is None:
                by_start = {}
                for g in facts:
                    key = (g["subject"], g["predicate"], g["valid_from"])
                    by_start.setdefault(key, []).append(g)
            end = None
            for g in by_start.get((f["subject"], f["predicate"], f.get("valid_to")), ()):
                if g["id"] > f["id"] and g["object"] != f["object"]:
                    end = g["ingested_at"] if end is None else min(end, g["ingested_at"])
            if end is None:
                end = f.get("invalidated_at") if f.get("invalidated_at") is not None else f.get("valid_to")
            ends[f["id"]] = end
        return ends

    def believed_as_of(self, at: float, subject: str = "", predicate: str = "") -> list[dict]:
        """Transaction-time recall: what the store BELIEVED at time *at*.

        A fact ingested by *at* and neither superseded nor retracted by *at*, shown as
        the store held it then (later closes are not visible). Unlike
        ``known_as_of`` this never returns a fact the store had already dropped."""
        at = float(at)
        with self._lock:
            facts = list(self._facts)
        ends = self._tx_ends(facts)
        out = []
        for f in facts:
            if f["ingested_at"] > at:
                continue
            end = ends[f["id"]]
            if end is not None and end <= at:
                continue
            if (subject and f["subject"] != subject) or (predicate and f["predicate"] != predicate):
                continue
            row = dict(f)
            row.pop("invalidated_tx", None)
            if end is not None:  # closed later than *at*: not yet visible then
                row["valid_to"] = None
                row["invalidated_at"] = None
            out.append(row)
        return out

    def first_seen(self) -> dict:
        """name -> earliest ingestion time of any fact naming it (subject or object)."""
        with self._lock:
            facts = list(self._facts)
        seen: dict = {}
        for f in facts:
            for n in (f["subject"], f["object"]):
                # A row written before the route validated its names (a list or a dict
                # object) must not take the whole map down: it names no entity.
                if not isinstance(n, str):
                    continue
                if n not in seen or f["ingested_at"] < seen[n]:
                    seen[n] = f["ingested_at"]
        return seen

    def bounds(self) -> dict:
        """The timeline's extent, for sizing the scrubber."""
        with self._lock:
            facts = list(self._facts)
        if not facts:
            return {"count": 0, "first_ingested": None, "last_ingested": None,
                    "first_valid": None, "last_change": None}
        ends = [e for e in self._tx_ends(facts).values() if e is not None]
        ingested = [f["ingested_at"] for f in facts]
        return {"count": len(facts), "first_ingested": min(ingested),
                "last_ingested": max(ingested),
                "first_valid": min(f["valid_from"] for f in facts),
                "last_change": max(ingested + ends)}

    def current(self, subject: str = "", predicate: str = "") -> list[dict]:
        """Facts valid right now (open valid_to, not invalidated)."""
        return self.as_of(time.time(), subject, predicate)

    def history(self, subject: str, predicate: str = "") -> list[dict]:
        """All versions (incl. invalidated) for a subject, oldest first."""
        with self._lock:
            facts = list(self._facts)
        out = [
            dict(f) for f in facts
            if f["subject"] == subject and (not predicate or f["predicate"] == predicate)
        ]
        out.sort(key=lambda f: (f["valid_from"], f["id"]))
        return out

    def clear(self) -> None:
        with self._lock:
            self._facts.clear()
            self._seq = 0
            self._save()
