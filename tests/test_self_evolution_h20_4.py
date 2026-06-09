"""H20.4 — Self-evolution (prompt optimization from trajectories). All offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.self_evolution import TrajectoryStore, propose_optimization


def test_store_best_selects_top_scoring():
    s = TrajectoryStore()
    s.record("a", "q1", "bad", 0.2)
    s.record("a", "q2", "great", 0.9)
    s.record("a", "q3", "ok", 0.5)
    s.record("b", "x", "y", 1.0)
    best = s.best("a", k=2)
    assert [b["output"] for b in best] == ["great", "ok"]
    assert s.count("a") == 3 and s.count() == 4


@pytest.mark.asyncio
async def test_propose_insufficient_trajectories():
    s = TrajectoryStore()
    s.record("a", "q", "o", 0.9)
    out = await propose_optimization("a", "base prompt", s, min_trajectories=3)
    assert out["ok"] is False and out["reason"] == "insufficient_trajectories"


@pytest.mark.asyncio
async def test_propose_heuristic_appends_demos_and_is_gated():
    s = TrajectoryStore()
    for i in range(3):
        s.record("a", f"q{i}", f"o{i}", 0.8 + i * 0.05)
    out = await propose_optimization("a", "base prompt", s)
    assert out["ok"] is True and out["requires_approval"] is True and out["reversible"] is True
    assert "base prompt" in out["proposed"] and "[learned few-shot demos]" in out["proposed"]
    assert out["from_trajectories"] == 3


@pytest.mark.asyncio
async def test_propose_uses_injected_optimizer():
    s = TrajectoryStore()
    for i in range(3):
        s.record("a", f"q{i}", f"o{i}", 0.9)

    async def optimizer(prompt, best):
        return "OPTIMIZED PROMPT"

    out = await propose_optimization("a", "base", s, optimizer=optimizer)
    assert out["proposed"] == "OPTIMIZED PROMPT"


@pytest.mark.asyncio
async def test_optimizer_failure_falls_back_to_heuristic():
    s = TrajectoryStore()
    for i in range(3):
        s.record("a", f"q{i}", f"o{i}", 0.9)

    async def boom(prompt, best):
        raise RuntimeError("x")

    out = await propose_optimization("a", "base", s, optimizer=boom)
    assert out["ok"] is True and "[learned few-shot demos]" in out["proposed"]
