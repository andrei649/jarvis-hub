"""
self_evolution.py — H20.4 Self-evolution (DSPy/GEPA-style).

Extends the agent learning-loop from "which agent" to "how well it is prompted":
captures ShareGPT-style **trajectories** (input/output + a quality score) and,
from the best ones, proposes an optimized prompt (few-shot demos appended, or a
real DSPy/GEPA optimizer injected). Every proposal is **gated + reversible** (it
goes to the decision inbox; nothing self-applies). Pure and offline-testable;
the optimizer is injected.
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable, Optional


class TrajectoryStore:
    """Bounded store of scored agent trajectories."""

    def __init__(self, cap: int = 500) -> None:
        self.cap = cap
        self._t: list[dict] = []

    def record(self, agent_id: str, input_text: str, output: str, score: float) -> dict:
        rec = {"agent": agent_id, "input": input_text, "output": output,
               "score": float(score), "ts": time.time()}
        self._t.append(rec)
        if len(self._t) > self.cap:
            self._t.pop(0)
        return rec

    def best(self, agent_id: str, k: int = 3) -> "list[dict]":
        items = [t for t in self._t if t["agent"] == agent_id]
        return sorted(items, key=lambda x: x["score"], reverse=True)[:k]

    def count(self, agent_id: Optional[str] = None) -> int:
        if agent_id is None:
            return len(self._t)
        return sum(1 for t in self._t if t["agent"] == agent_id)


async def propose_optimization(
    agent_id: str, current_prompt: str, store: TrajectoryStore,
    optimizer: Optional[Callable[[str, list], Awaitable[str]]] = None,
    min_trajectories: int = 3, k: int = 3,
) -> dict:
    """Propose an optimized prompt from the agent's best trajectories (gated)."""
    best = store.best(agent_id, k=k)
    if len(best) < min_trajectories:
        return {"ok": False, "reason": "insufficient_trajectories",
                "have": len(best), "need": min_trajectories}
    proposed = ""
    if optimizer is not None:
        try:
            proposed = await optimizer(current_prompt, best)
        except Exception:
            proposed = ""
    if not proposed:
        demos = "\n".join(f"- {b['input']} → {b['output']}" for b in best)
        proposed = f"{current_prompt}\n\n[learned few-shot demos]\n{demos}"
    return {"ok": True, "agent": agent_id, "proposed": proposed,
            "from_trajectories": len(best), "avg_score": round(
                sum(b["score"] for b in best) / len(best), 3),
            "requires_approval": True, "reversible": True}
