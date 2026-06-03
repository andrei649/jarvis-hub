"""Tests for H16.1 — MCP OAuth 2.1 resource server (2025-11 spec)."""
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.mcp.oauth import MCPResourceServer, protected_resource_metadata

RES = "http://host/api/mcp/server"


# ── metadata (RFC 9728) ──────────────────────────────────────────────────────

def test_protected_resource_metadata():
    md = protected_resource_metadata(RES, ["https://idp.example"])
    assert md["resource"] == RES
    assert md["authorization_servers"] == ["https://idp.example"]
    assert "mcp" in md["scopes_supported"] and md["bearer_methods_supported"] == ["header"]


# ── token issue + validate ───────────────────────────────────────────────────

def test_issue_and_validate_roundtrip():
    rs = MCPResourceServer(secret="s")
    tok = rs.issue_token("client", RES, ["mcp"])
    out = rs.validate(tok, RES, required_scope="mcp")
    assert out["ok"] and out["claims"]["sub"] == "client"
    # Authorization: Bearer prefix is accepted
    assert rs.validate(f"Bearer {tok}", RES)["ok"]


def test_rfc8707_audience_binding():
    rs = MCPResourceServer(secret="s")
    tok = rs.issue_token("client", RES, ["mcp"])
    # token bound to RES must be rejected for a different resource
    bad = rs.validate(tok, "http://other/api/mcp/server")
    assert bad["ok"] is False and "RFC 8707" in bad["error"]


def test_scope_enforced():
    rs = MCPResourceServer(secret="s")
    tok = rs.issue_token("client", RES, ["read"])     # no 'mcp' scope
    assert rs.validate(tok, RES, required_scope="mcp")["ok"] is False


def test_signature_and_expiry():
    rs = MCPResourceServer(secret="s")
    tok = rs.issue_token("client", RES, ["mcp"])
    # tampered signature
    assert rs.validate(tok[:-2] + "xx", RES)["ok"] is False
    # different secret cannot validate
    assert MCPResourceServer(secret="other").validate(tok, RES)["ok"] is False
    # expired
    expired = rs.issue_token("client", RES, ["mcp"], ttl=-1)
    assert rs.validate(expired, RES)["ok"] is False
    # malformed / missing
    assert rs.validate("", RES)["ok"] is False
    assert rs.validate("not-a-token", RES)["ok"] is False


def test_challenge_points_at_metadata():
    ch = MCPResourceServer.challenge(RES)
    assert ch.startswith("Bearer ") and "oauth-protected-resource" in ch and RES in ch


# ── endpoints ────────────────────────────────────────────────────────────────

def test_well_known_and_oauth_enforcement():
    from agents import web
    old = web.ADMIN_TOKEN
    web.ADMIN_TOKEN = "test-secret"
    web._mcp_rs = None                                # reset cached RS
    hdr = {"X-Admin-Token": "test-secret"}
    if web.orch is None:
        return
    orig_get = web.orch.get_setting
    flags = {"mcp.server_enabled": True, "mcp.oauth_required": True}
    web.orch.get_setting = lambda key, default=None: flags.get(key, orig_get(key, default))
    try:
        with TestClient(web.app) as c:
            # discovery doc is public
            md = c.get("/.well-known/oauth-protected-resource")
            assert md.status_code == 200 and md.json()["resource"].endswith("/api/mcp/server")

            rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

            # no token → 401 with a WWW-Authenticate challenge
            r = c.post("/api/mcp/server/rpc", json=rpc)
            assert r.status_code == 401 and "WWW-Authenticate" in r.headers

            # issue a token (admin) then call successfully
            issued = c.post("/api/mcp/token", json={"scopes": ["mcp"]}, headers=hdr)
            assert issued.status_code == 200
            token = issued.json()["token"]
            ok = c.post("/api/mcp/server/rpc", json=rpc,
                        headers={"Authorization": f"Bearer {token}"})
            assert ok.status_code == 200
    finally:
        web.ADMIN_TOKEN = old
        web.orch.get_setting = orig_get
