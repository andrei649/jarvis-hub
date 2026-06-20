"""Tests for GET /api/llm/status — live LM Studio controller state for the UI.

The endpoint exposes ``LMStudioController.status()`` ({online, enabled,
server_url, active_model}) so the admin Settings UI can show live controller
state. The orchestrator's controller is mocked so the test runs without a live
LM Studio / `lms` binary.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


def _ctrl(status):
    ctrl = MagicMock()
    ctrl.status = AsyncMock(return_value=status)
    return ctrl


def test_requires_admin_token(token_client):
    resp = token_client.get("/api/llm/status")
    assert resp.status_code == 401


def test_status_reflects_controller_online(token_client):
    import agents.web as web
    state = {"online": True, "enabled": True,
             "server_url": "http://localhost:1234", "active_model": "google/gemma-4-12b"}
    with patch.object(web, "orch", MagicMock(lmstudio=_ctrl(state))):
        resp = token_client.get("/api/llm/status", headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json() == state


def test_status_reflects_controller_offline(token_client):
    import agents.web as web
    state = {"online": False, "enabled": False,
             "server_url": "http://localhost:1234", "active_model": None}
    with patch.object(web, "orch", MagicMock(lmstudio=_ctrl(state))):
        resp = token_client.get("/api/llm/status", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["online"] is False
    assert data["enabled"] is False
    assert data["active_model"] is None


def test_status_shape_has_all_keys(token_client):
    import agents.web as web
    state = {"online": True, "enabled": True,
             "server_url": "http://localhost:1234", "active_model": "m/x"}
    with patch.object(web, "orch", MagicMock(lmstudio=_ctrl(state))):
        resp = token_client.get("/api/llm/status", headers=HEADERS)

    data = resp.json()
    assert set(data) >= {"online", "enabled", "server_url", "active_model"}


def test_status_503_when_controller_unavailable(token_client):
    import agents.web as web
    # Orchestrator present but no LM Studio controller wired (still booting).
    with patch.object(web, "orch", MagicMock(lmstudio=None)):
        resp = token_client.get("/api/llm/status", headers=HEADERS)

    assert resp.status_code == 503
    assert "error" in resp.json()


def test_status_degrades_when_status_raises(token_client):
    import agents.web as web
    ctrl = MagicMock(enabled=True, server_url="http://localhost:1234")
    ctrl.status = AsyncMock(side_effect=RuntimeError("probe blew up"))
    with patch.object(web, "orch", MagicMock(lmstudio=ctrl)):
        resp = token_client.get("/api/llm/status", headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["online"] is False
    assert data["active_model"] is None
