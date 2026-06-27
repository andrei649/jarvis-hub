"""Tests for the MOONSHOT §6 north-star aggregator + endpoint.

Pure-offline: in-memory TaskQueue + tiny fakes for run_history/tracer, and a
TestClient with `web.orch` rebound (the suite's standard pattern). No LLM,
network, or hardware — the whole point of the metric being computed here.
"""
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.observability.north_star import _percentile, compute_north_star

# ── fixtures / helpers ──────────────────────────────────────────────────────

@pytest.fixture
def q(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    yield queue
    queue.close()


def _make_done(queue: TaskQueue, agent: str = "jarvis") -> int:
    tid = queue.enqueue(agent, "draft_email", "t", risk_tier=1)
    queue.transition(tid, TaskStatus.APPROVED, decided_by="policy")
    queue.transition(tid, TaskStatus.RUNNING)
    queue.transition(tid, TaskStatus.DONE, result={"ok": True})
    return tid


def _make_rejected(queue: TaskQueue, agent: str = "jarvis") -> int:
    tid = queue.enqueue(agent, "draft_email", "t", risk_tier=3)
    queue.transition(tid, TaskStatus.REJECTED, decided_by="user", decision="reject")
    return tid


def _backdate(queue: TaskQueue, tid: int, days: int) -> None:
    old = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    queue._conn.execute("UPDATE tasks SET updated_at=? WHERE id=?", (old, tid))
    queue._conn.commit()


class _FakeRunHistory:
    def __init__(self, local_pct):
        self._lp = local_pct

    def locality(self):
        return {"local": 8, "cloud": 2, "unknown": 0, "total": 10, "local_pct": self._lp}


class _FakeTracer:
    def __init__(self, traces):
        self._traces = traces

    def list(self, limit=50):
        return list(self._traces)[:limit]


# ── percentile helper ───────────────────────────────────────────────────────

def test_percentile_linear_interpolation():
    assert _percentile([10, 20, 30, 40, 50], 95) == 48.0
    assert _percentile([42], 95) == 42.0
    assert _percentile([], 95) is None


# ── core aggregation ────────────────────────────────────────────────────────

def test_basic_north_star_and_counters(q):
    for _ in range(3):
        _make_done(q)
    rid = _make_rejected(q)
    # two interrupts (decision cards pushed to the inbox)
    q.mark_pushed(rid)
    q.mark_pushed(_make_done(q))  # 4th accepted, also pushed

    now = datetime.now(UTC).timestamp()
    rh = _FakeRunHistory(local_pct=80)
    tr = _FakeTracer([
        {"ts": now, "total_ms": 10},
        {"ts": now, "total_ms": 20},
        {"ts": now, "total_ms": 30},
        {"ts": now, "total_ms": 40},
        {"ts": now, "total_ms": 50},
    ])

    out = compute_north_star(q, rh, tr, days=7, now=now)

    assert out["north_star"]["total_accepted"] == 4
    assert out["north_star"]["active_users"] == 1
    assert out["north_star"]["accepted_per_active_user"] == 4.0
    assert out["counter_metrics"]["reject_rate"] == round(1 / 5, 4)  # 1 rejected / 5 decisions
    assert out["counter_metrics"]["interrupt_rate_per_day"] == round(2 / 7, 3)
    assert out["counter_metrics"]["local_pct"] == 80
    assert out["counter_metrics"]["p95_latency_ms"] == 48.0
    assert out["raw"] == {
        "accepted": 4, "rejected": 1, "decisions": 5, "interrupts": 2, "latency_samples": 5,
    }


def test_window_excludes_old_decisions(q):
    fresh = _make_done(q)
    stale = _make_done(q)
    _backdate(q, stale, days=30)

    now = datetime.now(UTC).timestamp()
    out = compute_north_star(q, None, None, days=7, now=now)
    assert out["north_star"]["total_accepted"] == 1  # only the fresh one
    assert fresh and stale  # both exist; windowing — not deletion — excludes the old


def test_empty_is_honest_no_fabrication(q):
    out = compute_north_star(q, None, None, days=7)
    assert out["north_star"]["total_accepted"] == 0
    assert out["north_star"]["active_users"] == 0
    assert out["north_star"]["accepted_per_active_user"] == 0.0
    assert out["counter_metrics"]["reject_rate"] is None
    assert out["counter_metrics"]["interrupt_rate_per_day"] == 0.0
    assert out["counter_metrics"]["local_pct"] is None
    assert out["counter_metrics"]["p95_latency_ms"] is None
    assert out["interrupt_budget"] is None


def test_budget_passthrough(q):
    budget = SimpleNamespace(per_day=4, remaining=lambda: 3)
    out = compute_north_star(q, None, None, budget=budget, days=7)
    assert out["interrupt_budget"] == {"per_day": 4, "remaining": 3}


def test_days_clamped_to_at_least_one(q):
    out = compute_north_star(q, None, None, days=0)
    assert out["days"] == 1


# ── endpoint ────────────────────────────────────────────────────────────────

def test_endpoint_shape_and_clamping(q, monkeypatch):
    from agents import web

    _make_done(q)
    fake_orch = SimpleNamespace(
        autonomy_queue=q,
        run_history=_FakeRunHistory(local_pct=100),
        tracer=_FakeTracer([]),
        autonomy=SimpleNamespace(budget=SimpleNamespace(per_day=4, remaining=lambda: 4)),
    )
    monkeypatch.setattr(web, "orch", fake_orch)
    client = TestClient(web.app)

    resp = client.get("/api/metrics/north-star?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["north_star"]["total_accepted"] == 1
    assert body["counter_metrics"]["local_pct"] == 100
    assert body["interrupt_budget"] == {"per_day": 4, "remaining": 4}

    # Query validation bounds (Query ge=1, le=90)
    assert client.get("/api/metrics/north-star?days=0").status_code == 422
    assert client.get("/api/metrics/north-star?days=500").status_code == 422


def test_endpoint_503_without_queue(monkeypatch):
    from agents import web

    monkeypatch.setattr(web, "orch", SimpleNamespace(autonomy_queue=None))
    client = TestClient(web.app)
    resp = client.get("/api/metrics/north-star")
    assert resp.status_code == 503


# ── P1 proposal-funnel diagnostic ───────────────────────────────────────────
def test_proposal_funnel(q):
    d1 = _make_done(q)
    _make_done(q)                                     # 2 accepted
    _make_rejected(q)                                 # 1 rejected
    p1 = q.enqueue("jarvis", "draft_email", "pending", risk_tier=2)   # 1 pending (proposed)
    q.mark_pushed(d1)                                 # an accepted one surfaced
    q.mark_pushed(p1)                                 # a pending one surfaced
    old = _make_done(q)                               # created OUTSIDE the window → excluded
    q._conn.execute("UPDATE tasks SET created_at=? WHERE id=?",
                    ((datetime.now(UTC) - timedelta(days=30)).isoformat(), old))
    q._conn.commit()

    f = compute_north_star(q, None, None, days=7)["proposal_funnel"]
    assert f["proposed"] == 4 and f["accepted"] == 2 and f["rejected"] == 1
    assert f["pending"] == 1 and f["surfaced"] == 2
    assert f["accept_rate"] == round(2 / 3, 4)        # 2 accepted of 3 resolved
    assert f["surface_rate"] == 0.5                   # 2 surfaced of 4 proposed


def test_proposal_funnel_empty(q):
    f = compute_north_star(q, None, None, days=7)["proposal_funnel"]
    assert f == {"proposed": 0, "surfaced": 0, "accepted": 0, "rejected": 0,
                 "pending": 0, "surface_rate": None, "accept_rate": None}


def test_proposal_funnel_none_queue():
    assert compute_north_star(None, None, None, days=7)["proposal_funnel"] is None
