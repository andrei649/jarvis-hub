"""Tests for the JARVIS Neural Mesh feed (agents/core/routers/brain.py)."""

import sys
import time
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.observability.tracer import Tracer
from agents.core.routers import brain


def _agent(name, model):
    return SimpleNamespace(name=name, config={"model": model})


def _fake_orch(traces=()):
    tracer = Tracer()
    for t in traces:
        tracer.record(t)
    agents = {
        "jarvis": _agent("Jarvis", "local-model"),       # the core — excluded from ring
        "frigga": _agent("Frigga", "local-gemma"),
        "vision": _agent("Vision", "claude-sonnet-4-6"),
        "athena": _agent("Athena", "gemini-2.5-flash"),
    }
    return SimpleNamespace(tracer=tracer, agents=agents)


def test_empty_orch_returns_shape():
    s = brain.build_summary(None, "all")
    for key in ("events", "tokens_out", "cost_eur", "by_agent", "by_model",
                "by_harness", "recent", "rtk"):
        assert key in s
    assert s["events"] == 0
    assert s["by_agent"] == [] and s["by_model"] == []
    assert s["rtk"] is None


def test_roster_seeded_even_when_idle():
    """With no traffic the mesh still shows every agent + model as a zero node."""
    s = brain.build_summary(_fake_orch(), "all")
    agent_ids = {r["agent"] for r in s["by_agent"]}
    assert {"frigga", "vision", "athena"} <= agent_ids
    assert "jarvis" not in agent_ids  # core is not a ring node
    assert all(r["cost_eur"] == 0 for r in s["by_agent"])
    models = {r["model"] for r in s["by_model"]}
    assert {"local-gemma", "claude-sonnet-4-6", "gemini-2.5-flash"} <= models


def test_activity_aggregates_and_attributes():
    now = time.time()
    traces = [
        {"ts": now, "route": "vision", "model": "claude-sonnet-4-6",
         "tokens_in": 100, "tokens_out": 200, "cost": 0.5,
         "timings": {"total_ms": 1200}, "channel": "web"},
        {"ts": now, "route": "vision", "model": "claude-sonnet-4-6",
         "tokens_in": 50, "tokens_out": 80, "cost": 0.25,
         "timings": {"total_ms": 600}, "channel": "web"},
        {"ts": now, "route": "athena", "model": "gemini-2.5-flash",
         "tokens_in": 10, "tokens_out": 20, "cost": 0.01,
         "timings": {"total_ms": 300}, "channel": "telegram"},
    ]
    s = brain.build_summary(_fake_orch(traces), "all")

    assert s["events"] == 3
    assert s["tokens_out"] == 300
    assert s["tokens_in"] == 160
    assert round(s["cost_eur"], 2) == 0.76
    assert s["sessions"] == 2  # web + telegram channels

    vision = next(r for r in s["by_agent"] if r["agent"] == "vision")
    assert vision["tokens_out"] == 280
    assert round(vision["cost_eur"], 2) == 0.75
    # highest-cost agent sorts first
    assert s["by_agent"][0]["agent"] == "vision"

    harnesses = {h["harness"]: h for h in s["by_harness"]}
    assert harnesses["claude"]["events"] == 2
    assert harnesses["gemini"]["events"] == 1
    assert "local" not in harnesses  # no local-model traffic recorded


def test_backend_mapping():
    assert brain._backend_for("claude-opus-4") == "claude"
    assert brain._backend_for("gemini-2.5-pro") == "gemini"
    assert brain._backend_for("google/gemma-4-31b") == "local"
    assert brain._backend_for("") == "local"


def test_recent_is_epoch_ms_and_capped():
    now = time.time()
    traces = [
        {"ts": now, "route": "frigga", "model": "local-gemma",
         "tokens_out": 5, "cost": 0.0, "timings": {"total_ms": 100}, "channel": "web"}
    ]
    s = brain.build_summary(_fake_orch(traces), "all")
    assert len(s["recent"]) == 1
    r = s["recent"][0]
    assert r["ts"] > 1e12          # ms, not seconds
    assert r["harness"] == "local"
    assert r["duration_ms"] == 100


def test_range_filters_old_traces():
    now = time.time()
    old = now - 40 * 86400
    traces = [
        {"ts": now, "route": "vision", "model": "claude-x", "tokens_out": 10,
         "cost": 0.1, "channel": "web"},
        {"ts": old, "route": "vision", "model": "claude-x", "tokens_out": 99,
         "cost": 9.9, "channel": "web"},
    ]
    orch = _fake_orch(traces)
    all_s = brain.build_summary(orch, "all")
    recent_s = brain.build_summary(orch, "30d")
    assert all_s["events"] == 2
    assert recent_s["events"] == 1
    assert round(recent_s["cost_eur"], 2) == 0.10


def test_route_registered():
    paths = {r.path for r in brain.router.routes}
    assert "/brain" in paths
    assert "/api/brain/summary" in paths
