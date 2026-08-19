"""MCP (Model Context Protocol) endpoints — extracted from web.py (CLN-3).

Two surfaces:
- **Admin client management** (`/api/admin/mcp*`): list/add/remove/connect/disconnect the
  MCP *client* servers Jarvis talks out to (over `orch.mcp`).
- **Server mode** (H10.5) + **OAuth resource server** (H16.1): `/api/mcp/server` status,
  `/.well-known/oauth-protected-resource`, `/api/mcp/token`, and `/api/mcp/server/rpc` (the
  JSON-RPC HTTP transport — disabled by default, with the #294 HF-1 transport-auth gate).

The stateful / app-coupled machinery STAYS in web.py and is reached at request time via
`sys.modules` (no import cycle, monkeypatch-observable):
- the route-tool builders (`_build_mcp_server` / `_build_mcp_route_tools`) — they introspect
  `app.routes`, so they're tied to the web module;
- the OAuth resource-server singleton (`_mcp_rs` / `_get_mcp_rs`) — `test_h16_1_mcp_oauth`
  rebinds `web._mcp_rs`;
- the MCP config persistence pair (`_save_mcp_config` / `_load_mcp_config`, lifespan-coupled);
- the user-auth layer the RPC gate consults (`USER_TOKEN`, `_request_is_authed`,
  `_real_client_host`, `_LOCALHOSTS`).
The orchestrator is reached via `get_orch()`.
"""

import logging
import sys
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.web")

router = APIRouter(tags=["mcp"])


def _web():
    # MCP server builders, the OAuth RS singleton (test-rebound), config persistence and
    # the user-auth layer stay in web.py; resolve them at request time, not import time.
    return sys.modules.get("agents.web")


def _mcp_resource(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/api/mcp/server"


# ── MCP admin (client servers) ───────────────────────────────────

@router.get("/api/admin/mcp", dependencies=[Depends(admin_guard)])
async def admin_mcp_list():
    """List all configured MCP servers with their status."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    servers = []
    for name, srv in orch.mcp.servers.items():
        servers.append({
            "name": name,
            "transport": srv.transport,
            "command": srv.command,
            "url": srv.url,
            "connected": srv._proc is not None and srv._proc.returncode is None,
            "tools_count": len(srv.tools),
            "tools": [{"name": t.name, "description": t.description} for t in srv.tools],
        })
    return {"servers": servers, "total": len(servers)}


class MCPServerConfig(BaseModel):
    name: str
    transport: str = "stdio"
    command: Optional[str] = None
    url: Optional[str] = None


@router.post("/api/admin/mcp", dependencies=[Depends(admin_guard)])
async def admin_mcp_add(req: MCPServerConfig):
    """Add a new MCP server configuration."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from core.mcp.client import MCPServer
    if req.name in orch.mcp.servers:
        return JSONResponse({"error": f"MCP server '{req.name}' already exists"}, status_code=409)
    srv = MCPServer(
        name=req.name,
        transport=req.transport,
        command=req.command,
        url=req.url,
    )
    orch.mcp.servers[srv.name] = srv
    # Persist to settings DB
    _web()._save_mcp_config()
    return {"ok": True, "server": req.name, "message": f"MCP server '{req.name}' added"}


@router.delete("/api/admin/mcp/{name}", dependencies=[Depends(admin_guard)])
async def admin_mcp_remove(name: str):
    """Remove an MCP server configuration."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if name not in orch.mcp.servers:
        return JSONResponse({"error": f"MCP server '{name}' not found"}, status_code=404)
    srv = orch.mcp.servers[name]
    if srv._proc:
        await srv.close()
    del orch.mcp.servers[name]
    # Persist to settings DB
    _web()._save_mcp_config()
    return {"ok": True, "server": name, "message": f"MCP server '{name}' removed"}


@router.post("/api/admin/mcp/{name}/connect", dependencies=[Depends(admin_guard)])
async def admin_mcp_connect(name: str):
    """Connect to an MCP server and discover tools."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if name not in orch.mcp.servers:
        return JSONResponse({"error": f"MCP server '{name}' not found"}, status_code=404)
    srv = orch.mcp.servers[name]
    try:
        await srv.connect()
        return {
            "ok": True,
            "server": name,
            "connected": True,
            "tools_count": len(srv.tools),
            "tools": [{"name": t.name, "description": t.description} for t in srv.tools],
        }
    except Exception:
        from core.log_safe import log_safe
        logger.exception("MCP server probe failed: %s", log_safe(name))
        return JSONResponse({"error": "internal error", "server": name, "code": 500}, status_code=500)


@router.post("/api/admin/mcp/{name}/disconnect", dependencies=[Depends(admin_guard)])
async def admin_mcp_disconnect(name: str):
    """Disconnect from an MCP server."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if name not in orch.mcp.servers:
        return JSONResponse({"error": f"MCP server '{name}' not found"}, status_code=404)
    srv = orch.mcp.servers[name]
    if srv._proc:
        await srv.close()
        return {"ok": True, "server": name, "message": f"MCP server '{name}' disconnected"}
    return {"ok": True, "server": name, "message": f"MCP server '{name}' was not connected"}


# ── MCP server mode (H10.5) + OAuth resource server (H16.1) ───────

@router.get("/api/mcp/server")
async def mcp_server_status():
    """Status + governed tool list for Jarvis's MCP server mode (H10.5)."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    enabled = bool(orch.get_setting("mcp.server_enabled", False))
    status = _web()._build_mcp_server().status()
    status["enabled"] = enabled
    return nocache_json(status)


@router.get("/.well-known/oauth-protected-resource")
async def mcp_protected_resource_metadata(request: Request):
    """RFC 9728 — lets MCP clients discover the authorization server(s)."""
    from agents.core.mcp.oauth import protected_resource_metadata
    orch = get_orch()
    resource = _mcp_resource(request)
    auth_servers = []
    if orch:
        configured = orch.get_setting("mcp.authorization_servers", None)
        if isinstance(configured, list):
            auth_servers = configured
    return nocache_json(protected_resource_metadata(resource, auth_servers or [resource]))


@router.post("/api/mcp/token", dependencies=[Depends(admin_guard)])
async def mcp_issue_token(req: Request):
    """Issue a local LAN-only bearer token bound to this MCP resource (admin)."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    resource = _mcp_resource(req)
    scopes = (body or {}).get("scopes") or ["mcp"]
    # A typo'd ttl is a client error, not a server error. Bare int() on request
    # data raised ValueError/TypeError straight out of the handler as a 500.
    try:
        ttl = int((body or {}).get("ttl", 3600))
    except (TypeError, ValueError):
        return JSONResponse({"error": "ttl must be an integer number of seconds"},
                            status_code=400)
    if ttl <= 0:
        return JSONResponse({"error": "ttl must be positive"}, status_code=400)
    token = _web()._get_mcp_rs().issue_token(
        subject=(body or {}).get("subject", "local-client"),
        resource=resource, scopes=scopes, ttl=ttl)
    return nocache_json({"ok": True, "token": token, "resource": resource, "scopes": scopes})


@router.post("/api/mcp/server/rpc")
async def mcp_server_rpc(message: dict, request: Request):
    """JSON-RPC 2.0 entry point (HTTP transport). Disabled by default; LAN-only.

    When ``mcp.oauth_required`` is set, requires an OAuth 2.1 bearer token bound to
    this resource (RFC 8707) with the ``mcp`` scope.
    """
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    if not bool(orch.get_setting("mcp.server_enabled", False)):
        return nocache_json(
            {"error": "MCP server mode disabled (set mcp.server_enabled)"},
            status_code=403,
        )
    w = _web()
    verified_identity = None
    if bool(orch.get_setting("mcp.oauth_required", False)):
        from agents.core.mcp.oauth import MCPResourceServer
        from agents.core.mcp.server import VerifiedMCPIdentity
        resource = _mcp_resource(request)
        result = w._get_mcp_rs().validate(
            request.headers.get("authorization", ""), resource, required_scope="mcp")
        if not result["ok"]:
            return JSONResponse(
                {"error": f"unauthorized: {result['error']}"}, status_code=401,
                headers={"WWW-Authenticate": MCPResourceServer.challenge(resource)})
        verified_identity = VerifiedMCPIdentity(
            subject=str((result.get("claims") or {}).get("sub") or "").strip()
        )
        if not verified_identity.subject:
            return JSONResponse(
                {"error": "unauthorized: OAuth subject required"}, status_code=401,
                headers={"WWW-Authenticate": MCPResourceServer.challenge(resource)})
    else:
        # SEC (review F1/F2, #294): with OAuth off, the MCP transport must enforce the
        # SAME posture as every other user route (HF-1) — a matching user/admin token if
        # JARVIS_USER_TOKEN is set, else localhost-only (fail closed behind an untrusted
        # proxy, HF-7). Without this gate a REMOTE caller could reach the read tools
        # (dashboard/memory) over the MCP transport even though the HTTP routes are guarded.
        if w.USER_TOKEN:
            if not w._request_is_authed(request):
                return JSONResponse(
                    {"error": "unauthorized: user token required"}, status_code=401)
        elif w._real_client_host(request) not in w._LOCALHOSTS:
            return JSONResponse(
                {"error": "MCP server disabled from network — set JARVIS_USER_TOKEN to enable remote access"},
                status_code=403,
            )
    # Thread the caller's user identity (same header user_guard reads) into the server
    # so MUTATING route tools can enforce the per-identity gate. An admin token also
    # satisfies the user gate (admin ⊇ user).
    identity = verified_identity or (
        request.headers.get("x-user-token") or request.headers.get("x-admin-token")
    )
    response = await w._build_mcp_server().handle(message, identity=identity)
    # JSON-RPC notifications produce no response body.
    return nocache_json(response if response is not None else {"ok": True})
