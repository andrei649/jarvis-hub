"""
ensemble.py — H21.5 Ensemble diversity & identity-anchored maturation (cognition).

Keeps the cast of agent personas **distinct** (no two within ε in trait space),
lets each persona **mature** over time but only via **identity-anchored, bounded**
drift (≤ ±0.10 lifetime per trait), tracks a **relational delta** per (agent,
user), and runs a **psychometric self-test** tripwire that fires when drift
exceeds a bound. Drift is a *proposal* — reversible and human-gated (it goes
through the approval queue + SOUL versioning; this module never self-applies an
unapproved change). Pure, offline-testable, gated behind cognition.personality.
"""

from __future__ import annotations

import itertools
from typing import Optional

LIFETIME_CAP = 0.10


def trait_distance(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    return round(sum((a.get(k, 0.0) - b.get(k, 0.0)) ** 2 for k in keys) ** 0.5, 4)


def diversity_check(personas: dict, eps: float = 0.1) -> dict:
    """`personas` = {agent: {trait: μ}}. Flags any pair closer than ε in trait space."""
    ids = list(personas)
    violations, min_d = [], None
    for a, b in itertools.combinations(ids, 2):
        d = trait_distance(personas[a], personas[b])
        min_d = d if min_d is None else min(min_d, d)
        if d < eps:
            violations.append({"a": a, "b": b, "distance": d})
    return {"ok": not violations, "min_distance": min_d, "violations": violations, "eps": eps}


def bounded_drift(baseline: dict, proposed: dict, cap: float = LIFETIME_CAP) -> dict:
    """Clamp each trait's drift from `baseline` to ±cap (the identity anchor)."""
    out = {}
    for k, base in baseline.items():
        delta = max(-cap, min(cap, proposed.get(k, base) - base))
        out[k] = round(base + delta, 4)
    return out


def drift_magnitude(baseline: dict, current: dict) -> float:
    return trait_distance(baseline, current)


class EnsembleModule:
    """Casting + diversity + bounded maturation + relational deltas + self-test."""

    def __init__(self, eps: float = 0.1, selftest_threshold: float = 0.15) -> None:
        self.eps = eps
        self.selftest_threshold = selftest_threshold
        self._cast: dict[str, dict] = {}        # agent -> baseline traits (anchor)
        self._current: dict[str, dict] = {}     # agent -> current traits
        self._relational: dict[str, float] = {} # "agent::user" -> delta

    def register_persona(self, agent_id: str, traits_mu: dict) -> None:
        self._cast[agent_id] = dict(traits_mu)
        self._current.setdefault(agent_id, dict(traits_mu))

    def diversity(self, eps: Optional[float] = None) -> dict:
        return diversity_check(self._current, self.eps if eps is None else eps)

    def drift_proposal(self, agent_id: str, proposed_traits: dict) -> dict:
        """A bounded, reversible drift proposal — NOT applied (human-gated)."""
        base = self._cast.get(agent_id, {})
        target = bounded_drift(base, proposed_traits)
        return {"agent": agent_id, "baseline": base, "proposed": target,
                "magnitude": drift_magnitude(base, target),
                "reversible": True, "requires_approval": True}

    def apply_drift(self, agent_id: str, traits: dict) -> dict:
        """Apply an already-APPROVED drift (still clamped to the lifetime anchor)."""
        self._current[agent_id] = bounded_drift(self._cast.get(agent_id, {}), traits)
        return dict(self._current[agent_id])

    def psychometric_selftest(self, agent_id: str) -> dict:
        base = self._cast.get(agent_id, {})
        cur = self._current.get(agent_id, base)
        mag = drift_magnitude(base, cur)
        return {"agent": agent_id, "drift": mag, "tripwire": mag > self.selftest_threshold}

    def relational_delta(self, agent_id: str, user_id: str, delta: float = 0.0) -> float:
        k = f"{agent_id}::{user_id}"
        self._relational[k] = round(self._relational.get(k, 0.0) + delta, 4)
        return self._relational[k]

    def diff(self, agent_id: str) -> dict:
        base = self._cast.get(agent_id, {})
        cur = self._current.get(agent_id, base)
        return {"agent": agent_id, "baseline": base, "current": cur,
                "delta": {k: round(cur.get(k, 0.0) - base.get(k, 0.0), 4) for k in base}}

    def status(self) -> dict:
        return {"available": True, "agents": sorted(self._cast.keys()),
                "diversity": self.diversity()}
