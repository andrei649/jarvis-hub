"""H310 / H537 / H607 — web_search and web_extract at the accepted Hermes contract.

What this file proves, offline (no socket is opened; every dial goes to an
``httpx.MockTransport`` or a fake provider):

* search runs through one provider ABC and registry: the three built-ins register
  through it, a first-party plugin can add a backend that ``JARVIS_WEB_BACKEND``
  selects, and registration is refused for an egress identity with no manifest or a
  manifest that may reach the whole web;
* the selector, the free/paid tier pin and the one-shot rescue are read per call;
  a provider *failure* may be rescued, a *policy block* never is;
* a TTL cache stops a repeat query from reaching (and billing) the provider again;
* ``web_extract`` reads up to five URLs, cuts each page head+tail at a 15,000-char
  default, keeps the whole result under the declared 100,000 bytes, writes the full
  text to the tool-result store and names it in a footer that promises ``file_read``
  only when ``file_read`` can open it; the page cache re-cuts from the full text;
* PDFs are read through the optional ``pypdf`` (a fake module here — no live PDF is
  claimed), in a worker thread, page-bounded, refused by name when cut or unparsable;
* a kernel deny on ``plugin.egress`` turns both tools into refusals with no dial.
"""

import asyncio
import hashlib
import json
import sys
import threading
import time
import types
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import web_tools as wt  # noqa: E402
from agents.core.plugins import web_providers as wp  # noqa: E402
from agents.core.plugins import websearch as ws  # noqa: E402
from agents.core.tool_result_store import ToolResultStore  # noqa: E402
from agents.core.tool_rpc import ToolRPCServer  # noqa: E402

PUBLIC_IP = (["93.184.216.34"], None)


@pytest.fixture(autouse=True)
def _clean_web_env(monkeypatch):
    for name in (wp.BACKEND_ENV, wp.TIER_ENV, wp.RESCUE_ENV, wp.BLOCKED_DOMAINS_ENV,
                 "TAVILY_API_KEY", "SEARXNG_URL"):
        monkeypatch.delenv(name, raising=False)


async def _call(server, tool, args):
    return await server.handle({"tool": tool, "args": args})


def _server(plugin, **kw):
    server = ToolRPCServer()
    wt.register_web_tools(server, lambda: plugin, **kw)
    return server


class Recorder(wp.SearchProvider):
    """A provider whose answers are scripted; it records what it was handed."""

    def __init__(self, name, *, tier="free", rows=None, raises=None, plugin_id="websearch",
                 configured=True):
        self.name = name
        self.tier = tier
        self.plugin_id = plugin_id
        self._rows = rows if rows is not None else [
            {"title": f"{name} hit", "url": f"https://{name}.example/r", "snippet": "s"}]
        self._raises = raises
        self._configured = configured
        self.calls: list[tuple] = []

    def configured(self, plugin) -> bool:
        return self._configured

    async def search(self, client, plugin, query, max_results):
        self.calls.append((client.plugin_name, query, max_results))
        if self._raises is not None:
            raise self._raises
        return [dict(r) for r in self._rows]


@pytest.fixture
def swap_builtins(monkeypatch):
    """Replace the three built-ins with recorders for one test (registry order kept)."""

    def _swap(**overrides):
        swapped = {}
        for name in ("tavily", "searxng", "duckduckgo"):
            original = wp.get_search_provider(name)
            fake = overrides.get(name) or Recorder(name, tier=original.tier)
            fake.keyless = original.keyless
            fake.configured = original.configured          # the real configured() rule
            monkeypatch.setitem(wp._REGISTRY, name, fake)
            swapped[name] = fake
        return swapped

    return _swap


# ── the provider ABC and registry (H537) ─────────────────────────────────────

def test_builtins_register_through_the_one_registry():
    names = wp.search_providers()
    assert names[:3] == ("tavily", "searxng", "duckduckgo")
    for name in names[:3]:
        provider = wp.get_search_provider(name)
        assert isinstance(provider, wp.SearchProvider)
        assert provider.plugin_id == "websearch"
    assert wp.get_search_provider("tavily").tier == "paid"
    assert wp.get_search_provider("searxng").tier == "free"
    assert wp.get_search_provider("duckduckgo").keyless is True
    # x_search is excluded by the accepted scope and must not come back.
    assert "x_search" not in names and "xai" not in names


def test_registration_refuses_unmanifested_full_network_and_duplicate_identities():
    with pytest.raises(ValueError, match="manifest"):
        wp.register_search_provider(Recorder("ghost", plugin_id="no-such-plugin"))
    # webread may reach the whole web by declaration: a search backend on it would be a
    # second, unallowlisted egress route around the websearch manifest.
    with pytest.raises(ValueError, match="network"):
        wp.register_search_provider(Recorder("wide", plugin_id="webread"))
    with pytest.raises(ValueError, match="already"):
        wp.register_search_provider(Recorder("tavily"))
    with pytest.raises(ValueError, match="name"):
        wp.register_search_provider(Recorder("Bad Name!"))
    with pytest.raises(ValueError, match="tier"):
        wp.register_search_provider(Recorder("tiered", tier="gold"))
    assert "ghost" not in wp.search_providers() and "wide" not in wp.search_providers()


async def test_a_first_party_provider_is_selectable_tainted_and_dials_its_own_allowlisted_identity(
    monkeypatch,
):
    """A first-party plugin registers a backend; JARVIS_WEB_BACKEND selects it; it is
    handed the websearch PluginHTTPClient, so the manifest allowlist (plus the host the
    plugin registered dynamically) bounds where it can go — and a host outside it is a
    policy block that is never rescued."""
    from agents.core.http_client import PluginHTTPClient
    from agents.core.plugin_gate import register_dynamic_domain

    dialed = []

    def handler(request):
        dialed.append(request.headers.get("host"))
        return httpx.Response(200, json={"items": [
            {"name": "LAN result", "link": "https://lan.example/doc", "text": "body"}]})

    class LanIndex(wp.SearchProvider):
        name = "lan-index"
        plugin_id = "websearch"
        tier = "free"

        def __init__(self, base):
            self.base = base

        def configured(self, plugin):
            return True

        async def search(self, client, plugin, query, max_results):
            assert client.plugin_name == "websearch"
            resp = await wp.classified(client.get(f"{self.base}/q", params={"q": query}))
            return [{"title": i["name"], "url": i["link"], "snippet": i["text"]}
                    for i in resp.json()["items"]][:max_results]

    # The suite runs with strict egress downgraded (conftest); production is strict.
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "1")
    register_dynamic_domain("websearch", "http://index.lan.test:8080")
    good = LanIndex("http://index.lan.test:8080")
    wp.register_search_provider(good)
    try:
        plugin = ws.WebSearchPlugin()
        plugin._client = PluginHTTPClient(
            "websearch", resolver=lambda host, *a, **k: PUBLIC_IP,
            transport_factory=lambda _t: httpx.MockTransport(handler),
        )
        monkeypatch.setenv(wp.BACKEND_ENV, "lan-index")
        out = await _call(_server(plugin), wt.TOOL_SEARCH, {"query": "manual"})
        result = out["result"]
        assert result["available"] is True and result["provider"] == "lan-index"
        assert result["results"][0]["url"] == "https://lan.example/doc"
        assert result["results"][0]["tainted"] is True
        assert dialed == ["index.lan.test:8080"]
        # The same provider pointed at a host the manifest does not allow is a policy
        # block: refused by name, and the rescue path is not taken.
        good.base = "http://elsewhere.test"
        rescue = Recorder("duckduckgo")
        monkeypatch.setitem(wp._REGISTRY, "duckduckgo", rescue)
        monkeypatch.setenv(wp.RESCUE_ENV, "1")
        out = await _call(_server(plugin), wt.TOOL_SEARCH, {"query": "manual again"})
        assert out["result"]["ok"] is False and out["result"]["reason"] == "policy_blocked"
        assert out["result"]["provider"] == "lan-index"
        assert rescue.calls == [] and dialed == ["index.lan.test:8080"]
    finally:
        wp.unregister_search_provider("lan-index")
    assert "lan-index" not in wp.search_providers()


# ── the selector, the tier pin, the rescue (H310 / H607 / H537) ──────────────

async def test_backend_selector_is_read_per_call_and_forces_the_named_backend(
    monkeypatch, swap_builtins,
):
    fakes = swap_builtins()
    plugin = ws.WebSearchPlugin(tavily_api_key="k", searxng_url="http://searx.local")
    server = _server(plugin)
    out = await _call(server, wt.TOOL_SEARCH, {"query": "a"})
    assert out["result"]["provider"] == "tavily"          # auto keeps today's priority
    monkeypatch.setenv(wp.BACKEND_ENV, "duckduckgo")
    out = await _call(server, wt.TOOL_SEARCH, {"query": "b"})
    assert out["result"]["provider"] == "duckduckgo"      # no restart: read per call
    monkeypatch.setenv(wp.BACKEND_ENV, "SearXNG ")
    out = await _call(server, wt.TOOL_SEARCH, {"query": "c"})
    assert out["result"]["provider"] == "searxng"
    assert [c[1] for c in fakes["tavily"].calls] == ["a"]
    assert [c[1] for c in fakes["duckduckgo"].calls] == ["b"]
    assert [c[1] for c in fakes["searxng"].calls] == ["c"]


async def test_a_named_backend_that_cannot_answer_is_unavailable_with_its_reason(
    monkeypatch, swap_builtins,
):
    fakes = swap_builtins()
    plugin = ws.WebSearchPlugin(tavily_api_key="k")
    server = _server(plugin)
    for backend, detail in (("searxng", "backend_not_configured"),
                            ("bing", "unknown_backend")):
        monkeypatch.setenv(wp.BACKEND_ENV, backend)
        out = await _call(server, wt.TOOL_SEARCH, {"query": "q"})
        assert out["result"] == {
            "available": False, "ok": False, "reason": "websearch_unavailable",
            "detail": detail, "backend": backend,
        }
        assert plugin.available() is False
    assert all(not f.calls for f in fakes.values())        # nothing silently fell back


async def test_tier_pin_keeps_paid_providers_out_and_refuses_a_named_one(
    monkeypatch, swap_builtins,
):
    fakes = swap_builtins()
    plugin = ws.WebSearchPlugin(tavily_api_key="k")
    server = _server(plugin)
    monkeypatch.setenv(wp.TIER_ENV, "free")
    out = await _call(server, wt.TOOL_SEARCH, {"query": "q"})
    assert out["result"]["provider"] == "duckduckgo"       # the paid key is not used
    assert fakes["tavily"].calls == []
    # Keyless is not "configured": unattended research still sees no owner backend.
    assert plugin.available() is False
    monkeypatch.setenv(wp.BACKEND_ENV, "tavily")
    out = await _call(server, wt.TOOL_SEARCH, {"query": "q"})
    assert out["result"]["detail"] == "tier_pinned" and fakes["tavily"].calls == []
    monkeypatch.setenv(wp.TIER_ENV, "paid")
    monkeypatch.setenv(wp.BACKEND_ENV, "auto")
    out = await _call(server, wt.TOOL_SEARCH, {"query": "q2"})
    assert out["result"]["provider"] == "tavily"
    monkeypatch.setenv(wp.TIER_ENV, "platinum")
    out = await _call(server, wt.TOOL_SEARCH, {"query": "q3"})
    assert out["result"]["detail"] == "invalid_tier"


async def test_rescue_retries_a_failed_provider_once_and_never_a_policy_block(
    monkeypatch, swap_builtins,
):
    failing = Recorder("tavily", tier="paid", raises=wp.ProviderFailure("http_503"))
    fakes = swap_builtins(tavily=failing)
    plugin = ws.WebSearchPlugin(tavily_api_key="k", searxng_url="http://searx.local")
    server = _server(plugin)
    out = await _call(server, wt.TOOL_SEARCH, {"query": "q"})
    result = out["result"]
    assert result["provider"] == "searxng" and result["count"] == 1
    assert result["rescued_from"] == "tavily" and result["rescue_reason"] == "provider_failed"
    assert len(failing.calls) == 1 and len(fakes["searxng"].calls) == 1
    assert fakes["duckduckgo"].calls == []                 # one shot, not a ring

    blocked = Recorder("tavily", tier="paid", raises=wp.PolicyBlock("egress blocked"))
    fakes = swap_builtins(tavily=blocked)
    out = await _call(_server(plugin), wt.TOOL_SEARCH, {"query": "q-blocked"})
    assert out["result"] == {"available": True, "ok": False, "reason": "policy_blocked",
                             "provider": "tavily"}
    assert fakes["searxng"].calls == [] and fakes["duckduckgo"].calls == []

    # The owner can switch rescue off; a named backend is never rescued by default.
    fakes = swap_builtins(tavily=Recorder("tavily", tier="paid",
                                          raises=wp.ProviderFailure("timeout")))
    monkeypatch.setenv(wp.RESCUE_ENV, "0")
    out = await _call(_server(plugin), wt.TOOL_SEARCH, {"query": "q-off"})
    assert out["result"]["results"] == [] and out["result"]["error"] == "provider_failed"
    assert fakes["searxng"].calls == []
    monkeypatch.delenv(wp.RESCUE_ENV)
    monkeypatch.setenv(wp.BACKEND_ENV, "tavily")
    out = await _call(_server(plugin), wt.TOOL_SEARCH, {"query": "q-named"})
    assert out["result"]["error"] == "provider_failed" and fakes["searxng"].calls == []
    # ...unless the owner turns rescue on explicitly.
    monkeypatch.setenv(wp.RESCUE_ENV, "1")
    out = await _call(_server(plugin), wt.TOOL_SEARCH, {"query": "q-named-2"})
    assert out["result"]["provider"] == "searxng"


async def test_search_cache_stops_a_repeat_query_reaching_the_provider(swap_builtins, monkeypatch):
    fakes = swap_builtins()
    now = {"t": 100.0}
    plugin = ws.WebSearchPlugin(tavily_api_key="k", clock=lambda: now["t"])
    server = _server(plugin)
    first = await _call(server, wt.TOOL_SEARCH, {"query": "same"})
    second = await _call(server, wt.TOOL_SEARCH, {"query": "same"})
    assert first["result"]["cached"] is False and second["result"]["cached"] is True
    assert second["result"]["results"] == first["result"]["results"]
    assert all(r["tainted"] is True for r in second["result"]["results"])
    assert len(fakes["tavily"].calls) == 1
    await _call(server, wt.TOOL_SEARCH, {"query": "same", "max_results": 3})
    assert len(fakes["tavily"].calls) == 2                 # a different ask is a new key
    monkeypatch.setenv(wp.BACKEND_ENV, "duckduckgo")
    await _call(server, wt.TOOL_SEARCH, {"query": "same"})
    assert len(fakes["duckduckgo"].calls) == 1             # another backend, another key
    monkeypatch.delenv(wp.BACKEND_ENV)
    now["t"] += ws.SEARCH_CACHE_TTL_SECONDS + 1
    await _call(server, wt.TOOL_SEARCH, {"query": "same"})
    assert len(fakes["tavily"].calls) == 3                 # past the TTL it asks again
    # A failure is never cached.
    fakes = swap_builtins(tavily=Recorder("tavily", tier="paid",
                                          raises=wp.ProviderFailure("x")))
    monkeypatch.setenv(wp.RESCUE_ENV, "0")
    for _ in range(2):
        await _call(server, wt.TOOL_SEARCH, {"query": "fails"})
    assert len(fakes["tavily"].calls) == 2


async def test_kernel_deny_refuses_both_tools_with_no_dial(monkeypatch):
    from agents.core import http_client
    from agents.core.http_client import PluginHTTPClient

    def never(request):
        pytest.fail("a kernel-denied request must never be dialed")

    seen = []

    def hook(plugin, method, url, host):
        seen.append(plugin)
        return "emergency stop engaged"

    monkeypatch.setattr(http_client, "_EGRESS_KERNEL_HOOK", hook)
    plugin = ws.WebSearchPlugin(tavily_api_key="k")
    for attr, identity in (("_client", "websearch"), ("_reader", "webread")):
        setattr(plugin, attr, PluginHTTPClient(
            identity, resolver=lambda host, *a, **k: PUBLIC_IP,
            transport_factory=lambda _t: httpx.MockTransport(never),
        ))
    server = _server(plugin)
    out = await _call(server, wt.TOOL_SEARCH, {"query": "q"})
    assert out["result"]["ok"] is False and out["result"]["reason"] == "policy_blocked"
    out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://example.com/a"})
    assert out["result"] == {"available": True, "ok": False, "reason": "url_refused",
                             "url": "https://example.com/a"}
    assert set(seen) == {"websearch", "webread"}


def test_research_keeps_its_searxng_only_attribute_contract_under_the_selector(monkeypatch):
    from agents.core.acquisition.research import ResearchError, WebSearchResearchBackend

    monkeypatch.setenv(wp.BACKEND_ENV, "duckduckgo")
    monkeypatch.setenv(wp.RESCUE_ENV, "1")
    backend = WebSearchResearchBackend(searxng_url="https://searx.local")
    plugin = backend.plugin
    assert plugin.searxng_url == "https://searx.local" and plugin.tavily_api_key == ""
    assert backend.http_client is plugin._client
    selection = plugin.selection()
    assert selection.primary.name == "searxng" and selection.rescue == ()
    # A plugin whose live selection would leave SearXNG is refused, like a cloud key.
    roaming = ws.WebSearchPlugin(searxng_url="https://searx.local")
    with pytest.raises(ResearchError, match="cloud"):
        WebSearchResearchBackend(plugin=roaming)


# ── web_extract: many URLs, head+tail, full text on disk (H310) ──────────────

class Reader:
    """A plugin with ``read_page`` (the real plugin's full-text read) and scripted pages."""

    tavily_api_key = "k"
    searxng_url = ""

    def __init__(self, pages=None, rows=None):
        self.pages = pages or {}
        self.rows = rows or []
        self.reads: list[str] = []

    async def search(self, query, max_results=5):
        return list(self.rows)

    async def read_page(self, url, *, full_chars=ws.FULL_TEXT_MAX_CHARS):
        self.reads.append(url)
        page = self.pages.get(url, "p" * 300)
        if isinstance(page, ws.PageRead):
            return page
        return ws.PageRead(text=page[:full_chars], media="html",
                           text_cut=len(page) > full_chars)


def _store(tmp_path, readable=True):
    return ToolResultStore(tmp_path / "tool_results", read_back=lambda _p: readable)


async def test_extract_reads_up_to_five_urls_and_refuses_a_sixth(tmp_path):
    urls = [f"https://u{i}.example/" for i in range(6)]
    plugin = Reader({u: f"page {i}" for i, u in enumerate(urls)})
    server = _server(plugin, result_store=_store(tmp_path))
    out = await _call(server, wt.TOOL_EXTRACT, {"urls": urls[:5]})
    result = out["result"]
    assert result["available"] is True and result["count"] == 5
    assert [p["url"] for p in result["pages"]] == urls[:5]
    assert [p["text"] for p in result["pages"]] == [f"page {i}" for i in range(5)]
    for bad in ({"urls": urls}, {"urls": []}, {"urls": "https://x.example/"},
                {"url": urls[0], "urls": urls[:2]}, {}, {"urls": [urls[0], "ftp://x/"]}):
        out = await _call(server, wt.TOOL_EXTRACT, bad)
        assert out == {"ok": False, "reason": "bad_args", "tool": wt.TOOL_EXTRACT}, bad
    assert plugin.reads == urls[:5]
    assert wt.preflight_extract({"urls": [urls[0], urls[0], urls[1]]})["urls"] == urls[:2]


async def test_extract_refusals_are_per_url_and_every_fence_still_applies(tmp_path):
    from agents.core.action_origin import bind_action_origin, reset_action_origin
    from agents.core.security.secret_broker import SecretBroker

    broker = SecretBroker()
    broker._store.set("api_key", "sk-live-SECRET123")
    refused = "https://private.example/"
    plugin = Reader(
        {refused: ws.PageRead(text=None, refusal="url_refused"),
         "https://flaky.example/": ws.PageRead(text=None, refusal="fetch_failed")},
        rows=[{"title": "t", "url": "https://found.example/", "snippet": "s"}],
    )
    server = ToolRPCServer(secret_broker=broker)
    wt.register_web_tools(server, lambda: plugin, result_store=_store(tmp_path))
    out = await _call(server, wt.TOOL_EXTRACT, {"urls": [
        "https://ok.example/", refused, "https://c.example/?k=sk-live-SECRET123",
        "https://flaky.example/",
    ]})
    pages = out["result"]["pages"]
    assert pages[0]["text"] == "p" * 300
    assert pages[1] == {"ok": False, "reason": "url_refused", "url": refused}
    assert pages[2] == {"ok": False, "reason": "secret_in_url", "url": ""}
    assert pages[3] == {"ok": False, "reason": "fetch_failed", "url": "https://flaky.example/"}
    assert "SECRET123" not in json.dumps(out)
    assert all("SECRET123" not in u for u in plugin.reads)
    # Refusals are never cached: both are asked again.
    await _call(server, wt.TOOL_EXTRACT, {"urls": [refused, "https://flaky.example/"]})
    assert plugin.reads.count(refused) == 2

    token = bind_action_origin("inbound")
    try:
        await _call(server, wt.TOOL_SEARCH, {"query": "q"})
        out = await _call(server, wt.TOOL_EXTRACT, {"urls": [
            "https://found.example/", "https://composed.example/?memo=x"]})
        first, second = out["result"]["pages"]
        assert first["text"] == "p" * 300
        assert second == {"ok": False, "reason": "tainted_turn",
                          "url": "https://composed.example/?memo=x"}
    finally:
        reset_action_origin(token)
    assert "https://composed.example/?memo=x" not in plugin.reads


async def test_default_budget_is_15000_chars_cut_head_plus_tail(tmp_path):
    page = "HEAD" + "x" * 40000 + "TAIL"
    plugin = Reader({"https://long.example/": page})
    out = await _call(_server(plugin, result_store=_store(tmp_path)), wt.TOOL_EXTRACT,
                      {"url": "https://long.example/"})
    result = out["result"]
    assert wt.DEFAULT_EXTRACT_CHARS == 15000
    assert result["chars"] == len(result["text"]) == 15000
    assert result["text"].startswith("HEAD") and result["text"].endswith("TAIL")
    assert result["truncated"] is True and result["total_chars"] == len(page)
    head, marker, tail = wt.split_head_tail(result["text"])
    assert result["text"] == head + marker + tail and "chars omitted" in marker
    omitted = int(marker.split("[... ", 1)[1].split(" ", 1)[0])
    assert omitted == len(page) - len(head) - len(tail)
    assert page.startswith(head) and page.endswith(tail)
    assert len(head) > len(tail) > 0
    # head+tail of a short page is the page itself.
    text, cut = wt.head_tail("short", 300)
    assert (text, cut) == ("short", False)


async def test_full_text_is_spilled_and_the_footer_names_file_read_only_when_it_can_open_it(
    tmp_path,
):
    page = "HEAD" + "y" * 30000 + "TAIL"
    plugin = Reader({"https://long.example/": page, "https://short.example/": "tiny"})
    out = await _call(_server(plugin, result_store=_store(tmp_path, readable=True)),
                      wt.TOOL_EXTRACT, {"url": "https://long.example/"})
    result = out["result"]
    saved = Path(result["full_text_file"])
    assert saved.is_file() and saved.parent == (tmp_path / "tool_results").resolve()
    assert saved.read_text(encoding="utf-8") == page
    assert result["full_text_sha256"] == hashlib.sha256(page.encode()).hexdigest()
    assert result["read_with"]["tool"] == "file_read"
    assert result["read_with"]["arguments"]["path"] == str(saved)
    assert str(saved) in result["footer"] and "file_read(" in result["footer"]

    blind = tmp_path / "blind"
    out = await _call(_server(plugin, result_store=_store(blind, readable=False)),
                      wt.TOOL_EXTRACT, {"url": "https://long.example/"})
    result = out["result"]
    assert Path(result["full_text_file"]).is_file()
    assert "read_with" not in result
    assert "file_read(" not in result["footer"] and "cannot" in result["footer"]

    quiet = tmp_path / "quiet"
    out = await _call(_server(plugin, result_store=_store(quiet)), wt.TOOL_EXTRACT,
                      {"url": "https://short.example/"})
    assert "full_text_file" not in out["result"] and "footer" not in out["result"]
    assert not (quiet / "tool_results").exists() or not any((quiet / "tool_results").iterdir())

    class Broken(ToolResultStore):
        def open_stream(self, **kw):
            return None

    out = await _call(_server(plugin, result_store=Broken(tmp_path / "broken")),
                      wt.TOOL_EXTRACT, {"url": "https://long.example/"})
    assert out["result"]["chars"] == 15000 and "full_text_file" not in out["result"]


async def test_cache_recuts_from_the_full_text_and_keeps_the_footer_valid(tmp_path):
    now = {"t": 10.0}
    big = "HEAD" + "z" * 60000 + "TAIL"          # longer than the cache keeps whole
    small = "S" * 3000
    plugin = Reader({"https://big.example/": big, "https://small.example/": small})
    store = _store(tmp_path)
    server = _server(plugin, result_store=store, clock=lambda: now["t"])

    first = (await _call(server, wt.TOOL_EXTRACT, {"url": "https://big.example/"}))["result"]
    again = (await _call(server, wt.TOOL_EXTRACT,
                         {"url": "https://big.example/", "max_chars": 1000}))["result"]
    assert again["cached"] is True and plugin.reads.count("https://big.example/") == 1
    # Re-cut from what was kept of the full text — never the old cut re-cut by head.
    assert again["chars"] == 1000
    assert again["text"].startswith("HEAD") and again["text"].endswith("TAIL")
    assert again["text"].count("chars omitted") == 1
    assert again["full_text_file"] == first["full_text_file"]
    assert Path(again["full_text_file"]).read_text(encoding="utf-8") == big

    # Retention swept the file: a cache hit must not name a file that is gone.
    Path(first["full_text_file"]).unlink()
    third = (await _call(server, wt.TOOL_EXTRACT,
                         {"url": "https://big.example/", "max_chars": 2000}))["result"]
    assert third["cached"] is False and Path(third["full_text_file"]).is_file()
    assert plugin.reads.count("https://big.example/") == 2

    # A page that fitted the first time is kept whole, so a smaller cut later spills
    # from the cache without a second fetch.
    whole = (await _call(server, wt.TOOL_EXTRACT,
                         {"url": "https://small.example/", "max_chars": 5000}))["result"]
    assert whole["truncated"] is False and "full_text_file" not in whole
    cut = (await _call(server, wt.TOOL_EXTRACT,
                       {"url": "https://small.example/", "max_chars": 1000}))["result"]
    assert cut["cached"] is True and cut["truncated"] is True
    assert Path(cut["full_text_file"]).read_text(encoding="utf-8") == small
    assert plugin.reads.count("https://small.example/") == 1


async def test_five_wide_pages_stay_under_the_declared_result_bytes(tmp_path):
    urls = [f"https://wide{i}.example/" + "q" * 1500 for i in range(5)]
    plugin = Reader(dict.fromkeys(urls, "漢" * 30000))
    server = _server(plugin, result_store=_store(tmp_path))
    out = await _call(server, wt.TOOL_EXTRACT, {"urls": urls, "max_chars": wt.MAX_EXTRACT_CHARS})
    encoded = json.dumps(out["result"], ensure_ascii=False).encode("utf-8")
    assert len(encoded) <= wt.MAX_RESULT_BYTES
    for page in out["result"]["pages"]:
        assert page["truncated"] is True and Path(page["full_text_file"]).is_file()
        assert page["text"].startswith("漢") and page["text"].endswith("漢")
    # One page alone still gets the per-page byte cap, not the whole declared budget.
    out = await _call(server, wt.TOOL_EXTRACT, {"url": urls[0], "max_chars": wt.MAX_EXTRACT_CHARS})
    assert len(out["result"]["text"].encode("utf-8")) <= wt.MAX_EXTRACT_BYTES


def test_both_tools_declare_their_result_ceiling():
    server = _server(Reader())
    assert wt.MAX_RESULT_BYTES == 100_000
    assert server.declared_result_bytes(wt.TOOL_SEARCH) == wt.MAX_SEARCH_RESULT_BYTES == 50_000
    assert server.declared_result_bytes(wt.TOOL_EXTRACT) == wt.MAX_RESULT_BYTES
    rows = {row["name"]: row for row in server.tools()}
    urls = rows[wt.TOOL_EXTRACT]["input_schema"]["properties"]["urls"]
    assert (urls["minItems"], urls["maxItems"]) == (1, wt.MAX_EXTRACT_URLS) == (1, 5)
    for row in rows.values():
        assert row["untrusted_output"] is True and row["gated"] is False


def test_default_read_back_probe_asks_reaches_not_just_registration(monkeypatch, tmp_path):
    from agents.core import file_tools, job_toolsets

    server = ToolRPCServer()
    probe = wt.default_read_back(server)
    assert probe(str(tmp_path / "x.txt")) is False          # file_read not registered
    monkeypatch.setattr(server, "allows", lambda name: name == "file_read")
    answers = {"reach": False}
    monkeypatch.setattr(file_tools.FileTools, "reaches", lambda self, p: answers["reach"])
    assert probe(str(tmp_path / "x.txt")) is False          # registered is not reachable
    answers["reach"] = True
    assert probe(str(tmp_path / "x.txt")) is True
    monkeypatch.setattr(job_toolsets, "allows", lambda name: False)
    assert probe(str(tmp_path / "x.txt")) is False          # a job toolset fences it off


# ── the reader: PDFs, classified refusals, blocked sites ─────────────────────

def _fake_pypdf(pages, *, record=None, encrypted=False):
    module = types.ModuleType("pypdf")

    class _Page:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class PdfReader:
        def __init__(self, stream):
            if record is not None:
                record.append(threading.current_thread() is threading.main_thread())
            data = stream.read()
            if not data.startswith(b"%PDF"):
                raise ValueError("not a pdf")
            self.is_encrypted = encrypted
            self.pages = [_Page(t) for t in pages]

    module.PdfReader = PdfReader
    return module


def _pdf_transport(body=b"%PDF-1.7 fake", content_type="application/pdf"):
    return httpx.MockTransport(lambda request: httpx.Response(
        200, content=body, headers={"content-type": content_type}))


async def test_pdf_pages_are_read_off_the_loop_bounded_and_refused_by_name(monkeypatch):
    monkeypatch.setattr(ws, "resolve_and_validate", lambda host, *a, **k: PUBLIC_IP)
    plugin = ws.WebSearchPlugin()
    on_main = []
    monkeypatch.setitem(sys.modules, "pypdf", _fake_pypdf(["one", "two", "three"], record=on_main))
    got = await plugin.read_page("https://docs.example/a.pdf", _transport=_pdf_transport())
    assert got.text == "one\n\ntwo\n\nthree" and got.media == "pdf" and got.refusal == ""
    assert on_main == [False]                                # parsed in a worker thread
    monkeypatch.setattr(ws, "PDF_MAX_PAGES", 2)
    got = await plugin.read_page("https://docs.example/a.pdf", _transport=_pdf_transport())
    assert got.text == "one\n\ntwo" and got.text_cut is True and got.pages == (2, 3)
    got = await plugin.read_page("https://docs.example/a.pdf", full_chars=2,
                                 _transport=_pdf_transport())
    assert got.text == "on" and got.text_cut is True
    # Unparsable or encrypted: refused, not handed back as noise.
    got = await plugin.read_page("https://docs.example/b.pdf",
                                 _transport=_pdf_transport(body=b"garbage"))
    assert got.text is None and got.refusal == "url_refused"
    monkeypatch.setitem(sys.modules, "pypdf", _fake_pypdf(["x"], encrypted=True))
    got = await plugin.read_page("https://docs.example/c.pdf", _transport=_pdf_transport())
    assert got.text is None and got.refusal == "url_refused"
    # A PDF cut at the byte cap has lost its cross-reference table: refused by name.
    monkeypatch.setattr(ws, "PAGE_MAX_BYTES", 8)
    got = await plugin.read_page("https://docs.example/big.pdf",
                                 _transport=_pdf_transport(body=b"%PDF-1.7 " + b"0" * 64))
    assert got.text is None and got.refusal == "too_large"
    # No parser installed: named, before the body is read.
    monkeypatch.setitem(sys.modules, "pypdf", None)
    got = await plugin.read_page("https://docs.example/a.pdf", _transport=_pdf_transport())
    assert got.text is None and got.refusal == "parser_missing" and got.missing == "pypdf"
    # Other binary media stay refused.
    got = await plugin.read_page("https://docs.example/i.png",
                                 _transport=_pdf_transport(content_type="image/png"))
    assert got.refusal == "url_refused"
    # The legacy text API still answers None for all of these.
    assert await plugin.fetch_page("https://docs.example/a.pdf", _transport=_pdf_transport()) is None


async def test_web_extract_reads_a_pdf_and_names_a_missing_parser(monkeypatch, tmp_path):
    monkeypatch.setattr(ws, "resolve_and_validate", lambda host, *a, **k: PUBLIC_IP)
    real = ws.WebSearchPlugin()

    class Wired:
        tavily_api_key = ""
        searxng_url = ""

        async def read_page(self, url, *, full_chars=ws.FULL_TEXT_MAX_CHARS):
            return await real.read_page(url, full_chars=full_chars, _transport=_pdf_transport())

    server = _server(Wired(), result_store=_store(tmp_path))
    monkeypatch.setitem(sys.modules, "pypdf", _fake_pypdf(["page text"]))
    out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://docs.example/a.pdf"})
    assert out["result"]["text"] == "page text" and out["result"]["media"] == "pdf"
    monkeypatch.setitem(sys.modules, "pypdf", None)
    out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://docs.example/other.pdf"})
    assert out["result"] == {"available": True, "ok": False, "reason": "parser_missing",
                             "missing": "pypdf", "url": "https://docs.example/other.pdf"}


async def test_reader_tells_a_policy_refusal_from_a_fetch_failure(monkeypatch):
    monkeypatch.setattr(
        ws, "resolve_and_validate",
        lambda host, *a, **k: ([], "URL resolves to private IP") if host == "127.0.0.1" else PUBLIC_IP,
    )
    plugin = ws.WebSearchPlugin()

    def down(request):
        raise httpx.ConnectError("refused")

    got = await plugin.read_page("https://a.example/", _transport=httpx.MockTransport(down))
    assert got.refusal == "fetch_failed"
    got = await plugin.read_page("https://a.example/", _transport=httpx.MockTransport(
        lambda r: httpx.Response(503, text="busy", headers={"content-type": "text/html"})))
    assert got.refusal == "fetch_failed"
    got = await plugin.read_page("http://127.0.0.1/", _transport=httpx.MockTransport(down))
    assert got.refusal == "url_refused"


async def test_operator_blocked_sites_are_a_policy_refusal_on_every_hop(monkeypatch, tmp_path):
    monkeypatch.setattr(ws, "resolve_and_validate", lambda host, *a, **k: PUBLIC_IP)
    monkeypatch.setenv(wp.BLOCKED_DOMAINS_ENV, "blocked.example, Other.Test")
    assert wp.blocked_host("https://blocked.example/x") is True
    assert wp.blocked_host("https://deep.sub.blocked.example/") is True
    assert wp.blocked_host("https://notblocked.example/") is False
    assert wp.blocked_host("https://other.test/") is True

    dialed = []

    def handler(request):
        dialed.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://blocked.example/landing"})

    plugin = ws.WebSearchPlugin()
    got = await plugin.read_page("https://redirector.example/", _transport=httpx.MockTransport(handler))
    assert got.refusal == "site_blocked" and len(dialed) == 1   # the blocked hop is not dialed

    reader = Reader(rows=[{"title": "a", "url": "https://blocked.example/a", "snippet": "s"},
                          {"title": "b", "url": "https://fine.example/b", "snippet": "s"}])
    server = _server(reader, result_store=_store(tmp_path))
    out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://www.blocked.example/p"})
    assert out["result"] == {"available": True, "ok": False, "reason": "site_blocked",
                             "url": "https://www.blocked.example/p"}
    assert reader.reads == []
    out = await _call(server, wt.TOOL_SEARCH, {"query": "q"})
    assert [r["url"] for r in out["result"]["results"]] == ["https://fine.example/b"]
    assert out["result"]["blocked"] == 1


# ── the verification command (H607) ──────────────────────────────────────────

def test_verification_command_reports_the_resolution_without_printing_keys(monkeypatch, capsys):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-SECRET-VALUE")
    monkeypatch.setenv(wp.TIER_ENV, "free")
    code = wp.main(["--json"])
    report = json.loads(capsys.readouterr().out)
    assert "tvly-SECRET-VALUE" not in json.dumps(report)
    assert report["backend"] == "auto" and report["tier"] == "free"
    providers = {p["name"]: p for p in report["providers"]}
    assert providers["tavily"]["configured"] is True and providers["tavily"]["eligible"] is False
    assert providers["tavily"]["tier"] == "paid"
    assert report["primary"] in {"duckduckgo", None}
    assert set(report["parsers"]) == {"beautifulsoup4", "pypdf"}
    assert code == (0 if report["primary"] else 1)
    monkeypatch.setenv(wp.BACKEND_ENV, "searxng")
    assert wp.main([]) == 1
    text = capsys.readouterr().out
    assert "backend_not_configured" in text and "tvly-SECRET-VALUE" not in text


# ── fix round 1: the keyless fallback, block-list shapes, empty answers, PDF stop ──

async def test_a_keyless_provider_is_never_a_rescue_target_for_unattended_callers(
    monkeypatch, swap_builtins,
):
    """search() feeds the research handler, the tech scout and the plugin gatherer. A
    configured backend that fails must not send their query to DuckDuckGo."""
    failing = Recorder("tavily", tier="paid", raises=wp.ProviderFailure("http_503"))
    fakes = swap_builtins(tavily=failing)
    plugin = ws.WebSearchPlugin(tavily_api_key="k")           # Tavily only
    assert await plugin.search("unattended") == []
    assert fakes["duckduckgo"].calls == []
    outcome = await plugin.search_detailed("unattended-2")
    assert outcome.reason == "provider_failed" and outcome.rescued_from == ""
    assert plugin.selection().rescue == ()
    # An explicit JARVIS_WEB_RESCUE=1 does not widen it for those callers either.
    monkeypatch.setenv(wp.RESCUE_ENV, "1")
    assert await plugin.search("unattended-3") == []
    assert fakes["duckduckgo"].calls == []
    # SearXNG-only owner: same.
    monkeypatch.delenv(wp.RESCUE_ENV)
    fakes = swap_builtins(searxng=Recorder("searxng", raises=wp.ProviderFailure("timeout")))
    searx = ws.WebSearchPlugin(searxng_url="http://searx.local")
    assert await searx.search("q") == [] and fakes["duckduckgo"].calls == []


async def test_the_interactive_tool_reaches_the_keyless_fallback_only_on_an_explicit_rescue(
    monkeypatch, swap_builtins,
):
    failing = Recorder("tavily", tier="paid", raises=wp.ProviderFailure("http_503"))
    fakes = swap_builtins(tavily=failing)
    plugin = ws.WebSearchPlugin(tavily_api_key="k")
    server = _server(plugin)
    out = await _call(server, wt.TOOL_SEARCH, {"query": "default"})
    assert out["result"]["error"] == "provider_failed" and out["result"]["results"] == []
    assert fakes["duckduckgo"].calls == []                    # default rescue skips keyless
    monkeypatch.setenv(wp.RESCUE_ENV, "1")
    out = await _call(server, wt.TOOL_SEARCH, {"query": "explicit"})
    assert out["result"]["provider"] == "duckduckgo"
    assert out["result"]["rescued_from"] == "tavily"
    assert len(fakes["duckduckgo"].calls) == 1


def test_verification_command_says_which_callers_may_use_the_keyless_rescue(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.setenv(wp.RESCUE_ENV, "1")
    report = wp.describe()
    assert report["rescue_to"] == [] and report["rescue_to_interactive"] == ["duckduckgo"]
    assert "interactive web_search tool only" in wp._text_report(report)


def test_block_list_compares_one_normalised_host_form(monkeypatch):
    monkeypatch.setenv(
        wp.BLOCKED_DOMAINS_ENV,
        "https://evil.com, M\u00fcnchen.de, bad.org, 1.2.3.4, example.com/path, host.test:8080, nonsense words",
    )
    for url in ("http://evil.com/x", "http://sub.evil.com./", "http://EVIL.com:81/",
                "http://m\u00fcnchen.de/", "http://xn--mnchen-3ya.de/", "http://a.xn--mnchen-3ya.de/",
                "http://bad\u3002org/x", "http://bad\uff0eorg/x", "http://1.2.3.4/",
                "http://example.com/other", "https://host.test/"):
        assert wp.blocked_host(url) is True, url
    for url in ("http://notevil.com/", "http://evil.com.au/", "http://1.2.3.45/", ""):
        assert wp.blocked_host(url) is False, url
    assert wp.unusable_blocked_entries() == ("nonsense words",)
    report = wp.describe(types.SimpleNamespace(tavily_api_key="", searxng_url="",
                                               backend=None, provider_tier=None, rescue=None))
    assert report["blocked_domains_unusable"] == ["nonsense words"]
    assert "WARNING" in wp._text_report(report)


async def test_an_empty_answer_is_not_cached_and_a_throttled_page_is_a_failure(swap_builtins):
    empty = Recorder("tavily", tier="paid", rows=[])
    swap_builtins(tavily=empty)
    plugin = ws.WebSearchPlugin(tavily_api_key="k")
    for _ in range(2):
        outcome = await plugin.search_detailed("nothing yet")
        assert outcome.rows == [] and outcome.reason == "" and outcome.cached is False
    assert len(empty.calls) == 2                              # asked again, not pinned for 15 min

    # DuckDuckGo's 202 anomaly page parses to zero rows: that is a failed answer.
    pytest.importorskip("bs4")
    for status, expect_failure in ((202, True), (200, False)):
        client = types.SimpleNamespace(plugin_name="websearch")

        async def get(url, _status=status, **kw):
            return types.SimpleNamespace(status_code=_status, text="<html></html>")

        client.get = get
        provider = wp.DuckDuckGoProvider()
        if expect_failure:
            with pytest.raises(wp.ProviderFailure):
                await provider.search(client, None, "q", 5)
        else:
            assert await provider.search(client, None, "q", 5) == []


async def test_a_provider_sees_a_narrow_view_not_the_plugin_and_builtins_cannot_be_replaced(
    monkeypatch,
):
    seen = {}

    class Nosy(wp.SearchProvider):
        name = "nosy"
        tier = "free"

        def configured(self, plugin):
            seen["configured"] = plugin
            return True

        async def search(self, client, plugin, query, max_results):
            seen["search"] = plugin
            return []

    wp.register_search_provider(Nosy())
    try:
        monkeypatch.setenv(wp.BACKEND_ENV, "nosy")
        plugin = ws.WebSearchPlugin(tavily_api_key="secret-key", searxng_url="http://searx.local")
        await plugin.search("q")
        for view in (seen["configured"], seen["search"]):
            assert view is not plugin
            assert not hasattr(view, "_reader") and not hasattr(view, "_client")
            assert not hasattr(view, "read_page")
            assert (view.tavily_api_key, view.searxng_url) == ("secret-key", "http://searx.local")
    finally:
        wp.unregister_search_provider("nosy")
    for name in ("tavily", "searxng", "duckduckgo"):
        with pytest.raises(ValueError, match="already"):
            wp.register_search_provider(Recorder(name), replace=True)
        assert wp.unregister_search_provider(name) is False
        assert name in wp.search_providers()


async def test_a_slow_pdf_stops_at_a_page_boundary_and_reads_as_retryable(monkeypatch):
    import time as _time

    monkeypatch.setattr(ws, "resolve_and_validate", lambda host, *a, **k: PUBLIC_IP)
    monkeypatch.setattr(ws, "PDF_PARSE_TIMEOUT_SECONDS", 0.3)
    extracted = []
    module = types.ModuleType("pypdf")

    class _Page:
        def extract_text(self):
            extracted.append(1)
            _time.sleep(0.1)
            return "p"

    class PdfReader:
        def __init__(self, stream):
            self.is_encrypted = False
            self.pages = [_Page() for _ in range(40)]

    module.PdfReader = PdfReader
    monkeypatch.setitem(sys.modules, "pypdf", module)
    plugin = ws.WebSearchPlugin()
    got = await plugin.read_page("https://docs.example/slow.pdf", _transport=_pdf_transport())
    # Slow is not forbidden: the model is told it may retry, not "url_refused".
    assert got.text is None and got.refusal == "fetch_failed"
    freed = False
    for _ in range(60):                       # the worker releases its slot when it really ends
        if ws._PDF_SLOTS.acquire(blocking=False):
            ws._PDF_SLOTS.release()
            freed = True
            break
        await asyncio.sleep(0.05)
    assert freed
    assert len(extracted) < 40                                # the worker stopped itself


async def test_pdf_parses_are_bounded_in_number(monkeypatch):
    monkeypatch.setattr(ws, "resolve_and_validate", lambda host, *a, **k: PUBLIC_IP)
    monkeypatch.setitem(sys.modules, "pypdf", _fake_pypdf(["text"]))
    held = [ws._PDF_SLOTS.acquire(blocking=False) for _ in range(ws.PDF_MAX_CONCURRENT)]
    try:
        assert all(held)
        plugin = ws.WebSearchPlugin()
        got = await plugin.read_page("https://docs.example/a.pdf", _transport=_pdf_transport())
        # Not "fetch_failed": a retry would meet the same hung parses, so it says so.
        assert got.text is None and got.refusal == "parser_busy"
    finally:
        for _ in held:
            ws._PDF_SLOTS.release()
    got = await plugin.read_page("https://docs.example/a.pdf", _transport=_pdf_transport())
    assert got.text == "text"


def test_research_pins_its_tier_and_reports_an_unavailable_backend_honestly(monkeypatch):
    from agents.core.acquisition.research import ResearchError, WebSearchResearchBackend

    monkeypatch.setenv(wp.TIER_ENV, "paid")                   # an owner's cloud preference
    backend = WebSearchResearchBackend(searxng_url="https://searx.local")
    selection = backend.plugin.selection()
    assert selection.primary.name == "searxng" and selection.rescue == ()
    # A plugin that merely cannot answer is "unavailable", not mislabelled as cloud.
    free_only = ws.WebSearchPlugin(searxng_url="https://searx.local")
    with pytest.raises(ResearchError, match="unavailable"):
        WebSearchResearchBackend(plugin=free_only)


# ── fix round 2: queued PDF parses, DNS is not a policy block, status before media ──

def _slow_pypdf(pages=2, delay=0.1, peak=None):
    module = types.ModuleType("pypdf")
    live = {"now": 0}
    lock = threading.Lock()

    class _Page:
        def extract_text(self):
            with lock:
                live["now"] += 1
                if peak is not None:
                    peak.append(live["now"])
            time.sleep(delay)
            with lock:
                live["now"] -= 1
            return "page"

    class PdfReader:
        def __init__(self, stream):
            stream.read()
            self.is_encrypted = False
            self.pages = [_Page() for _ in range(pages)]

    module.PdfReader = PdfReader
    return module


async def test_five_pdf_urls_in_one_call_are_queued_not_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(ws, "resolve_and_validate", lambda host, *a, **k: PUBLIC_IP)
    peak: list = []
    monkeypatch.setitem(sys.modules, "pypdf", _slow_pypdf(pages=2, delay=0.1, peak=peak))
    real = ws.WebSearchPlugin()

    class Wired:
        tavily_api_key = ""
        searxng_url = ""

        async def read_page(self, url, *, full_chars=ws.FULL_TEXT_MAX_CHARS):
            return await real.read_page(url, full_chars=full_chars, _transport=_pdf_transport())

    server = _server(Wired(), result_store=_store(tmp_path))
    urls = [f"https://docs.example/{i}.pdf" for i in range(5)]
    out = await _call(server, wt.TOOL_EXTRACT, {"urls": urls})
    pages = out["result"]["pages"]
    assert [p.get("ok", True) for p in pages] == [True] * 5, pages
    assert all(p["text"] == "page\n\npage" for p in pages)
    # ...and the bound still holds: never more than PDF_MAX_CONCURRENT parses at once.
    assert max(peak) <= ws.PDF_MAX_CONCURRENT


async def test_queued_pdf_parses_work_across_event_loops(monkeypatch):
    monkeypatch.setattr(ws, "resolve_and_validate", lambda host, *a, **k: PUBLIC_IP)
    monkeypatch.setitem(sys.modules, "pypdf", _fake_pypdf(["x"]))
    plugin = ws.WebSearchPlugin()

    def one_loop():
        async def run():
            return await asyncio.gather(*[
                plugin.read_page(f"https://docs.example/{i}.pdf", _transport=_pdf_transport())
                for i in range(4)])
        return asyncio.run(run())

    for _ in range(2):                                        # a fresh loop each time
        got = await asyncio.to_thread(one_loop)
        assert [g.refusal for g in got] == [""] * 4


async def test_parser_busy_is_a_distinct_page_reason(tmp_path):
    busy = ws.PageRead(None, media="pdf", refusal=ws.PARSER_BUSY)
    server = _server(Reader(pages={"https://a.example/x.pdf": busy}), result_store=_store(tmp_path))
    out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://a.example/x.pdf"})
    assert out["result"]["ok"] is False and out["result"]["reason"] == "parser_busy"


async def test_a_dns_failure_is_a_failure_not_a_policy_block(monkeypatch, swap_builtins):
    from agents.core.http_client import PluginEgressError

    async def dns():
        raise PluginEgressError("egress blocked: DNS resolution failed for searx.internal")

    with pytest.raises(wp.ProviderFailure):
        await wp.classified(dns())

    async def empty():
        raise PluginEgressError("egress blocked: empty DNS answer")

    with pytest.raises(wp.ProviderFailure):
        await wp.classified(empty())

    async def gate():
        raise PluginEgressError("egress blocked: host not in the manifest allowlist")

    with pytest.raises(wp.PolicyBlock):
        await wp.classified(gate())
    async def private():
        raise PluginEgressError("egress blocked: URL resolves to unsafe address for public mode: 10.0.0.1")

    with pytest.raises(wp.PolicyBlock):
        await wp.classified(private())

    # End to end through the real egress client: a resolver outage on the first
    # backend is a retryable failure, so the one-shot rescue to the next backend runs.
    fakes = swap_builtins(tavily=Recorder("tavily", tier="paid", raises=wp.ProviderFailure("x")))
    plugin = ws.WebSearchPlugin(tavily_api_key="k", searxng_url="https://searx.example")
    outcome = await plugin.search_detailed("q")
    assert outcome.reason == "" and outcome.rescued_from == "tavily"
    assert fakes["searxng"].calls


async def test_a_dns_failure_on_a_page_read_is_retryable(monkeypatch):
    monkeypatch.setattr(ws, "resolve_and_validate",
                        lambda host, *a, **k: ([], f"DNS resolution failed for {host}"))
    plugin = ws.WebSearchPlugin()
    got = await plugin.read_page("https://nowhere.example/", _transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text="x", headers={"content-type": "text/html"})))
    assert got.refusal == "fetch_failed"
    monkeypatch.setattr(ws, "resolve_and_validate",
                        lambda host, *a, **k: ([], "URL resolves to unsafe address for public mode: 10.0.0.1"))
    got = await plugin.read_page("https://nowhere.example/", _transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text="x", headers={"content-type": "text/html"})))
    assert got.refusal == "url_refused"                      # a real gate refusal stays one


async def test_an_http_error_status_is_a_fetch_failure_whatever_the_media_type(monkeypatch):
    monkeypatch.setattr(ws, "resolve_and_validate", lambda host, *a, **k: PUBLIC_IP)
    plugin = ws.WebSearchPlugin()
    cases = [
        (503, {"content-type": "application/json"}, b'{"error":"busy"}'),
        (429, {}, b""),
        (404, {"content-type": "image/png"}, b"\x89PNG"),
    ]
    for status, headers, body in cases:
        got = await plugin.read_page("https://a.example/x", _transport=httpx.MockTransport(
            lambda r, s=status, h=headers, b=body: httpx.Response(s, content=b, headers=h)))
        assert got.refusal == "fetch_failed", status
    # A 200 with an unreadable media type is still a refusal.
    got = await plugin.read_page("https://a.example/x", _transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})))
    assert got.refusal == "url_refused"


async def test_web_search_answer_is_fitted_to_its_declared_byte_ceiling():
    rows = [{"title": "漢" * 300, "url": "https://x.example/" + "a" * 1980 + str(i),
             "snippet": "字" * 1000} for i in range(10)]

    class Many:
        tavily_api_key = "k"
        searxng_url = ""

        async def search(self, query, max_results=5):
            return list(rows)

    server = _server(Many())
    out = await _call(server, wt.TOOL_SEARCH, {"query": "q", "max_results": 10})
    result = out["result"]
    size = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    assert size <= wt.MAX_SEARCH_RESULT_BYTES
    assert 0 < result["count"] < 10 and result["count"] == len(result["results"])
    assert result["omitted"] == 10 - result["count"]
    # ASCII rows (the normal case) are untouched.
    class Few(Many):
        async def search(self, query, max_results=5):
            return [{"title": "t", "url": "https://x.example/1", "snippet": "s"}] * 3

    out = await _call(_server(Few()), wt.TOOL_SEARCH, {"query": "q"})
    assert out["result"]["count"] == 3 and "omitted" not in out["result"]


def test_block_list_compares_numeric_host_spellings_and_warns_on_typos(monkeypatch, caplog):
    monkeypatch.setenv(wp.BLOCKED_DOMAINS_ENV, "evil.com,10.1.2.3,nonsense words")
    for url in ("http://10.1.2.3/", "http://167838211/", "http://0xa010203/",
                "http://012.1.2.3/", "http://[::ffff:10.1.2.3]/", "http://10.1.2.3./"):
        assert wp.blocked_host(url) is True, url
    for url in ("http://10.1.2.4/", "http://167838212/", "http://abc.def/", "http://evil.com/"):
        assert wp.blocked_host(url) is (url == "http://evil.com/"), url
    monkeypatch.setenv(wp.BLOCKED_DOMAINS_ENV, "[::1], 2001:db8::1")
    assert wp.blocked_host("http://[::1]/") is True
    assert wp.blocked_host("http://[2001:db8:0::1]/") is True
    # A typo is not silent at runtime: it is logged (once per distinct list).
    wp._WARNED_UNUSABLE.clear()
    caplog.clear()
    monkeypatch.setenv(wp.BLOCKED_DOMAINS_ENV, "evil.com,not a host")
    with caplog.at_level("WARNING", logger="jarvis.plugins.web_providers"):
        wp.blocked_host("http://a.example/")
        wp.blocked_host("http://b.example/")
    warned = [r for r in caplog.records if "JARVIS_WEB_BLOCKED_DOMAINS" in r.getMessage()]
    assert len(warned) == 1
