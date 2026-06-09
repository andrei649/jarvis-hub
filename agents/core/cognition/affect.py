"""
affect.py — H21.2 Mood attractor.

Mood is a slow-moving state that **relaxes toward a setpoint** with time constant
τ (exponential), is nudged by events, and is **clamped**. Two dimensions:
valence (−1..1, pleasant↔unpleasant) and arousal (0..1, calm↔activated). This is
the "alive" layer under the (stable) personality.
"""

from __future__ import annotations

import math
from typing import Optional


class Mood:
    """One mood dimension: relaxes toward `setpoint` with time constant `tau`."""

    def __init__(self, setpoint: float = 0.0, tau: float = 600.0,
                 value: Optional[float] = None, lo: float = -1.0, hi: float = 1.0) -> None:
        self.setpoint = self._clamp(setpoint, lo, hi)
        self.tau = max(1e-3, float(tau))
        self.lo, self.hi = lo, hi
        self.value = self.setpoint if value is None else self._clamp(value, lo, hi)

    @staticmethod
    def _clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    def nudge(self, delta: float) -> float:
        self.value = self._clamp(self.value + delta, self.lo, self.hi)
        return self.value

    def relax(self, dt: float) -> float:
        a = 1.0 - math.exp(-max(0.0, dt) / self.tau)
        self.value = self._clamp(self.value + a * (self.setpoint - self.value), self.lo, self.hi)
        return self.value


class Affect:
    """Valence + arousal mood attractors."""

    def __init__(self, valence_setpoint: float = 0.0, arousal_setpoint: float = 0.0,
                 tau: float = 600.0) -> None:
        self.valence = Mood(valence_setpoint, tau, lo=-1.0, hi=1.0)
        self.arousal = Mood(arousal_setpoint, tau, lo=0.0, hi=1.0)

    def nudge(self, valence: float = 0.0, arousal: float = 0.0) -> dict:
        self.valence.nudge(valence)
        self.arousal.nudge(arousal)
        return self.state()

    def relax(self, dt: float) -> dict:
        self.valence.relax(dt)
        self.arousal.relax(dt)
        return self.state()

    def state(self) -> dict:
        return {"valence": round(self.valence.value, 3), "arousal": round(self.arousal.value, 3)}
