"""Tests for the autonomy HTTP endpoints (H6.1+H6.2+H6.3) via TestClient."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

HEADERS = {"X-Admin-Token": "test-secret"}


@pytest.fixture(scope="module")
def token_client():
    import agents.web as web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    with TestClient(web.app) as c:
        yield c
    web.ADMIN_TOKEN = old


def test_submit_reversible_auto_approved(token_client):
    body = {"agent": "jarvis", "kind": "draft_email", "title": "Draft a reply"}
    r = token_client.post("/autonomy/tasks", json=body, headers=HEADERS)
    assert r.status_code == 200
    task = r.json()["task"]
    assert task["status"] == "approved"
    assert task["risk_tier"] == 1


def test_submit_irreversible_blocks(token_client):
    body = {"agent": "jarvis", "kind": "delete_file", "title": "Delete old logs"}
    r = token_client.post("/autonomy/tasks", json=body, headers=HEADERS)
    assert r.status_code == 200
    task = r.json()["task"]
    assert task["status"] == "blocked"
    assert task["risk_tier"] == 3


def test_decision_accept_then_listed_approved(token_client):
    sub = token_client.post(
        "/autonomy/tasks",
        json={"agent": "jarvis", "kind": "delete_file", "title": "Delete tmp"},
        headers=HEADERS,
    ).json()["task"]
    assert sub["status"] == "blocked"

    dec = token_client.post(
        f"/autonomy/tasks/{sub['id']}/decision",
        json={"action": "accept"}, headers=HEADERS,
    )
    assert dec.status_code == 200
    assert dec.json()["task"]["status"] == "approved"


def test_decision_illegal_transition_conflicts(token_client):
    # reversible task is auto-approved; rejecting an approved task is illegal
    sub = token_client.post(
        "/autonomy/tasks",
        json={"agent": "jarvis", "kind": "research_market", "title": "Research"},
        headers=HEADERS,
    ).json()["task"]
    assert sub["status"] == "approved"
    dec = token_client.post(
        f"/autonomy/tasks/{sub['id']}/decision",
        json={"action": "reject"}, headers=HEADERS,
    )
    assert dec.status_code == 409


def test_status_endpoint_shape(token_client):
    r = token_client.get("/autonomy/status", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert "stats" in data
    assert "interrupt_budget_remaining" in data
    assert isinstance(data["pending_decisions"], list)


def test_list_filter_by_status(token_client):
    r = token_client.get("/autonomy/tasks", params={"status": "blocked"}, headers=HEADERS)
    assert r.status_code == 200
    for t in r.json()["tasks"]:
        assert t["status"] == "blocked"


def test_admin_guard_blocks_without_token(token_client):
    assert token_client.get("/autonomy/tasks").status_code in (401, 403)


def test_brief_endpoint(token_client):
    r = token_client.get("/autonomy/brief", params={"kind": "morning"}, headers=HEADERS)
    assert r.status_code == 200
    assert "text" in r.json()
    assert r.json()["kind"] == "morning"
    r2 = token_client.get("/autonomy/brief", params={"kind": "evening"}, headers=HEADERS)
    assert r2.status_code == 200
    assert "Evening retro" in r2.json()["text"]


def test_preference_suggestions_endpoint(token_client):
    r = token_client.get("/autonomy/preferences/suggestions", headers=HEADERS)
    assert r.status_code == 200
    assert isinstance(r.json()["suggestions"], list)
