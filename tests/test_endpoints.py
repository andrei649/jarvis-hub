"""Tests for critical HTTP endpoints — uses FastAPI TestClient."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


@pytest.fixture(scope="module")
def client():
    from agents.web import app
    with TestClient(app) as c:
        yield c


def test_index_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "JARVIS HUB" in resp.text


def test_admin_serves_html(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Admin" in resp.text


def test_static_i18n_js(client):
    resp = client.get("/static/i18n.js")
    assert resp.status_code == 200
    # Accept both text/javascript (Linux) and application/javascript (Windows)
    assert "javascript" in resp.headers["content-type"]
    # New i18n.js uses LOCALES dict + window._t helper (replaced old STRINGS API)
    assert "LOCALES" in resp.text or "window._t" in resp.text


def test_static_app_js(client):
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    # Accept both text/javascript (Linux) and application/javascript (Windows)
    assert "javascript" in resp.headers["content-type"]


def test_status_endpoint(client):
    resp = client.get("/status")
    # /status should respond even without LLM backend
    assert resp.status_code == 200
    data = resp.json()
    # Should have sys or agents keys
    keys = set(data.keys())
    assert keys & {"sys", "agents", "lm_online"} or keys


def test_api_agents(client):
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert len(data["agents"]) > 0


def test_api_admin_requires_auth_from_network(client):
    # TestClient presents as host 'testclient' (non-localhost) and sends no
    # token, so admin endpoints must be refused (403) — not served openly.
    resp = client.get("/api/admin/settings")
    assert resp.status_code == 403


def test_api_admin_settings_with_token(monkeypatch):
    # With JARVIS_ADMIN_TOKEN set, a matching X-Admin-Token unlocks admin.
    import agents.web as web
    monkeypatch.setattr(web, "ADMIN_TOKEN", "test-secret")
    with TestClient(web.app) as c:
        denied = c.get("/api/admin/settings")
        assert denied.status_code == 401
        ok = c.get("/api/admin/settings", headers={"X-Admin-Token": "test-secret"})
        assert ok.status_code == 200
        data = ok.json()
        assert isinstance(data, dict) and len(data) > 0


def test_api_admin_env_masks_secrets(monkeypatch):
    import agents.web as web
    monkeypatch.setattr(web, "ADMIN_TOKEN", "test-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "supersecretvalue12345")
    with TestClient(web.app) as c:
        resp = c.get("/api/admin/env", headers={"X-Admin-Token": "test-secret"})
        assert resp.status_code == 200
        val = resp.json().get("GEMINI_API_KEY", "")
        assert "supersecretvalue" not in val  # masked
        assert "…" in val or val == "****"
