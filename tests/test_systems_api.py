"""Tests for SystemsPanel live data endpoints."""
import pytest
from fastapi.testclient import TestClient
from agents import web

client = TestClient(web.app)


def test_learning_stats_endpoint():
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


def test_memory_stats_endpoint():
    from fastapi.testclient import TestClient
    from agents import web
    client = TestClient(web.app)
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


def test_plugins_endpoint():
    resp = client.get("/plugins")
    assert resp.status_code == 200
    data = resp.json()
    assert "plugins" in data
    assert isinstance(data["plugins"], list)


def test_bench_stats_endpoint():
    resp = client.get("/bench/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "latency" in data
    assert "throughput" in data
    assert "by_agent" in data


def test_security_status_endpoint():
    resp = client.get("/security/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "guardrails" in data
    assert "scanners" in data
    assert "ssrf" in data


def test_agent_soul_endpoint():
    resp = client.get("/api/agents/jarvis/soul")
    assert resp.status_code == 200
    data = resp.json()
    assert "agent_id" in data
    assert "soul" in data
    assert "Prime Orchestrator" in data["soul"]


def test_plugin_toggle_endpoint():
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
