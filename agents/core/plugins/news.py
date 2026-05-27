import logging
import xml.etree.ElementTree as ET

import httpx

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
        self.client = httpx.AsyncClient(timeout=15.0)

    async def get_headlines(self, category: str = "general", limit: int = 5) -> list[dict]:
        feed_url = FEEDS.get(category, FEEDS["general"])
        try:
            resp = await self.client.get(feed_url)
            resp.raise_for_status()
            return self._parse_rss(resp.text, limit)
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
        except ET.ParseError:
            items = [{"title": "Failed to parse news feed", "link": ""}]
        return items

    async def summarize(self, category: str = "general", limit: int = 5) -> str:
        headlines = await self.get_headlines(category, limit)
        lines = [f"{i+1}. {h['title']}" for i, h in enumerate(headlines)]
        return "\n".join(lines) if lines else "No news found."

    async def close(self):
        await self.client.aclose()
