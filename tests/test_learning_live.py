"""Tests for H3.4 — Learning Loop live: health-based routing + bench promotion."""

import sys
import time
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.learning.loop import LearningLoop  # noqa: E402


@pytest.fixture
def loop(tmp_path):
    return LearningLoop(db_path=str(tmp_path / "learning"))


def _seed(loop, agent_id, n, success):
    for _ in range(n):
        loop.record(agent_id=agent_id, task="t", response="r", success=success, latency=0.1)


# ── Health scoring & ranking ───────────────────────────────────────────────
def test_success_rate_untracked_is_neutral(loop):
    assert loop.get_success_rate("nobody") == 1.0


def test_rank_candidates_prefers_healthier(loop):
    _seed(loop, "good", 10, success=True)
    _seed(loop, "bad", 10, success=False)
    assert loop.rank_candidates(["bad", "good"]) == ["good", "bad"]


def test_rank_is_stable_on_ties(loop):
    # No history → equal neutral score → input order preserved.
    assert loop.rank_candidates(["b", "a", "c"]) == ["b", "a", "c"]


def test_is_unhealthy_requires_min_sample(loop):
    _seed(loop, "x", 2, success=False)  # below UNHEALTHY_MIN_SAMPLE
    assert loop.is_unhealthy("x") is False


def test_is_unhealthy_flags_failing_agent(loop):
    _seed(loop, "x", 8, success=False)
    assert loop.is_unhealthy("x") is True


def test_healthy_agent_not_flagged(loop):
    _seed(loop, "x", 8, success=True)
    assert loop.is_unhealthy("x") is False


# ── Bench promotion suggestions ────────────────────────────────────────────
def test_no_promotion_below_threshold(loop):
    _seed(loop, "vision", 19, success=True)  # default rule: bruce <- vision @ 20
    assert loop.suggest_promotions() == []


def test_promotion_suggested_at_threshold(loop):
    _seed(loop, "vision", 20, success=True)
    sugg = loop.suggest_promotions()
    assert len(sugg) == 1
    assert sugg[0]["bench_agent"] == "bruce"
    assert sugg[0]["source_agent"] == "vision"
    assert sugg[0]["count"] == 20


def test_promotion_skipped_when_already_active(loop):
    _seed(loop, "vision", 25, success=True)
    assert loop.suggest_promotions(active_ids={"bruce"}) == []


def test_promotion_respects_time_window(loop):
    # Record 20 interactions but stamp them older than the 30d window.
    old = time.time() - (40 * 86400)
    for _ in range(20):
        loop.record(agent_id="vision", task="t", response="r", success=True, latency=0.1)
        loop.interactions[-1].timestamp = old
    assert loop.suggest_promotions() == []


def test_custom_promotion_rules(loop):
    loop.set_promotion_rules({"natasha": {"source": "ultron", "threshold": 3, "window_days": 7}})
    _seed(loop, "ultron", 3, success=True)
    sugg = loop.suggest_promotions()
    assert sugg[0]["bench_agent"] == "natasha"


def test_get_stats_includes_suggestions(loop):
    _seed(loop, "vision", 20, success=True)
    stats = loop.get_stats()
    assert stats["promotion_suggestions"][0]["bench_agent"] == "bruce"
    # active filter removes the suggestion
    assert loop.get_stats(active_ids={"bruce"})["promotion_suggestions"] == []
