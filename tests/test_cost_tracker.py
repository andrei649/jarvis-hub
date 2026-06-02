"""Tests for H7.10 — Cost tracker module and /api/analytics/cost endpoint."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


@pytest.fixture(autouse=True)
def reset_tracker():
    """Reset cost tracker state before each test to avoid cross-test pollution."""
    from agents.core import cost_tracker
    cost_tracker.reset()
    yield
    cost_tracker.reset()


# ── Unit tests for cost_tracker module ───────────────────────────

def test_record_accumulates_tokens():
    from agents.core import cost_tracker
    cost_tracker.record("jarvis", input_tokens=100, output_tokens=50, model="default")
    cost_tracker.record("jarvis", input_tokens=200, output_tokens=100, model="default")
    summary = cost_tracker.get_summary()
    assert summary["agents"]["jarvis"]["input_tokens"] == 300
    assert summary["agents"]["jarvis"]["output_tokens"] == 150
    assert summary["agents"]["jarvis"]["calls"] == 2


def test_record_multiple_agents():
    from agents.core import cost_tracker
    cost_tracker.record("jarvis", input_tokens=1000, output_tokens=500, model="gpt-4o")
    cost_tracker.record("friday", input_tokens=500, output_tokens=250, model="gpt-4o-mini")
    summary = cost_tracker.get_summary()
    assert "jarvis" in summary["agents"]
    assert "friday" in summary["agents"]


def test_get_summary_calculates_cost_default():
    from agents.core import cost_tracker
    # 1M input tokens @ $3.00, 1M output @ $15.00
    cost_tracker.record("agent-x", input_tokens=1_000_000, output_tokens=1_000_000, model="default")
    summary = cost_tracker.get_summary()
    cost = summary["agents"]["agent-x"]["cost_usd"]
    assert abs(cost - 18.0) < 0.001  # $3 input + $15 output


def test_get_summary_calculates_cost_haiku():
    from agents.core import cost_tracker
    # claude-haiku: $0.25 input / $1.25 output per 1M tokens
    cost_tracker.record("agent-y", input_tokens=1_000_000, output_tokens=1_000_000, model="claude-haiku")
    summary = cost_tracker.get_summary()
    cost = summary["agents"]["agent-y"]["cost_usd"]
    assert abs(cost - 1.50) < 0.001  # $0.25 + $1.25


def test_get_summary_local_model_zero_cost():
    from agents.core import cost_tracker
    cost_tracker.record("local-agent", input_tokens=100_000, output_tokens=100_000, model="local")
    summary = cost_tracker.get_summary()
    assert summary["agents"]["local-agent"]["cost_usd"] == 0.0


def test_get_summary_total_cost():
    from agents.core import cost_tracker
    cost_tracker.record("a1", input_tokens=1_000_000, output_tokens=0, model="gpt-4o")
    cost_tracker.record("a2", input_tokens=0, output_tokens=1_000_000, model="gpt-4o")
    summary = cost_tracker.get_summary()
    # a1: 1M input @ $5.00 = $5.00; a2: 1M output @ $15.00 = $15.00; total $20.00
    assert abs(summary["total_cost_usd"] - 20.0) < 0.001


def test_reset_clears_state():
    from agents.core import cost_tracker
    cost_tracker.record("jarvis", input_tokens=1000, output_tokens=500)
    cost_tracker.reset()
    summary = cost_tracker.get_summary()
    assert summary["agents"] == {}
    assert summary["total_cost_usd"] == 0.0


def test_get_summary_empty():
    from agents.core import cost_tracker
    summary = cost_tracker.get_summary()
    assert "agents" in summary
    assert "total_cost_usd" in summary
    assert summary["total_cost_usd"] == 0.0


# ── Endpoint test ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from agents.web import app
    with TestClient(app) as c:
        yield c


def test_cost_analytics_endpoint_returns_200(client):
    """GET /api/analytics/cost must return 200 with expected keys."""
    resp = client.get("/api/analytics/cost")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert "total_cost_usd" in data


def test_cost_analytics_endpoint_total_is_float(client):
    """total_cost_usd must be a number."""
    resp = client.get("/api/analytics/cost")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["total_cost_usd"], (int, float))
