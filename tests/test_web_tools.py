"""web_search / web_extract on ToolRPC (Hermes absorption 5a).

A fake plugin records what the tools ask of it; a real ``ToolRPCServer`` runs the
preflights and handlers through ``handle()`` exactly as the sandbox would. The one
test that uses the real ``WebSearchPlugin`` proves a private-IP URL is refused before
any transport is dialed.
"""

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import web_tools as wt  # noqa: E402
from agents.core.tool_rpc import ToolRPCServer  # noqa: E402


class FakePlugin:
    """Just enough of WebSearchPlugin for the tools: the two attributes the provider
    name is read from and the two async methods, both recording their calls."""

    def __init__(self, *, tavily_api_key="", searxng_url="", rows=None, page="", raise_on=None):
        self.tavily_api_key = tavily_api_key
        self.searxng_url = searxng_url
        self.rows = rows if rows is not None else []
        self.page = page
        self.raise_on = raise_on or set()
        self.search_calls: list[tuple] = []
        self.fetch_calls: list[tuple] = []

    async def search(self, query, max_results=5):
        self.search_calls.append((query, max_results))
        if "search" in self.raise_on:
            raise RuntimeError("backend exploded")
        return list(self.rows)

    async def fetch_page(self, url, *, max_chars=8000):
        self.fetch_calls.append((url, max_chars))
        if "fetch" in self.raise_on:
            raise RuntimeError("fetch exploded")
        if self.page is None:
            return None
        return self.page[:max_chars]


def _server(plugin, **kw):
    server = ToolRPCServer()
    names = wt.register_web_tools(server, lambda: plugin, **kw)
    assert names == (wt.TOOL_SEARCH, wt.TOOL_EXTRACT)
    return server


async def _call(server, tool, args):
    return await server.handle({"tool": tool, "args": args})


# ── web_search ───────────────────────────────────────────────────────────────

async def test_web_search_returns_tainted_rows_from_a_fake_plugin():
    plugin = FakePlugin(
        tavily_api_key="k",
        rows=[
            {"title": "T" * 500, "url": "https://a.example/" + "p" * 3000,
             "snippet": "S" * 2000},          # the plugin did not taint this one
            {"title": "b", "url": "https://b.example/", "snippet": "s",
             "tainted": True, "taint_source": "websearch"},
            "not a dict",
        ],
    )
    server = _server(plugin)
    out = await _call(server, wt.TOOL_SEARCH, {"query": "  hello  ", "max_results": 2})
    assert out["ok"] is True and out["tool"] == wt.TOOL_SEARCH
    result = out["result"]
    assert result["available"] is True
    assert result["provider"] == "tavily"
    assert result["query"] == "hello"
    assert result["count"] == 2 and len(result["results"]) == 2
    first = result["results"][0]
    assert first["tainted"] is True and first["taint_source"] == "websearch"
    assert len(first["title"]) == wt.TITLE_CHARS
    assert len(first["url"]) == wt.MAX_URL_CHARS
    assert len(first["snippet"]) == wt.SNIPPET_CHARS
    assert all(r["tainted"] is True for r in result["results"])
    assert plugin.search_calls == [("hello", 2)]


async def test_web_search_unavailable_when_plugin_is_dark():
    server = _server(None)
    out = await _call(server, wt.TOOL_SEARCH, {"query": "x"})
    assert out["ok"] is True
    assert out["result"] == {"available": False, "ok": False, "reason": "websearch_unavailable"}

    class NoSearch:
        tavily_api_key = "k"
        searxng_url = ""

    out = await _call(_server(NoSearch()), wt.TOOL_SEARCH, {"query": "x"})
    assert out["result"] == {"available": False, "ok": False, "reason": "websearch_unavailable"}


async def test_web_search_provider_names_the_backend():
    assert wt.provider_name(FakePlugin(tavily_api_key="k", searxng_url="http://s")) == "tavily"
    assert wt.provider_name(FakePlugin(searxng_url="http://s")) == "searxng"
    assert wt.provider_name(FakePlugin()) == "duckduckgo"
    for plugin, name in (
        (FakePlugin(tavily_api_key="k"), "tavily"),
        (FakePlugin(searxng_url="http://searx.local"), "searxng"),
        (FakePlugin(), "duckduckgo"),
    ):
        out = await _call(_server(plugin), wt.TOOL_SEARCH, {"query": "q"})
        assert out["result"]["available"] is True
        assert out["result"]["provider"] == name


async def test_web_search_duckduckgo_without_bs4_is_named_unavailable(monkeypatch):
    real = importlib.util.find_spec

    def no_bs4(name, *args, **kwargs):
        if name == "bs4":
            return None
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", no_bs4)
    plugin = FakePlugin(rows=[{"title": "t", "url": "https://x.example/", "snippet": "s"}])
    out = await _call(_server(plugin), wt.TOOL_SEARCH, {"query": "q"})
    assert out["result"] == {
        "available": False, "ok": False, "reason": "websearch_unavailable", "missing": "beautifulsoup4",
    }
    assert plugin.search_calls == []
    # A configured backend does not parse HTML itself, so it still answers.
    tavily = FakePlugin(tavily_api_key="k", rows=[])
    out = await _call(_server(tavily), wt.TOOL_SEARCH, {"query": "q"})
    assert out["result"]["available"] is True and out["result"]["provider"] == "tavily"


async def test_web_search_plugin_exception_yields_empty_rows_not_a_stack_trace():
    plugin = FakePlugin(tavily_api_key="k", raise_on={"search"})
    out = await _call(_server(plugin), wt.TOOL_SEARCH, {"query": "q"})
    assert out["ok"] is True
    assert out["result"]["available"] is True
    assert out["result"]["results"] == [] and out["result"]["count"] == 0
    assert "exploded" not in repr(out)


# ── web_extract ──────────────────────────────────────────────────────────────

async def test_web_extract_truncates_at_max_chars_and_reports_it():
    plugin = FakePlugin(page="a" * 5000)
    server = _server(plugin)
    out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://x.example/p", "max_chars": 300})
    result = out["result"]
    assert result["available"] is True and result["cached"] is False
    assert result["chars"] == 300 and len(result["text"]) == 300
    assert result["truncated"] is True
    assert result["url"] == "https://x.example/p"

    out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://y.example/p", "max_chars": 6000})
    result = out["result"]
    assert result["chars"] == 5000 and result["truncated"] is False


async def test_web_extract_passes_max_chars_to_fetch_page():
    plugin = FakePlugin(page="b" * 100)
    server = _server(plugin)
    await _call(server, wt.TOOL_EXTRACT, {"url": "https://x.example/", "max_chars": 777})
    assert plugin.fetch_calls == [("https://x.example/", 777)]
    await _call(server, wt.TOOL_EXTRACT, {"url": "https://z.example/"})
    assert plugin.fetch_calls[-1] == ("https://z.example/", wt.DEFAULT_EXTRACT_CHARS)


async def test_web_extract_private_ip_url_is_refused_before_any_connect(monkeypatch):
    from agents.core.plugins import websearch as ws

    monkeypatch.setattr(
        ws, "resolve_and_validate",
        lambda host, *a, **k: ([], f"URL resolves to private IP: {host}"),
    )
    dialed = []

    def handler(request):
        dialed.append(request.url)
        pytest.fail("transport must never be dialed for a private-IP URL")

    transport = httpx.MockTransport(handler)
    real = ws.WebSearchPlugin()

    class Wired:
        tavily_api_key = ""
        searxng_url = ""

        async def fetch_page(self, url, *, max_chars):
            return await real.fetch_page(url, max_chars=max_chars, _transport=transport)

    out = await _call(_server(Wired()), wt.TOOL_EXTRACT, {"url": "http://internal.host/secret"})
    assert out["ok"] is True
    assert out["result"] == {
        "available": True, "ok": False, "reason": "url_refused", "url": "http://internal.host/secret",
    }
    assert dialed == []

    # The real guard, un-stubbed: literal loopback / metadata hosts need no DNS.
    monkeypatch.undo()
    for literal in ("http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest/"):
        out = await _call(_server(Wired()), wt.TOOL_EXTRACT, {"url": literal})
        assert out["result"] == {"available": True, "ok": False, "reason": "url_refused", "url": literal}
    assert dialed == []


async def test_web_extract_refusal_is_never_cached():
    plugin = FakePlugin(page=None)
    server = _server(plugin)
    for _ in range(2):
        out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://x.example/"})
        assert out["result"]["ok"] is False and out["result"]["reason"] == "url_refused"
    assert len(plugin.fetch_calls) == 2

    raising = FakePlugin(page="p" * 300, raise_on={"fetch"})
    server = _server(raising)
    out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://x.example/"})
    assert out["ok"] is True and out["result"]["reason"] == "url_refused"
    assert "exploded" not in repr(out)
    await _call(server, wt.TOOL_EXTRACT, {"url": "https://x.example/"})
    assert len(raising.fetch_calls) == 2


async def test_web_extract_cache_hit_costs_no_second_fetch():
    now = {"t": 1000.0}
    plugin = FakePlugin(page="c" * 5000)
    server = _server(plugin, clock=lambda: now["t"])
    url = "https://x.example/page"

    first = await _call(server, wt.TOOL_EXTRACT, {"url": url, "max_chars": 1000})
    assert first["result"]["cached"] is False
    now["t"] += wt.CACHE_TTL_SECONDS - 1
    second = await _call(server, wt.TOOL_EXTRACT, {"url": url, "max_chars": 1000})
    assert second["result"]["cached"] is True
    assert second["result"]["text"] == first["result"]["text"]
    assert len(plugin.fetch_calls) == 1

    # A smaller cut is served from the same entry, cut down.
    smaller = await _call(server, wt.TOOL_EXTRACT, {"url": url, "max_chars": 300})
    assert smaller["result"]["cached"] is True and smaller["result"]["chars"] == 300
    assert smaller["result"]["truncated"] is True
    assert len(plugin.fetch_calls) == 1

    # A larger cut than the cached cap must refetch — the entry cannot know the rest.
    larger = await _call(server, wt.TOOL_EXTRACT, {"url": url, "max_chars": 2000})
    assert larger["result"]["cached"] is False and larger["result"]["chars"] == 2000
    assert len(plugin.fetch_calls) == 2

    # Past the TTL the page is fetched again.
    now["t"] += wt.CACHE_TTL_SECONDS + 1
    stale = await _call(server, wt.TOOL_EXTRACT, {"url": url, "max_chars": 2000})
    assert stale["result"]["cached"] is False
    assert len(plugin.fetch_calls) == 3


def _closure_var(server, name):
    handler = server._tools[wt.TOOL_EXTRACT]["handler"]
    cells = dict(zip(handler.__code__.co_freevars, handler.__closure__, strict=True))
    return cells[name].cell_contents


def _cache_of(server):
    cache = _closure_var(server, "cache")
    assert isinstance(cache, dict)
    return cache


async def test_web_extract_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(wt, "CACHE_ENTRIES", 3)
    plugin = FakePlugin(page="d" * 400)
    server = _server(plugin)
    cache = _cache_of(server)
    urls = [f"https://x.example/{i}" for i in range(4)]
    for url in urls:
        await _call(server, wt.TOOL_EXTRACT, {"url": url})
        assert len(cache) <= 3
    assert len(cache) == 3
    assert urls[0] not in cache and urls[3] in cache
    # The evicted oldest is fetched again; the newest is still served from cache.
    await _call(server, wt.TOOL_EXTRACT, {"url": urls[0]})
    assert plugin.fetch_calls[-1][0] == urls[0]
    assert len(cache) <= 3
    out = await _call(server, wt.TOOL_EXTRACT, {"url": urls[3]})
    assert out["result"]["cached"] is True
    assert len(plugin.fetch_calls) == 5


# ── preflight + registration ─────────────────────────────────────────────────

async def test_preflight_refuses_bad_scheme_userinfo_and_out_of_range():
    plugin = FakePlugin(tavily_api_key="k", rows=[], page="p" * 300)
    server = _server(plugin)
    bad_extract = [
        {"url": "ftp://x.example/f"},
        {"url": "javascript:alert(1)"},
        {"url": "http://user:pw@host/"},
        {"url": "http://user@host/"},
        {"url": "http:///nohost"},
        {"url": "x" * (wt.MAX_URL_CHARS + 1)},
        {"url": 12},
        {"url": "https://x.example/", "max_chars": wt.MIN_EXTRACT_CHARS - 1},
        {"url": "https://x.example/", "max_chars": wt.MAX_EXTRACT_CHARS + 1},
        {"url": "https://x.example/", "max_chars": True},
        {"url": "https://x.example/", "max_chars": "300"},
    ]
    for args in bad_extract:
        out = await _call(server, wt.TOOL_EXTRACT, args)
        assert out == {"ok": False, "reason": "bad_args", "tool": wt.TOOL_EXTRACT}, args
    bad_search = [
        {"query": ""},
        {"query": "   "},
        {"query": "q" * (wt.MAX_QUERY_CHARS + 1)},
        {"query": None},
        {},
        {"query": "q", "max_results": 0},
        {"query": "q", "max_results": wt.MAX_RESULTS + 1},
        {"query": "q", "max_results": True},
        {"query": "q", "max_results": "3"},
    ]
    for args in bad_search:
        out = await _call(server, wt.TOOL_SEARCH, args)
        assert out == {"ok": False, "reason": "bad_args", "tool": wt.TOOL_SEARCH}, args
    assert plugin.search_calls == [] and plugin.fetch_calls == []


def test_tools_rows_declare_untrusted_output_and_are_ungated():
    server = _server(FakePlugin())
    rows = {row["name"]: row for row in server.tools()}
    assert set(rows) == {wt.TOOL_SEARCH, wt.TOOL_EXTRACT}
    search, extract = rows[wt.TOOL_SEARCH], rows[wt.TOOL_EXTRACT]
    for row in (search, extract):
        assert row["gated"] is False
        assert row["untrusted_output"] is True
        assert row["input_schema"]["additionalProperties"] is False
        assert "untrusted" in row["description"].lower()
    assert search["capability_id"] == "tool:web_search"
    assert extract["capability_id"] == "tool:web_extract"
    q = search["input_schema"]["properties"]["query"]
    assert (q["minLength"], q["maxLength"]) == (1, wt.MAX_QUERY_CHARS)
    n = search["input_schema"]["properties"]["max_results"]
    assert (n["minimum"], n["maximum"]) == (1, wt.MAX_RESULTS)
    u = extract["input_schema"]["properties"]["url"]
    assert u["maxLength"] == wt.MAX_URL_CHARS
    c = extract["input_schema"]["properties"]["max_chars"]
    assert (c["minimum"], c["maximum"]) == (wt.MIN_EXTRACT_CHARS, wt.MAX_EXTRACT_CHARS)
    assert "url_refused" in extract["description"]


async def test_unknown_keys_are_dropped_not_refused():
    plugin = FakePlugin(tavily_api_key="k", rows=[], page="p" * 500)
    server = _server(plugin)
    out = await _call(server, wt.TOOL_SEARCH, {"query": "q", "verbose": True, "page": 2})
    assert out["ok"] is True and out["result"]["available"] is True
    assert plugin.search_calls == [("q", wt.DEFAULT_RESULTS)]
    out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://x.example/", "render": "js"})
    assert out["ok"] is True and out["result"]["chars"] == 500
    assert plugin.fetch_calls == [("https://x.example/", wt.DEFAULT_EXTRACT_CHARS)]
    assert wt.preflight_search({"query": "q", "extra": 1}) == {
        "query": "q", "max_results": wt.DEFAULT_RESULTS,
    }
    assert wt.preflight_extract({"url": "https://x.example/", "extra": 1}) == {
        "url": "https://x.example/", "max_chars": wt.DEFAULT_EXTRACT_CHARS,
    }


# ── fixer round: findings applied (Hermes absorption 5a) ─────────────────────

async def test_web_extract_bounds_bytes_not_only_chars():
    """A page of wide characters cut at MAX_EXTRACT_CHARS would still exceed the
    tool loop's byte envelope; the byte cap keeps the text itself under it."""
    plugin = FakePlugin(page="漢" * wt.MAX_EXTRACT_CHARS)
    server = _server(plugin)
    out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://x.example/wide", "max_chars": wt.MAX_EXTRACT_CHARS})
    result = out["result"]
    assert len(result["text"].encode("utf-8")) <= wt.MAX_EXTRACT_BYTES
    assert result["chars"] == len(result["text"]) < wt.MAX_EXTRACT_CHARS
    assert result["truncated"] is True
    # The cached copy is the byte-bounded one and still says truncated.
    again = await _call(server, wt.TOOL_EXTRACT, {"url": "https://x.example/wide", "max_chars": wt.MAX_EXTRACT_CHARS})
    assert again["result"]["cached"] is True and again["result"]["truncated"] is True
    assert len(again["result"]["text"].encode("utf-8")) <= wt.MAX_EXTRACT_BYTES
    # Narrow text below the cap is untouched.
    narrow = FakePlugin(page="n" * 1000)
    out = await _call(_server(narrow), wt.TOOL_EXTRACT, {"url": "https://x.example/n", "max_chars": 2000})
    assert out["result"]["chars"] == 1000 and out["result"]["truncated"] is False


async def test_web_extract_refuses_a_url_carrying_a_known_secret():
    from agents.core.security.secret_broker import SecretBroker

    broker = SecretBroker()
    broker._store.set("api_key", "sk-live-SECRET123")
    plugin = FakePlugin(tavily_api_key="k", page="p" * 300, rows=[])
    server = ToolRPCServer(secret_broker=broker)
    wt.register_web_tools(server, lambda: plugin)

    out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://c.example/?k=sk-live-SECRET123"})
    assert out["ok"] is True
    assert out["result"]["ok"] is False and out["result"]["reason"] == "secret_in_url"
    assert "SECRET123" not in repr(out)
    assert plugin.fetch_calls == []

    out = await _call(server, wt.TOOL_SEARCH, {"query": "what is sk-live-SECRET123"})
    assert out["result"]["ok"] is False and out["result"]["reason"] == "secret_in_query"
    assert "SECRET123" not in repr(out)
    assert plugin.search_calls == []

    # A URL without the secret still reads; the broker is the server's own by default.
    out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://c.example/clean"})
    assert out["result"]["chars"] == 300


async def test_web_extract_in_a_tainted_turn_reads_only_search_result_urls():
    from agents.core.action_origin import bind_action_origin, reset_action_origin

    plugin = FakePlugin(
        tavily_api_key="k", page="p" * 300,
        rows=[{"title": "t", "url": "https://found.example/page", "snippet": "s"}],
    )
    server = _server(plugin)
    composed = "https://composed.example/?memo=owner+lives+at"
    # An inbound turn: its own label, so a search still runs — and only what the
    # search returned may then be read.
    token = bind_action_origin("inbound")
    try:
        out = await _call(server, wt.TOOL_EXTRACT, {"url": composed})
        assert out["ok"] is True
        assert out["result"] == {"available": True, "ok": False, "reason": "tainted_turn", "url": composed}
        assert all(c[0] != composed for c in plugin.fetch_calls)
        found = await _call(server, wt.TOOL_SEARCH, {"query": "q"})
        assert found["result"]["results"][0]["url"] == "https://found.example/page"
        out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://found.example/page"})
        assert out["result"]["chars"] == 300
        # Never cached, so the fence is re-decided every time.
        out = await _call(server, wt.TOOL_EXTRACT, {"url": composed})
        assert out["result"]["reason"] == "tainted_turn"
    finally:
        reset_action_origin(token)
    # A turn that has read untrusted content: no further search either, but a URL a
    # search returned on this server is still readable (from the cache here).
    token = bind_action_origin("recall:untrusted")
    try:
        out = await _call(server, wt.TOOL_EXTRACT, {"url": composed})
        assert out["result"]["reason"] == "tainted_turn"
        assert (await _call(server, wt.TOOL_SEARCH, {"query": "q"}))["result"]["reason"] == "tainted_turn"
        out = await _call(server, wt.TOOL_EXTRACT, {"url": "https://found.example/page"})
        assert out["result"]["chars"] == 300 and out["result"]["cached"] is True
    finally:
        reset_action_origin(token)
    # Fetched once; every later read of it was a cache hit; the composed URL never.
    assert [c[0] for c in plugin.fetch_calls] == ["https://found.example/page"]
    assert plugin.search_calls == [("q", 5)]
    # A clean turn reads any well-formed URL.
    out = await _call(server, wt.TOOL_EXTRACT, {"url": composed})
    assert out["result"]["chars"] == 300


async def test_web_search_after_reading_untrusted_content_is_refused_but_an_inbound_turn_still_searches():
    """The query is an outbound payload composed after reading: refused once the turn
    carries the tainted-recall label. An inbound turn keeps its own label, so its first
    search still runs — the URL rule, not the query rule, guards it."""
    from agents.core.action_origin import bind_action_origin, reset_action_origin

    plugin = FakePlugin(tavily_api_key="k", rows=[{"title": "t", "url": "https://f.example/", "snippet": "s"}])
    server = _server(plugin)
    token = bind_action_origin("recall:untrusted")
    try:
        out = await _call(server, wt.TOOL_SEARCH, {"query": "owner lives at 12 Elm St"})
        assert out["ok"] is True
        assert out["result"] == {"available": True, "ok": False, "reason": "tainted_turn"}
        assert plugin.search_calls == []
    finally:
        reset_action_origin(token)
    token = bind_action_origin("inbound")
    try:
        out = await _call(server, wt.TOOL_SEARCH, {"query": "coffee"})
        assert out["result"]["count"] == 1 and plugin.search_calls == [("coffee", 5)]
    finally:
        reset_action_origin(token)
    out = await _call(server, wt.TOOL_SEARCH, {"query": "tea"})
    assert out["result"]["count"] == 1 and plugin.search_calls[-1] == ("tea", 5)


async def test_search_url_memory_is_bounded(monkeypatch):
    monkeypatch.setattr(wt, "SEARCH_URLS_REMEMBERED", 2)
    plugin = FakePlugin(tavily_api_key="k", rows=[
        {"title": "t", "url": f"https://r.example/{i}", "snippet": "s"} for i in range(3)
    ])
    server = _server(plugin)
    await _call(server, wt.TOOL_SEARCH, {"query": "q", "max_results": 3})
    seen = _closure_var(server, "seen_urls")
    assert len(seen) == 2 and list(seen) == ["https://r.example/1", "https://r.example/2"]


async def test_preflight_refuses_control_characters_in_url():
    plugin = FakePlugin(page="p" * 300)
    server = _server(plugin)
    for url in ("http://x.example/a\r\nHost: evil", "http://x.example/\tb", "http://x.example/\x7f"):
        out = await _call(server, wt.TOOL_EXTRACT, {"url": url})
        assert out == {"ok": False, "reason": "bad_args", "tool": wt.TOOL_EXTRACT}, repr(url)
    assert plugin.fetch_calls == []


async def test_plugin_getter_that_raises_answers_unavailable(caplog):
    def boom():
        raise RuntimeError("orchestrator not built yet https://secret.example/?token=abc")

    server = ToolRPCServer()
    wt.register_web_tools(server, boom)
    for tool, args in ((wt.TOOL_SEARCH, {"query": "q"}), (wt.TOOL_EXTRACT, {"url": "https://x.example/"})):
        out = await _call(server, tool, args)
        assert out["ok"] is True
        assert out["result"] == {"available": False, "ok": False, "reason": "websearch_unavailable"}
    assert "secret.example" not in caplog.text and "token=abc" not in caplog.text


async def test_web_search_null_fields_read_empty_and_taint_source_is_bounded():
    plugin = FakePlugin(tavily_api_key="k", rows=[
        {"title": None, "url": None, "snippet": None, "taint_source": "z" * 5000},
        {"title": "ok", "url": "https://o.example/", "snippet": "s", "taint_source": None},
    ])
    out = await _call(_server(plugin), wt.TOOL_SEARCH, {"query": "q"})
    first, second = out["result"]["results"]
    assert (first["title"], first["url"], first["snippet"]) == ("", "", "")
    assert len(first["taint_source"]) == wt.TAINT_SOURCE_CHARS
    assert second["taint_source"] == "websearch" and second["tainted"] is True
