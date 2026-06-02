"""
websearch.py — Web search plugin for Vision (OSINT / research).
Supports DuckDuckGo (no-API) and optional Tavily / SearXNG.
"""

import json
import logging
from typing import Optional

import httpx

from ..http_client import PluginHTTPClient
from ..security.ssrf import check_ssrf

logger = logging.getLogger("jarvis.plugins.websearch")


class WebSearchPlugin:
    def __init__(self, tavily_api_key: str = "", searxng_url: str = ""):
        self.tavily_api_key = tavily_api_key
        self.searxng_url = searxng_url
        self._client = PluginHTTPClient.for_plugin("websearch")

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        if self.tavily_api_key:
            return await self._search_tavily(query, max_results)
        if self.searxng_url:
            return await self._search_searxng(query, max_results)
        return await self._search_duckduckgo(query, max_results)

    async def _search_tavily(self, query: str, max_results: int) -> list[dict]:
        try:
            resp = await self._client.post(
                "https://api.tavily.com/search",
                json={"api_key": self.tavily_api_key, "query": query, "max_results": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
                for r in data.get("results", [])
            ]
        except Exception as e:
            logger.error(f"Tavily search error: {e}")
            return []

    async def _search_searxng(self, query: str, max_results: int) -> list[dict]:
        try:
            resp = await self._client.get(
                f"{self.searxng_url}/search",
                params={"q": query, "format": "json", "number_of_results": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
                for r in data.get("results", [])[:max_results]
            ]
        except Exception as e:
            logger.error(f"SearXNG search error: {e}")
            return []

    async def _search_duckduckgo(self, query: str, max_results: int) -> list[dict]:
        try:
            resp = await self._client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for r in soup.select(".result")[:max_results]:
                title_el = r.select_one(".result__title a")
                snippet_el = r.select_one(".result__snippet")
                if title_el:
                    results.append({
                        "title": title_el.get_text(strip=True),
                        "url": title_el.get("href", ""),
                        "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                    })
            return results
        except ImportError:
            logger.warning("BeautifulSoup not installed — DuckDuckGo search unavailable")
            return []
        except Exception as e:
            logger.error(f"DuckDuckGo search error: {e}")
            return []

    async def fetch_page(self, url: str) -> Optional[str]:
        # Block SSRF: refuse private IPs / cloud metadata before fetching.
        blocked = check_ssrf(url)
        if blocked:
            logger.warning(f"Blocked page fetch (SSRF): {blocked}")
            return None
        try:
            # fetch_page needs follow_redirects + max_redirects — use a one-off client
            # so we can pass those options without affecting the shared client.
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, max_redirects=5) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                # A redirect could land on an internal host — re-validate final URL.
                final_block = check_ssrf(str(resp.url))
                if final_block:
                    logger.warning(f"Blocked page fetch after redirect (SSRF): {final_block}")
                    return None
                resp.raise_for_status()
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
                return text[:8000]
        except ImportError:
            logger.warning("BeautifulSoup not installed — page fetch unavailable")
            return None
        except Exception as e:
            logger.error(f"Page fetch error for {url}: {e}")
            return None

    async def close(self):
        await self._client.close()
