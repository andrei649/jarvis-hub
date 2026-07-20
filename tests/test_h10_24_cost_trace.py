"""Tests for H10.24 — Cost per Trace.

Covers the two pieces this horizon adds on top of H7.10 analytics:
  1. per-trace `cost` (computed via the existing cost_estimator), and
  2. per-agent / per-day cost rollups derived from the tracer ring buffer,
     surfaced at GET /api/cost.
"""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.observability.tracer import Tracer
from agents.core.llm.cost_estimator import estimate_cost
from agents.core.llm.model_config import DEFAULT_CLAUDE_MODEL


# ── per-trace cost via the shared estimator ─────────────────────────────────

def test_local_model_is_free():
    assert estimate_cost("local", 1000, 1000)["total"] == 0.0
    assert estimate_cost("google/gemma-4-31b-a4b", 5000, 5000)["total"] == 0.0


def test_cloud_model_has_cost():
    out = estimate_cost(DEFAULT_CLAUDE_MODEL, 1_000_000, 1_000_000)
    # 3.00 in + 15.00 out per 1M tokens
    assert out["total"] == 18.0


def test_unknown_model_falls_back_to_zero():
    assert estimate_cost("totally-made-up-model", 1000, 2000)["total"] == 0.0


# ── tracer rollups ──────────────────────────────────────────────────────────

def test_tracer_records_cost_field_default():
    tr = Tracer()
    tid = tr.record({"route": "jarvis", "agents": ["jarvis"]})
    full = tr.get(tid)
    assert full["cost"] == 0.0  # default when not supplied
    # cost surfaces in the summarized list view too
    assert tr.list(10)[0]["cost"] == 0.0


def test_cost_by_agent_aggregates():
    tr = Tracer()
    tr.record({"route": "athena", "cost": 0.02})
    tr.record({"route": "athena", "cost": 0.03})
    tr.record({"route": "friday", "cost": 0.01})
    by_agent = {r["agent_id"]: r for r in tr.cost_by_agent()}
    assert by_agent["athena"]["calls"] == 2
    assert by_agent["athena"]["cost"] == 0.05
    assert by_agent["friday"]["cost"] == 0.01
    # highest cost first
    assert tr.cost_by_agent()[0]["agent_id"] == "athena"


def test_cost_by_day_and_summary():
    tr = Tracer()
    base = 1_700_006_400  # 2023-11-15 00:00:00 UTC (midnight, safe within-day math)
    tr.record({"route": "a", "cost": 0.10, "ts": base})           # day 1
    tr.record({"route": "a", "cost": 0.20, "ts": base + 3600})    # day 1, +1h
    tr.record({"route": "b", "cost": 0.05, "ts": base + 90000})   # day 2 (+25h)
    by_day = tr.cost_by_day()
    assert len(by_day) == 2
    busiest = max(by_day, key=lambda r: r["calls"])
    assert busiest["calls"] == 2
    assert busiest["cost"] == 0.30
    summary = tr.cost_summary()
    assert summary["calls"] == 3
    assert summary["total_cost"] == 0.35


def test_route_falls_back_to_first_agent():
    tr = Tracer()
    tr.record({"agents": ["stark"], "cost": 0.04})  # no explicit route
    assert tr.cost_by_agent()[0]["agent_id"] == "stark"


# ── endpoint ────────────────────────────────────────────────────────────────

def test_api_cost_endpoint_shape():
    from agents import web
    with TestClient(web.app) as c:
        resp = c.get("/api/cost")
        assert resp.status_code == 200
        data = resp.json()
        assert "by_agent" in data
        assert "by_day" in data
        assert "summary" in data
        assert isinstance(data["by_agent"], list)
        assert isinstance(data["by_day"], list)
