"""Tests for MCP admin endpoints (H4.7 admin-wiring).

Replaces the standalone test_mcp_endpoints.py script that required a live
server on :8000. Uses TestClient so the endpoints are covered in CI.
"""
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


@pytest.fixture(autouse=True)
def _cleanup_test_server(token_client):
    """Ensure the synthetic server is gone before and after each test."""
    token_client.delete("/api/admin/mcp/test-server", headers=HEADERS)
    yield
    token_client.delete("/api/admin/mcp/test-server", headers=HEADERS)


def test_list_returns_servers_shape(token_client):
    resp = token_client.get("/api/admin/mcp", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "servers" in data and isinstance(data["servers"], list)
    assert "total" in data and data["total"] == len(data["servers"])


def test_add_server(token_client):
    config = {"name": "test-server", "transport": "stdio", "command": "echo test", "url": None}
    resp = token_client.post("/api/admin/mcp", json=config, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json().get("ok") is True

    listing = token_client.get("/api/admin/mcp", headers=HEADERS).json()
    names = [s["name"] for s in listing["servers"]]
    assert "test-server" in names


def test_add_duplicate_conflicts(token_client):
    config = {"name": "test-server", "transport": "stdio", "command": "echo test", "url": None}
    assert token_client.post("/api/admin/mcp", json=config, headers=HEADERS).status_code == 200
    dup = token_client.post("/api/admin/mcp", json=config, headers=HEADERS)
    assert dup.status_code == 409


def test_delete_server(token_client):
    config = {"name": "test-server", "transport": "stdio", "command": "echo test", "url": None}
    token_client.post("/api/admin/mcp", json=config, headers=HEADERS)

    resp = token_client.delete("/api/admin/mcp/test-server", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json().get("ok") is True

    listing = token_client.get("/api/admin/mcp", headers=HEADERS).json()
    assert "test-server" not in [s["name"] for s in listing["servers"]]


def test_delete_nonexistent_returns_404(token_client):
    resp = token_client.delete("/api/admin/mcp/nonexistent", headers=HEADERS)
    assert resp.status_code == 404


def test_admin_guard_blocks_without_token(token_client):
    """Without the admin token the endpoint must not be reachable."""
    resp = token_client.get("/api/admin/mcp")
    assert resp.status_code in (401, 403)
