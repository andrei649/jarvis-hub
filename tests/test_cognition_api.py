"""Tests for H5.11 live cognition and widget endpoints."""
import pytest
import time
from fastapi.testclient import TestClient
from agents import web


@pytest.fixture
def client():
    with TestClient(web.app) as c:
        yield c


def test_cognition_endpoint_fallback(client):
    resp = client.get("/api/cognition")
    assert resp.status_code == 200
    data = resp.json()
    assert "scoring" in data
    assert "decision" in data
    assert "trace" in data
    assert isinstance(data["scoring"], list)
    assert isinstance(data["decision"], dict)
    assert data["decision"]["source"] == "standby"
    assert data["decision"]["confidence"] == 1.0


def test_oauth_status_endpoint(client):
    resp = client.get("/api/oauth/status")
    assert resp.status_code == 200
    data = resp.json()
    # verify Gmail, Google Calendar and Spotify status
    for key in ("gmail", "calendar", "spotify"):
        assert key in data
        assert "connected" in data[key]
        assert "label" in data[key]


def test_oracle_endpoints(client):
    # /api/oracle/status should return status or 503 if not initialized
    resp = client.get("/api/oracle/status")
    if resp.status_code == 200:
        data = resp.json()
        # oracle bridge returns watcher_running and last_checked
        assert "watcher_running" in data or "sync_active" in data
    else:
        assert resp.status_code == 503

    # /api/oracle/conflicts should return conflicts or 503 if not initialized
    resp_conflicts = client.get("/api/oracle/conflicts")
    if resp_conflicts.status_code == 200:
        data_c = resp_conflicts.json()
        assert "conflicts" in data_c
        assert isinstance(data_c["conflicts"], list)
    else:
        assert resp_conflicts.status_code == 503


@pytest.mark.asyncio
async def test_live_interaction_updates_cognition():
    from agents.web import orch
    if not orch:
        pytest.skip("Orchestrator not initialized in test environment")

    # Clear prior cognition data
    orch.last_cognition = None

    # Call handle_input to trigger real intent classification and timing metrics
    reply = await orch.handle_input("ce e nou pe email", channel="web")
    assert reply is not None

    # Assert last_cognition has been updated dynamically
    assert orch.last_cognition is not None
    assert "decision" in orch.last_cognition
    assert orch.last_cognition["decision"]["source"] == "keyword_match"
    assert "email" in orch.last_cognition["decision"]["agents_selected"] or "pepper" in orch.last_cognition["decision"]["agents_selected"]
    assert orch.last_cognition["decision"]["timing"]["classify"] >= 0
    assert len(orch.last_cognition["trace"]) >= 2
    assert orch.last_cognition["trace"][0]["step"] == "classify"
    assert orch.last_cognition["trace"][1]["step"] == "route"
