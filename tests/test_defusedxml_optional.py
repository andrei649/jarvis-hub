"""Startup hardening: the optional ``defusedxml`` dependency.

If defusedxml is missing, feed parsing must DISABLE itself (return an empty
result / a clear placeholder) rather than crash the whole server at import — and
it must NEVER fall back to the unsafe stdlib ``xml.etree`` parser on this
untrusted RSS/Atom input. Covers ``agents/core/digest.py:parse_feed`` and
``agents/core/plugins/news.py:NewsPlugin.get_headlines`` for the dep-absent path.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core import digest as digest_mod  # noqa: E402
from core.plugins import news as news_mod  # noqa: E402

_WELL_FORMED_RSS = (
    "<rss><channel>"
    "<item><title>Alpha</title><link>http://x/a</link></item>"
    "</channel></rss>"
)


def test_digest_parse_feed_disabled_when_defusedxml_missing(monkeypatch):
    # Even a perfectly well-formed feed parses to EMPTY when the hardening dep is
    # unavailable — we must not silently fall back to the unsafe stdlib parser.
    monkeypatch.setattr(digest_mod, "_XML_OK", False)
    assert digest_mod.parse_feed(_WELL_FORMED_RSS) == []


def test_digest_parse_feed_works_when_defusedxml_present():
    # Sanity: in the normal case (dep installed) parsing still works.
    assert digest_mod._XML_OK is True
    out = digest_mod.parse_feed(_WELL_FORMED_RSS)
    assert out and out[0]["title"] == "Alpha"


async def test_news_headlines_disabled_when_defusedxml_missing(monkeypatch):
    # get_headlines returns a clear placeholder (no network call, no crash) when
    # parsing is disabled — the rest of the server keeps running.
    monkeypatch.setattr(news_mod, "_XML_OK", False)
    plugin = news_mod.NewsPlugin()
    headlines = await plugin.get_headlines()
    assert headlines and "defusedxml" in headlines[0]["title"].lower()
