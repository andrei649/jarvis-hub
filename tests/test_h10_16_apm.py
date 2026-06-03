"""Tests for H10.16 — APM Dashboard (org metrics)."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core import cost_tracker


@pytest.fixture(autouse=True)
def reset_cost():
    cost_tracker.reset()
    yield
    cost_tracker.reset()


# ── apm_summary aggregation (pure) ──────────────────────────────────────────

def test_apm_summary_totals_and_breakdowns():
    cost_tracker.record("jarvis", input_tokens=1000, output_tokens=500, model="gpt-4o")
    cost_tracker.record("jarvis", input_tokens=1000, output_tokens=500, model="gpt-4o")
    cost_tracker.record("friday", input_tokens=2000, output_tokens=1000, model="gpt-4o-mini")

    apm = cost_tracker.apm_summary()
    # totals
    assert apm["totals"]["runs"] == 3
    assert apm["totals"]["input_tokens"] == 4000
    assert apm["totals"]["output_tokens"] == 2000
    assert apm["totals"]["cost_usd"] > 0

    # per-agent (jarvis has 2 runs)
    by_agent = {a["agent"]: a for a in apm["by_agent"]}
    assert by_agent["jarvis"]["runs"] == 2
    assert by_agent["friday"]["runs"] == 1

    # per-model
    by_model = {m["model"]: m for m in apm["by_model"]}
    assert by_model["gpt-4o"]["runs"] == 2
    assert by_model["gpt-4o-mini"]["runs"] == 1
    # totals reconcile across models
    assert sum(m["runs"] for m in apm["by_model"]) == apm["totals"]["runs"]


def test_apm_summary_empty():
    apm = cost_tracker.apm_summary()
    assert apm["totals"]["runs"] == 0
    assert apm["by_agent"] == []
    assert apm["by_model"] == []


# ── admin endpoint ──────────────────────────────────────────────────────────

def test_apm_endpoint_requires_admin_and_returns_shape():
    from agents import web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    try:
        with TestClient(web.app) as c:
            cost_tracker.record("stark", input_tokens=500, output_tokens=200, model="gpt-4o")
            # without token → 401
            assert c.get("/api/admin/apm").status_code == 401
            # with token → 200 + shape
            resp = c.get("/api/admin/apm", headers={"X-Admin-Token": "test-secret"})
            assert resp.status_code == 200
            body = resp.json()
            assert "totals" in body and "by_agent" in body and "by_model" in body
    finally:
        web.ADMIN_TOKEN = old
