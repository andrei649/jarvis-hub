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
    monkeypatch.setattr("httpx.AsyncClient.get", mock_get)
    wp = WebSearchPlugin()
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
async def test_search_tavily_network_error():
    wp = WebSearchPlugin(tavily_api_key="bad-key")
    results = await wp._search_tavily("test", 5)
    assert results == []


@pytest.mark.asyncio
async def test_search_searxng_network_error():
    wp = WebSearchPlugin(searxng_url="http://localhost:1")
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
