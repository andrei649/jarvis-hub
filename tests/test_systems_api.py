"""Tests for SystemsPanel live data endpoints."""
import pytest
from fastapi.testclient import TestClient
from agents import web


@pytest.fixture
def client():
    with TestClient(web.app) as c:
        yield c


def test_learning_stats_endpoint(client):
    resp = client.get("/learning/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "interactions_total" in data
    assert "success_rate" in data
    assert "prompt_optimizations" in data
    assert "promotion_candidates" in data
    assert "demotion_warnings" in data
    assert isinstance(data["interactions_total"], int)
    assert isinstance(data["success_rate"], (int, float))
    assert isinstance(data["prompt_optimizations"], list)
    assert isinstance(data["promotion_candidates"], list)
    assert isinstance(data["demotion_warnings"], list)


def test_memory_stats_endpoint(client):
    resp = client.get("/memory/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data
    assert "vectors" in data
    assert "knowledge_graph" in data
    assert "agent_contexts" in data
    assert isinstance(data["agent_contexts"], dict)
    assert isinstance(data["sessions"]["total"], int)
    assert isinstance(data["vectors"]["stored"], int)


def test_plugins_endpoint(client):
    resp = client.get("/plugins")
    assert resp.status_code == 200
    data = resp.json()
    assert "plugins" in data
    assert isinstance(data["plugins"], list)


def test_bench_stats_endpoint(client):
    resp = client.get("/bench/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "latency" in data
    assert "throughput" in data
    assert "by_agent" in data


def test_security_status_endpoint(client):
    resp = client.get("/security/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "guardrails" in data
    assert "scanners" in data
    assert "ssrf" in data


def test_agent_soul_endpoint(client):
    resp = client.get("/api/agents/jarvis/soul")
    assert resp.status_code == 200
    data = resp.json()
    assert "agent_id" in data
    assert "soul" in data
    assert "Prime Orchestrator" in data["soul"]


def test_plugin_toggle_endpoint(client):
    get_resp = client.get("/plugins")
    assert get_resp.status_code == 200
    plugins = get_resp.json()["plugins"]
    if plugins:
        plugin_id = plugins[0]["id"]
        initial_enabled = plugins[0]["enabled"]

        # Toggle once
        toggle_resp = client.put(f"/plugins/{plugin_id}/toggle")
        assert toggle_resp.status_code == 200
        assert toggle_resp.json()["id"] == plugin_id
        assert toggle_resp.json()["enabled"] == (not initial_enabled)

        # Toggle back
        toggle_back = client.put(f"/plugins/{plugin_id}/toggle")
        assert toggle_back.status_code == 200
        assert toggle_back.json()["enabled"] == initial_enabled


def test_service_worker_endpoint(client):
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert "application/javascript" in resp.headers.get("content-type", "")
    content = resp.text
    # Match the versioned cache prefix so intentional cache-version bumps
    # (which invalidate stale/corrupted cached assets) don't break this test.
    assert "jarvis-hud-v" in content
    assert "STATIC_ASSETS" in content


def test_agent_history_unknown_agent_404(client):
    """API honesty: an unknown agent 404s on /history, consistent with /soul —
    not a misleading 200 + empty runs (found by running the app, 2026-06-10)."""
    r = client.get("/api/agents/definitely-not-an-agent/history")
    assert r.status_code == 404


def test_agent_history_known_agent_200(client):
    r = client.get("/api/agents/jarvis/history")
    assert r.status_code == 200
    assert r.json()["agent_id"] == "jarvis"


def test_promote_unknown_bench_is_not_ok(client, monkeypatch):
    """Promoting a nonexistent bench agent must not report success — it returns
    404 / ok:false, not the old {ok:true, promoted:false} that lied to the UI."""
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm")
    r = client.post("/learning/promote", json={"bench_agent": "nobody-here"},
                    headers={"X-Admin-Token": "adm"})
    assert r.status_code == 404
    assert r.json()["ok"] is False
