"""Tests for H7.11 — Learning-loop activation (scheduled promotions → inbox)."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.learning.loop import LearningLoop
from agents.core.learning.scheduler import propose_promotions, PROMOTION_KIND
from agents.core.autonomy.queue import TaskQueue


def _loop_with_traffic(tmp_path, count=3):
    loop = LearningLoop(db_path=str(tmp_path / "learn/"))
    loop.set_promotion_rules({"bench1": {"source": "gecko", "threshold": 2, "window_days": 30}})
    for _ in range(count):
        loop.record("gecko", "task", "resp", success=True, latency=0.1)
    return loop


def _queue(tmp_path):
    q = TaskQueue(db_path=str(tmp_path / "q.db"))
    q.initialize()
    return q


# ── proposal enqueueing ──────────────────────────────────────────────────────

def test_proposes_promotion_into_queue(tmp_path):
    loop = _loop_with_traffic(tmp_path)
    q = _queue(tmp_path)
    enqueued = propose_promotions(loop, q, active_ids=[])
    assert len(enqueued) == 1
    p = enqueued[0]
    assert p["bench_agent"] == "bench1" and p["source_agent"] == "gecko"
    # task landed in the decision inbox, gated + reversible
    tasks = q.list(status="proposed")
    task = [t for t in tasks if t.kind == PROMOTION_KIND][0]
    assert task.autonomy_level == "ask" and task.origin == "generated"
    assert task.payload["bench_agent"] == "bench1"


def test_idempotent_no_duplicate_proposal(tmp_path):
    loop = _loop_with_traffic(tmp_path)
    q = _queue(tmp_path)
    propose_promotions(loop, q, active_ids=[])
    again = propose_promotions(loop, q, active_ids=[])      # already an open proposal
    assert again == []
    assert len([t for t in q.list(status="proposed") if t.kind == PROMOTION_KIND]) == 1


def test_below_threshold_no_proposal(tmp_path):
    loop = _loop_with_traffic(tmp_path, count=1)             # 1 < threshold 2
    q = _queue(tmp_path)
    assert propose_promotions(loop, q, active_ids=[]) == []


def test_already_active_skipped(tmp_path):
    loop = _loop_with_traffic(tmp_path)
    q = _queue(tmp_path)
    assert propose_promotions(loop, q, active_ids=["bench1"]) == []   # already active


def test_handles_missing_components():
    assert propose_promotions(None, None, []) == []


# ── endpoint ─────────────────────────────────────────────────────────────────

def test_learning_propose_endpoint():
    from agents import web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    try:
        with TestClient(web.app) as c:
            assert c.post("/api/learning/propose").status_code == 401   # admin-guarded
            r = c.post("/api/learning/propose", headers={"X-Admin-Token": "test-secret"})
            assert r.status_code == 200 and "proposed" in r.json()
    finally:
        web.ADMIN_TOKEN = old
