"""Tests for web_research skill (no network calls)."""

import importlib.util
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


@pytest.fixture
def optional_web_research():
    """Exercise the shipped optional source without installing/activating it."""
    path = repo_root / "optional-skills/web_research/main.py"
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("nerva_optional_web_research", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_research_with_results(monkeypatch, optional_web_research):

    async def fake_search(self, query, max_results=5):
        return [
            {"title": "MarTech CEE 2025", "url": "https://example.com/1", "snippet": "Creștere rapidă..."},
            {"title": "Marketing Tech Report", "url": "https://example.com/2", "snippet": "Analiză detaliată."},
        ]

    monkeypatch.setattr("agents.core.plugins.websearch.WebSearchPlugin.search", fake_search)

    output = await optional_web_research.research("piața MarTech CEE")
    assert "piața MarTech CEE" in output
    assert "MarTech CEE 2025" in output
    assert "https://example.com/1" in output
    assert "https://example.com/2" in output
    assert "S-au găsit 2 rezultate" in output


@pytest.mark.asyncio
async def test_research_no_results(monkeypatch, optional_web_research):

    async def fake_search(self, query, max_results=5):
        return []

    monkeypatch.setattr("agents.core.plugins.websearch.WebSearchPlugin.search", fake_search)

    output = await optional_web_research.research("xyzzy_nonexistent_123")
    assert "Niciun rezultat găsit" in output


@pytest.mark.asyncio
async def test_research_empty_query(optional_web_research):
    output = await optional_web_research.research("")
    assert "Folosire: research" in output


@pytest.mark.asyncio
async def test_research_plugin_unavailable(monkeypatch, optional_web_research):

    def raise_import_error():
        raise ImportError("No module named 'websearch'")

    monkeypatch.setattr(optional_web_research, "_get_plugin", raise_import_error)

    output = await optional_web_research.research("test query")
    assert "indisponibil" in output


@pytest.mark.asyncio
async def test_research_search_exception(monkeypatch, optional_web_research):

    async def fake_search(self, query, max_results=5):
        raise RuntimeError("Connection timeout")

    monkeypatch.setattr("agents.core.plugins.websearch.WebSearchPlugin.search", fake_search)

    output = await optional_web_research.research("test query")
    assert "Eroare la căutarea web" in output


def test_get_commands(optional_web_research):
    cmds = optional_web_research.get_commands()
    assert "research" in cmds
    assert len(cmds) == 1


@pytest.mark.asyncio
async def test_handle_research(monkeypatch, optional_web_research):

    async def fake_search(self, query, max_results=5):
        return [{"title": "Test", "url": "https://x.com", "snippet": "desc"}]

    monkeypatch.setattr("agents.core.plugins.websearch.WebSearchPlugin.search", fake_search)

    output = await optional_web_research.handle("research", "test")
    assert "Test" in output
    assert "https://x.com" in output


@pytest.mark.asyncio
async def test_handle_unknown_command(optional_web_research):
    output = await optional_web_research.handle("unknown_cmd", "")
    assert "comandă necunoscută" in output


@pytest.mark.asyncio
async def test_research_results_missing_fields(monkeypatch, optional_web_research):

    async def fake_search(self, query, max_results=5):
        return [
            {"title": "", "url": "", "snippet": ""},
            {},
        ]

    monkeypatch.setattr("agents.core.plugins.websearch.WebSearchPlugin.search", fake_search)

    output = await optional_web_research.research("test")
    assert "[fără titlu]" in output
    assert "S-au găsit 2 rezultate" in output
