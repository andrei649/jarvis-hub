"""HTTP integration tests for admin MCP management endpoints.

Covers:
  GET    /api/admin/mcp              — list configured servers
  POST   /api/admin/mcp              — add server config (409 on duplicate)
  DELETE /api/admin/mcp/{name}       — remove server (404 if missing)
  POST   /api/admin/mcp/{name}/connect    — connect + tool discovery
  POST   /api/admin/mcp/{name}/disconnect — disconnect
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web

_TOKEN = "mcp-test-token"
_HDR = {"X-Admin-Token": _TOKEN}


def _make_server(name: str, connected: bool = False, tools: list | None = None) -> MagicMock:
    srv = MagicMock()
    srv.name = name
    srv.transport = "stdio"
    srv.command = f"run-{name}"
    srv.url = None
    if connected:
        srv._proc = MagicMock()
        srv._proc.returncode = None
    else:
        srv._proc = None
    srv.tools = tools or []
    srv.connect = AsyncMock()
    srv.close = AsyncMock()
    return srv


def _mock_orch(servers: dict | None = None) -> MagicMock:
    m = MagicMock()
    m.mcp.servers = servers if servers is not None else {}
    m.mcp.to_config = MagicMock(return_value=[])
    return m


# ---------------------------------------------------------------------------
# GET /api/admin/mcp
# ---------------------------------------------------------------------------

def test_mcp_list_returns_servers_and_total(monkeypatch):
    srv = _make_server("filesystem", connected=True)
    srv.tools = [MagicMock(name="read_file", description="Read a file")]
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch({"filesystem": srv}))
    client = TestClient(web.app)
    resp = client.get("/api/admin/mcp", headers=_HDR)
    assert resp.status_code == 200
    data = resp.json()
    assert "servers" in data
    assert "total" in data
    assert data["total"] == 1


def test_mcp_list_empty_servers(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch({}))
    client = TestClient(web.app)
    resp = client.get("/api/admin/mcp", headers=_HDR)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["servers"] == []


def test_mcp_list_server_has_expected_fields(monkeypatch):
    srv = _make_server("memory")
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch({"memory": srv}))
    client = TestClient(web.app)
    item = client.get("/api/admin/mcp", headers=_HDR).json()["servers"][0]
    for field in ("name", "transport", "command", "url", "connected", "tools_count", "tools"):
        assert field in item, f"Missing field: {field}"


def test_mcp_list_requires_auth(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    client = TestClient(web.app)
    resp = client.get("/api/admin/mcp")
    assert resp.status_code == 401


def test_mcp_list_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.get("/api/admin/mcp", headers=_HDR)
    assert resp.status_code == 503


def test_mcp_add_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.post("/api/admin/mcp", json={"name": "x"}, headers=_HDR)
    assert resp.status_code == 503


def test_mcp_delete_no_orch_returns_503(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.delete("/api/admin/mcp/x", headers=_HDR)
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /api/admin/mcp
# ---------------------------------------------------------------------------

def test_mcp_add_new_server_returns_ok(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch({}))
    patch_save_mcp(monkeypatch)
    client = TestClient(web.app)
    resp = client.post(
        "/api/admin/mcp",
        json={"name": "git", "transport": "stdio", "command": "git-mcp"},
        headers=_HDR,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["server"] == "git"


def test_mcp_add_duplicate_returns_409(monkeypatch):
    srv = _make_server("git")
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch({"git": srv}))
    patch_save_mcp(monkeypatch)
    client = TestClient(web.app)
    resp = client.post(
        "/api/admin/mcp",
        json={"name": "git", "transport": "stdio", "command": "git-mcp"},
        headers=_HDR,
    )
    assert resp.status_code == 409
    assert "already exists" in resp.json()["error"]


# ---------------------------------------------------------------------------
# DELETE /api/admin/mcp/{name}
# ---------------------------------------------------------------------------

def test_mcp_delete_existing_server(monkeypatch):
    srv = _make_server("notes")
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch({"notes": srv}))
    patch_save_mcp(monkeypatch)
    client = TestClient(web.app)
    resp = client.delete("/api/admin/mcp/notes", headers=_HDR)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["server"] == "notes"


def test_mcp_delete_unknown_returns_404(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch({}))
    patch_save_mcp(monkeypatch)
    client = TestClient(web.app)
    resp = client.delete("/api/admin/mcp/ghost", headers=_HDR)
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"]


# ---------------------------------------------------------------------------
# POST /api/admin/mcp/{name}/connect
# ---------------------------------------------------------------------------

def test_mcp_connect_unknown_returns_404(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch({}))
    client = TestClient(web.app)
    resp = client.post("/api/admin/mcp/ghost/connect", headers=_HDR)
    assert resp.status_code == 404


def test_mcp_connect_calls_srv_connect(monkeypatch):
    srv = _make_server("filesystem")
    srv.tools = []
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch({"filesystem": srv}))
    client = TestClient(web.app)
    resp = client.post("/api/admin/mcp/filesystem/connect", headers=_HDR)
    assert resp.status_code == 200
    srv.connect.assert_called_once()
    assert resp.json()["ok"] is True
    assert resp.json()["server"] == "filesystem"


# ---------------------------------------------------------------------------
# POST /api/admin/mcp/{name}/disconnect
# ---------------------------------------------------------------------------

def test_mcp_disconnect_unknown_returns_404(monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch({}))
    client = TestClient(web.app)
    resp = client.post("/api/admin/mcp/ghost/disconnect", headers=_HDR)
    assert resp.status_code == 404


def test_mcp_disconnect_calls_srv_close(monkeypatch):
    srv = _make_server("filesystem", connected=True)
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch({"filesystem": srv}))
    client = TestClient(web.app)
    resp = client.post("/api/admin/mcp/filesystem/disconnect", headers=_HDR)
    assert resp.status_code == 200
    srv.close.assert_called_once()
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# Helper: suppress _save_mcp_config DB writes in tests
# ---------------------------------------------------------------------------

def patch_save_mcp(monkeypatch):
    monkeypatch.setattr(web, "_save_mcp_config", lambda: None)
