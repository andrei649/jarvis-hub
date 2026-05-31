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
