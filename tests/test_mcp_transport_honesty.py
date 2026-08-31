"""The MCP client surface must not advertise a transport it cannot speak (DRA-25).

`MCPServer.connect()` only implements stdio; the `sse` branch logs and returns
False. The admin API accepted `transport="sse"` anyway, persisted it, and then
answered every connect probe with `connected: true`. These tests pin the honest
behaviour: sse is rejected at the door, the connect probe reports what actually
happened, and the tool-call contract admits stdio only.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from fastapi.testclient import TestClient  # noqa: E402

import agents.web as web  # noqa: E402

_TOKEN = "mcp-honesty-token"
_HDR = {"X-Admin-Token": _TOKEN}


def _mock_orch(servers: dict | None = None) -> MagicMock:
    m = MagicMock()
    m.mcp.servers = servers if servers is not None else {}
    m.mcp.to_config = MagicMock(return_value=[])
    return m


def test_add_rejects_unsupported_transport(monkeypatch):
    orch = _mock_orch()
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", orch)
    saved: list[int] = []
    monkeypatch.setattr(web, "_save_mcp_config", lambda: saved.append(1))
    client = TestClient(web.app)
    resp = client.post(
        "/api/admin/mcp",
        json={"name": "remote", "transport": "sse", "url": "http://127.0.0.1:9/sse"},
        headers=_HDR,
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "unsupported_transport"
    assert body["transport"] == "sse"
    assert "stdio" in body["supported"]
    # Nothing registered, nothing persisted.
    assert "remote" not in orch.mcp.servers
    assert saved == []


def test_add_still_accepts_stdio(monkeypatch):
    orch = _mock_orch()
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "_save_mcp_config", lambda: None)
    client = TestClient(web.app)
    resp = client.post(
        "/api/admin/mcp",
        json={"name": "fs", "transport": "stdio", "command": "run-fs"},
        headers=_HDR,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "fs" in orch.mcp.servers


def test_connect_reports_failure_instead_of_claiming_success(monkeypatch):
    srv = MagicMock()
    srv.name = "fs"
    srv.transport = "stdio"
    srv.tools = []
    srv.connect = AsyncMock(return_value=False)
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", _mock_orch({"fs": srv}))
    client = TestClient(web.app)
    resp = client.post("/api/admin/mcp/fs/connect", headers=_HDR)
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False
    assert body["ok"] is False
    assert body["error"] == "connect_failed"


def test_tool_call_contract_denies_non_stdio_transport():
    from agents.core.mcp.client import MCPServer

    srv = MCPServer(name="legacy", transport="sse", url="http://127.0.0.1:9/sse")
    blocked = srv._tool_call_blocked("do_thing", {})
    assert blocked is not None
    assert blocked["error"]
    assert blocked["server"] == "legacy"

    ok = MCPServer(name="fs", transport="stdio", command="run-fs")
    assert ok._tool_call_blocked("do_thing", {}) is None


def test_sources_do_not_advertise_sse():
    admin_js = (repo_root / "agents/web/static/admin.js").read_text(encoding="utf-8")
    transport_rows = [ln for ln in admin_js.splitlines() if "mcp.transport" in ln]
    assert transport_rows, "mcp.transport SelectRow disappeared — update this guard"
    for line in transport_rows:
        assert "'sse'" not in line, line

    client_py = (repo_root / "agents/core/mcp/client.py").read_text(encoding="utf-8")
    header = client_py.split('"""')[1]
    # The module docstring used to read "Connects to MCP servers via stdio or SSE
    # transport." Any mention of a remote transport must now be a disclaimer.
    assert "via stdio or SSE" not in header, header
    if "SSE" in header.upper():
        assert "NOT implemented" in header, header


def test_live_docs_do_not_advertise_an_mcp_sse_transport():
    """DRA-25 remainder — the client-side surfaces beyond the module itself.

    `POST /api/admin/mcp` now refuses every non-stdio transport with 400
    `unsupported_transport`, so a reader who is told the MCP client speaks "stdio/SSE"
    is told something the product will actively reject. These are the live prose
    surfaces that carried the claim; `docs/2026-06-08-future-developments-report.md`
    is deliberately not listed — it calls the transport *unbuilt*, which is true.
    """
    surfaces = (
        "GO_LIVE_PLAN.md",
        "AI_SYSTEM_PROMPT.md",
        "docs/ARCHITECTURE.md",
        "docs/HISTORY.md",
    )
    for rel in surfaces:
        text = (repo_root / rel).read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "MCP" not in line and "mcp/" not in line:
                continue
            assert "stdio/SSE" not in line, f"{rel}:{i} {line.strip()}"
            assert "stdio or SSE" not in line, f"{rel}:{i} {line.strip()}"


def test_an_accepted_transport_is_persisted_normalised_not_raw():
    """DRA-25, found by the adversarial review of the first fix.

    The gate normalises for its own check (`transport = (req.transport or "stdio")
    .strip().lower()`) but the MCPServer was constructed from the RAW value. So
    `{"transport": "STDIO"}` passed the gate and then registered a server whose
    stored transport is not the string `connect()` dispatches on — re-creating the
    permanently-dead admin row this row exists to remove, just one case further in.
    """
    import agents.core.routers.mcp as mcp_router

    captured = {}

    class _Servers(dict):
        pass

    class _MCP:
        servers = _Servers()

    class _Orch:
        mcp = _MCP()

    body = SimpleNamespace(name="probe", transport="  STDIO  ", command="echo hi", url=None)

    async def _run():
        return await mcp_router.admin_mcp_add(body)  # type: ignore[arg-type]

    class _Web:
        @staticmethod
        def _save_mcp_config():
            captured["saved"] = True

    with mock.patch.object(mcp_router, "get_orch", lambda: _Orch()), \
         mock.patch.object(mcp_router, "_web", lambda: _Web()):
        asyncio.run(_run())

    stored = _Orch.mcp.servers.get("probe")
    assert stored is not None, "an accepted stdio config must register"
    assert stored.transport == "stdio", (
        f"persisted transport must be the normalised value the connector dispatches on, "
        f"got {stored.transport!r} — a raw spelling registers a permanently dead server"
    )
