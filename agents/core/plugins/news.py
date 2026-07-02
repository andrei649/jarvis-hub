import logging

# defusedxml hardens parsing of the untrusted RSS/Atom feeds this plugin fetches
# (Python's stdlib xml.etree is unsafe on hostile input — entity-expansion DoS).
# Drop-in: exposes fromstring + ParseError; rejects DTD/entity attacks as ValueError.
# The dep is OPTIONAL at import time: if it's missing we disable feed parsing (a
# clear placeholder) rather than crash the whole server at startup — and we never
# fall back to the unsafe stdlib parser on this untrusted input.
try:
    import defusedxml.ElementTree as ET

    _XML_OK = True
except ImportError:  # pragma: no cover - only when the optional dep is uninstalled
    ET = None
    _XML_OK = False

from ..http_client import PluginHTTPClient
from ..security import taint

logger = logging.getLogger("jarvis.plugins.news")

FEEDS = {
    "general": "https://feeds.bbci.co.uk/news/rss.xml",
    "world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "technology": "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "science": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "romania": "https://www.hotnews.ro/rss",
    "local": "https://www.stiripesurse.ro/rss",
}


class NewsPlugin:
    def __init__(self):
        self.client = PluginHTTPClient.for_plugin("news")

    async def get_headlines(self, category: str = "general", limit: int = 5) -> list[dict]:
        if not _XML_OK:
            logger.warning("News feed parsing disabled: defusedxml is not installed.")
            return [{"title": "News feed disabled — install defusedxml to enable.", "link": ""}]
        feed_url = FEEDS.get(category, FEEDS["general"])
        try:
            resp = await self.client.get(feed_url)
            resp.raise_for_status()
            # TASK-3/H23.6: RSS feed content is untrusted external input — mark
            # each item so any action later built from it escalates through the
            # kernel instead of auto-executing.
            return [taint.mark(item, source="news") for item in self._parse_rss(resp.text, limit)]
        except Exception as e:
            logger.warning(f"News feed '{category}' error: {e}")
            return [{"title": f"News unavailable: {e}", "link": ""}]

    def _parse_rss(self, xml: str, limit: int) -> list[dict]:
        items = []
        try:
            root = ET.fromstring(xml)
            ns = {"": "http://www.w3.org/2005/Atom"}
            for entry in root.iter("entry"):
                title = entry.findtext("title", "") or entry.findtext("title", "", ns)
                link_el = entry.find("link")
                link = ""
                if link_el is not None:
                    link = link_el.get("href", "")
                items.append({"title": title.strip(), "link": link})
                if len(items) >= limit:
                    break

            if not items:
                for item in root.iter("item"):
                    title = item.findtext("title", "")
                    link = item.findtext("link", "")
                    items.append({"title": title.strip(), "link": link})
                    if len(items) >= limit:
                        break
        except (ET.ParseError, ValueError):
            # ValueError covers defusedxml's DTD/entity-attack rejections (DefusedXmlException);
            # a malformed or hostile feed degrades to a placeholder rather than raising.
            items = [{"title": "Failed to parse news feed", "link": ""}]
        return items

    async def summarize(self, category: str = "general", limit: int = 5) -> str:
        headlines = await self.get_headlines(category, limit)
        lines = [f"{i+1}. {h['title']}" for i, h in enumerate(headlines)]
        return "\n".join(lines) if lines else "No news found."

    async def close(self):
        await self.client.close()
