"""Tests for memory recall endpoints."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

import pytest
from fastapi.testclient import TestClient

@pytest.fixture(scope="module")
def client():
    from agents.web import app
    with TestClient(app) as c:
        yield c

def test_memory_profile_returns_dict(client):
    resp = client.get("/api/memory/profile")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_memory_recall_empty_query(client):
    resp = client.get("/api/memory/recall")
    assert resp.status_code == 200
    assert resp.json()["results"] == []

def test_memory_recall_with_query(client):
    resp = client.get("/api/memory/recall?q=test")
    assert resp.status_code == 200
    assert "results" in resp.json()

def test_model_tiers_endpoint(client):
    resp = client.get("/api/analytics/model-tiers")
    assert resp.status_code == 200
    data = resp.json()
    assert "tiers" in data
    assert "total_cost_usd" in data
    assert set(data["tiers"].keys()) == {"local", "fast", "standard", "heavy"}

def test_cost_endpoint_still_works(client):
    resp = client.get("/api/analytics/cost")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data and "total_cost_usd" in data
