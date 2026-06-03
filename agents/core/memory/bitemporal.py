"""
bitemporal.py — H14.1 Bi-temporal Knowledge Graph (Graphiti/Zep-style).

Facts are (subject, predicate, object) triples carrying two timelines:

* **valid-time** (`valid_from` / `valid_to`) — when the fact is true in the world;
* **transaction-time** (`ingested_at`) — when we learned it.

A contradicting fact does **not delete** the prior one: for a single-valued
predicate the old fact is *invalidated* (its `valid_to` is closed at the new
fact's `valid_from`, and `invalidated_at` is stamped), preserving history. Recall
is "as-of": ``as_of(at)`` returns what was true in the world at time *at*, and
``known_as_of(at)`` returns what we believed had we asked at ingest-time *at*.

Times are plain numbers (epoch seconds) so the store is deterministic and
offline-testable. Persistence is a single JSON file (atomic writes).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

DEFAULT_PATH = Path("memory_logs/bitemporal_kg.json")


class BiTemporalKG:
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._facts: list[dict] = []
        self._seq = 0
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._facts = data.get("facts", [])
                self._seq = data.get("seq", len(self._facts))
            except Exception:
                self._facts, self._seq = [], 0

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"facts": self._facts, "seq": self._seq},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

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

    def invalidate(self, subject: str, predicate: str, obj: str, at: Optional[float] = None) -> bool:
        """Explicitly retract a currently-valid fact (close it, keep history)."""
        at = time.time() if at is None else float(at)
        with self._lock:
            for f in self._facts:
                if (f["subject"] == subject and f["predicate"] == predicate
                        and f["object"] == obj and f["valid_to"] is None):
                    f["valid_to"] = at
                    f["invalidated_at"] = at
                    self._save()
                    return True
        return False

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
