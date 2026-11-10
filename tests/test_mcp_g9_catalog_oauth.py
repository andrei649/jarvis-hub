"""G9 — MCP install catalog (H549), client OAuth (H550) and the callback relay (H692).

Hermetic: the OAuth authorization server and the remote MCP server are one fake behind
``httpx.MockTransport``, reached through the real guarded egress client (a resolver stub
answers a public address), so the SSRF pinning and the no-redirect rule are the real ones.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from fastapi.testclient import TestClient  # noqa: E402

import agents.web as web  # noqa: E402
from agents.core.mcp import catalog as cat  # noqa: E402
from agents.core.mcp import client as client_mod  # noqa: E402
from agents.core.mcp import oauth_client as oc  # noqa: E402
from agents.core.mcp.client import MCPManager, MCPServer  # noqa: E402
from agents.core.mcp.http_transport import HTTP_CLIENT_FLAG, StreamableHttpTransport, _MCPHTTPClient  # noqa: E402

_TOKEN = "g9-admin-token"
_HDR = {"X-Admin-Token": _TOKEN}
MCP_URL = "https://mcp.example.test/mcp"
AS = "https://auth.example.test"


def _public(host, *, mode):
    return ["93.184.216.34"], None


class FakeWorld:
    """One authorization server and one MCP server, by Host header."""

    def __init__(self, *, prm_resource: str | None = MCP_URL, issuer: str = AS,
                 methods=("S256",), registration: bool = True):
        self.requests: list[httpx.Request] = []
        self.prm_resource = prm_resource
        self.issuer = issuer
        self.methods = list(methods) if methods is not None else None
        self.registration = registration
        self.codes: dict[str, dict] = {}
        self.access = {"at-1"}
        self.refresh = {"rt-1": ("at-2", "rt-2")}
        self.revoked: list[str] = []
        self.expires_in = 3600

    def factory(self, target):
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.headers.get("host", "")
        path = request.url.path
        if host == "mcp.example.test":
            return self._mcp(request, path)
        if host == "auth.example.test":
            return self._as(request, path)
        return httpx.Response(404)

    def _mcp(self, request, path):
        if path in ("/.well-known/oauth-protected-resource/mcp",):
            if self.prm_resource is None:
                return httpx.Response(404)
            return httpx.Response(200, json={"resource": self.prm_resource,
                                             "authorization_servers": [AS], "scopes_supported": ["read"]})
        if path != "/mcp":
            return httpx.Response(404)
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] not in self.access:
            return httpx.Response(401, headers={"www-authenticate": 'Bearer resource_metadata="x"'})
        if request.method == "DELETE":
            return httpx.Response(200)
        body = json.loads(request.content or b"{}")
        if "id" not in body:
            return httpx.Response(202)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {
                "protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "f"}}})
        if body["method"] == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [
                {"name": "echo", "description": "e", "inputSchema": {"type": "object"},
                 "annotations": {"readOnlyHint": True}}]}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})

    def _as(self, request, path):
        if path == "/.well-known/oauth-authorization-server":
            meta = {"issuer": self.issuer, "authorization_endpoint": f"{AS}/authorize",
                    "token_endpoint": f"{AS}/token", "revocation_endpoint": f"{AS}/revoke"}
            if self.registration:
                meta["registration_endpoint"] = f"{AS}/register"
            if self.methods is not None:
                meta["code_challenge_methods_supported"] = self.methods
            meta.update(getattr(self, "meta_overrides", {}))
            return httpx.Response(200, json=meta)
        if path == "/register":
            body = json.loads(request.content)
            self.registrations = getattr(self, "registrations", 0) + 1
            assert body["token_endpoint_auth_method"] == "none"
            self.registered_redirects = body["redirect_uris"]
            return httpx.Response(201, json={"client_id": "cid-1"})
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if path == "/token":
            if form.get("grant_type") == "authorization_code":
                issued = self.codes.pop(form.get("code"), None)
                if issued is None:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                challenge = base64.urlsafe_b64encode(
                    hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                if challenge != issued["challenge"] or form["redirect_uri"] != issued["redirect_uri"] \
                        or form["client_id"] != "cid-1" or form.get("resource") != MCP_URL:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json={"access_token": "at-1", "token_type": "Bearer",
                                                 "expires_in": self.expires_in, "refresh_token": "rt-1",
                                                 "scope": "read"})
            if form.get("grant_type") == "refresh_token":
                pair = self.refresh.pop(form.get("refresh_token"), None)
                if pair is None:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.access.add(pair[0])
                return httpx.Response(200, json={"access_token": pair[0], "token_type": "Bearer",
                                                 "expires_in": 3600, "refresh_token": pair[1]})
        if path == "/revoke":
            self.revoked.append(form.get("token"))
            return httpx.Response(200)
        return httpx.Response(404)

    def authorize(self, authorization_url: str, code: str = "code-1") -> tuple[str, str]:
        """The owner approving in the browser: the AS remembers the challenge for *code*."""
        q = {k: v[0] for k, v in parse_qs(urlsplit(authorization_url).query).items()}
        assert q["code_challenge_method"] == "S256" and q["resource"] == MCP_URL
        self.codes[code] = {"challenge": q["code_challenge"], "redirect_uri": q["redirect_uri"]}
        return code, q["state"]


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv(HTTP_CLIENT_FLAG, "1")
    w = FakeWorld()
    monkeypatch.setattr(oc, "HTTP_FACTORY", lambda server: _MCPHTTPClient(
        f"mcp-oauth:{server}", resolver=_public, transport_factory=w.factory))

    class _Transport(StreamableHttpTransport):
        def __init__(self, url, headers=None, *, name="mcp", **kw):
            super().__init__(url, headers, name=name, transport_factory=w.factory, resolver=_public)

    # The admin routes build servers from the ``core.`` alias of the client module.
    import core.mcp.client as alias_mod

    for mod in {client_mod, alias_mod}:
        monkeypatch.setattr(mod, "StreamableHttpTransport", _Transport)
    oc.reset_for_tests()
    yield w
    oc.reset_for_tests()


class Intents:
    def __init__(self):
        self.rows = []

    def record(self, **kw):
        self.rows.append(kw)


@pytest.fixture
def hub(monkeypatch, world):
    orch = SimpleNamespace(mcp=MCPManager(), intent_log=Intents())
    monkeypatch.setattr(web, "ADMIN_TOKEN", _TOKEN)
    monkeypatch.setattr(web, "orch", orch)
    saved = []
    monkeypatch.setattr(web, "_save_mcp_config", lambda: saved.append(orch.mcp.to_config()))
    client = TestClient(web.app, base_url="https://hub.local")
    return SimpleNamespace(orch=orch, client=client, saved=saved, world=world)


def _link(cfg: dict) -> str:
    return base64.b64encode(json.dumps(cfg).encode()).decode()


# ── catalog data ─────────────────────────────────────────────────────────────

def test_catalog_bytes_match_manifest():
    manifest = json.loads((cat.VENDOR_ROOT / "MANIFEST.json").read_text())
    rows = {f["path"]: f for f in manifest["files"] if f["path"].startswith("optional-mcps/")}
    assert len(rows) == 66
    for rel, row in rows.items():
        data = (cat.VENDOR_ROOT / rel).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row["vendored_sha256"] == row["upstream_sha256"]
        assert row["rules_applied"] == []
    commit, entries = cat.load_catalog()
    assert commit == manifest["upstream"]["commit"]
    assert len(entries) == 66 and all(e.status == cat.STATUS_OK for e in entries)
    assert {e.auth for e in entries} == {"oauth", "none"}


def test_a_tampered_manifest_is_listed_and_never_installable(tmp_path):
    root = tmp_path / "vendor"
    shutil.copytree(cat.VENDOR_ROOT / "optional-mcps", root / "optional-mcps")
    shutil.copy(cat.VENDOR_ROOT / "MANIFEST.json", root / "MANIFEST.json")
    target = root / "optional-mcps" / "linear" / "manifest.yaml"
    target.write_text(target.read_text().replace("https://mcp.linear.app/mcp", "https://evil.example/mcp"))
    _, entries = cat.load_catalog(root)
    linear = next(e for e in entries if e.name == "linear")
    assert linear.status == cat.STATUS_TAMPERED
    with pytest.raises(cat.CatalogError) as exc:
        cat.resolve_plan(catalog_name="linear", root=root)
    assert exc.value.reason == "not_installable"


def test_manifest_reader_refusals():
    base = b"manifest_version: 1\nname: x\ntransport:\n  type: stdio\n  command: npx\n"
    assert cat.parse_manifest(base).command == "npx"
    with pytest.raises(cat.CatalogError) as exc:
        cat.parse_manifest(b"manifest_version: 2\nname: x\n")
    assert exc.value.reason == cat.STATUS_FUTURE
    with pytest.raises(cat.CatalogError) as exc:
        cat.parse_manifest(base + b"install:\n  type: git\n  url: u\n  ref: r\n")
    assert exc.value.reason == cat.STATUS_UNSUPPORTED
    with pytest.raises(cat.CatalogError):
        cat.parse_manifest(base + b"  env:\n    NODE_OPTIONS: --require=/tmp/x.js\n")
    with pytest.raises(cat.CatalogError):
        cat.parse_manifest(b"manifest_version: 1\nname: x\ntransport:\n  type: http\n  url: file:///etc\n")


def test_typed_url_is_part_of_the_plan_digest():
    plan, _ = cat.resolve_plan(catalog_name="n8n-official")
    assert plan["needs"] == ["N8N_MCP_SERVER_URL"] and plan["url"] is None
    a, _ = cat.resolve_plan(catalog_name="n8n-official", values={"N8N_MCP_SERVER_URL": "https://a.example/mcp"})
    b, _ = cat.resolve_plan(catalog_name="n8n-official", values={"N8N_MCP_SERVER_URL": "https://b.example/mcp"})
    assert a["url"] == "https://a.example/mcp" and a["digest"] != b["digest"]


def test_catalog_route_lists_and_searches(hub):
    r = hub.client.get("/api/admin/mcp/catalog?q=linear", headers=_HDR)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 66 and [e["name"] for e in body["entries"]] == ["linear"]
    assert body["entries"][0]["installed"] is False and body["entries"][0]["auth"] == "oauth"
    assert hub.client.get("/api/admin/mcp/catalog").status_code in (401, 403)


# ── install ──────────────────────────────────────────────────────────────────

STDIO_LINK = {"command": "npx", "args": ["-y", "@vendor/mcp-server@1.2.3"],
              "env": {"VENDOR_API_KEY": "planted-by-the-link"}}


def test_install_shows_the_command_and_needs_the_owner_confirmation(hub):
    req = {"name": "vendor", "link_config": _link(STDIO_LINK)}
    preview = hub.client.post("/api/admin/mcp/catalog/preview", json=req, headers=_HDR).json()["plan"]
    assert preview["will_run"] == "spawn on this hub: npx -y @vendor/mcp-server@1.2.3"
    assert preview["origin"] == "link" and preview["starts"] == "only when you press connect"
    # A link's env value is never taken: the name becomes a secret the owner types.
    assert preview["secrets"] == [{"name": "VENDOR_API_KEY", "prompt": "VENDOR_API_KEY",
                                   "required": True, "has_default": False}]
    assert "planted-by-the-link" not in json.dumps(preview)
    assert preview["env"] == {}

    missing = hub.client.post("/api/admin/mcp/catalog/install", json=req, headers=_HDR)
    assert missing.status_code == 428 and missing.json()["plan"]["digest"] == preview["digest"]
    wrong = hub.client.post("/api/admin/mcp/catalog/install", json={**req, "confirm": "0" * 64}, headers=_HDR)
    assert wrong.status_code == 409 and wrong.json()["error"] == "plan_changed"
    no_secret = hub.client.post("/api/admin/mcp/catalog/install",
                                json={**req, "confirm": preview["digest"]}, headers=_HDR)
    assert no_secret.status_code == 400 and no_secret.json()["error"] == "missing_secret"
    assert "vendor" not in hub.orch.mcp.servers

    ok = hub.client.post("/api/admin/mcp/catalog/install",
                         json={**req, "confirm": preview["digest"], "secrets": {"VENDOR_API_KEY": "sk-owner-typed"}},
                         headers=_HDR)
    assert ok.status_code == 200, ok.text
    assert ok.json()["secrets_stored"] == ["VENDOR_API_KEY"] and ok.json()["next"] == "connect"
    srv = hub.orch.mcp.servers["vendor"]
    # Installed, not started: stdio servers start only when the owner connects.
    assert srv._proc is None and srv.wanted is False
    # The secret is in the encrypted store only, never in the saved configuration.
    saved = json.dumps(hub.saved[-1])
    assert "sk-owner-typed" not in saved and "VENDOR_API_KEY" in saved
    assert cat.read_secret("vendor", "VENDOR_API_KEY") == "sk-owner-typed"
    store_file = Path(cat._store().path).read_bytes()
    assert b"sk-owner-typed" not in store_file
    # It reaches the child's environment at spawn.
    assert srv._merged_env()["VENDOR_API_KEY"] == "sk-owner-typed"
    row = hub.orch.intent_log.rows[-1]
    assert row["action"] == "mcp.install" and row["metadata"]["command"] == "npx -y @vendor/mcp-server@1.2.3"
    assert "sk-owner-typed" not in json.dumps(row)
    # Never overwritten.
    again = hub.client.post("/api/admin/mcp/catalog/install",
                            json={**req, "confirm": preview["digest"], "secrets": {"VENDOR_API_KEY": "x"}},
                            headers=_HDR)
    assert again.status_code == 409 and again.json()["error"] == "name_taken"
    assert cat.read_secret("vendor", "VENDOR_API_KEY") == "sk-owner-typed"
    # Removing the server removes its secrets.
    gone = hub.client.delete("/api/admin/mcp/vendor", headers=_HDR)
    assert gone.status_code == 200 and gone.json()["secrets_removed"] == 1
    assert cat.read_secret("vendor", "VENDOR_API_KEY") is None


def test_install_honours_the_managed_gate(hub, monkeypatch):
    from agents.core import managed_scope

    def refuse(*a, **kw):
        raise managed_scope.ManagedRefused("pinned", names=["mcp.servers"], source="managed.json")

    monkeypatch.setattr(managed_scope, "check_setting_write", refuse)
    monkeypatch.setattr(managed_scope, "audit_refusal", lambda *a, **kw: True)
    plan, _ = cat.resolve_plan(catalog_name="context7")
    r = hub.client.post("/api/admin/mcp/catalog/install",
                        json={"name": "context7", "confirm": plan["digest"]}, headers=_HDR)
    assert r.status_code == 409 and r.json()["error"] == "managed"
    assert "context7" not in hub.orch.mcp.servers and hub.saved == []


def test_install_refused_under_estop_and_cross_site(hub, monkeypatch):
    from agents.core import estop

    plan, _ = cat.resolve_plan(catalog_name="context7")
    cross = hub.client.post("/api/admin/mcp/catalog/install", json={"name": "context7", "confirm": plan["digest"]},
                            headers={**_HDR, "Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    form = hub.client.post("/api/admin/mcp/catalog/install", content=b"name=context7",
                           headers={**_HDR, "Content-Type": "application/x-www-form-urlencoded"})
    assert form.status_code == 415
    monkeypatch.setattr(estop, "is_engaged", lambda: True)
    r = hub.client.post("/api/admin/mcp/catalog/install", json={"name": "context7", "confirm": plan["digest"]},
                        headers=_HDR)
    assert r.status_code == 409 and r.json()["error"] == "estop_engaged"
    assert "context7" not in hub.orch.mcp.servers


def test_link_limits():
    with pytest.raises(cat.CatalogError) as exc:
        cat.parse_link_config("big", "A" * (cat.MAX_LINK_CONFIG + 1))
    assert exc.value.reason == "link_too_large"
    with pytest.raises(cat.CatalogError) as exc:
        cat.parse_link_config("h", _link({"url": MCP_URL, "headers": {"Authorization": "Bearer x"}}))
    assert exc.value.reason == "link_headers_refused"
    with pytest.raises(cat.CatalogError):
        cat.parse_link_config("p", _link({"command": "node", "env": {"NODE_OPTIONS": "--require /tmp/x"}}))
    with pytest.raises(cat.CatalogError):
        cat.parse_link_config("../x", _link({"command": "node"}))


def test_http_catalog_install_then_connect_needs_sign_in(hub):
    plan = hub.client.post("/api/admin/mcp/catalog/preview", json={"name": "linear"}, headers=_HDR).json()["plan"]
    assert plan["will_run"] == "connect over HTTPS to https://mcp.linear.app/mcp"
    r = hub.client.post("/api/admin/mcp/catalog/install", json={"name": "linear", "confirm": plan["digest"]},
                        headers=_HDR)
    assert r.status_code == 200 and r.json()["next"] == "sign_in"
    srv = hub.orch.mcp.servers["linear"]
    assert srv.auth == "oauth" and srv.origin["catalog"] == "linear"
    assert asyncio.run(srv.connect()) is False and srv.last_error == "oauth_required"


# ── OAuth (H550) ─────────────────────────────────────────────────────────────

def _add_http(hub, name="remote"):
    r = hub.client.post("/api/admin/mcp", json={"name": name, "transport": "streamable-http", "url": MCP_URL,
                                                 "trust": "full", "auth": "oauth"}, headers=_HDR)
    assert r.status_code == 200, r.text


def _sign_in(hub, name="remote"):
    start = hub.client.post(f"/api/admin/mcp/{name}/oauth/start", json={"redirect": "hub"}, headers=_HDR)
    assert start.status_code == 200, start.text
    body = start.json()
    code, state = hub.world.authorize(body["authorization_url"])
    page = hub.client.get(f"/api/oauth/mcp/callback?code={code}&state={state}")
    return body, page


def test_full_oauth_flow_with_pkce_refresh_and_revocation(hub):
    _add_http(hub)
    body, page = _sign_in(hub)
    assert body["redirect_uri"] == "https://hub.local/api/oauth/mcp/callback"
    assert body["server_origin"] == "https://mcp.example.test:443" and body["as_host"] == "auth.example.test"
    assert hub.world.registered_redirects == [body["redirect_uri"]]
    assert page.status_code == 200 and "Signed in to remote" in page.text
    status = hub.client.get("/api/admin/mcp/remote/oauth", headers=_HDR).json()
    assert status["signed_in"] and status["refreshable"] and "at-1" not in json.dumps(status)
    assert any(r["action"] == "mcp.oauth.sign_in" for r in hub.orch.intent_log.rows)
    # Tokens live in the secret store only, never in the saved configuration.
    assert "at-1" not in json.dumps(hub.orch.mcp.to_config())
    store = cat._store()
    assert store.get("mcp.oauth.remote.access") == "at-1"
    assert b"at-1" not in Path(store.path).read_bytes()

    srv = hub.orch.mcp.servers["remote"]
    assert asyncio.run(srv.connect()) is True
    bearer = [r for r in hub.world.requests if r.headers.get("authorization", "").startswith("Bearer ")]
    assert bearer and {r.headers["host"] for r in bearer} == {"mcp.example.test"}

    # Expired → refreshed once, the new token used.
    meta = json.loads(store.get("mcp.oauth.remote.meta"))
    meta["expires_at"] = int(time.time()) - 5
    store.set("mcp.oauth.remote.meta", json.dumps(meta))
    token, reason = asyncio.run(oc.access_token("remote", MCP_URL))
    assert (token, reason) == ("at-2", None) and store.get("mcp.oauth.remote.refresh") == "rt-2"

    out = hub.client.delete("/api/admin/mcp/remote/oauth", headers=_HDR)
    assert out.status_code == 200 and out.json()["revoked"] is True
    assert set(hub.world.revoked) == {"rt-2", "at-2"}
    assert [n for n in store.names() if n.startswith("mcp.oauth.remote.")] == ["mcp.oauth.remote.issuer_pin"]


def test_a_token_refused_mid_session_is_refreshed_once_and_the_call_retried(hub):
    _add_http(hub)
    _sign_in(hub)
    srv = hub.orch.mcp.servers["remote"]
    assert asyncio.run(srv.connect()) is True

    async def calls():
        hub.world.access.discard("at-1")      # the server stops accepting the first token
        return await asyncio.gather(*(srv.request("tools/list", {}) for _ in range(3)))

    replies = asyncio.run(calls())
    assert all("result" in r for r in replies)
    refreshes = [r for r in hub.world.requests if r.url.path == "/token"
                 and b"grant_type=refresh_token" in r.content]
    assert len(refreshes) == 1
    assert cat._store().get("mcp.oauth.remote.access") == "at-2"


def test_remove_revokes_tokens(hub):
    _add_http(hub)
    _sign_in(hub)
    r = hub.client.delete("/api/admin/mcp/remote", headers=_HDR)
    assert r.status_code == 200 and r.json()["oauth_revoked"] is True
    assert "rt-1" in hub.world.revoked
    assert not oc.has_tokens("remote")


def test_state_mismatch_foreign_binding_and_replay_are_refused(hub):
    _add_http(hub)
    start = hub.client.post("/api/admin/mcp/remote/oauth/start", json={"redirect": "hub"}, headers=_HDR).json()
    code, state = hub.world.authorize(start["authorization_url"])
    bad_state = hub.client.get(f"/api/oauth/mcp/callback?code={code}&state=forged-state-value")
    assert bad_state.status_code == 400 and not oc.has_tokens("remote")
    # A browser without the start's cookie (another person's browser): refused, flow kept.
    foreign = TestClient(web.app, base_url="https://hub.local")
    stranger = foreign.get(f"/api/oauth/mcp/callback?code={code}&state={state}")
    assert stranger.status_code == 403 and not oc.has_tokens("remote") and oc.pending("remote")
    relay_wrong = hub.client.post("/api/admin/mcp/remote/oauth/callback",
                                  json={"state": state, "code": code, "binding": "x" * 40}, headers=_HDR)
    assert relay_wrong.status_code == 403
    ok = hub.client.post("/api/admin/mcp/remote/oauth/callback",
                         json={"state": state, "code": code, "binding": start["binding"]}, headers=_HDR)
    assert ok.status_code == 200 and oc.has_tokens("remote")
    replay = hub.client.post("/api/admin/mcp/remote/oauth/callback",
                             json={"state": state, "code": code, "binding": start["binding"]}, headers=_HDR)
    assert replay.status_code == 400 and replay.json()["error"] == "unknown_state"


def test_token_is_sent_only_to_its_origin(hub, world):
    _add_http(hub)
    _sign_in(hub)
    other = MCPServer("remote", transport="streamable-http", url="https://other.example.test/mcp", auth="oauth")
    headers, refusal = asyncio.run(oc.connect_headers(other))
    assert refusal == "token_origin_mismatch" and "Authorization" not in headers
    # The authorization server never receives the access token as a bearer.
    assert not [r for r in world.requests if r.headers.get("host") == "auth.example.test"
                and r.headers.get("authorization", "").startswith("Bearer")]


@pytest.mark.parametrize("change, reason", [
    ({"prm_resource": "https://evil.example.test/mcp"}, "resource_mismatch"),
    ({"issuer": "https://evil.example.test"}, "issuer_mismatch"),
    ({"methods": ["plain"]}, "pkce_unsupported"),
    ({"registration": False}, "client_registration_unavailable"),
])
def test_discovery_refusals(hub, world, change, reason):
    for key, value in change.items():
        setattr(world, key, value)
    _add_http(hub)
    r = hub.client.post("/api/admin/mcp/remote/oauth/start", json={"redirect": "hub"}, headers=_HDR)
    assert r.status_code >= 400 and r.json()["error"] == reason
    assert not oc.pending("remote")


def test_a_pinned_client_signs_in_without_registration(hub, world):
    world.registration = False
    r = hub.client.post("/api/admin/mcp", json={
        "name": "pinned", "transport": "streamable-http", "url": MCP_URL, "auth": "oauth",
        "oauth": {"client_id": "cid-1", "client_secret": "cs-owner-typed", "scope": "read"}}, headers=_HDR)
    assert r.status_code == 200, r.text
    assert "cs-owner-typed" not in json.dumps(hub.saved[-1])
    assert hub.orch.mcp.servers["pinned"].oauth["client_secret"] == "${OAUTH_CLIENT_SECRET}"
    _, page = _sign_in(hub, "pinned")
    assert page.status_code == 200 and oc.has_tokens("pinned")
    token_call = [r for r in world.requests if r.url.path == "/token"][-1]
    assert b"client_secret=cs-owner-typed" in token_call.content
    assert not [r for r in world.requests if r.url.path == "/register"]
    bad = hub.client.post("/api/admin/mcp", json={"name": "bad", "transport": "streamable-http", "url": MCP_URL,
                                                  "oauth": {"client_secret": "x"}}, headers=_HDR)
    assert bad.status_code == 400


def test_sign_in_refused_under_estop(hub, monkeypatch):
    from agents.core import estop

    _add_http(hub)
    monkeypatch.setattr(estop, "is_engaged", lambda: True)
    r = hub.client.post("/api/admin/mcp/remote/oauth/start", json={"redirect": "hub"}, headers=_HDR)
    assert r.status_code == 409 and r.json()["error"] == "estop_engaged"


def test_pending_flows_are_capped(hub):
    for i in range(oc.MAX_PENDING):
        _add_http(hub, f"r{i}")
        assert hub.client.post(f"/api/admin/mcp/r{i}/oauth/start", json={"redirect": "hub"},
                               headers=_HDR).status_code == 200
    _add_http(hub, "r9")
    r = hub.client.post("/api/admin/mcp/r9/oauth/start", json={"redirect": "hub"}, headers=_HDR)
    assert r.status_code == 429


# ── the callback relay (H692) ────────────────────────────────────────────────

@pytest.mark.parametrize("uri", [
    "https://evil.example/cb", "http://evil.example:8080/cb", "http://127.0.0.1/cb",
    "http://127.0.0.1:8080/cb?next=https://evil.example", "http://127.0.0.1:80/cb",
    "http://user@127.0.0.1:8080/cb", "javascript:alert(1)", "http://127.0.0.1:8080/cb#x",
])
def test_relay_refuses_open_redirects(hub, uri):
    _add_http(hub)
    r = hub.client.post("/api/admin/mcp/remote/oauth/start", json={"redirect": "loopback", "redirect_uri": uri},
                        headers=_HDR)
    assert r.status_code == 400 and r.json()["error"] == "invalid_redirect"


def test_loopback_relay_completes_with_the_binding(hub):
    _add_http(hub)
    uri = "http://127.0.0.1:47123/callback"
    start = hub.client.post("/api/admin/mcp/remote/oauth/start", json={"redirect": "loopback", "redirect_uri": uri},
                            headers=_HDR).json()
    assert start["relay"] is True and hub.world.registered_redirects == [uri]
    code, state = hub.world.authorize(start["authorization_url"])
    # A relay for another server's flow is refused.
    _add_http(hub, "other")
    cross = hub.client.post("/api/admin/mcp/other/oauth/callback",
                            json={"state": state, "code": code, "binding": start["binding"]}, headers=_HDR)
    assert cross.status_code == 403 and cross.json()["error"] == "server_mismatch"
    ok = hub.client.post("/api/admin/mcp/remote/oauth/callback",
                         json={"state": state, "code": code, "binding": start["binding"]}, headers=_HDR)
    assert ok.status_code == 200 and ok.json()["relay"] is True
    assert any(r["metadata"].get("via") == "relay" for r in hub.orch.intent_log.rows)


def test_callback_page_never_redirects(hub):
    r = hub.client.get("/api/oauth/mcp/callback?state=whatever&code=x&next=https://evil.example",
                       follow_redirects=False)
    assert r.status_code == 400 and "location" not in r.headers


# ── secrets stay internal ────────────────────────────────────────────────────

def test_mcp_secrets_are_not_handles():
    from agents.core.security.secret_broker import SecretBroker

    class Store(dict):
        def set(self, k, v):
            self[k] = v

        def names(self):
            return sorted(self)

        def delete(self, k):
            return self.pop(k, None) is not None

    store = Store({"mcp.oauth.x.access": "tok-value-123456", "mcp.secret.x.KEY": "sec-value-123456"})
    broker = SecretBroker(store)
    assert broker.names() == []
    out = broker.inject("{{secret:mcp.oauth.x.access}} {{secret:mcp.secret.x.KEY}}", approved=True)
    assert "tok-value" not in out["text"] and "sec-value" not in out["text"]
    assert "tok-value-123456" not in broker.redact("leak tok-value-123456")
    with pytest.raises(ValueError):
        broker.put("mcp.secret.x.KEY", "v")


# ── the vendor mode ──────────────────────────────────────────────────────────

def test_vendor_mcp_catalog_mode_refuses_a_folder_with_code(tmp_path):
    sys.path.insert(0, str(repo_root / "scripts"))
    import io

    import hermes_vendor as hv

    up = tmp_path / "up"
    (up / "optional-mcps" / "ok").mkdir(parents=True)
    (up / "optional-mcps" / "ok" / "manifest.yaml").write_text("manifest_version: 1\nname: ok\n")
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    out = io.StringIO()
    assert hv.main(["mcp-catalog", "--upstream", str(up), "--commit", "a" * 40], vendor_root=vendor, out=out) == 0
    manifest = json.loads((vendor / "MANIFEST.json").read_text())
    assert [f["path"] for f in manifest["files"]] == ["optional-mcps/ok/manifest.yaml"]
    (up / "optional-mcps" / "ok" / "run.sh").write_text("curl x | sh\n")
    out = io.StringIO()
    assert hv.main(["mcp-catalog", "--upstream", str(up), "--commit", "a" * 40], vendor_root=vendor, out=out) == 2
    assert "only manifest.yaml" in out.getvalue()
    assert hv.content_problems(b"x: 1\n", "optional-mcps/ok/run.py")


# ── the CLI (`nerva mcp catalog | install | login`) ──────────────────────────

class _Hub:
    """Forwards the CLI's requests to the real routes through the TestClient."""

    def __init__(self, client, on_start=None):
        self.client = client
        self.on_start = on_start
        self.calls = []

    def request(self, method, path, body=None, **kw):
        self.calls.append((method, path, body))
        r = self.client.request(method, path, json=body, headers=_HDR)
        if r.status_code >= 400:
            from agents.cli.client import HubError

            raise HubError(r.status_code, r.json().get("error", ""))
        data = r.json()
        if path.endswith("/oauth/start") and self.on_start:
            self.on_start(data)
        return data

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body if body is not None else {})


def _cli(hub_client, argv, stdin=""):
    import io

    from agents.cli.nerva import Context, main

    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(stdin), client_factory=lambda env: hub_client)
    return main(argv, context=ctx), out.getvalue(), err.getvalue()


def test_cli_catalog_and_install_shows_the_plan_and_asks(hub):
    code, out, _ = _cli(_Hub(hub.client), ["mcp", "catalog", "--search", "context7"])
    assert code == 0 and "context7" in out and "mcp.context7.com" in out
    code, out, _ = _cli(_Hub(hub.client), ["mcp", "install", "context7"], stdin="n\n")
    assert code != 0 and "will connect over HTTPS to https://mcp.context7.com/mcp" in out
    assert "context7" not in hub.orch.mcp.servers
    code, out, _ = _cli(_Hub(hub.client), ["mcp", "install", "context7"], stdin="y\n")
    assert code == 0 and "context7" in hub.orch.mcp.servers


def test_cli_login_relays_only_code_and_state(hub):
    import threading
    import urllib.request

    _add_http(hub)

    def browser(start):
        code, state = hub.world.authorize(start["authorization_url"])
        redirect = start["redirect_uri"]
        assert redirect.startswith("http://127.0.0.1:")

        def go():
            time.sleep(0.2)
            urllib.request.urlopen(f"{redirect}?code={code}&state={state}", timeout=5).read()  # nosec B310

        threading.Thread(target=go, daemon=True).start()

    fake = _Hub(hub.client, on_start=browser)
    code, out, err = _cli(fake, ["mcp", "login", "remote", "--no-browser"])
    assert code == 0, err
    assert "Signed in to 'remote'" in out and oc.has_tokens("remote")
    relay = [c for c in fake.calls if c[1].endswith("/oauth/callback")][0][2]
    assert set(relay) == {"state", "binding", "code"}


# ── review fixes: SSRF via metadata, mix-up, issuer pin, pinned redirects ────

def test_a_public_servers_metadata_cannot_point_at_local_addresses(hub, world):
    world.meta_overrides = {"registration_endpoint": "http://127.0.0.1:8080/api/ops/estop/resume",
                            "revocation_endpoint": "http://127.0.0.1:8080/api/admin/memory/clear"}
    _add_http(hub)
    r = hub.client.post("/api/admin/mcp/remote/oauth/start", json={"redirect": "hub"}, headers=_HDR)
    assert r.status_code == 400 and r.json()["error"] == "insecure_endpoint"
    assert not [q for q in world.requests if "127.0.0.1" in q.headers.get("host", "")]


@pytest.mark.parametrize("url, server, hub_origin, ok", [
    ("http://127.0.0.1:9000/token", "https://mcp.example.test/mcp", None, False),   # public server → local AS
    ("http://192.168.1.5/token", "https://mcp.example.test/mcp", None, False),
    ("http://127.0.0.1:9000/token", "http://127.0.0.1:9000/mcp", None, True),       # same local host
    ("http://localhost:9000/token", "http://127.0.0.1:9000/mcp", None, True),
    ("http://127.0.0.1:8080/token", "http://127.0.0.1:9000/mcp", "https://hub.local:8080", False),  # hub port
    ("https://hub.local/token", "https://mcp.example.test/mcp", "https://hub.local", False),        # hub itself
    ("http://auth.example.test/token", "https://mcp.example.test/mcp", None, False),                # not https
    ("https://auth.example.test/to\x1b[2Jken", "https://mcp.example.test/mcp", None, False),       # control chars
    ("https://auth.example.test/token", "https://mcp.example.test/mcp", None, True),
])
def test_endpoint_policy(url, server, hub_origin, ok):
    assert (oc.endpoint_problem(url, server_url=server, hub_origin=hub_origin) is None) is ok


def test_endpoints_must_belong_to_the_issuer(hub, world):
    world.meta_overrides = {"authorization_endpoint": "https://github.com/login/oauth/authorize"}
    _add_http(hub)
    r = hub.client.post("/api/admin/mcp/remote/oauth/start", json={"redirect": "hub"}, headers=_HDR)
    assert r.json()["error"] == "endpoint_not_on_issuer"
    assert not [q for q in world.requests if q.url.path in ("/register", "/token")]
    assert oc._on_issuer("https://login.example.co.uk/a", "https://auth.example.co.uk")
    assert not oc._on_issuer("https://evil.co.uk/a", "https://auth.example.co.uk")


def test_rfc9207_issuer_in_the_response(hub, world):
    world.meta_overrides = {"authorization_response_iss_parameter_supported": True}
    _add_http(hub)
    start = hub.client.post("/api/admin/mcp/remote/oauth/start", json={"redirect": "hub"}, headers=_HDR).json()
    assert start["authorize_host"] == "auth.example.test"
    code, state = world.authorize(start["authorization_url"])
    wrong = hub.client.post("/api/admin/mcp/remote/oauth/callback", json={
        "state": state, "code": code, "binding": start["binding"], "iss": "https://github.com"}, headers=_HDR)
    assert wrong.json()["error"] == "issuer_mismatch" and not oc.has_tokens("remote")
    assert not [q for q in world.requests if q.url.path == "/token"]
    start = hub.client.post("/api/admin/mcp/remote/oauth/start", json={"redirect": "hub"}, headers=_HDR).json()
    code, state = world.authorize(start["authorization_url"])
    missing = hub.client.post("/api/admin/mcp/remote/oauth/callback", json={
        "state": state, "code": code, "binding": start["binding"]}, headers=_HDR)
    assert missing.json()["error"] == "issuer_missing"
    start = hub.client.post("/api/admin/mcp/remote/oauth/start", json={"redirect": "hub"}, headers=_HDR).json()
    code, state = world.authorize(start["authorization_url"])
    page = hub.client.get(f"/api/oauth/mcp/callback?code={code}&state={state}&iss={AS}")
    assert page.status_code == 200 and oc.has_tokens("remote")


def test_plain_http_hub_callback_only_on_loopback(hub):
    _add_http(hub)
    plain = TestClient(web.app, base_url="http://192.168.1.5:8080")
    r = plain.post("/api/admin/mcp/remote/oauth/start", json={"redirect": "hub"}, headers=_HDR)
    assert r.status_code == 400 and r.json()["error"] == "insecure_redirect"
    local = TestClient(web.app, base_url="http://127.0.0.1:8080")
    assert local.post("/api/admin/mcp/remote/oauth/start", json={"redirect": "hub"}, headers=_HDR).status_code == 200


def test_revocation_is_skipped_under_estop_but_tokens_go(hub, world, monkeypatch):
    from agents.core import estop

    _add_http(hub)
    _sign_in(hub)
    monkeypatch.setattr(estop, "is_engaged", lambda: True)
    r = hub.client.delete("/api/admin/mcp/remote", headers=_HDR)
    assert r.status_code == 200 and r.json()["oauth_revoked"] == "skipped_estop"
    assert world.revoked == [] and not oc.has_tokens("remote")


def test_the_first_issuer_is_pinned(hub, world):
    _add_http(hub)
    _sign_in(hub)
    assert hub.client.delete("/api/admin/mcp/remote/oauth", headers=_HDR).status_code == 200
    assert cat._store().get("mcp.oauth.remote.issuer_pin") == AS       # kept past sign-out
    cat._store().set("mcp.oauth.remote.issuer_pin", "https://other.example.test")
    r = hub.client.post("/api/admin/mcp/remote/oauth/start", json={"redirect": "hub"}, headers=_HDR)
    assert r.json()["error"] == "issuer_changed"
    assert hub.client.delete("/api/admin/mcp/remote", headers=_HDR).status_code == 200
    assert cat._store().get("mcp.oauth.remote.issuer_pin") is None     # removal forgets it


def test_one_dynamic_client_per_server(hub, world):
    _add_http(hub)
    for _ in range(2):
        _sign_in(hub)
    start = hub.client.post("/api/admin/mcp/remote/oauth/start",
                            json={"redirect": "loopback", "redirect_uri": "http://127.0.0.1:47123/callback"},
                            headers=_HDR).json()
    assert world.registrations == 2 and set(world.registered_redirects) == {
        "https://hub.local/api/oauth/mcp/callback", "http://127.0.0.1:47123/callback"}
    status = hub.client.get("/api/admin/mcp/remote/oauth", headers=_HDR).json()
    assert status["loopback_redirects"] == ["http://127.0.0.1:47123/callback"] and start["state"]


def test_asana_installs_with_its_client_id_and_pinned_redirect(hub, world):
    world.registration = False
    plan = hub.client.post("/api/admin/mcp/catalog/preview",
                           json={"name": "asana", "inputs": {"ASANA_CLIENT_ID": "cid-1"}}, headers=_HDR).json()["plan"]
    assert plan["oauth"]["client_id"] == "cid-1" and plan["oauth"]["client_secret"] == "${ASANA_CLIENT_SECRET}"
    assert "hermes" not in plan["post_install"].lower() and "nerva mcp login asana" in plan["post_install"]
    r = hub.client.post("/api/admin/mcp/catalog/install", json={
        "name": "asana", "inputs": {"ASANA_CLIENT_ID": "cid-1"}, "confirm": plan["digest"],
        "secrets": {"ASANA_CLIENT_SECRET": "cs-asana"}}, headers=_HDR)
    assert r.status_code == 200, r.text
    saved = json.dumps(hub.saved[-1])
    assert "cid-1" in saved and "cs-asana" not in saved
    srv = hub.orch.mcp.servers["asana"]
    srv.url = MCP_URL                        # point the installed server at the fake world
    status = hub.client.get("/api/admin/mcp/asana/oauth", headers=_HDR).json()
    assert status["redirect_pin"] == "http://localhost:27890/callback"
    hubbed = hub.client.post("/api/admin/mcp/asana/oauth/start", json={"redirect": "hub"}, headers=_HDR)
    assert hubbed.json()["error"] == "redirect_pinned"
    start = hub.client.post("/api/admin/mcp/asana/oauth/start", json={
        "redirect": "loopback", "redirect_uri": "http://localhost:27890/callback"}, headers=_HDR)
    assert start.status_code == 200, start.text
    code, state = world.authorize(start.json()["authorization_url"])
    ok = hub.client.post("/api/admin/mcp/asana/oauth/callback",
                         json={"state": state, "code": code, "binding": start.json()["binding"]}, headers=_HDR)
    assert ok.status_code == 200 and b"client_secret=cs-asana" in [
        q for q in world.requests if q.url.path == "/token"][-1].content


def test_cli_listener_ignores_a_request_without_the_state(hub):
    import threading
    import urllib.error
    import urllib.request

    _add_http(hub)
    codes = []

    def browser(start):
        code, state = hub.world.authorize(start["authorization_url"])
        redirect = start["redirect_uri"]

        def go():
            time.sleep(0.2)
            try:
                urllib.request.urlopen(f"{redirect}?code=evil&state=forged", timeout=5)  # nosec B310
            except urllib.error.HTTPError as exc:
                codes.append(exc.code)
            urllib.request.urlopen(f"{redirect}?code={code}&state={state}", timeout=5).read()  # nosec B310

        threading.Thread(target=go, daemon=True).start()

    code, out, err = _cli(_Hub(hub.client, on_start=browser), ["mcp", "login", "remote", "--no-browser"])
    assert code == 0, err
    assert codes == [400] and oc.has_tokens("remote")


def test_review_nits():
    with pytest.raises(cat.CatalogError):
        cat.parse_link_config("p", _link({"command": "npx", "env": {"npm_config_registry": "https://x"}}))
    with pytest.raises(cat.CatalogError):
        cat.parse_link_config("p", _link({"command": "npx", "env": {"GIT_SSH_COMMAND": "x"}}))
    assert "nerva mcp login linear" in cat.for_nerva("run `hermes mcp login linear`")


def test_server_names_have_no_dots(hub):
    r = hub.client.post("/api/admin/mcp", json={"name": "a.b", "transport": "stdio", "command": "x"}, headers=_HDR)
    assert r.status_code == 400 and r.json()["error"] == "invalid_name"
