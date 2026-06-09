"""
digest.py — H12.23 Composable multi-source digest + idea-reality scorer.

A small, *composable* digest engine: several weighted sources (news / Reddit /
arXiv / HN / YouTube / HF — anything with an RSS/Atom feed) are fetched, merged,
deduped, and ranked by a composite of source weight × recency × an
**idea-reality score** that demotes hype and promotes substance (numbers,
releases, papers, code). Sources share one URL-template shape, so adding a feed
is one line.

The HTTP fetch is **injected** (``fetcher``), so the engine is fully
offline-testable; the live fetch uses the shared ``PluginHTTPClient``. Signed,
packaged skills that wrap this engine are a downstream/offline-gated follow-up.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Awaitable, Callable, Optional
from urllib.parse import quote_plus

logger = logging.getLogger("jarvis.digest")

# Substance vs hype lexicons for the idea-reality score.
_SUBSTANCE = re.compile(
    r"\b(release[ds]?|shipp?(?:ed|ing)?|benchmark|dataset|open[\s-]?source|"
    r"paper|results?|code|sdk|api|version|v?\d+(?:\.\d+)+|\d+%|\$\d|launch(?:ed)?)\b",
    re.IGNORECASE,
)
_HYPE = re.compile(
    r"\b(revolutionary|breakthrough|game[\s-]?chang\w+|insane|mind[\s-]?blow\w+|"
    r"unbelievable|will change everything|shocking|secret|you won'?t believe)\b",
    re.IGNORECASE,
)


def idea_reality_score(text: str) -> float:
    """0..1 — higher = more concrete/substantive, lower = more hype. Neutral=0.5."""
    if not text:
        return 0.5
    substance = len(_SUBSTANCE.findall(text))
    hype = len(_HYPE.findall(text))
    if substance == 0 and hype == 0:
        return 0.5
    raw = (substance - hype) / (substance + hype)   # -1..1
    return round(0.5 + 0.5 * raw, 3)                 # 0..1


def parse_feed(xml: str, limit: int = 20) -> list[dict]:
    """Parse an RSS ``<item>`` or Atom ``<entry>`` feed → [{title, link, summary}]."""
    out: list[dict] = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    # strip namespaces so Atom + RSS parse uniformly
    for el in root.iter():
        el.tag = el.tag.rsplit("}", 1)[-1]
    for node in list(root.iter("item")) + list(root.iter("entry")):
        title = (node.findtext("title") or "").strip()
        if not title:
            continue
        link = ""
        link_el = node.find("link")
        if link_el is not None:
            link = (link_el.get("href") or link_el.text or "").strip()
        summary = (node.findtext("summary") or node.findtext("description") or "").strip()
        out.append({"title": title, "link": link, "summary": summary})
        if len(out) >= limit:
            break
    return out


class DigestSource:
    """One weighted feed. ``url_template`` may contain ``{topic}`` (URL-encoded)."""

    def __init__(self, name: str, url_template: str, weight: float = 1.0,
                 fetcher: Optional[Callable[[str], Awaitable[str]]] = None) -> None:
        self.name = name
        self.url_template = url_template
        self.weight = float(weight)
        self._fetcher = fetcher

    def url_for(self, topic: str) -> str:
        return self.url_template.replace("{topic}", quote_plus(topic or ""))

    async def fetch(self, topic: str = "", limit: int = 20) -> list[dict]:
        if self._fetcher is None:
            return []
        try:
            xml = await self._fetcher(self.url_for(topic))
        except Exception:
            logger.warning("digest source %s fetch failed", self.name, exc_info=True)
            return []
        items = parse_feed(xml, limit)
        for it in items:
            it["source"] = self.name
            it["weight"] = self.weight
        return items


# Built-in source templates (RSS/Atom). The fetcher is supplied at build time.
SOURCE_TEMPLATES = {
    "hn": "https://hnrss.org/newest?q={topic}",
    "reddit": "https://www.reddit.com/search.rss?q={topic}&sort=top",
    "arxiv": "http://export.arxiv.org/api/query?search_query=all:{topic}&max_results=20",
    "youtube": "https://www.youtube.com/feeds/videos.xml?search_query={topic}",
    "news": "https://news.google.com/rss/search?q={topic}",
}


class DigestAggregator:
    """Fetch all sources, dedupe, and rank by weight × reality × recency."""

    def __init__(self, sources: Optional[list[DigestSource]] = None) -> None:
        self.sources = sources or []

    async def run(self, topic: str = "", limit: int = 10) -> dict:
        seen: set[str] = set()
        ranked: list[dict] = []
        for src in self.sources:
            for item in await src.fetch(topic):
                key = (item.get("link") or item.get("title", "")).lower().strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                reality = idea_reality_score(f"{item['title']} {item.get('summary', '')}")
                item["reality"] = reality
                # composite: source weight, biased by substance (0.5..1.5 multiplier)
                item["score"] = round(item["weight"] * (0.5 + reality), 4)
                ranked.append(item)
        ranked.sort(key=lambda it: it["score"], reverse=True)
        top = ranked[:limit]
        return {
            "topic": topic,
            "count": len(top),
            "sources": [s.name for s in self.sources],
            "items": [{k: it[k] for k in ("title", "link", "source", "reality", "score")}
                      for it in top],
        }


def build_default_aggregator(
        fetcher: Callable[[str], Awaitable[str]],
        weights: Optional[dict] = None,
        names: Optional[list[str]] = None) -> DigestAggregator:
    """Compose an aggregator over the built-in templates with a shared fetcher."""
    weights = weights or {}
    names = names or list(SOURCE_TEMPLATES)
    sources = [
        DigestSource(name, SOURCE_TEMPLATES[name], weight=weights.get(name, 1.0), fetcher=fetcher)
        for name in names if name in SOURCE_TEMPLATES
    ]
    return DigestAggregator(sources)
