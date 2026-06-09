"""
personality.py — H21.2 Whole-trait personality sampler.

A personality is a set of traits, each a distribution ``{μ, σ, skew}`` rather
than a fixed value. Each turn we *sample* the traits (reproducibly, from a
seed), so the agent is **consistent-but-alive**: the realized mean tracks μ
(±0.05) while individual turns vary (live σ). Traits live in [0, 1].
"""

from __future__ import annotations

import hashlib
import random
from typing import Optional

# A compact, legible default trait set (extend per agent via SOUL front-matter).
DEFAULT_TRAITS = {
    "warmth": {"mu": 0.6, "sigma": 0.10, "skew": 0.0},
    "assertiveness": {"mu": 0.5, "sigma": 0.12, "skew": 0.0},
    "humor": {"mu": 0.4, "sigma": 0.15, "skew": 0.0},
    "formality": {"mu": 0.5, "sigma": 0.10, "skew": 0.0},
    "curiosity": {"mu": 0.7, "sigma": 0.10, "skew": 0.0},
}


def stable_seed(text: str) -> int:
    """A stable per-agent seed so each agent has a reproducible personality."""
    return int(hashlib.sha256((text or "").encode()).hexdigest()[:8], 16)


def sample_trait(mu: float, sigma: float, skew: float = 0.0,
                 rng: Optional[random.Random] = None) -> float:
    """Sample one trait. `skew` adds mean-preserving asymmetric liveness."""
    rng = rng or random
    x = rng.gauss(mu, sigma)
    if skew:
        x += skew * sigma * (rng.random() - 0.5)   # mean 0 → mean still tracks μ
    return max(0.0, min(1.0, x))


class Personality:
    """A trait distribution that samples a live-but-consistent persona."""

    def __init__(self, traits: Optional[dict] = None, seed: Optional[int] = None) -> None:
        self.traits = traits or {k: dict(v) for k, v in DEFAULT_TRAITS.items()}
        self._seed = seed

    def sample(self, seed: Optional[int] = None) -> dict:
        rng = random.Random(seed if seed is not None else self._seed)
        return {name: round(sample_trait(t["mu"], t["sigma"], t.get("skew", 0.0), rng), 3)
                for name, t in self.traits.items()}

    def realized_mean(self, n: int = 2000) -> dict:
        """Mean over n samples — should track each trait's μ within ±0.05."""
        rng = random.Random(0)
        sums = {k: 0.0 for k in self.traits}
        for _ in range(n):
            for name, t in self.traits.items():
                sums[name] += sample_trait(t["mu"], t["sigma"], t.get("skew", 0.0), rng)
        return {k: round(v / n, 3) for k, v in sums.items()}
