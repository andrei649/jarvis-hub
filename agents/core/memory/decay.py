"""
decay.py — H14.4 Forgetting with decay + dependency-aware deletion.

Implements the "inspectable & forgettable" principle rigorously:

* **ACT-R base-level activation** as a recency/frequency ranking signal —
  ``B_i = ln(Σ_j (now - t_j)^(-d))`` over an item's access times. Recent and
  frequently-accessed memories rank higher; stale ones decay toward forgetting.
* **Dependency-aware deletion** — when you forget an item, anything *derived from*
  it (its transitive dependents) is forgotten too, so the fact can't be silently
  reconstructed later ("recontamination").

Times are epoch seconds; persistence is a single JSON file (atomic writes).
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from ..persistence import JsonStore
from typing import Optional

DEFAULT_PATH = Path("memory_logs/decay.json")
DEFAULT_DECAY = 0.5            # ACT-R d parameter
_EPS = 1e-3                    # floor for time-since-access (avoid div-by-zero)


def activation(access_times: list[float], now: float, decay: float = DEFAULT_DECAY) -> float:
    """ACT-R base-level activation. Returns -inf with no (past) accesses."""
    total = 0.0
    for t in access_times:
        dt = max(now - t, _EPS)
        total += dt ** (-decay)
    return math.log(total) if total > 0 else float("-inf")


class DecayMemory(JsonStore):
    def __init__(self, path: str | Path = DEFAULT_PATH, decay: float = DEFAULT_DECAY) -> None:
        self.decay = decay
        super().__init__(path)

    def _serialize(self):
        return self._items

    def _deserialize(self, raw) -> None:
        # {id: {"accesses": [ts...], "depends_on": [ids...], "label": str}}
        self._items = raw if isinstance(raw, dict) else {}


    # ── write ──────────────────────────────────────────────────────────────

    def add(self, item_id: str, ts: Optional[float] = None,
            depends_on: Optional[list] = None, label: str = "") -> dict:
        ts = time.time() if ts is None else float(ts)
        with self._lock:
            item = self._items.setdefault(
                item_id, {"accesses": [], "depends_on": [], "label": label})
            if label:
                item["label"] = label
            if depends_on:
                for dep in depends_on:
                    if dep not in item["depends_on"]:
                        item["depends_on"].append(dep)
            item["accesses"].append(ts)
            self._save()
            return dict(item)

    def access(self, item_id: str, ts: Optional[float] = None) -> bool:
        ts = time.time() if ts is None else float(ts)
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return False
            item["accesses"].append(ts)
            self._save()
            return True

    # ── scoring / ranking ────────────────────────────────────────────────────

    def score(self, item_id: str, now: Optional[float] = None) -> float:
        now = time.time() if now is None else float(now)
        with self._lock:
            item = self._items.get(item_id)
            accesses = list(item["accesses"]) if item else []
        return activation(accesses, now, self.decay)

    def ranking(self, now: Optional[float] = None, limit: int = 100) -> list[dict]:
        now = time.time() if now is None else float(now)
        with self._lock:
            ids = list(self._items.keys())
        scored = [
            {"id": i, "activation": round(self.score(i, now), 4),
             "label": self._items[i].get("label", "")}
            for i in ids
        ]
        scored.sort(key=lambda r: r["activation"], reverse=True)
        return scored[:max(1, limit)]

    def forget_candidates(self, threshold: float, now: Optional[float] = None) -> list[dict]:
        """Items whose activation has decayed below *threshold*."""
        return [r for r in self.ranking(now, limit=10_000) if r["activation"] < threshold]

    # ── dependency-aware deletion ────────────────────────────────────────────

    def _dependents(self, item_id: str) -> list[str]:
        return [i for i, it in self._items.items() if item_id in it.get("depends_on", [])]

    def forget(self, item_id: str) -> list[str]:
        """Remove *item_id* and its transitive dependents (anti-recontamination)."""
        with self._lock:
            if item_id not in self._items:
                return []
            to_remove: list[str] = []
            stack = [item_id]
            seen = set()
            while stack:
                cur = stack.pop()
                if cur in seen or cur not in self._items:
                    continue
                seen.add(cur)
                to_remove.append(cur)
                stack.extend(self._dependents(cur))
            for i in to_remove:
                self._items.pop(i, None)
            self._save()
            return to_remove

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._save()
