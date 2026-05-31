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
