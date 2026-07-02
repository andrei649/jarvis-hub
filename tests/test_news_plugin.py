"""Tests for NewsPlugin (RSS feed fetch + parse, no network calls).

TASK-3/H23.6 — headlines are untrusted external content; get_headlines must
mark every parsed item so any action later built from it escalates through
the kernel instead of auto-executing.
"""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.plugins.news import NewsPlugin  # noqa: E402
from core.security import taint  # noqa: E402

_RSS = """<rss><channel>
  <item><title>Alpha headline</title><link>http://x/a</link></item>
  <item><title>Beta headline</title><link>http://x/b</link></item>
</channel></rss>"""


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


@pytest.mark.asyncio
async def test_get_headlines_results_are_tainted(monkeypatch):
    plugin = NewsPlugin()

    async def fake_get(url):
        return _Resp(_RSS)
    monkeypatch.setattr(plugin.client, "get", fake_get)

    headlines = await plugin.get_headlines("general", limit=5)
    assert [h["title"] for h in headlines] == ["Alpha headline", "Beta headline"]
    assert all(taint.is_tainted(h) and h["taint_source"] == "news" for h in headlines)


@pytest.mark.asyncio
async def test_get_headlines_error_placeholder_is_not_tainted(monkeypatch):
    # A synthetic error placeholder isn't real external content — no taint needed.
    plugin = NewsPlugin()

    async def boom(url):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(plugin.client, "get", boom)

    headlines = await plugin.get_headlines("general", limit=5)
    assert headlines and "unavailable" in headlines[0]["title"].lower()
    assert taint.is_tainted(headlines[0]) is False
