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


def test_list_row_reports_live_env_baseline_posture(token_client, monkeypatch):
    """H502 — stdio MCP servers are spawned with the allow-listed env baseline by
    default. The admin row carries that posture so the panel cannot claim a
    containment the running process is not applying: it is a live flag read per
    request, not a value stored on the server row.
    """
    config = {"name": "test-server", "transport": "stdio", "command": "echo test", "url": None}
    assert token_client.post("/api/admin/mcp", json=config, headers=HEADERS).status_code == 200

    def _row():
        listing = token_client.get("/api/admin/mcp", headers=HEADERS).json()
        return next(s for s in listing["servers"] if s["name"] == "test-server")

    # Unset -> the shipped default is containment ON.
    monkeypatch.delenv("JARVIS_MCP_STDIO_ENV_BASELINE", raising=False)
    assert _row()["env_baseline"] is True
    # The named escape hatch is visible in the panel rather than invisible.
    monkeypatch.setenv("JARVIS_MCP_STDIO_ENV_BASELINE", "0")
    assert _row()["env_baseline"] is False


def test_env_baseline_is_null_for_rows_that_spawn_no_subprocess(token_client, monkeypatch):
    """H502 repair (defect 4) — `env_baseline` describes how a subprocess is spawned, so a
    row that spawns none must not claim it. A non-stdio row is reachable from an on-disk
    config written before DRA-25 refused non-stdio at save time, and `load_from_config`
    does not filter transport; a stdio row with no `command` fails `missing_command` and
    never spawns either. Stamping True on those showed a containment badge for an HTTP
    server whose credentials live in `headers`, which the baseline never touches.
    """
    import agents.web as web

    mgr = web.orch.mcp
    added = []
    for cfg in (
        {"name": "zz-legacy-http", "transport": "streamable-http",
         "url": "https://x/mcp", "trust": "read-only"},
        {"name": "zz-nocmd", "transport": "stdio", "trust": "read-only"},
        # The third case, and the only one an owner can create today: `POST
        # /api/admin/mcp` does no command validation, so a row whose command is
        # whitespace-only or carries a shell metacharacter persists — and
        # `connect()` answers `unsafe_command` from `_command_argv()` BEFORE
        # `create_subprocess_exec`. The first cut of this test enumerated two cases
        # and stayed green while such a row reported a containment badge for a child
        # that never existed.
        {"name": "zz-unsafe-cmd", "transport": "stdio", "trust": "read-only",
         "command": "curl x ; rm -rf /"},
        {"name": "zz-blank-cmd", "transport": "stdio", "trust": "read-only",
         "command": "   "},
    ):
        from agents.core.mcp.client import MCPServer
        srv = MCPServer(
            name=cfg["name"], transport=cfg["transport"],
            command=cfg.get("command"), url=cfg.get("url"), trust=cfg["trust"],
        )
        mgr.servers[srv.name] = srv
        added.append(srv.name)
    try:
        monkeypatch.delenv("JARVIS_MCP_STDIO_ENV_BASELINE", raising=False)
        rows = {s["name"]: s for s in
                token_client.get("/api/admin/mcp", headers=HEADERS).json()["servers"]}
        assert rows["zz-legacy-http"]["env_baseline"] is None
        assert rows["zz-nocmd"]["env_baseline"] is None
        assert rows["zz-unsafe-cmd"]["env_baseline"] is None, (
            "a row whose command `connect()` refuses as unsafe still claims the badge"
        )
        assert rows["zz-blank-cmd"]["env_baseline"] is None
        # ...while a row that really is spawned still reports the live posture.
        assert token_client.post(
            "/api/admin/mcp",
            json={"name": "test-server", "transport": "stdio", "command": "echo test",
                  "url": None},
            headers=HEADERS,
        ).status_code == 200
        rows = {s["name"]: s for s in
                token_client.get("/api/admin/mcp", headers=HEADERS).json()["servers"]}
        assert rows["test-server"]["env_baseline"] is True
    finally:
        for name in added:
            mgr.servers.pop(name, None)
