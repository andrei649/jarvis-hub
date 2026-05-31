"""Tests for admin charts endpoint."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


@pytest.fixture(scope="module")
def token_client():
    import agents.web as web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    with TestClient(web.app) as c:
        yield c
    web.ADMIN_TOKEN = old


def test_stats_endpoint_structure(token_client):
    """GET /api/admin/stats returns expected JSON shape."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert "overview" in data
    assert "agents" in data
    assert "daily" in data
    assert "channels" in data
    assert "error_types" in data
    ov = data["overview"]
    for key in ("total_interactions", "success_rate", "avg_latency", "agents_tracked"):
        assert key in ov


def test_stats_agents_has_expected_fields(token_client):
    """Each agent entry has expected fields."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    agents = resp.json().get("agents", [])
    if agents:
        for a in agents:
            for key in ("agent_id", "samples", "success_rate", "avg_latency"):
                assert key in a


def test_stats_daily_sorted_by_date(token_client):
    """Daily entries are sorted chronologically."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    daily = resp.json().get("daily", [])
    dates = [d["date"] for d in daily]
    assert dates == sorted(dates)


def test_stats_channels_is_dict(token_client):
    """Channels field is a dict."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    channels = resp.json().get("channels", {})
    assert isinstance(channels, dict)


def test_stats_error_types_is_list(token_client):
    """Error types is a list of [str, int] pairs."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    errors = resp.json().get("error_types", [])
    assert isinstance(errors, list)
    for item in errors:
        assert isinstance(item, list) and len(item) == 2


def test_stats_route_usage_is_dict(token_client):
    """Route usage field is present and is a dict."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert "route_usage" in data
    assert isinstance(data["route_usage"], dict)


def test_stats_cost_estimates_present(token_client):
    """Cost estimates field has expected structure."""
    resp = token_client.get("/api/admin/stats", headers={"X-Admin-Token": "test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert "cost_estimates" in data
    ce = data["cost_estimates"]
    assert "total" in ce
    assert "total_savings" in ce
    assert "total_interactions" in ce
    assert "per_model" in ce
    assert isinstance(ce["total"], (int, float))
    assert isinstance(ce["total_interactions"], int)
    assert ce["total_interactions"] >= 0
