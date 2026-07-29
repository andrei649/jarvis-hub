"""Tests for H5.11 live cognition and widget endpoints."""
import pytest
import time
from fastapi.testclient import TestClient
from agents import web


@pytest.fixture
def client():
    with TestClient(web.app) as c:
        yield c


def test_cognition_endpoint_is_honestly_empty_before_any_request(client):
    """No request routed yet → empty, and SAID to be empty.

    This endpoint used to manufacture a cognition context out of the first five
    ``INTENT_RULES`` entries plus a ``decision`` with ``confidence: 1.0`` and
    ``agents_selected: ["jarvis"]``. The HUD rendered that as "ROUTING DECISION /
    STANDBY / Confidence 100%" with weight bars for keywords the owner had never
    typed — a routing decision the router never made. The previous version of this
    test asserted that fabrication (``confidence == 1.0``), so the gate protected
    the bug.
    """
    resp = client.get("/api/cognition")
    assert resp.status_code == 200
    data = resp.json()

    assert data["scoring"] == []
    assert data["decision"] is None
    assert data["trace"] == []
    # The two fields that let a caller tell "nothing happened" from "here is what happened".
    assert data["live"] is False
    assert data["state"] in ("no-request-routed-yet", "starting")


def test_cognition_endpoint_marks_a_real_context_live(client, monkeypatch):
    """A real recorded context passes through untouched, flagged live."""
    real = {
        "scoring": [{"keyword": "weather", "weight": 0.8, "agents": ["jarvis"],
                     "category": "info"}],
        "decision": {"source": "keyword", "confidence": 0.8,
                     "agents_selected": ["jarvis"], "alternatives": [],
                     "timing": {"classify": 3, "route": 1, "total": 4}},
        "trace": [{"step": "classify", "duration_ms": 3, "result": "keyword"}],
    }
    monkeypatch.setattr(web.orch, "last_cognition", real, raising=False)
    data = client.get("/api/cognition").json()
    assert data["live"] is True
    assert data["state"] == "last-request"
    assert data["decision"]["confidence"] == 0.8
    assert data["scoring"] == real["scoring"]


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
