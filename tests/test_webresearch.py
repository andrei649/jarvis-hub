"""Tests for web_research skill (no network calls)."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


@pytest.mark.asyncio
async def test_research_with_results(monkeypatch):
    from skills.web_research.main import research

    async def fake_search(self, query, max_results=5):
        return [
            {"title": "MarTech CEE 2025", "url": "https://example.com/1", "snippet": "Creștere rapidă..."},
            {"title": "Marketing Tech Report", "url": "https://example.com/2", "snippet": "Analiză detaliată."},
        ]

    monkeypatch.setattr("agents.core.plugins.websearch.WebSearchPlugin.search", fake_search)

    output = await research("piața MarTech CEE")
    assert "piața MarTech CEE" in output
    assert "MarTech CEE 2025" in output
    assert "https://example.com/1" in output
    assert "https://example.com/2" in output
    assert "S-au găsit 2 rezultate" in output


@pytest.mark.asyncio
async def test_research_no_results(monkeypatch):
    from skills.web_research.main import research

    async def fake_search(self, query, max_results=5):
        return []

    monkeypatch.setattr("agents.core.plugins.websearch.WebSearchPlugin.search", fake_search)

    output = await research("xyzzy_nonexistent_123")
    assert "Niciun rezultat găsit" in output


@pytest.mark.asyncio
async def test_research_empty_query():
    from skills.web_research.main import research

    output = await research("")
    assert "Folosire: research" in output


@pytest.mark.asyncio
async def test_research_plugin_unavailable(monkeypatch):
    from skills.web_research.main import research, _get_plugin

    def raise_import_error():
        raise ImportError("No module named 'websearch'")

    monkeypatch.setattr("skills.web_research.main._get_plugin", raise_import_error)

    output = await research("test query")
    assert "indisponibil" in output


@pytest.mark.asyncio
async def test_research_search_exception(monkeypatch):
    from skills.web_research.main import research

    async def fake_search(self, query, max_results=5):
        raise RuntimeError("Connection timeout")

    monkeypatch.setattr("agents.core.plugins.websearch.WebSearchPlugin.search", fake_search)

    output = await research("test query")
    assert "Eroare la căutarea web" in output


def test_get_commands():
    from skills.web_research.main import get_commands

    cmds = get_commands()
    assert "research" in cmds
    assert len(cmds) == 1


@pytest.mark.asyncio
async def test_handle_research(monkeypatch):
    from skills.web_research.main import handle

    async def fake_search(self, query, max_results=5):
        return [{"title": "Test", "url": "https://x.com", "snippet": "desc"}]

    monkeypatch.setattr("agents.core.plugins.websearch.WebSearchPlugin.search", fake_search)

    output = await handle("research", "test")
    assert "Test" in output
    assert "https://x.com" in output


@pytest.mark.asyncio
async def test_handle_unknown_command():
    from skills.web_research.main import handle

    output = await handle("unknown_cmd", "")
    assert "comandă necunoscută" in output


@pytest.mark.asyncio
async def test_research_results_missing_fields(monkeypatch):
    from skills.web_research.main import research

    async def fake_search(self, query, max_results=5):
        return [
            {"title": "", "url": "", "snippet": ""},
            {},
        ]

    monkeypatch.setattr("agents.core.plugins.websearch.WebSearchPlugin.search", fake_search)

    output = await research("test")
    assert "[fără titlu]" in output
    assert "S-au găsit 2 rezultate" in output
