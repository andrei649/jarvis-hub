"""MCP (Model Context Protocol) endpoints — extracted from web.py (CLN-3).

Two surfaces:
- **Admin client management** (`/api/admin/mcp*`): list/add/remove/connect/disconnect the
  MCP *client* servers Jarvis talks out to (over `orch.mcp`).
- **Catalog and sign-in** (G9: H549, H550, H692): browse the vendored Hermes MCP catalog,
  preview exactly what an install would run, install it through the same add path (managed
  gate, safe mode, load set) only with the owner's confirmation of that plan, and sign in to
  an OAuth-protected HTTP server (``agents/core/mcp/oauth_client.py``); the browser's
  callback lands on ``/api/oauth/mcp/callback`` (``routers/oauth.py``) or is relayed here.
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
from contextlib import suppress
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard
from agents.core.security.auth_audit import submit_auth_event
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.web")

router = APIRouter(tags=["mcp"])


def _web():
    # MCP server builders, the OAuth RS singleton (test-rebound), config persistence and
    # the user-auth layer stay in web.py; resolve them at request time, not import time.
    return sys.modules.get("agents.web")


def _mcp_resource(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/api/mcp/server"


def _audit_mcp_auth(request: Request, *, success: bool, reason: str) -> None:
    """Record the transport decision without retaining credential or RPC values."""
    # An unavailable audit queue cannot change the transport decision.
    with suppress(Exception):
        submit_auth_event(
            "auth_success" if success else "auth_failure",
            tier="user", reason=reason,
            client=request.client.host if request.client else "",
            surface="mcp",
        )


# ── MCP admin (client servers) ───────────────────────────────────

@router.get("/api/admin/mcp", dependencies=[Depends(admin_guard)])
async def admin_mcp_list():
    """List all configured MCP servers with their status."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from agents.core.mcp.client import TRANSPORT_STDIO, stdio_env_baseline_enabled
    # H502 — the live FLAG, read per request. Stated precisely, because the first
    # wording ("so the admin panel can never claim a hardening the running process is
    # not applying") claimed more than this is: `_merged_env()` runs once, at connect
    # time, while this row is evaluated per request. Clear the flag after a server
    # connected under it and the row reports the new value for a child that was
    # spawned under the old one. Nothing in production mutates `os.environ` after
    # boot except one diagnostic harness, so the divergence is not reachable today —
    # but the field describes the host's posture for the NEXT spawn, not the
    # environment the running child actually holds, and saying otherwise is the kind
    # of claim this slice exists to stop making.
    env_baseline = stdio_env_baseline_enabled()
    servers = []
    for name, srv in orch.mcp.servers.items():
        servers.append({
            "name": name,
            "transport": srv.transport,
            "command": srv.command,
            "url": srv.url,
            "connected": srv._proc is not None and srv._proc.returncode is None,
            # True → the next spawn of this server gets the allow-listed env baseline
            # plus its own `env` only; False → it inherits the hub's whole
            # environment; None → the field does not apply, because this row spawns no
            # subprocess at all. Stamping True there would show a containment badge
            # for an HTTP server whose credentials live in `headers`, which the
            # baseline never touches.
            #
            # Three ways a row spawns nothing, not two. The first cut enumerated a
            # non-stdio server (persisted before DRA-25 refused them) and a stdio row
            # with no `command` — and missed the one an owner can create today:
            # `POST /api/admin/mcp` does no command validation, so a row with a
            # whitespace-only command or a shell metacharacter in it persists, and
            # `connect()` answers `unsafe_command` from `_command_argv()` BEFORE
            # `create_subprocess_exec`. Such a row reported `env_baseline: true` for a
            # child that never existed. `_command_argv()` is the same check `connect`
            # makes, so the row and the spawn cannot disagree.
            "env_baseline": (
                env_baseline
                if (srv.transport == TRANSPORT_STDIO and srv.command
                    and srv._command_argv())
                else None
            ),
            # Hermes absorption 4b — the owner's trust tier for this server and, per tool,
            # whether the server itself declared it read-only (the only claim a read-only
            # tier honours).
            "trust": _trust_of(srv),
            "tools_allow": _patterns_of(srv, "tools_allow"),
            "tools_deny": _patterns_of(srv, "tools_deny"),
            "tools_count": len(srv.tools),
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "read_only": getattr(t, "read_only", None) is True,
                }
                for t in srv.tools
            ],
            # H552 — the resource/prompt tools this server's capabilities admit.
            "resource_tools": [t.name for t in getattr(srv, "utility_tools", [])],
            # H556 — connection health (state, retries, last error, next retry) and the
            # H553 sampling/elicitation counters; H553 — the owner's settings for both.
            "health": _health_of(srv),
            "sampling": _config_of(srv, "sampling"),
            "elicitation": _config_of(srv, "elicitation"),
            # G9 — how it signs in, where it came from, and which of its secrets are set
            # (names only; a value never leaves the store).
            **_g9_row(srv),
        })
    from agents.core import load_set

    host = getattr(orch.mcp, "host", None)
    budget = getattr(host, "budget", None)
    # H285: the saved servers the load set switched off, and what it names that is not saved.
    return {"servers": servers, "total": len(servers), "load_set": load_set.status("mcp"),
            "sampling_budget": _safe_call(getattr(budget, "status", None)),
            "pending_elicitations": _safe_call(getattr(host, "pending_elicitations", None)) or []}


def _safe_call(fn):
    try:
        return fn() if callable(fn) else None
    except Exception:
        return None


def _health_of(srv) -> Optional[dict]:
    health = getattr(srv, "health", None)
    status = _safe_call(getattr(health, "status", None))
    if isinstance(status, dict):
        status["connected"] = bool(_safe_call(getattr(srv, "is_connected", None)))
    return status


def _config_of(srv, attr: str) -> Optional[dict]:
    return _safe_call(getattr(getattr(srv, attr, None), "to_config", None))


def _trust_of(srv) -> Optional[str]:
    trust = getattr(srv, "trust", None)
    return trust if isinstance(trust, str) else None


def _patterns_of(srv, attr: str) -> Optional[list]:
    value = getattr(srv, attr, None)
    return list(value) if isinstance(value, (list, tuple)) else None


class MCPServerConfig(BaseModel):
    name: str
    transport: str = "stdio"
    command: Optional[str] = None
    url: Optional[str] = None
    #: Trust tier: ``read-only`` (default — only tools the server marks ``readOnlyHint``
    #: may be called) or ``full``.
    trust: str = "read-only"
    #: Glob patterns on tool names: ``tools_allow`` (None = every tool) and ``tools_deny``
    #: (a deny always wins). Attaching a server is not attaching every one of its tools.
    tools_allow: Optional[list[str]] = None
    tools_deny: Optional[list[str]] = None
    #: H553 — may this server ask Nerva for a model completion: ``off`` (default), ``ask``
    #: (an approval card per request) or ``auto`` (inside the budget and rate limit).
    sampling: Optional[str] = None
    #: H553 — may this server ask the owner for input (always as an approval card).
    elicitation: Optional[bool] = None
    #: G9 — ``oauth``: an HTTP server that needs a sign-in before it connects.
    auth: Optional[str] = None
    #: G9 / H550 — a pre-registered OAuth client for a server without dynamic registration:
    #: ``client_id``, ``scope`` and ``client_secret`` only. The secret goes to the encrypted
    #: store (``mcp.secret.<name>.OAUTH_CLIENT_SECRET``); the config keeps a reference.
    oauth: Optional[dict[str, str]] = None


class ElicitationAnswer(BaseModel):
    content: dict


def _held_refusal(name: str):
    """H285: a saved server the load set switched off is not in the manager. Adding one
    of that name would duplicate it, and removing it would do nothing the owner can see:
    both refuse and name the list."""
    held = getattr(_web(), "mcp_held_names", None)
    if held is None or name not in held():
        return None
    return JSONResponse(
        {"error": "switched_off",
         "message": f"MCP server '{name}' is saved but switched off by the load set "
                    "(loadset.mcp_disabled / loadset.mcp_only); change the list and restart"},
        status_code=409,
    )


async def _managed_refusal():
    """G1 — the saved MCP server list is configuration: when the administrator pinned
    ``mcp.servers`` (or managed mode is on, or the managed configuration cannot be read),
    an add or a remove is refused before the live manager changes. 409, audited."""
    import asyncio

    from agents.core.managed_scope import ANY, ManagedRefused, audit_refusal, check_setting_write

    try:
        check_setting_write("mcp", "servers", ANY)
    except ManagedRefused as exc:
        await asyncio.to_thread(audit_refusal, exc, "mcp servers")
        return JSONResponse(exc.payload(), status_code=409)
    return None


def _safe_mode_refusal():
    """H275: in safe mode the saved servers are not loaded, so an add or a remove would
    rewrite the saved list from an empty manager. Both refuse until a normal boot."""
    from agents.core import safe_mode

    if not safe_mode.enabled():
        return None
    return JSONResponse(
        {"error": safe_mode.REASON,
         "message": "MCP servers cannot be added or removed in safe mode; restart normally first"},
        status_code=409,
    )


@router.post("/api/admin/mcp", dependencies=[Depends(admin_guard)])
async def admin_mcp_add(req: MCPServerConfig):
    """Add a new MCP server configuration."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    refusal = _safe_mode_refusal() or _held_refusal(req.name) or await _managed_refusal()
    if refusal is not None:
        return refusal
    from core.mcp.client import TRUST_TIERS, MCPServer, normalize_trust, tool_patterns_over_bounds

    # stdio is the only transport MCPServer.connect() actually speaks. Accepting
    # an "sse" config used to register + persist a server that could never
    # connect, so the admin list showed a permanently dead row. Reject it here,
    # before anything is written (DRA-25).
    from core.mcp.http_transport import normalize_transport, validate_mcp_url
    transport = normalize_transport((req.transport or "stdio").strip().lower())
    if transport not in ("stdio", "streamable-http"):
        return JSONResponse(
            {"error": "unsupported_transport", "transport": req.transport,
             "supported": ["stdio", "streamable-http"]},
            status_code=400,
        )
    if transport == "streamable-http":
        # G9: the client speaks Streamable HTTP (still armed by JARVIS_MCP_HTTP_CLIENT at
        # connect). The URL is checked here so a bad one is never saved.
        problem = validate_mcp_url(req.url)
        if problem:
            return JSONResponse({"error": "invalid_url", "reason": problem}, status_code=400)
    trust = normalize_trust(getattr(req, "trust", "read-only"))
    if trust is None:
        return JSONResponse(
            {"error": "invalid_trust", "trust": req.trust, "supported": list(TRUST_TIERS)},
            status_code=400,
        )
    for field in ("tools_allow", "tools_deny"):
        patterns = getattr(req, field, None)
        # Over the 64-pattern / 128-char bounds is refused, not trimmed: a trimmed
        # filter differs from what was sent, and a trimmed deny shows the tool it named.
        if patterns is not None and (
            not isinstance(patterns, list)
            or not all(isinstance(p, str) and p.strip() for p in patterns)
            or tool_patterns_over_bounds(patterns)
        ):
            return JSONResponse({"error": "invalid_tool_filter", "field": field}, status_code=400)
    from core.mcp.host_requests import SAMPLING_MODES, normalize_sampling_mode
    sampling = normalize_sampling_mode(getattr(req, "sampling", None))
    if sampling is None:
        return JSONResponse(
            {"error": "invalid_sampling", "sampling": req.sampling, "supported": list(SAMPLING_MODES)},
            status_code=400,
        )
    from agents.core.mcp.catalog import NAME_RE
    if not isinstance(req.name, str) or not NAME_RE.match(req.name):
        return JSONResponse({"error": "invalid_name",
                             "message": "a server name is letters, digits, - and _ (at most 64)"},
                            status_code=400)
    if req.name in orch.mcp.servers:
        return JSONResponse({"error": f"MCP server '{req.name}' already exists"}, status_code=409)
    auth = getattr(req, "auth", None)
    if auth not in (None, "none", "oauth"):
        return JSONResponse({"error": "invalid_auth", "supported": ["none", "oauth"]}, status_code=400)
    oauth_pins, oauth_secret = _oauth_overrides(getattr(req, "oauth", None))
    if oauth_pins is None or (oauth_pins and transport != "streamable-http"):
        return JSONResponse({"error": "invalid_oauth",
                             "message": "oauth takes client_id, scope and client_secret, for an HTTP server"},
                            status_code=400)
    srv = MCPServer(
        name=req.name,
        # Persist the NORMALISED value, not req.transport. The gate above lower-cases
        # and strips only for its own comparison, so "  STDIO  " passed it and then
        # stored a spelling connect() does not dispatch on — re-creating the
        # permanently-dead admin row this row exists to remove, one case further in.
        transport=transport,
        command=req.command,
        url=req.url,
        trust=trust,
        tools_allow=getattr(req, "tools_allow", None),
        tools_deny=getattr(req, "tools_deny", None),
        sampling={"mode": sampling},
        elicitation=getattr(req, "elicitation", None),
        auth=auth if transport == "streamable-http" else None,
        oauth=oauth_pins or None,
    )
    if oauth_secret:
        import asyncio

        from agents.core.mcp.catalog import store_secrets
        try:
            await asyncio.to_thread(store_secrets, req.name, {"OAUTH_CLIENT_SECRET": oauth_secret})
        except Exception:
            return JSONResponse({"error": "secret_store_unavailable"}, status_code=503)
    _register_server(orch, srv)
    return {"ok": True, "server": req.name, "message": f"MCP server '{req.name}' added"}


def _oauth_overrides(raw) -> tuple[Optional[dict], Optional[str]]:
    """``(pins, client_secret)`` from the owner's ``oauth`` block; ``(None, None)`` when it is
    malformed. The secret is replaced by a reference to the server's stored secret."""
    if raw is None:
        return {}, None
    if not isinstance(raw, dict) or set(raw) - {"client_id", "client_secret", "scope"} or not all(
            isinstance(v, str) and v.strip() and len(v) <= 2048 and not any(c in v for c in "\r\n\x00")
            for v in raw.values()):
        return None, None
    pins = {k: raw[k].strip() for k in ("client_id", "scope") if k in raw}
    secret = raw.get("client_secret")
    if secret:
        if "client_id" not in pins:
            return None, None
        pins["client_secret"] = "${OAUTH_CLIENT_SECRET}"  # nosec B105 - a reference to a stored secret, not a secret
    return pins, secret


def _register_server(orch, srv) -> None:
    """The one place a new server joins the live manager and the saved list."""
    if callable(getattr(type(orch.mcp), "register", None)):
        orch.mcp.register(srv)          # host services + reconnect policy (H553/H556)
    else:
        orch.mcp.servers[srv.name] = srv
    # Persist to settings DB
    _web()._save_mcp_config()


@router.delete("/api/admin/mcp/{name}", dependencies=[Depends(admin_guard)])
async def admin_mcp_remove(name: str):
    """Remove an MCP server configuration."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    refusal = _safe_mode_refusal() or _held_refusal(name) or await _managed_refusal()
    if refusal is not None:
        return refusal
    if name not in orch.mcp.servers:
        return JSONResponse({"error": f"MCP server '{name}' not found"}, status_code=404)
    if callable(getattr(type(orch.mcp), "remove_server", None)):
        # Closed in every state — connected, connecting, waiting to reconnect — so no
        # child is left running outside the manager (H556).
        await orch.mcp.remove_server(name)
    else:
        srv = orch.mcp.servers[name]
        await srv.close()
        del orch.mcp.servers[name]
    # Persist to settings DB
    _web()._save_mcp_config()
    # G9: its stored secrets go, and its OAuth tokens are revoked and deleted.
    cleanup = await _forget_credentials(name)
    return {"ok": True, "server": name, "message": f"MCP server '{name}' removed", **cleanup}


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
        # connect() returns False for a failed handshake (and for any non-stdio
        # transport). Reporting a hardcoded connected:true made every dead server
        # look healthy in the admin panel. Through the manager when it can (H556): the
        # server gets the host services and the reconnect policy before it connects.
        if callable(getattr(type(orch.mcp), "connect_server", None)):
            connected = bool(await orch.mcp.connect_server(name))
        else:
            connected = bool(await srv.connect())
        body = {
            "ok": connected,
            "server": name,
            "connected": connected,
            "tools_count": len(srv.tools),
            "tools": [{"name": t.name, "description": t.description} for t in srv.tools],
        }
        if not connected:
            body["error"] = "connect_failed"
            body["reason"] = getattr(srv, "last_error", None)
        return body
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
    was_up = bool(srv._proc or getattr(srv, "_http", None) is not None)
    # Always: a server waiting to reconnect, or mid-connect, is stopped too (H556).
    await srv.close()
    if was_up:
        return {"ok": True, "server": name, "message": f"MCP server '{name}' disconnected"}
    return {"ok": True, "server": name, "message": f"MCP server '{name}' was not connected"}


@router.post("/api/admin/mcp/elicitations/{card_id}/answer", dependencies=[Depends(admin_guard)])
async def admin_mcp_elicitation_answer(card_id: str, body: ElicitationAnswer):
    """H553 — the owner's typed answer to an MCP server's request for input.

    The card stays in the ordinary approval queue; this fills its fields (checked against
    the schema the server sent) and approves it in one step. Rejecting the card there
    declines; a card nobody answers is cancelled when it times out."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    host = getattr(orch.mcp, "host", None)
    if host is None:
        return JSONResponse({"error": "elicitation_unavailable"}, status_code=503)
    result = host.answer_elicitation(card_id, body.content)
    if not result.get("ok"):
        # too_late: the call that asked ended before the answer; the card was withdrawn.
        status = {"unknown_elicitation": 404, "too_late": 410,
                  "already_answered": 409}.get(result.get("error"), 400)
        return JSONResponse(result, status_code=status)
    return result


# ── G9: the MCP catalog, install, and sign-in (H549, H550, H692) ───────────────

async def _same_origin(request: Request) -> None:
    """A catalog install or a sign-in starts a third-party program or mints a credential.
    The admin guard trusts loopback on a default install, so a page the owner visits could
    otherwise post here: a write must be JSON (which forces the browser's pre-check the CORS
    allow-list decides) and a request the browser marks cross-site is refused."""
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(status_code=403, detail="this change must come from Nerva's own page")
    if request.method == "POST":
        kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if kind != "application/json":
            raise HTTPException(status_code=415, detail="expected application/json")


_WRITE = [Depends(admin_guard), Depends(_same_origin)]


def _g9_row(srv) -> dict:
    from agents.core.mcp import oauth_client
    from agents.core.mcp.catalog import read_secret

    auth = getattr(srv, "auth", "none")
    auth = auth if isinstance(auth, str) else "none"
    names = getattr(srv, "secret_env", None) or []
    names = list(names) if isinstance(names, (list, tuple)) else []
    import re as _re

    for refs in (getattr(srv, "secret_headers", None), getattr(srv, "oauth", None)):
        if isinstance(refs, dict):
            names += [m for t in refs.values() for m in _re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(t))]
    origin = getattr(srv, "origin", None)
    name = getattr(srv, "name", "")
    transport = getattr(srv, "transport", "")
    oauth = None
    if transport == "streamable-http" and isinstance(name, str):
        oauth = _safe_call(lambda: oauth_client.status(name))
    return {
        "auth": auth,
        "origin": dict(origin) if isinstance(origin, dict) else None,
        "secrets": [{"name": n, "set": bool(_safe_call(lambda n=n: read_secret(name, n)))}
                    for n in dict.fromkeys(names)],
        "oauth": oauth,
    }


async def _forget_credentials(name: str) -> dict:
    import asyncio

    from agents.core.mcp import oauth_client
    from agents.core.mcp.catalog import delete_secrets

    out: dict = {}
    try:
        out["secrets_removed"] = await asyncio.to_thread(delete_secrets, name)
    except Exception:
        logger.warning("MCP server secrets could not be removed (type=store)")
        out["secrets_removed"] = None
    if oauth_client._SERVER_RE.match(name or ""):
        try:
            result = await oauth_client.sign_out(name, forget=True)
            out["oauth_revoked"] = result.get("revoked")
        except Exception as exc:
            logger.warning("MCP OAuth sign-out on remove failed (type=%s)", type(exc).__name__)
            out["oauth_revoked"] = None
    return out


def _audit(orch, action: str, why: str, metadata: dict) -> bool:
    audit = getattr(orch, "intent_log", None)
    if not callable(getattr(audit, "record", None)):
        return False
    try:
        audit.record(actor="owner", action=action, why=why, cause="mcp.catalog", metadata=metadata)
        return True
    except Exception:
        logger.warning("MCP %s intent projection failed", action, exc_info=True)
        return False


def _estop_refusal():
    from agents.core import estop

    if estop.is_engaged():
        return JSONResponse({"error": "estop_engaged",
                             "message": "the emergency stop is engaged; nothing is installed or signed in"},
                            status_code=409)
    return None


class CatalogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: A catalog entry's name (``linear``), or, with ``link_config``, the link's server name.
    name: str = Field(min_length=1, max_length=64)
    #: Install under another server name (a second account, a name already taken).
    server_name: Optional[str] = Field(default=None, max_length=64)
    #: A deep link's ``config=`` payload (base64 JSON; 32 KB cap): not from the catalog.
    link_config: Optional[str] = Field(default=None, max_length=32 * 1024)
    #: Non-secret inputs the manifest declares (a server URL to type): part of the plan.
    inputs: Optional[dict[str, str]] = None


class CatalogInstall(CatalogRequest):
    #: The digest of the plan the owner saw and confirmed (``preview``'s ``digest``).
    confirm: Optional[str] = Field(default=None, max_length=128)
    #: The secret values the plan names. Stored encrypted; never echoed, never in the config.
    secrets: Optional[dict[str, str]] = None


def _catalog_error(exc) -> JSONResponse:
    status = {"not_in_catalog": 404, "not_installable": 409, "catalog_unavailable": 503,
              "link_too_large": 413}.get(exc.reason, 400)
    return JSONResponse({"error": exc.reason, "message": exc.message}, status_code=status)


def _resolve(body: CatalogRequest):
    from agents.core.mcp.catalog import resolve_plan

    if body.link_config is not None:
        return resolve_plan(link_name=body.name, link_config=body.link_config,
                            server_name=body.server_name, values=body.inputs)
    return resolve_plan(catalog_name=body.name, server_name=body.server_name, values=body.inputs)


@router.get("/api/admin/mcp/catalog", dependencies=[Depends(admin_guard)])
async def admin_mcp_catalog(q: str = ""):
    """H549 — the reviewed MCP servers Nerva can install (vendored Hermes manifests, each
    re-checked against MANIFEST.json), next to the owner's own servers."""
    import asyncio

    from agents.core.mcp.catalog import CatalogError, load_catalog, search

    try:
        commit, entries = await asyncio.to_thread(load_catalog)
    except CatalogError as exc:
        return _catalog_error(exc)
    orch = get_orch()
    servers = getattr(getattr(orch, "mcp", None), "servers", None) or {}
    installed_urls = {getattr(s, "url", None) for s in servers.values() if getattr(s, "url", None)}
    rows = []
    for entry in search(entries, q[:200]):
        row = entry.summary()
        row["installed"] = entry.name in servers or (entry.url is not None and entry.url in installed_urls)
        rows.append(row)
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    return nocache_json({"commit": commit, "entries": rows, "total": len(entries), "counts": counts,
                         "http_client_enabled": _http_client_enabled()})


def _http_client_enabled() -> bool:
    from agents.core.mcp.http_transport import http_client_enabled

    return http_client_enabled()


@router.post("/api/admin/mcp/catalog/preview", dependencies=_WRITE)
async def admin_mcp_catalog_preview(body: CatalogRequest):
    """H549 — exactly what an install would write and run, with its digest. Writes nothing.
    A deep link opens this (``/v2/console/mcp?install=<name>`` or ``?link=…&config=…``)."""
    import asyncio

    from agents.core.mcp.catalog import CatalogError

    try:
        plan, _entry = await asyncio.to_thread(_resolve, body)
    except CatalogError as exc:
        return _catalog_error(exc)
    orch = get_orch()
    servers = getattr(getattr(orch, "mcp", None), "servers", None) or {}
    plan_out = dict(plan)
    plan_out["name_taken"] = plan["name"] in servers
    plan_out["http_client_enabled"] = _http_client_enabled()
    return nocache_json({"ok": True, "plan": plan_out})


@router.post("/api/admin/mcp/catalog/install", dependencies=_WRITE)
async def admin_mcp_catalog_install(body: CatalogInstall):
    """H549 — install a catalog entry (or a deep link's server) through the add path.

    Refused unless ``confirm`` is the digest of the plan as it is now (428 with the plan
    when missing, 409 ``plan_changed`` when it differs), under the e-stop, in safe mode, for
    a name the load set holds, when the managed configuration pins ``mcp.servers``, and for
    a name already taken (never overwritten). Secrets go to the encrypted store; the saved
    config keeps their names. Nothing starts: the owner connects (and signs in) after."""
    import asyncio
    import hmac

    from agents.core.mcp.catalog import CatalogError, store_secrets, validate_inputs

    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        plan, entry = await asyncio.to_thread(_resolve, body)
    except CatalogError as exc:
        return _catalog_error(exc)
    if not body.confirm:
        return JSONResponse({"error": "confirmation_required",
                             "message": "show the plan to the owner and send its digest as confirm",
                             "plan": plan}, status_code=428)
    if not hmac.compare_digest(str(body.confirm), plan["digest"]):
        return JSONResponse({"error": "plan_changed",
                             "message": "what would be installed differs from what was confirmed",
                             "plan": plan}, status_code=409)
    if plan["needs"]:
        return JSONResponse({"error": "missing_input", "needs": plan["needs"]}, status_code=400)
    refusal = (_estop_refusal() or _safe_mode_refusal() or _held_refusal(plan["name"])
               or await _managed_refusal())
    if refusal is not None:
        return refusal
    if plan["name"] in orch.mcp.servers:
        return JSONResponse({"error": "name_taken",
                             "message": f"an MCP server named '{plan['name']}' exists; it is never "
                                        "overwritten — choose another server_name"}, status_code=409)
    try:
        values = validate_inputs(entry, body.secrets)
    except CatalogError as exc:
        return _catalog_error(exc)
    from core.mcp.client import MCPServer

    origin = {"kind": plan["origin"], "catalog": plan["catalog_name"], "commit": plan["commit"],
              "manifest_sha256": plan["manifest_sha256"]}
    srv = MCPServer(
        name=plan["name"], transport=plan["transport"], command=plan["command"], url=plan["url"],
        env=plan["env"], trust=plan["trust"], tools_allow=plan["tools_allow"],
        tools_deny=plan["tools_deny"], sampling={"mode": "off"}, elicitation=False,
        auth=plan["auth"], secret_env=plan["secret_env"], secret_headers=plan["secret_headers"],
        oauth=plan["oauth"], origin=origin,
    )
    try:
        stored = await asyncio.to_thread(store_secrets, plan["name"], values)
    except Exception:
        logger.warning("MCP install: the secret store refused the server's secrets")
        return JSONResponse({"error": "secret_store_unavailable"}, status_code=503)
    _register_server(orch, srv)
    audited = _audit(orch, "mcp.install",
                     f"the owner installed the MCP server {plan['name']} "
                     + (f"from the Hermes catalog @{(plan['commit'] or '')[:8]}" if plan["origin"] == "catalog"
                        else "from a link (not in the reviewed catalog)"),
                     {"server": plan["name"], "origin": plan["origin"], "catalog": plan["catalog_name"],
                      "commit": plan["commit"], "transport": plan["transport"], "command": plan["command"],
                      "url": plan["url"], "env_names": sorted(plan["env"]), "secret_names": stored,
                      "digest": plan["digest"]})
    needs_sign_in = plan["auth"] == "oauth"
    return {"ok": True, "server": plan["name"], "secrets_stored": stored, "audited": audited,
            "next": "sign_in" if needs_sign_in else "connect",
            "message": (f"'{plan['name']}' installed. Sign in, then connect." if needs_sign_in
                        else f"'{plan['name']}' installed. It starts when you press connect.")}


# ── OAuth sign-in for a remote server (H550) and its callback relay (H692) ────

class OAuthStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: ``hub``: the browser returns to this hub's ``/api/oauth/mcp/callback``. ``loopback``:
    #: it returns to ``redirect_uri`` on the owner's own machine (a CLI listener, or a
    #: page whose address the owner pastes back), which relays code and state here.
    redirect: str = Field(default="hub", pattern=r"^(hub|loopback)$")
    redirect_uri: Optional[str] = Field(default=None, max_length=200)


class OAuthRelay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str = Field(min_length=8, max_length=200)
    binding: str = Field(min_length=8, max_length=200)
    code: Optional[str] = Field(default=None, max_length=4096)
    error: Optional[str] = Field(default=None, max_length=200)
    #: RFC 9207: the issuer the authorization response named, when it named one.
    iss: Optional[str] = Field(default=None, max_length=2048)


def _oauth_error(exc) -> JSONResponse:
    return JSONResponse({"error": exc.reason, "message": exc.message}, status_code=exc.status)


def _http_server(orch, name: str):
    srv = (getattr(getattr(orch, "mcp", None), "servers", None) or {}).get(name)
    if srv is None:
        return None, JSONResponse({"error": f"MCP server '{name}' not found"}, status_code=404)
    if getattr(srv, "transport", "") != "streamable-http":
        return None, JSONResponse({"error": "not_http_server",
                                   "message": "sign-in is for a server reached over HTTP"}, status_code=400)
    return srv, None


def _cookie_name(state: str) -> str:
    import hashlib

    from agents.core.mcp.oauth_client import COOKIE_PREFIX

    return COOKIE_PREFIX + hashlib.sha256(state.encode()).hexdigest()[:16]


@router.get("/api/admin/mcp/{name}/oauth", dependencies=[Depends(admin_guard)])
async def admin_mcp_oauth_status(name: str):
    """H550 — whether this server holds a token (never the token), until when, from whom."""
    from agents.core.mcp import oauth_client

    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    _srv, refusal = _http_server(orch, name)
    if refusal is not None:
        return refusal
    return nocache_json({"server": name, **oauth_client.status(name),
                         "redirect_pin": oauth_client.redirect_pin(getattr(_srv, "oauth", None))})


@router.post("/api/admin/mcp/{name}/oauth/start", dependencies=_WRITE)
async def admin_mcp_oauth_start(name: str, body: OAuthStart, request: Request):
    """H550 — begin the sign-in: discovery, client registration, PKCE. Answers the address
    to open in the browser and a ``binding`` only this caller holds (also set as an
    HttpOnly cookie on the hub's callback path). Refused under the e-stop."""
    from agents.core.mcp import oauth_client

    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    srv, refusal = _http_server(orch, name)
    if refusal is not None:
        return refusal
    hub_base = str(request.base_url).rstrip("/")
    redirect_uri = (hub_base + oauth_client.HUB_CALLBACK_PATH if body.redirect == "hub"
                    else (body.redirect_uri or ""))
    try:
        started = await oauth_client.start(name, srv.url, redirect_uri=redirect_uri, hub_base=hub_base,
                                           pins=getattr(srv, "oauth", None) or {})
    except oauth_client.OAuthError as exc:
        return _oauth_error(exc)
    response = nocache_json({"ok": True, "server": name, **started})
    response.set_cookie(_cookie_name(started["state"]), started["binding"], max_age=oauth_client.FLOW_TTL,
                        path=oauth_client.HUB_CALLBACK_PATH, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")
    return response


@router.post("/api/admin/mcp/{name}/oauth/callback", dependencies=_WRITE)
async def admin_mcp_oauth_relay(name: str, body: OAuthRelay):
    """H692 — the relay: code and state captured on the owner's machine (a loopback listener,
    or the address the browser ended on) handed back with the start's ``binding``. Only the
    hub redeems; state and binding are checked in constant time, once."""
    from agents.core.mcp import oauth_client

    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    _srv, refusal = _http_server(orch, name)
    if refusal is not None:
        return refusal
    try:
        result = await oauth_client.complete(body.state, body.code or "", body.binding, server=name,
                                             error=body.error, iss=body.iss)
    except oauth_client.OAuthError as exc:
        return _oauth_error(exc)
    audited = audit_sign_in(orch, result, via="relay")
    return nocache_json({"ok": True, **result, "audited": audited})


def audit_sign_in(orch, result: dict, *, via: str) -> bool:
    """One intent row per acquired credential (never the token)."""
    return _audit(orch, "mcp.oauth.sign_in",
                  f"the owner signed in to the MCP server {result.get('server')} "
                  f"({result.get('issuer')}) via the {via} callback",
                  {"server": result.get("server"), "issuer": result.get("issuer"),
                   "scope": result.get("scope"), "expires_at": result.get("expires_at"),
                   "refreshable": result.get("refreshable"), "via": via})


@router.delete("/api/admin/mcp/{name}/oauth", dependencies=_WRITE)
async def admin_mcp_oauth_sign_out(name: str):
    """H550 — sign out: revoke the tokens at the server (best effort) and delete them, and
    drop a waiting sign-in."""
    from agents.core.mcp import oauth_client

    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    srv, refusal = _http_server(orch, name)
    if refusal is not None:
        return refusal
    try:
        result = await oauth_client.sign_out(name)
    except oauth_client.OAuthError as exc:
        return _oauth_error(exc)
    with suppress(Exception):
        await srv.close()
    audited = _audit(orch, "mcp.oauth.sign_out", f"the owner signed out of the MCP server {name}",
                     {"server": name, "revoked": result.get("revoked")})
    return nocache_json({"ok": True, "server": name, **result, "audited": audited})




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
    # Signing succeeded; audit delivery is best-effort and cannot hold the token.
    with suppress(Exception):
        submit_auth_event(
            "token_issued", tier="user", reason="issue", count=1,
            revoke_env=False, surface="mcp",
        )
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
    owner = False
    success_reason = "credential"
    if bool(orch.get_setting("mcp.oauth_required", False)):
        from agents.core.mcp.oauth import MCPResourceServer
        from agents.core.mcp.server import VerifiedMCPIdentity
        resource = _mcp_resource(request)
        result = w._get_mcp_rs().validate(
            request.headers.get("authorization", ""), resource, required_scope="mcp")
        if not result["ok"]:
            _audit_mcp_auth(
                request, success=False,
                reason="invalid" if request.headers.get("authorization") else "missing",
            )
            return JSONResponse(
                {"error": f"unauthorized: {result['error']}"}, status_code=401,
                headers={"WWW-Authenticate": MCPResourceServer.challenge(resource)})
        verified_identity = VerifiedMCPIdentity(
            subject=str((result.get("claims") or {}).get("sub") or "").strip()
        )
        # G10: an OAuth token is the owner's only when the owner minted it with the
        # ``mcp:owner`` scope (``POST /api/mcp/token`` is itself admin-guarded).
        from agents.core.mcp.inbox_tools import OWNER_SCOPE
        scope = (result.get("claims") or {}).get("scope")
        owner = isinstance(scope, str) and OWNER_SCOPE in scope.split()
        if not verified_identity.subject:
            _audit_mcp_auth(request, success=False, reason="invalid")
            return JSONResponse(
                {"error": "unauthorized: OAuth subject required"}, status_code=401,
                headers={"WWW-Authenticate": MCPResourceServer.challenge(resource)})
    else:
        # G10: without OAuth the owner is decided exactly as ``admin_guard`` (and the
        # HUD's principal) decides it — an admin credential in X-Admin-Token, or the
        # fresh-box direct-localhost posture while no admin credential exists.
        principal = getattr(w, "_web_principal", None)
        owner = bool(principal(request).admin) if callable(principal) else False
        # SEC (review F1/F2, #294): with OAuth off, the MCP transport must enforce the
        # SAME posture as every other user route (HF-1) — a matching user/admin token if
        # JARVIS_USER_TOKEN is set, else localhost-only (fail closed behind an untrusted
        # proxy, HF-7). Without this gate a REMOTE caller could reach the read tools
        # (dashboard/memory) over the MCP transport even though the HTTP routes are guarded.
        # The credential is required exactly when the guard requires it (H273, review-H273e
        # M1): one predicate, so a lapsed or revoked credential locks MCP as it locks HTTP.
        credential_required = w._user_credential_required()
        if credential_required:
            if not w._request_is_authed(request):
                _audit_mcp_auth(
                    request, success=False,
                    reason="invalid" if (
                        request.headers.get("x-user-token") or request.headers.get("x-admin-token")
                    ) else "missing",
                )
                return JSONResponse(
                    {"error": "unauthorized: user token required"}, status_code=401)
        elif w._real_client_host(request) not in w._LOCALHOSTS:
            _audit_mcp_auth(request, success=False, reason="network_disabled")
            return JSONResponse(
                {"error": "MCP server disabled from network — set JARVIS_USER_TOKEN to enable remote access"},
                status_code=403,
            )
        else:
            success_reason = "local_bypass"
    # Thread the caller's user identity (same header user_guard reads) into the server
    # so MUTATING route tools can enforce the per-identity gate. An admin token also
    # satisfies the user gate (admin ⊇ user).
    identity = verified_identity or (
        request.headers.get("x-user-token") or request.headers.get("x-admin-token")
    )
    _audit_mcp_auth(request, success=True, reason=success_reason)
    from agents.core.mcp.inbox_tools import transport_owner
    with transport_owner(owner):
        response = await w._build_mcp_server().handle(message, identity=identity)
    # JSON-RPC notifications produce no response body.
    return nocache_json(response if response is not None else {"ok": True})
