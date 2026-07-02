"""H12.23: composable multi-source digest + idea-reality scorer.

Sources are weighted RSS/Atom feeds; results are merged, deduped, and ranked by
source weight × an idea-reality score that demotes hype and promotes substance.
The HTTP fetch is injected, so the whole engine runs offline.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.digest import (  # noqa: E402
    idea_reality_score, parse_feed, DigestSource, DigestAggregator,
    build_default_aggregator, SOURCE_TEMPLATES,
)
from core.security import taint  # noqa: E402
import agents.web as web  # noqa: E402


# ── idea-reality score ────────────────────────────────────────────

def test_score_neutral_when_no_signal():
    assert idea_reality_score("a quiet update") == 0.5
    assert idea_reality_score("") == 0.5


def test_substance_scores_high_hype_scores_low():
    assert idea_reality_score("Model v2.1 released with benchmark results and code") > 0.7
    assert idea_reality_score("This revolutionary breakthrough will change everything") < 0.3


# ── feed parsing (RSS + Atom) ─────────────────────────────────────

_RSS = """<rss><channel>
  <item><title>Alpha release v1.2</title><link>http://x/a</link><description>ships code</description></item>
  <item><title>Beta news</title><link>http://x/b</link></item>
</channel></rss>"""

_ATOM = """<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>Paper on datasets</title><link href="http://y/p"/><summary>results</summary></entry>
</feed>"""


def test_parse_rss_and_atom():
    rss = parse_feed(_RSS)
    assert [i["title"] for i in rss] == ["Alpha release v1.2", "Beta news"]
    assert rss[0]["link"] == "http://x/a"
    atom = parse_feed(_ATOM)
    assert atom[0]["title"] == "Paper on datasets" and atom[0]["link"] == "http://y/p"


def test_parse_bad_xml_is_safe():
    assert parse_feed("<not xml") == []


# ── source: injectable fetch (offline) ────────────────────────────

def _fetcher(mapping):
    async def f(url):
        for frag, xml in mapping.items():
            if frag in url:
                return xml
        return "<rss><channel></channel></rss>"
    return f


async def test_source_fetch_tags_source_and_weight():
    src = DigestSource("hn", "http://h/?q={topic}", weight=2.0, fetcher=_fetcher({"h/": _RSS}))
    items = await src.fetch("ai")
    assert items and items[0]["source"] == "hn" and items[0]["weight"] == 2.0


async def test_source_url_encodes_topic():
    captured = {}

    async def f(url):
        captured["url"] = url
        return _RSS
    src = DigestSource("news", "http://n/?q={topic}", fetcher=f)
    await src.fetch("large models")
    assert "large+models" in captured["url"]


async def test_source_fetch_failure_is_graceful():
    async def boom(url):
        raise RuntimeError("network down")
    assert await DigestSource("x", "http://x/{topic}", fetcher=boom).fetch("t") == []


# ── aggregator: dedup + weighted ranking ──────────────────────────

async def test_aggregator_dedupes_and_ranks():
    # two sources; one returns a substantive item, the other a hype dup + a hype item
    s1 = DigestSource("a", "a/{topic}", weight=1.0, fetcher=_fetcher({"a/": _RSS}))
    hype = """<rss><channel>
      <item><title>Alpha release v1.2</title><link>http://x/a</link></item>
      <item><title>Shocking secret you won't believe</title><link>http://x/c</link></item>
    </channel></rss>"""
    s2 = DigestSource("b", "b/{topic}", weight=1.0, fetcher=_fetcher({"b/": hype}))
    out = await DigestAggregator([s1, s2]).run("ai", limit=10)
    titles = [i["title"] for i in out["items"]]
    assert titles.count("Alpha release v1.2") == 1            # deduped by link
    # substantive item outranks the hype one
    assert titles[0] == "Alpha release v1.2"
    assert out["items"][-1]["title"].startswith("Shocking")


async def test_aggregator_limit_and_shape():
    s = DigestSource("a", "a/{topic}", fetcher=_fetcher({"a/": _RSS}))
    out = await DigestAggregator([s]).run("ai", limit=1)
    assert out["count"] == 1 and out["sources"] == ["a"]
    assert set(out["items"][0]) == {"title", "link", "source", "reality", "score", "tainted", "taint_source"}


# ── TASK-3/H23.6: every digest item is external feed content — must be tainted ──

async def test_source_fetch_taints_every_item():
    src = DigestSource("hn", "http://h/?q={topic}", fetcher=_fetcher({"h/": _RSS}))
    items = await src.fetch("ai")
    assert items and all(taint.is_tainted(it) and it["taint_source"] == "hn" for it in items)


async def test_aggregator_output_carries_taint_mark():
    s = DigestSource("a", "a/{topic}", fetcher=_fetcher({"a/": _RSS}))
    out = await DigestAggregator([s]).run("ai", limit=10)
    assert out["items"] and all(taint.is_tainted(it) for it in out["items"])


def test_build_default_aggregator_uses_templates():
    async def f(url):
        return _RSS
    agg = build_default_aggregator(f, weights={"hn": 3.0}, names=["hn", "arxiv", "bogus"])
    assert [s.name for s in agg.sources] == ["hn", "arxiv"]    # bogus dropped
    assert agg.sources[0].weight == 3.0
    assert "arxiv" in SOURCE_TEMPLATES


# ── endpoint ──────────────────────────────────────────────────────

async def test_endpoint_runs_offline(monkeypatch):
    # stub the shared HTTP client so the endpoint never hits the network
    class _Resp:
        text = _RSS
        def raise_for_status(self): pass

    class _Client:
        async def get(self, url): return _Resp()

    from agents.core import http_client
    monkeypatch.setattr(http_client.PluginHTTPClient, "for_plugin",
                        classmethod(lambda cls, name: _Client()))
    client = TestClient(web.app)
    r = client.post("/api/digest/run", json={"topic": "ai", "sources": ["hn"], "limit": 5})
    assert r.status_code == 200
    data = r.json()
    assert data["topic"] == "ai" and data["sources"] == ["hn"]
    assert any(i["title"] == "Alpha release v1.2" for i in data["items"])
