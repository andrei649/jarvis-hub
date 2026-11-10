"""Owner settings govern the real HTTP, browser and ToolRPC entry points."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import agents.web as web
from agents.core import settings_db, web_tools
from agents.core.browser_agent import BrowserPolicy
from agents.core.http_client import PluginEgressError, PluginHTTPClient, RequiredEgressHTTPClient
from agents.core.resilience import CircuitBreaker
from agents.core.tool_rpc import ToolRPCServer


@pytest.fixture
def owner(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(web, "ADMIN_TOKEN", "owner-h492")
    monkeypatch.setattr(web, "USER_TOKEN", "reader-h492")
    monkeypatch.setattr(web, "orch", SimpleNamespace(intent_log=None))
    monkeypatch.delenv("JARVIS_WEB_BLOCKED_DOMAINS", raising=False)
    monkeypatch.setenv("JARVIS_SAFE_MODE", "0")
    settings_db.init_db()
    return TestClient(web.app), {"X-Admin-Token": "owner-h492"}


def _configure(owner, value):
    client, headers = owner
    response = client.get("/api/admin/settings/security", headers=headers)
    assert response.status_code == 200
    row = next((r for r in response.json()["security"] if r["key"] == "website_blocklist"), None)
    assert row is not None and row["kind"] == "json"
    response = client.put("/api/admin/settings/security",
                          json={"values": {"website_blocklist": value}}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 1
    return client, headers


def test_website_policy_owner_auth_and_invalid_value_leave_persisted_policy_intact(owner):
    value = {"enabled": True, "domains": ["blocked.example"], "shared_files": []}
    client, headers = _configure(owner, value)
    for request_headers in ({}, {"X-User-Token": "reader-h492"}):
        denied = client.put("/api/admin/settings/security",
                            json={"values": {"website_blocklist": {"enabled": False}}},
                            headers=request_headers)
        assert denied.status_code == 401
    bad = client.put("/api/admin/settings/security",
                     json={"values": {"website_blocklist": {
                         "enabled": True, "domains": "not a list", "shared_files": []}}}, headers=headers)
    assert bad.status_code == 422
    assert settings_db.read_setting("security", "website_blocklist") == (True, value)


class _WebPlugin:
    tavily_api_key = "synthetic-key"
    searxng_url = ""

    def __init__(self):
        self.search_calls = []
        self.fetch_calls = []

    async def search(self, query, max_results=5):
        self.search_calls.append(query)
        return [{"title": "blocked", "url": "https://blocked.example/page"},
                {"title": "allowed", "url": "https://allowed.example/page"}]

    async def fetch_page(self, url, *, max_chars=8000):
        self.fetch_calls.append(url)
        return "A synthetic page."


@pytest.mark.parametrize("strict,safe_mode", [("0", "0"), ("1", "0"), ("1", "1")])
async def test_owner_website_denial_reaches_http_browser_and_real_web_tools(
    owner, monkeypatch, strict, safe_mode,
):
    _configure(owner, {"enabled": True, "domains": ["blocked.example"], "shared_files": []})
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", strict)
    monkeypatch.setenv("JARVIS_SAFE_MODE", safe_mode)
    resolutions, requests = [], []

    def resolver(host, *, mode):
        resolutions.append(host)
        return ["93.184.216.34"], None

    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=b"must not be fetched")

    client = PluginHTTPClient(
        "h492-owner-entry", circuit_breaker=CircuitBreaker(key="h492-owner-entry"),
        resolver=resolver, transport_factory=lambda target: httpx.MockTransport(respond),
    )
    try:
        with pytest.raises(PluginEgressError, match="website_blocked"):
            await client.get("https://blocked.example/page")
        assert resolutions == requests == []
    finally:
        await client.close()

    from agents.core.security import ssrf

    monkeypatch.setattr(ssrf, "check_ssrf", lambda _url: pytest.fail("blocked browser target reached DNS guard"))
    assert BrowserPolicy(["blocked.example"]).domain_allowed("https://blocked.example/page") == (
        False, "website_blocked")

    plugin = _WebPlugin()
    server = ToolRPCServer()
    web_tools.register_web_tools(server, lambda: plugin)
    refused = await server.handle({"tool": "web_extract", "args": {"url": "https://blocked.example/page"}})
    assert refused["ok"] is True and refused["result"]["reason"] == "site_blocked"
    assert plugin.fetch_calls == []
    found = await server.handle({"tool": "web_search", "args": {"query": "synthetic"}})
    assert found["ok"] is True
    assert found["result"]["count"] == 1 and found["result"]["blocked"] == 1
    assert [row["url"] for row in found["result"]["results"]] == ["https://allowed.example/page"]
    assert plugin.search_calls == ["synthetic"]


async def test_unavailable_enabled_policy_prevents_a_tool_query_instead_of_empty_success(owner, tmp_path):
    _configure(owner, {"enabled": True, "domains": [],
                       "shared_files": [str(tmp_path / "missing-shared-list.txt")]})
    plugin = _WebPlugin()
    server = ToolRPCServer()
    web_tools.register_web_tools(server, lambda: plugin)
    result = await server.handle({"tool": "web_search", "args": {"query": "synthetic"}})
    assert result["ok"] is True
    assert result["result"]["reason"] == "website_policy_unavailable"
    assert result["result"].get("ok") is False or result["result"].get("available") is False
    assert plugin.search_calls == plugin.fetch_calls == []


async def test_saved_owner_edit_rechecks_an_already_used_client_before_any_more_io(owner):
    _configure(owner, {"enabled": False, "domains": [], "shared_files": []})
    dns, sent, granted = [], [], []

    def resolve(host, *, mode):
        dns.append(host)
        return ["93.184.216.34"], None

    def respond(request):
        sent.append(request)
        return httpx.Response(200, content=b"allowed before the owner edit")

    client = RequiredEgressHTTPClient(
        "h492-owner-edit", authorize_egress=lambda *args: granted.append(args),
        circuit_breaker=CircuitBreaker(key="h492-owner-edit"), resolver=resolve,
        transport_factory=lambda target: httpx.MockTransport(respond),
    )
    try:
        assert (await client.get("https://blocked.example/page")).status_code == 200
        assert len(dns) == len(sent) == len(granted) == 1
        _configure(owner, {"enabled": True, "domains": ["blocked.example"], "shared_files": []})
        with pytest.raises(PluginEgressError, match="website_blocked"):
            await client.get("https://blocked.example/page")
        assert len(dns) == len(sent) == len(granted) == 1
    finally:
        await client.close()
