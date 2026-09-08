"""Tests for WebSearchPlugin (no network calls)."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.plugins.websearch import WebSearchPlugin
from core.security import taint


def test_plugin_instantiates():
    wp = WebSearchPlugin()
    assert wp.tavily_api_key == ""
    assert wp.searxng_url == ""


def test_plugin_with_tavily_key():
    wp = WebSearchPlugin(tavily_api_key="test-key")
    assert wp.tavily_api_key == "test-key"


def test_plugin_with_searxng():
    wp = WebSearchPlugin(searxng_url="http://searxng:8888")
    assert wp.searxng_url == "http://searxng:8888"


@pytest.mark.asyncio
async def test_search_duckduckgo_httpx_error(monkeypatch):
    async def mock_get(*a, **kw):
        raise Exception("Connection refused")
    wp = WebSearchPlugin()
    monkeypatch.setattr(wp._client, "get", mock_get)
    results = await wp._search_duckduckgo("test", 3)
    assert results == []


@pytest.mark.asyncio
async def test_search_uses_tavily_when_key_set(monkeypatch):
    async def fake_tavily(self, q, m):
        return [{"title": "result"}]
    monkeypatch.setattr("core.plugins.websearch.WebSearchPlugin._search_tavily",
                        fake_tavily)
    wp = WebSearchPlugin(tavily_api_key="test-key")
    results = await wp.search("test", 3)
    assert len(results) == 1
    assert results[0]["title"] == "result"


@pytest.mark.asyncio
async def test_search_uses_searxng_when_url_set(monkeypatch):
    async def fake_searxng(self, q, m):
        return [{"title": "searxng-result"}]
    monkeypatch.setattr("core.plugins.websearch.WebSearchPlugin._search_searxng",
                        fake_searxng)
    wp = WebSearchPlugin(searxng_url="http://searxng:8888")
    results = await wp.search("test", 3)
    assert len(results) == 1
    assert results[0]["title"] == "searxng-result"


@pytest.mark.asyncio
async def test_search_tavily_network_error(monkeypatch):
    async def mock_post(*a, **kw):
        raise Exception("Connection refused")

    wp = WebSearchPlugin(tavily_api_key="bad-key")
    monkeypatch.setattr(wp._client, "post", mock_post)
    results = await wp._search_tavily("test", 5)
    assert results == []


@pytest.mark.asyncio
async def test_search_searxng_network_error(monkeypatch):
    async def mock_get(*a, **kw):
        raise Exception("Connection refused")

    wp = WebSearchPlugin(searxng_url="http://localhost:1")
    monkeypatch.setattr(wp._client, "get", mock_get)
    results = await wp._search_searxng("test", 5)
    assert results == []


@pytest.mark.asyncio
async def test_fetch_page_network_error():
    wp = WebSearchPlugin()
    result = await wp.fetch_page("http://localhost:1/nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_close_is_noop():
    wp = WebSearchPlugin()
    result = await wp.close()
    assert result is None


# ── TASK-3/H23.6: search results are untrusted external content ─────────────

@pytest.mark.asyncio
async def test_search_results_are_tainted(monkeypatch):
    async def fake_tavily(self, q, m):
        return [{"title": "result", "url": "http://x", "snippet": "s"}]
    monkeypatch.setattr("core.plugins.websearch.WebSearchPlugin._search_tavily", fake_tavily)
    wp = WebSearchPlugin(tavily_api_key="test-key")
    results = await wp.search("test", 3)
    assert results and all(taint.is_tainted(r) and r["taint_source"] == "websearch" for r in results)


# ── Hermes absorption 5a: the page reader has its own egress identity ────────

@pytest.mark.asyncio
async def test_fetch_page_cap_is_clamped_and_reader_identity_is_webread(monkeypatch):
    import httpx
    from core.plugins import websearch as ws

    wp = WebSearchPlugin()
    assert wp._reader.plugin_name == "webread"
    assert wp._client.plugin_name == "websearch"

    monkeypatch.setattr(ws, "resolve_and_validate",
                        lambda host, *a, **k: (["93.184.216.34"], None))
    body = "<html><body><p>" + ("x" * 30000) + "</p></body></html>"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=body))

    over = await wp.fetch_page("http://example.com/", max_chars=999999, _transport=transport)
    assert len(over) == ws.PAGE_MAX_CHARS_MAX
    under = await wp.fetch_page("http://example.com/", max_chars=1, _transport=transport)
    assert len(under) == ws.PAGE_MAX_CHARS_MIN
    default = await wp.fetch_page("http://example.com/", _transport=transport)
    assert len(default) == ws.PAGE_MAX_CHARS_DEFAULT
    exact = await wp.fetch_page("http://example.com/", max_chars=1000, _transport=transport)
    assert len(exact) == 1000


# ── fixer round: the reader is bounded in bytes and media type ───────────────

@pytest.mark.asyncio
async def test_fetch_page_refuses_non_text_media_types(monkeypatch):
    import os

    import httpx
    from core.plugins import websearch as ws

    monkeypatch.setattr(ws, "resolve_and_validate",
                        lambda host, *a, **k: (["93.184.216.34"], None))
    wp = WebSearchPlugin()
    for content_type in ("image/png", "application/pdf", "application/octet-stream", ""):
        headers = {"content-type": content_type} if content_type else {}
        transport = httpx.MockTransport(
            lambda request, h=headers: httpx.Response(200, content=os.urandom(2048), headers=h)
        )
        assert await wp.fetch_page("http://example.com/blob", _transport=transport) is None, content_type
    html = httpx.MockTransport(lambda request: httpx.Response(
        200, content=b"<html><body><p>readable</p></body></html>",
        headers={"content-type": "text/html; charset=utf-8"},
    ))
    assert await wp.fetch_page("http://example.com/page", _transport=html) == "readable"


@pytest.mark.asyncio
async def test_fetch_page_stops_reading_at_the_byte_cap(monkeypatch):
    import httpx
    from core.plugins import websearch as ws

    monkeypatch.setattr(ws, "resolve_and_validate",
                        lambda host, *a, **k: (["93.184.216.34"], None))

    class Endless(httpx.AsyncByteStream):
        """Yields 8 MB in 64 KB chunks and counts what the reader pulled."""

        def __init__(self):
            self.sent = 0

        async def __aiter__(self):
            for _ in range(8 * 1024 * 1024 // 65536):
                self.sent += 65536
                yield b"y" * 65536

    stream = Endless()
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, stream=stream, headers={"content-type": "text/html"},
    ))
    text = await WebSearchPlugin().fetch_page("http://example.com/big", max_chars=300, _transport=transport)
    assert text is not None and len(text) == 300
    assert stream.sent <= ws.PAGE_MAX_BYTES + ws.PAGE_READ_CHUNK_BYTES


@pytest.mark.asyncio
async def test_ssrf_refusals_do_not_open_the_reader_breaker(monkeypatch):
    import httpx
    from core.http_client import PluginHTTPClient
    from core.plugins import websearch as ws
    from core.resilience import CircuitBreaker

    table = {"good.example": (["93.184.216.34"], None)}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<p>fine</p>"))
    wp = WebSearchPlugin()
    wp._reader = PluginHTTPClient(
        "webread",
        circuit_breaker=CircuitBreaker(failure_threshold=5, recovery_timeout=60.0, key="test:webread"),
        resolver=lambda host, *a, **k: table.get(host, ([], f"URL resolves to private IP: {host}")),
        transport_factory=lambda _target: transport,
    )
    for i in range(7):
        assert await wp.fetch_page(f"http://private{i}.internal/") is None
    # A policy refusal is not a backend failure: the breaker stays closed and a
    # good page still reads instead of being blinded for the recovery window.
    assert wp._reader.circuit_breaker.is_open() is False
    assert await wp.fetch_page("http://good.example/") == "fine"
    await wp.close()


# ── the DuckDuckGo redirector is unwrapped at the parser ─────────────────────
# The HTML endpoint hands back `//duckduckgo.com/l/?uddg=<target>`, protocol-relative
# and scheme-less, which `web_extract`'s preflight refuses as `bad_args` — so with the
# keyless backend the model could search and never open what it found.

def test_unwrap_turns_the_protocol_relative_redirector_into_the_real_url():
    from core.plugins.websearch import _unwrap_result_url

    href = ("//duckduckgo.com/l/?uddg=https%3A%2F%2Fpypi.org%2Fproject%2Fruff%2F"
            "&rut=0d0b1f2e3a")
    assert _unwrap_result_url(href) == "https://pypi.org/project/ruff/"
    # the same wrapper with a scheme, and the http one
    assert _unwrap_result_url(
        "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa%3Fb%3Dc"
    ) == "https://example.com/a?b=c"
    assert _unwrap_result_url(
        "//html.duckduckgo.com/l/?uddg=http%3A%2F%2Fexample.com%2F"
    ) == "http://example.com/"


def test_unwrap_leaves_a_direct_result_url_alone():
    from core.plugins.websearch import _unwrap_result_url

    assert _unwrap_result_url("https://example.com/page") == "https://example.com/page"
    assert _unwrap_result_url("  https://example.com/page  ") == "https://example.com/page"


def test_unwrap_never_percent_decodes_the_target_twice():
    """`parse_qs` already percent-decodes exactly once, which is the whole decoding the
    wrapper needs. A second pass would turn the `%20` that decode produced into a literal
    space and hand the reader a different address than the one the result named."""
    from core.plugins.websearch import _unwrap_result_url

    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa%2520b"
    assert _unwrap_result_url(href) == "https://example.com/a%20b"
    assert " " not in _unwrap_result_url(href)   # the double-decoded shape


def test_unwrap_refuses_everything_that_is_not_an_http_result():
    from core.plugins.websearch import MAX_RESULT_URL_CHARS, _unwrap_result_url

    for href in (
        "", "   ", None, 42,
        "/relative/path",
        "javascript:alert(1)",
        "ftp://example.com/f",
        "//duckduckgo.com/l/?rut=nouddg",                       # wrapper with no target
        "//duckduckgo.com/l/?uddg=javascript%3Aalert(1)",       # target is not http(s)
        "//duckduckgo.com/l/?uddg=%2Frelative",                 # target has no host
        # a redirector pointing at another redirector is not a result: one hop only
        "//duckduckgo.com/l/?uddg=https%3A%2F%2Fduckduckgo.com%2Fl%2F%3Fuddg%3D"
        "https%253A%252F%252Fexample.com%252F",
        "https://example.com/" + "x" * MAX_RESULT_URL_CHARS,    # over the cap
    ):
        got = _unwrap_result_url(href)
        if href == ("//duckduckgo.com/l/?uddg=https%3A%2F%2Fduckduckgo.com%2Fl%2F%3Fuddg%3D"
                    "https%253A%252F%252Fexample.com%252F"):
            # it unwraps to a duckduckgo.com URL, which is a real http(s) address —
            # honest, and the reader may fetch it; what must NOT happen is a second hop
            assert got.startswith("https://duckduckgo.com/l/"), got
            continue
        assert got == "", (href, got)


@pytest.mark.asyncio
async def test_duckduckgo_rows_carry_a_readable_url(monkeypatch):
    """End to end through the real parser: the row `web_search` hands the model must be
    an address `web_extract` will accept, not the scheme-less wrapper DDG emits."""
    from core.plugins.websearch import WebSearchPlugin

    html = """
    <div class="result">
      <h2 class="result__title"><a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpypi.org%2Fproject%2Fruff%2F&amp;rut=9">ruff · PyPI</a></h2>
      <a class="result__snippet">An extremely fast Python linter.</a>
    </div>
    <div class="result">
      <h2 class="result__title"><a href="/relative-nonsense">broken</a></h2>
      <a class="result__snippet">no usable address</a>
    </div>
    """

    class _Resp:
        text = html
        def raise_for_status(self):
            return None

    wp = WebSearchPlugin()
    async def fake_get(*a, **kw):
        return _Resp()
    monkeypatch.setattr(wp._client, "get", fake_get)

    rows = await wp._search_duckduckgo("ruff", 5)
    assert rows[0]["url"] == "https://pypi.org/project/ruff/"
    assert rows[0]["title"] == "ruff · PyPI"
    assert rows[1]["url"] == ""          # honest empty, never the unusable href

    # and the address really is one the reader's own preflight accepts
    from agents.core.web_tools import preflight_extract
    assert preflight_extract({"url": rows[0]["url"]})["url"] == "https://pypi.org/project/ruff/"
