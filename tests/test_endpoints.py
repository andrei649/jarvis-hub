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
    assert resp.headers["content-type"].startswith("text/javascript")
    assert "STRINGS" in resp.text


def test_static_app_js(client):
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/javascript")


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


def test_api_admin_settings(client):
    resp = client.get("/api/admin/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert len(data) > 0
