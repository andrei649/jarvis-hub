"""
learning.py — H21.4 Governed learning SIGNALS (not the loop).

Tracks Knowledge-Component (KC) **mastery** per (component, scope=user|agent)
together with **calibration** (predicted confidence vs actual correctness, as a
mean Brier score), a **correction-ledger** that captures user edit-deltas, and a
**calibration-gated autonomy** signal that only ever *adds* caution.

It does NOT reimplement the skill loop (H20.4/H20.5) — it *feeds and governs* it:
weak / poorly-calibrated components become night-shift ``practice`` proposals,
and miscalibration bumps autonomy toward "ask". Pure, offline-testable, gated
behind ``cognition.learning_enabled``.
"""

from __future__ import annotations

import time
from typing import Optional


class KCStore:
    """Per-(component, scope, who) mastery + calibration (mean Brier)."""

    def __init__(self) -> None:
        self._kc: dict[str, dict] = {}

    @staticmethod
    def key(component: str, scope: str = "agent", who: str = "") -> str:
        return f"{scope}:{who}:{component}"

    def record(self, component: str, correct: bool, confidence: float = 0.5,
               scope: str = "agent", who: str = "") -> dict:
        k = self.key(component, scope, who)
        e = self._kc.setdefault(k, {"component": component, "scope": scope, "who": who,
                                    "attempts": 0, "correct": 0, "brier_sum": 0.0})
        e["attempts"] += 1
        e["correct"] += 1 if correct else 0
        outcome = 1.0 if correct else 0.0
        conf = max(0.0, min(1.0, float(confidence)))
        e["brier_sum"] += (conf - outcome) ** 2     # Brier: lower is better
        return self.get(component, scope, who)

    def mastery(self, component: str, scope: str = "agent", who: str = "") -> float:
        e = self._kc.get(self.key(component, scope, who))
        return round(e["correct"] / e["attempts"], 3) if e and e["attempts"] else 0.0

    def calibration_error(self, component: str, scope: str = "agent",
                          who: str = "") -> Optional[float]:
        e = self._kc.get(self.key(component, scope, who))
        return round(e["brier_sum"] / e["attempts"], 3) if e and e["attempts"] else None

    def get(self, component: str, scope: str = "agent", who: str = "") -> Optional[dict]:
        e = self._kc.get(self.key(component, scope, who))
        if not e:
            return None
        return {**e, "mastery": self.mastery(component, scope, who),
                "calibration_error": self.calibration_error(component, scope, who)}

    def list(self) -> "list[dict]":
        return [self.get(e["component"], e["scope"], e["who"]) for e in self._kc.values()]


class CorrectionLedger:
    """Append-only edit-deltas captured when the user corrects the agent."""

    def __init__(self) -> None:
        self._entries: list[dict] = []

    def record(self, original: str, corrected: str, component: str = "", who: str = "") -> dict:
        delta = {"original": original, "corrected": corrected, "component": component,
                 "who": who, "ts": time.time(), "changed": original != corrected}
        self._entries.append(delta)
        return delta

    def entries(self, limit: int = 50) -> "list[dict]":
        return self._entries[-max(1, limit):][::-1]

    def count(self) -> int:
        return len(self._entries)


def calibration_autonomy_adjustment(mastery: float, calibration_error: Optional[float]) -> int:
    """Tier bump (0 = none, +1 = more caution). NEVER lowers gating."""
    if calibration_error is None:
        return 0
    if calibration_error > 0.25 or mastery < 0.5:
        return 1
    return 0


class LearningModule:
    """KC mastery + calibration + corrections → governance signals for H20.4/.5."""

    def __init__(self) -> None:
        self.kc = KCStore()
        self.corrections = CorrectionLedger()

    def record_outcome(self, component: str, correct: bool, confidence: float = 0.5,
                       scope: str = "agent", who: str = "") -> dict:
        return self.kc.record(component, correct, confidence, scope, who)

    def record_correction(self, original: str, corrected: str, component: str = "",
                          who: str = "") -> dict:
        return self.corrections.record(original, corrected, component, who)

    def autonomy_adjustment(self, component: str, scope: str = "agent", who: str = "") -> int:
        return calibration_autonomy_adjustment(
            self.kc.mastery(component, scope, who),
            self.kc.calibration_error(component, scope, who))

    def practice_proposals(self, max_n: int = 5) -> "list[dict]":
        """Night-shift: propose practice/reinforce on weak or miscalibrated KCs."""
        weak = []
        for e in self.kc.list():
            if e["mastery"] < 0.6 or (e["calibration_error"] or 0.0) > 0.25:
                weak.append({"component": e["component"],
                             "kind": "reinforce" if e["mastery"] >= 0.4 else "practice",
                             "mastery": e["mastery"],
                             "calibration_error": e["calibration_error"]})
        return weak[:max_n]

    def status(self) -> dict:
        return {"available": True, "kc_count": len(self.kc.list()),
                "corrections": self.corrections.count()}
