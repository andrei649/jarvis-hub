"""
websearch.py — Web search plugin for Vision (OSINT / research).
Supports DuckDuckGo (no-API) and optional Tavily / SearXNG.
"""

import logging
from typing import Optional

import httpx

from ..http_client import PluginHTTPClient
from ..security.ssrf import resolve_and_validate

logger = logging.getLogger("jarvis.plugins.websearch")


class WebSearchPlugin:
    def __init__(self, tavily_api_key: str = "", searxng_url: str = ""):
        self.tavily_api_key = tavily_api_key
        self.searxng_url = searxng_url
        self._client = PluginHTTPClient.for_plugin("websearch")
        # SEC-5b: the optional SearXNG host is config-driven; allow it through.
        if self.searxng_url:
            from ..plugin_gate import register_dynamic_domain
            register_dynamic_domain("websearch", self.searxng_url)

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

    async def fetch_page(
        self, url: str, *, _transport: Optional[httpx.AsyncBaseTransport] = None
    ) -> Optional[str]:
        """Fetch a page and return its readable text, SSRF-safe.

        DNS-rebinding proof (HF-4): each hop is resolved+validated and then dialed
        by its *pinned* validated IP (the Host header and TLS SNI are preserved),
        so the IP we checked is the IP httpx connects to — DNS can't rebind to a
        private host in the gap. Redirects are followed manually so **every** hop,
        not just the final URL, is SSRF-checked before we connect.
        """
        from urllib.parse import urlparse, urljoin

        current = url
        # follow_redirects=False — we follow manually to SSRF-check each hop.
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=False, transport=_transport
        ) as client:
            for _hop in range(6):  # initial request + up to 5 redirects
                parsed = urlparse(current)
                host = parsed.hostname
                if not host or parsed.scheme not in ("http", "https"):
                    logger.warning("Blocked page fetch (SSRF): unsupported URL %s", current)
                    return None
                ips, err = resolve_and_validate(host)
                if err:
                    logger.warning("Blocked page fetch (SSRF): %s", err)
                    return None

                # Pin: connect to the validated IP, keep Host + TLS SNI = hostname.
                pinned = ips[0]
                ip_host = f"[{pinned}]" if ":" in pinned else pinned
                port = f":{parsed.port}" if parsed.port else ""
                ip_url = parsed._replace(netloc=f"{ip_host}{port}").geturl()
                host_header = f"{host}:{parsed.port}" if parsed.port else host
                try:
                    resp = await client.get(
                        ip_url,
                        headers={"User-Agent": "Mozilla/5.0", "Host": host_header},
                        extensions={"sni_hostname": host},
                    )
                except Exception as e:
                    logger.error("Page fetch error for %s: %s", url, e)
                    return None

                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        return None
                    current = urljoin(current, location)
                    continue

                try:
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
                    logger.error("Page fetch error for %s: %s", url, e)
                    return None

            logger.warning("Blocked page fetch (SSRF): too many redirects for %s", url)
            return None

    async def close(self):
        await self._client.close()
