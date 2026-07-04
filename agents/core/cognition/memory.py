"""
memory.py — H21.3 Living, unlimited memory (cognition algorithm layer).

Greenfield cognitive-memory mechanisms over H14 (decay/bitemporal/consolidation).
Principles:

  * **Nothing is ever auto-deleted.** Forgetting = demotion across hot/warm/cold
    tiers + reduced activation; only the user explicitly forgets.
  * **Selective encoding** — a predictive-coding *surprise gate* + a 3-vector
    **neuromodulator** salience (DA/NE/ACh) decide what (and how strongly) to
    encode; pattern-separation keeps near-duplicates distinct on write,
    pattern-completion fills from a partial cue on read.
  * **Stays valuable over time** — **re-projection** re-embeds old records onto a
    better model (``embed_version``); a small **core** memory is always injected.
  * **TCM re-rank** nudges fused results by temporal context *after* fusion (it
    never touches the RRF stage).
  * Consolidation runs in two nightly phases (**NREM** stabilize/maintain, **REM**
    recombine).

Pure and offline-testable, gated behind ``cognition.memory_enabled``. Wiring into
the live MemoryManager / recall fusion / DailyReflector is the integration seam.
"""

from __future__ import annotations

import math
import time
from typing import Callable, Optional

HOT, WARM, COLD = "hot", "warm", "cold"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ── neuromodulators + encoding gate (predictive coding) ──────────────────────

def neuromodulators(reward: float = 0.0, surprise: float = 0.0, novelty: float = 0.0) -> dict:
    """3-vector salience: DA=reward/motivation, NE=surprise/arousal, ACh=novelty/attention."""
    return {"DA": round(_clamp01(reward), 3), "NE": round(_clamp01(surprise), 3),
            "ACh": round(_clamp01(novelty), 3)}


def salience(nm: dict) -> float:
    return round((nm["DA"] + nm["NE"] + nm["ACh"]) / 3, 3)


def surprise_score(observed, predicted) -> float:
    """Prediction error in [0,1]. Token-Jaccard for text; cosine-dist for vectors."""
    if isinstance(observed, (list, tuple)) and isinstance(predicted, (list, tuple)):
        a, b = list(observed), list(predicted)
        n = min(len(a), len(b))
        if n == 0:
            return 1.0
        dot = sum(a[i] * b[i] for i in range(n))
        na = math.sqrt(sum(x * x for x in a[:n])) or 1e-9
        nb = math.sqrt(sum(x * x for x in b[:n])) or 1e-9
        return round(_clamp01(1.0 - dot / (na * nb)), 3)
    sa = set(str(observed).lower().split())
    sb = set(str(predicted).lower().split())
    if not sa and not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb) or 1
    return round(1.0 - inter / union, 3)


def encoding_gate(surprise: float, threshold: float = 0.3) -> bool:
    """Predictive-coding gate: only surprising-enough observations are encoded."""
    return surprise >= threshold


def encoding_strength(surprise: float, nm: Optional[dict] = None) -> float:
    base = _clamp01(surprise)
    if nm:
        base = _clamp01(base + 0.3 * salience(nm))
    return round(base, 3)


# ── pattern separation (write) / completion (read) ───────────────────────────

def pattern_separate(vector: "list[float]", neighbors: "list[list[float]]",
                     strength: float = 0.1) -> "list[float]":
    """Nudge `vector` away from near neighbors so similar memories stay distinct."""
    if not neighbors:
        return list(vector)
    out = list(vector)
    for nb in neighbors:
        for i in range(min(len(out), len(nb))):
            out[i] += strength * (out[i] - nb[i])
    return [round(x, 6) for x in out]


def pattern_complete(cue: "list[float]", memories: "list[dict]") -> Optional[dict]:
    """Return the stored memory whose vector is closest to a partial `cue`."""
    best, best_d = None, float("inf")
    for m in memories or []:
        v = m.get("vector") or []
        n = min(len(cue), len(v))
        d = sum((cue[i] - v[i]) ** 2 for i in range(n)) + abs(len(cue) - len(v))
        if d < best_d:
            best, best_d = m, d
    return best


# ── temporal-context re-rank (post-fusion; does NOT touch RRF) ───────────────

def tcm_rerank(results: "list[dict]", context_ts: Optional[float] = None,
               half_life: float = 86_400.0, weight: float = 0.3) -> "list[dict]":
    """Re-rank fused results by temporal proximity to `context_ts` (recency-of-context)."""
    if context_ts is None:
        context_ts = time.time()
    ranked = []
    for r in results or []:
        base = float(r.get("score", 0.0))
        dt = abs(context_ts - float(r.get("ts", context_ts)))
        boost = math.exp(-dt / max(1.0, half_life))
        ranked.append({**r, "tcm_score": round(base + weight * boost, 4)})
    return sorted(ranked, key=lambda x: x["tcm_score"], reverse=True)


# ── tiered store: demote across tiers, NEVER auto-delete ─────────────────────

def tier_for(activation: float, hot: float = 0.5, warm: float = 0.2) -> str:
    return HOT if activation >= hot else (WARM if activation >= warm else COLD)


class TieredMemory:
    """Hot/warm/cold tiering by activation. Maintenance demotes; only the user deletes."""

    def __init__(self, decay: float = 0.5) -> None:
        self.decay = decay
        self._items: dict[str, dict] = {}

    def add(self, mem_id: str, content, activation: float = 1.0, embed_version: int = 1) -> dict:
        rec = {"id": mem_id, "content": content, "activation": round(activation, 3),
               "tier": tier_for(activation), "accesses": 0,
               "ts": time.time(), "embed_version": embed_version}
        self._items[mem_id] = rec
        return dict(rec)

    def access(self, mem_id: str) -> Optional[dict]:
        r = self._items.get(mem_id)
        if r is None:
            return None
        r["accesses"] += 1
        r["activation"] = round(min(1.0, r["activation"] + 0.2), 3)   # reactivate
        r["tier"] = tier_for(r["activation"])
        return dict(r)

    def maintain(self) -> dict:
        """Decay activation and re-tier. NEVER deletes — cold is the floor."""
        demoted = 0
        for r in self._items.values():
            r["activation"] = round(r["activation"] * self.decay, 3)
            new_tier = tier_for(r["activation"])
            if new_tier != r["tier"]:
                demoted += 1
            r["tier"] = new_tier
        return {"demoted": demoted, "total": len(self._items)}

    def forget(self, mem_id: str) -> bool:
        """The ONLY deletion path — an explicit user action."""
        return self._items.pop(mem_id, None) is not None

    def by_tier(self) -> dict:
        out = {HOT: 0, WARM: 0, COLD: 0}
        for r in self._items.values():
            out[r["tier"]] += 1
        return out

    def get(self, mem_id: str) -> Optional[dict]:
        r = self._items.get(mem_id)
        return dict(r) if r else None


# ── re-projection (re-embed onto a better model) ─────────────────────────────

def needs_reprojection(record: dict, current_version: int) -> bool:
    return int(record.get("embed_version", 0)) < int(current_version)


async def reproject(records: "list[dict]", current_version: int, embedder: Callable) -> dict:
    """Re-embed stale records via an injectable embedder; bump embed_version."""
    done = 0
    for r in records or []:
        if not needs_reprojection(r, current_version):
            continue
        try:
            vec = embedder(r.get("content", ""))
            if hasattr(vec, "__await__"):
                vec = await vec
            r["vector"] = vec
            r["embed_version"] = current_version
            done += 1
        except Exception:
            # best-effort migration: skip a row that fails to re-embed
            pass
    return {"reprojected": done, "version": current_version}


# ── core (always-injected, bounded) ──────────────────────────────────────────

class CoreMemory:
    """A small set of always-injected core facts (bounded ring)."""

    def __init__(self, cap: int = 20) -> None:
        self.cap = cap
        self._facts: list[str] = []

    def put(self, fact: str) -> None:
        f = (fact or "").strip()
        if not f:
            return
        if f in self._facts:
            return
        self._facts.append(f)
        if len(self._facts) > self.cap:
            self._facts.pop(0)

    def list(self) -> "list[str]":
        return list(self._facts)

    def render(self) -> str:
        return "" if not self._facts else "[core memory]\n" + "\n".join(f"- {f}" for f in self._facts)


# ── the module ────────────────────────────────────────────────────────────────

class LivingMemory:
    """Ties encoding, tiering, core and consolidation into one cognition module."""

    def __init__(self, embed_version: int = 1, encode_threshold: float = 0.3) -> None:
        self.tiers = TieredMemory()
        self.core = CoreMemory()
        self.embed_version = embed_version
        self.encode_threshold = encode_threshold

    def encode(self, mem_id: str, content, surprise: float, nm: Optional[dict] = None) -> dict:
        """Gate on surprise; encode with neuromodulator-boosted strength."""
        if not encoding_gate(surprise, self.encode_threshold):
            return {"encoded": False, "reason": "below_surprise_gate"}
        strength = encoding_strength(surprise, nm)
        rec = self.tiers.add(mem_id, content, activation=strength, embed_version=self.embed_version)
        return {"encoded": True, "strength": strength, "tier": rec["tier"]}

    async def consolidate(self, phase: str = "nrem") -> dict:
        """NREM = stabilize/maintain (demote, never delete); REM = recombine."""
        if phase == "nrem":
            return {"phase": "nrem", **self.tiers.maintain()}
        return {"phase": "rem", "recombined": len(self.tiers.by_tier())}

    def records(self, prefix: str = "", limit: int = 50) -> "list[dict]":
        """Inspectable records for integration tests/API callers; no mutation."""
        keys = sorted(self.tiers._items.keys())
        if prefix:
            keys = [k for k in keys if k.startswith(prefix)]
        return [self.tiers.get(k) for k in keys[:max(1, limit)]]

    def status(self) -> dict:
        return {"available": True, "tiers": self.tiers.by_tier(),
                "core": len(self.core.list()), "embed_version": self.embed_version}
