"""
websearch.py — Web search plugin for Vision (OSINT / research).
Supports DuckDuckGo (no-API) and optional Tavily / SearXNG.
"""

import logging
from typing import Optional
from urllib.parse import parse_qs, urlsplit

import httpx

from ..http_client import PluginHTTPClient
from ..security import taint
from ..security.ssrf import resolve_and_validate

logger = logging.getLogger("jarvis.plugins.websearch")

# Hermes absorption 5a: bounds on how much of one page ``fetch_page`` hands back.
# The caller's cap is clamped into this range so no argument can ask for a whole
# site or for nothing at all.
PAGE_MAX_CHARS_MIN = 256
PAGE_MAX_CHARS_DEFAULT = 8000
PAGE_MAX_CHARS_MAX = 20000
# Hermes absorption 5a: the body is read as a stream and reading stops at this many
# bytes, so a URL the model (or a redirect) chose cannot make the reader buffer and
# parse an unbounded response on the event loop; the char cap above only bounds the
# *output*. What was read before the cap is still parsed — a cut page is better than
# none, and the output cap applies anyway.
PAGE_MAX_BYTES = 2_000_000
PAGE_READ_CHUNK_BYTES = 65_536
# Only these media types are readable text; anything else (an image, a PDF, an
# archive, a missing declaration) is refused rather than decoded into noise that
# would then be cached and handed to the model as "the page".
PAGE_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})

# DuckDuckGo's HTML endpoint does not hand back a result's own address. It hands back
# its own redirector — `//duckduckgo.com/l/?uddg=<percent-encoded target>&rut=…`,
# protocol-relative, no scheme. That is useless to a reader: `web_extract` refuses it
# as `bad_args` because it carries no scheme, so with the keyless backend the model
# could search and never open what it found, and the tainted-turn rule ("only a URL
# `web_search` returned may be read") allowed an empty set in practice. The unwrap
# lives here, at the parser, so every backend hands the same shape upwards.
_REDIRECT_HOSTS = frozenset({"duckduckgo.com", "html.duckduckgo.com"})
_REDIRECT_PATH = "/l/"
_REDIRECT_PARAM = "uddg"
_RESULT_SCHEMES = frozenset({"http", "https"})
#: Longest result address kept. Matches ``web_tools.MAX_URL_CHARS`` — a longer one
#: would be refused by the reader's preflight anyway, so dropping it here is honest.
MAX_RESULT_URL_CHARS = 2048


def _unwrap_result_url(href: object) -> str:
    """The result's own http(s) address, or ``""`` when the href is not one.

    Handles the three shapes the HTML endpoint emits: the protocol-relative
    redirector, the same with a scheme, and the occasional direct link. Anything
    else — a relative path, a ``javascript:`` href, a redirector whose target is
    itself not http(s), a redirector pointing at another redirector — comes back
    empty rather than as a string the reader would refuse later under a less honest
    reason. ``parse_qs`` already percent-decodes, so the target is never decoded
    twice (decoding twice would turn a literal ``%2520`` inside a URL into ``%20``).
    """
    raw = str(href or "").strip()
    if not raw or len(raw) > MAX_RESULT_URL_CHARS:
        return ""
    if raw.startswith("//"):
        raw = f"https:{raw}"
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    if (parts.hostname or "").lower() in _REDIRECT_HOSTS and parts.path.startswith(_REDIRECT_PATH):
        # One hop only, on purpose: a redirector whose target is another redirector
        # is not a search result, and following the chain is someone else's job.
        raw = (parse_qs(parts.query).get(_REDIRECT_PARAM) or [""])[0].strip()
        if not raw or len(raw) > MAX_RESULT_URL_CHARS:
            return ""
        try:
            parts = urlsplit(raw)
        except ValueError:
            return ""
    if parts.scheme.lower() not in _RESULT_SCHEMES or not parts.hostname:
        return ""
    return raw


class WebSearchPlugin:
    def __init__(self, tavily_api_key: str = "", searxng_url: str = ""):
        self.tavily_api_key = tavily_api_key
        self.searxng_url = searxng_url
        self._client = PluginHTTPClient.for_plugin("websearch")
        # Hermes absorption 5a: a second egress identity for page reads, so the egress
        # ledger says "webread reached example.com" rather than charging a public-page
        # fetch to the search backends' allowlist (which would refuse it under strict
        # egress). Search never dials through the reader and the reader never searches.
        self._reader = PluginHTTPClient.for_plugin("webread")
        # SEC-5b: the optional SearXNG host is config-driven; allow it through.
        if self.searxng_url:
            from ..plugin_gate import register_dynamic_domain
            register_dynamic_domain("websearch", self.searxng_url)

    def available(self) -> bool:
        """True when an owner-provided search backend/key is configured.

        The DuckDuckGo fallback can still be attempted by direct calls, but the
        HUD should not treat that implicit network fallback as a configured
        Knowledge source.
        """
        return bool(self.tavily_api_key or self.searxng_url)

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        if self.tavily_api_key:
            results = await self._search_tavily(query, max_results)
        elif self.searxng_url:
            results = await self._search_searxng(query, max_results)
        else:
            results = await self._search_duckduckgo(query, max_results)
        # TASK-3/H23.6: web search results are untrusted external content — mark
        # each result so any action later built from it escalates through the
        # kernel instead of auto-executing.
        return [taint.mark(r, source="websearch") for r in results]

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
            logger.error("Tavily search error (type=%s)", type(e).__name__)
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
            logger.error("SearXNG search error (type=%s)", type(e).__name__)
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
                        "url": _unwrap_result_url(title_el.get("href", "")),
                        "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                    })
            return results
        except ImportError:
            logger.warning("BeautifulSoup not installed — DuckDuckGo search unavailable")
            return []
        except Exception as e:
            logger.error("DuckDuckGo search error (type=%s)", type(e).__name__)
            return []

    async def fetch_page(
        self,
        url: str,
        *,
        max_chars: int = PAGE_MAX_CHARS_DEFAULT,
        _transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> Optional[str]:
        """Fetch a page and return its readable text, SSRF-safe.

        DNS-rebinding proof (HF-4): each hop is resolved+validated and then dialed
        by its *pinned* validated IP (the Host header and TLS SNI are preserved),
        so the IP we checked is the IP httpx connects to — DNS can't rebind to a
        private host in the gap. Redirects are followed manually so **every** hop,
        not just the final URL, is SSRF-checked before we connect.

        The fetch goes out under the ``webread`` identity, not ``websearch``
        (Hermes absorption 5a): the search manifest allowlists search backends only,
        so under strict egress a real page would be refused, and the egress ledger
        must attribute a page read to the reader, not to search. ``max_chars`` is
        clamped into ``PAGE_MAX_CHARS_MIN..PAGE_MAX_CHARS_MAX``; the body is streamed
        and reading stops at ``PAGE_MAX_BYTES``; a response whose media type is not
        in ``PAGE_CONTENT_TYPES`` is refused (``None``) before any byte is read.
        """
        from urllib.parse import urljoin

        try:
            cap = int(max_chars)
        except (TypeError, ValueError):
            cap = PAGE_MAX_CHARS_DEFAULT
        cap = max(PAGE_MAX_CHARS_MIN, min(PAGE_MAX_CHARS_MAX, cap))

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.warning("BeautifulSoup not installed — page fetch unavailable")
            return None

        current = url
        client = self._reader
        temporary_client = None
        if _transport is not None:
            temporary_client = PluginHTTPClient(
                "webread",
                resolver=resolve_and_validate,
                transport_factory=lambda _target: _transport,
            )
            client = temporary_client
        try:
            for _hop in range(6):  # initial request + up to 5 redirects
                body: Optional[bytes] = None
                charset: Optional[str] = None
                try:
                    async with client.stream(
                        "GET",
                        current,
                        headers={"User-Agent": "Mozilla/5.0"},
                        follow_redirects=False,
                        timeout=30.0,
                    ) as resp:
                        if resp.is_redirect:
                            location = resp.headers.get("location")
                            if not location:
                                return None
                            current = urljoin(current, location)
                            continue
                        if not self._readable_media_type(resp):
                            logger.warning("Page fetch refused: media type is not readable text")
                            return None
                        resp.raise_for_status()
                        charset = resp.charset_encoding
                        body = await self._read_bounded(resp)
                except Exception as e:
                    logger.warning("Page fetch refused or failed (type=%s)", type(e).__name__)
                    return None

                try:
                    soup = BeautifulSoup(body or b"", "html.parser", from_encoding=charset)
                    for tag in soup(["script", "style", "nav", "footer", "header"]):
                        tag.decompose()
                    text = soup.get_text(separator="\n", strip=True)
                    return text[:cap]
                except Exception as e:
                    logger.warning("Page parse failed (type=%s)", type(e).__name__)
                    return None

            logger.warning("Blocked page fetch (SSRF): too many redirects")
            return None
        finally:
            if temporary_client is not None:
                await temporary_client.close()

    @staticmethod
    def _readable_media_type(resp: httpx.Response) -> bool:
        """True when the declared media type is one the reader turns into text."""
        declared = resp.headers.get("content-type", "")
        return declared.split(";", 1)[0].strip().lower() in PAGE_CONTENT_TYPES

    @staticmethod
    async def _read_bounded(resp: httpx.Response) -> bytes:
        """Read at most ``PAGE_MAX_BYTES`` of the body, then stop pulling from the socket."""
        body = bytearray()
        async for chunk in resp.aiter_bytes(PAGE_READ_CHUNK_BYTES):
            room = PAGE_MAX_BYTES - len(body)
            if room <= 0:
                break
            body.extend(chunk[:room])
            if len(body) >= PAGE_MAX_BYTES:
                logger.info("Page body cut at the byte cap (max_bytes=%d)", PAGE_MAX_BYTES)
                break
        return bytes(body)

    async def close(self):
        await self._client.close()
        await self._reader.close()
