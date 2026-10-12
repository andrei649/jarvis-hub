"""
websearch.py — Web search plugin for Vision (OSINT / research).

Search goes through the provider registry in ``web_providers`` (Tavily, SearXNG, the
keyless DuckDuckGo fallback, and any backend a first-party plugin registers), chosen
per call by ``JARVIS_WEB_BACKEND`` / ``JARVIS_WEB_PROVIDER_TIER`` with a one-shot
rescue for a failed provider and none for a policy block (H310/H537/H607). Page reads
(``read_page`` / ``fetch_page``) return clean text from HTML, plain text or — with the
optional ``pypdf`` installed — a PDF, never a model summary.
"""

import asyncio
import copy
import io
import logging
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Optional
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

import httpx

from ..http_client import PluginEgressError, PluginHTTPClient
from ..security import taint
from ..security.ssrf import resolve_and_validate
from . import web_providers

logger = logging.getLogger("jarvis.plugins.websearch")

# Hermes absorption 5a: bounds on how much of one page ``fetch_page`` hands back.
# The caller's cap is clamped into this range so no argument can ask for a whole
# site or for nothing at all.
PAGE_MAX_CHARS_MIN = 256
PAGE_MAX_CHARS_DEFAULT = 15000
PAGE_MAX_CHARS_MAX = 20000
# Hermes absorption 5a: the body is read as a stream and reading stops at this many
# bytes, so a URL the model (or a redirect) chose cannot make the reader buffer and
# parse an unbounded response on the event loop; the char cap above only bounds the
# *output*. What was read before the cap is still parsed — a cut page is better than
# none, and the output cap applies anyway.
PAGE_MAX_BYTES = 2_000_000
PAGE_READ_CHUNK_BYTES = 65_536
# Only these media types are readable text; anything else (an image, an archive, a
# missing declaration) is refused rather than decoded into noise that would then be
# cached and handed to the model as "the page". PDFs are their own case below.
PAGE_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
# H310: a PDF is read with the optional ``pypdf`` (already an optional import of the
# local-docs reader), parsed in a worker thread, page- and char-bounded. A PDF cut at
# PAGE_MAX_BYTES has lost its trailing cross-reference table, so it is refused as
# ``too_large`` rather than parsed into a partial, misleading text.
PDF_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf"})
PDF_MAX_PAGES = 200
PDF_PARSE_TIMEOUT_SECONDS = 30.0
# The most text one read hands back to a caller that wants the whole page (the full
# text ``web_extract`` writes to disk). The body cap above bounds it in practice.
FULL_TEXT_MAX_CHARS = 1_000_000
# H537: repeat searches inside this window are answered from memory, so the same
# query does not reach (or bill) the provider again. Failures are never cached.
SEARCH_CACHE_TTL_SECONDS = 900.0
SEARCH_CACHE_ENTRIES = 64

#: Why a read produced no text — machine reasons the tools pass through.
REFUSED = "url_refused"          # a gate refused it, or the answer is not readable text
FETCH_FAILED = "fetch_failed"    # network / HTTP error status: may be retried later
PARSER_MISSING = "parser_missing"
TOO_LARGE = "too_large"
SITE_BLOCKED = "site_blocked"    # operator-disallowed site (JARVIS_WEB_BLOCKED_DOMAINS)

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


@dataclass(frozen=True)
class PageRead:
    """One page read: its clean text, or why there is none.

    ``refusal`` is one of the module's reason constants when ``text`` is None.
    ``body_cut`` says the body reached ``PAGE_MAX_BYTES`` (the text is the readable part
    of what arrived); ``text_cut`` says the text was cut at the caller's ``full_chars``
    (or a PDF at ``PDF_MAX_PAGES``). ``pages`` is ``(read, total)`` for a PDF.
    """

    text: Optional[str]
    media: str = ""
    refusal: str = ""
    missing: str = ""
    body_cut: bool = False
    text_cut: bool = False
    pages: Optional[tuple[int, int]] = None


@dataclass(frozen=True)
class SearchOutcome:
    """What one search did: rows (tainted), who answered, and what went wrong."""

    rows: list
    provider: str = ""
    #: "" | "policy_blocked" | "provider_failed" | a ``web_providers`` selection reason
    reason: str = ""
    missing: str = ""
    rescued_from: str = ""
    rescue_reason: str = ""
    cached: bool = False
    backend: str = ""


class _PdfBusy(Exception):
    """Every parse slot is taken (earlier parses are still running)."""


def _pdf_worker(module: Any, body: bytes, cap: int, deadline: float):
    """Run :func:`_pdf_text` in a slot that is taken and freed on the worker thread
    itself, so it is released when the parse really ends and never leaks."""
    if not _PDF_SLOTS.acquire(blocking=False):
        raise _PdfBusy()
    try:
        return _pdf_text(module, body, cap, deadline)
    finally:
        _PDF_SLOTS.release()


def _pdf_module():
    """The optional PDF parser, or None. Imported per call so installing it needs no
    restart and a test can swap it."""
    try:
        import pypdf  # noqa: PLC0415 — optional dependency, read lazily
    except ImportError:
        return None
    return pypdf


# At most this many PDF parses run at once. A parse that outlives its timeout keeps its
# slot until the worker really stops, so abandoned parses cannot stack up unbounded.
PDF_MAX_CONCURRENT = 2
_PDF_SLOTS = threading.BoundedSemaphore(PDF_MAX_CONCURRENT)


def _pdf_text(module: Any, body: bytes, cap: int,
              deadline: Optional[float] = None) -> tuple[str, tuple[int, int], bool]:
    """Extract text page by page (worker thread). Raises on an unreadable PDF, and
    ``TimeoutError`` at a page boundary once *deadline* (monotonic) has passed — the
    worker really stops there instead of running on after the caller gave up."""
    reader = module.PdfReader(io.BytesIO(body))
    if getattr(reader, "is_encrypted", False):
        raise ValueError("encrypted PDF")
    pages = reader.pages
    total = len(pages)
    limit = max(1, int(PDF_MAX_PAGES))
    parts: list[str] = []
    size = 0
    for index, page in enumerate(pages):
        if index >= limit or size >= cap:
            break
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("pdf parse deadline")
        text = page.extract_text() or ""
        parts.append(text)
        size += len(text) + 2
    read = len(parts)
    joined = "\n\n".join(parts)
    cut = read < total or len(joined) > cap
    return joined[:cap], (read, total), cut


class WebSearchPlugin:
    def __init__(
        self,
        tavily_api_key: str = "",
        searxng_url: str = "",
        *,
        backend: Optional[str] = None,
        provider_tier: Optional[str] = None,
        rescue: Optional[bool] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.tavily_api_key = tavily_api_key
        self.searxng_url = searxng_url
        # H310: None means "read JARVIS_WEB_BACKEND / _PROVIDER_TIER / _RESCUE per call";
        # a caller that must not follow the env (local research: SearXNG only) pins them.
        self.backend = backend
        self.provider_tier = provider_tier
        self.rescue = rescue
        self._clock = clock
        self._client = PluginHTTPClient.for_plugin("websearch")
        # Hermes absorption 5a: a second egress identity for page reads, so the egress
        # ledger says "webread reached example.com" rather than charging a public-page
        # fetch to the search backends' allowlist (which would refuse it under strict
        # egress). Search never dials through the reader and the reader never searches.
        self._reader = PluginHTTPClient.for_plugin("webread")
        # Other egress identities a plugin-registered provider declared (manifest-checked
        # at registration); the built-ins all dial as ``websearch`` through ``_client``.
        self._egress_clients: dict[str, PluginHTTPClient] = {}
        self._search_cache: dict[tuple, tuple[float, list, str]] = {}
        # SEC-5b: the optional SearXNG host is config-driven; allow it through.
        if self.searxng_url:
            from ..plugin_gate import register_dynamic_domain
            register_dynamic_domain("websearch", self.searxng_url)

    # ── search ───────────────────────────────────────────────────────────────

    def _view(self) -> SimpleNamespace:
        """What a provider may see of the plugin: the two owner-configured values and
        nothing else — not the read-only ``webread`` client, not the other providers."""
        return SimpleNamespace(tavily_api_key=self.tavily_api_key, searxng_url=self.searxng_url)

    def selection(self, *, allow_keyless_rescue: bool = False) -> web_providers.Selection:
        """Which backend answers now (read per call), who may rescue it, or why nobody can.

        ``allow_keyless_rescue`` is for the interactive ``web_search`` tool only: with it
        (and ``JARVIS_WEB_RESCUE=1``) a failed configured backend may fall to the keyless
        DuckDuckGo. Every other caller keeps configured-only egress.
        """
        return web_providers.resolve(
            self._view(), backend=self.backend, tier=self.provider_tier, rescue=self.rescue,
            allow_keyless_rescue=allow_keyless_rescue,
        )

    def available(self) -> bool:
        """True when an owner-provided search backend/key would answer.

        The DuckDuckGo fallback can still answer the interactive tool, but the HUD and
        unattended research must not treat that implicit keyless egress as a configured
        Knowledge source — so a keyless selection reads as not available here.
        """
        selection = self.selection()
        return selection.primary is not None and not selection.primary.keyless

    def _egress(self, plugin_id: str) -> PluginHTTPClient:
        if plugin_id == "websearch":
            return self._client
        client = self._egress_clients.get(plugin_id)
        if client is None:
            client = PluginHTTPClient.for_plugin(plugin_id)
            self._egress_clients[plugin_id] = client
        return client

    async def _ask(self, provider: web_providers.SearchProvider, query: str,
                   max_results: int) -> list[dict]:
        try:
            raw = await provider.search(
                self._egress(provider.plugin_id), self._view(), query, max_results)
        except (web_providers.PolicyBlock, web_providers.ProviderFailure):
            raise
        except Exception as exc:  # an unclassified provider bug is a failure, not a block
            raise web_providers.ProviderFailure(type(exc).__name__) from None
        if not isinstance(raw, list):
            raise web_providers.ProviderFailure("bad_rows")
        # TASK-3/H23.6: web search results are untrusted external content — mark
        # each result so any action later built from it escalates through the
        # kernel instead of auto-executing.
        return [taint.mark(dict(r), source="websearch") for r in raw if isinstance(r, dict)]

    def _cache_get(self, key: tuple, now: float) -> Optional[tuple[list, str]]:
        hit = self._search_cache.get(key)
        if hit is None:
            return None
        expires, rows, provider = hit
        if expires <= now:
            self._search_cache.pop(key, None)
            return None
        return copy.deepcopy(rows), provider

    def _cache_put(self, key: tuple, rows: list, provider: str, now: float) -> None:
        for stale in [k for k, (expires, _r, _p) in self._search_cache.items() if expires <= now]:
            self._search_cache.pop(stale, None)
        self._search_cache.pop(key, None)
        while len(self._search_cache) >= max(1, int(SEARCH_CACHE_ENTRIES)):
            self._search_cache.pop(next(iter(self._search_cache)), None)
        self._search_cache[key] = (now + SEARCH_CACHE_TTL_SECONDS, copy.deepcopy(rows), provider)

    async def search_detailed(self, query: str, max_results: int = 5, *,
                              allow_keyless_rescue: bool = False) -> SearchOutcome:
        """Search once: cache, primary, at most one rescue — and say what happened."""
        selection = self.selection(allow_keyless_rescue=allow_keyless_rescue)
        if selection.primary is None:
            return SearchOutcome([], reason=selection.reason, missing=selection.missing,
                                 backend=selection.backend)
        primary = selection.primary
        key = (selection.key, query, int(max_results))
        now = self._clock()
        cached = self._cache_get(key, now)
        if cached is not None:
            rows, provider = cached
            return SearchOutcome(rows, provider=provider, cached=True, backend=selection.backend)
        try:
            rows = await self._ask(primary, query, max_results)
        except web_providers.PolicyBlock:
            logger.warning("web search refused by policy (provider=%s); not rescued", primary.name)
            return SearchOutcome([], provider=primary.name, reason="policy_blocked",
                                 backend=selection.backend)
        except web_providers.ProviderFailure as exc:
            logger.warning("web search provider failed (provider=%s, kind=%s)", primary.name, exc)
            for rescuer in selection.rescue:
                try:
                    rows = await self._ask(rescuer, query, max_results)
                except web_providers.PolicyBlock:
                    return SearchOutcome([], provider=rescuer.name, reason="policy_blocked",
                                         rescued_from=primary.name, rescue_reason="provider_failed",
                                         backend=selection.backend)
                except web_providers.ProviderFailure:
                    break
                return SearchOutcome(rows, provider=rescuer.name, rescued_from=primary.name,
                                     rescue_reason="provider_failed", backend=selection.backend)
            return SearchOutcome([], provider=primary.name, reason="provider_failed",
                                 backend=selection.backend)
        if rows:  # an empty answer may be transient; never pin it for the TTL
            self._cache_put(key, rows, primary.name, now)
        return SearchOutcome(rows, provider=primary.name, backend=selection.backend)

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        """The rows only (tainted); an empty list when nothing could answer."""
        return (await self.search_detailed(query, max_results)).rows

    async def _legacy(self, name: str, query: str, max_results: int) -> list[dict]:
        provider = web_providers.get_search_provider(name)
        if provider is None:
            return []
        try:
            return await provider.search(self._client, self._view(), query, max_results)
        except Exception as e:
            logger.error("%s search error (type=%s)", name, type(e).__name__)
            return []

    # The three backends one at a time, errors folded into "no rows" (kept for callers
    # and tests that address a backend directly; search() goes through the registry).
    async def _search_tavily(self, query: str, max_results: int) -> list[dict]:
        return await self._legacy("tavily", query, max_results)

    async def _search_searxng(self, query: str, max_results: int) -> list[dict]:
        return await self._legacy("searxng", query, max_results)

    async def _search_duckduckgo(self, query: str, max_results: int) -> list[dict]:
        return await self._legacy("duckduckgo", query, max_results)

    # ── page reads ───────────────────────────────────────────────────────────

    async def read_page(
        self,
        url: str,
        *,
        full_chars: int = FULL_TEXT_MAX_CHARS,
        _transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> PageRead:
        """Read one page and return its clean text, SSRF-safe, or why there is none.

        DNS-rebinding proof (HF-4): each hop is resolved+validated and then dialed
        by its *pinned* validated IP (the Host header and TLS SNI are preserved),
        so the IP we checked is the IP httpx connects to — DNS can't rebind to a
        private host in the gap. Redirects are followed manually so **every** hop,
        not just the final URL, is SSRF-checked (and checked against the operator's
        blocked sites) before we connect.

        The fetch goes out under the ``webread`` identity, not ``websearch``
        (Hermes absorption 5a). The body is streamed and reading stops at
        ``PAGE_MAX_BYTES``; a media type outside the text types and PDF is refused
        before any byte is read, and so is a PDF when ``pypdf`` is not installed.
        Refusals are classified: a gate (SSRF, egress allowlist, kernel) or an
        unreadable answer is ``url_refused``; a network failure or an HTTP error
        status is ``fetch_failed``.
        """
        from urllib.parse import urljoin

        try:
            cap = int(full_chars)
        except (TypeError, ValueError):
            cap = FULL_TEXT_MAX_CHARS
        cap = max(1, min(FULL_TEXT_MAX_CHARS, cap))

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
                if web_providers.blocked_host(current):
                    logger.info("Page fetch refused: operator-blocked site")
                    return PageRead(None, refusal=SITE_BLOCKED)
                body = b""
                body_cut = False
                charset: Optional[str] = None
                media = ""
                pdf = None
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
                                return PageRead(None, refusal=REFUSED)
                            current = urljoin(current, location)
                            continue
                        media = self._media_type(resp)
                        if media not in PAGE_CONTENT_TYPES and media not in PDF_CONTENT_TYPES:
                            logger.warning("Page fetch refused: media type is not readable text")
                            return PageRead(None, refusal=REFUSED)
                        resp.raise_for_status()
                        if media in PDF_CONTENT_TYPES:
                            pdf = _pdf_module()
                            if pdf is None:
                                return PageRead(None, media="pdf", refusal=PARSER_MISSING,
                                                missing="pypdf")
                        elif not self._html_parser():
                            return PageRead(None, media="html", refusal=PARSER_MISSING,
                                            missing="beautifulsoup4")
                        charset = resp.charset_encoding
                        body, body_cut = await self._read_bounded_cut(resp)
                except PluginEgressError:
                    logger.warning("Page fetch refused by the egress guard")
                    return PageRead(None, refusal=REFUSED)
                except Exception as e:
                    logger.warning("Page fetch failed (type=%s)", type(e).__name__)
                    return PageRead(None, refusal=FETCH_FAILED)

                if pdf is not None:
                    return await self._read_pdf(pdf, body, body_cut, cap)
                try:
                    # Every text type goes through the same tag-stripping parse it always
                    # did (a text/plain answer can still carry markup), off the loop.
                    text = await asyncio.to_thread(self._html_text, body, charset)
                except Exception as e:
                    logger.warning("Page parse failed (type=%s)", type(e).__name__)
                    return PageRead(None, refusal=REFUSED)
                kind = "text" if media == "text/plain" else "html"
                return PageRead(text[:cap], media=kind, body_cut=body_cut,
                                text_cut=len(text) > cap)

            logger.warning("Blocked page fetch (SSRF): too many redirects")
            return PageRead(None, refusal=REFUSED)
        finally:
            if temporary_client is not None:
                await temporary_client.close()

    async def _read_pdf(self, module: Any, body: bytes, body_cut: bool, cap: int) -> PageRead:
        if body_cut:
            logger.warning("PDF refused: cut at the byte cap (max_bytes=%d)", PAGE_MAX_BYTES)
            return PageRead(None, media="pdf", refusal=TOO_LARGE)
        deadline = time.monotonic() + PDF_PARSE_TIMEOUT_SECONDS
        try:
            # The deadline is checked between pages inside the worker, so the thread stops
            # there; wait_for frees the caller even if one page is slow on its own.
            text, pages, cut = await asyncio.wait_for(
                asyncio.to_thread(_pdf_worker, module, body, cap, deadline),
                PDF_PARSE_TIMEOUT_SECONDS,
            )
        except _PdfBusy:
            logger.warning("PDF parse deferred: %d parses already running", PDF_MAX_CONCURRENT)
            return PageRead(None, media="pdf", refusal=FETCH_FAILED)
        except TimeoutError:
            logger.warning("PDF parse timed out (%.0fs)", PDF_PARSE_TIMEOUT_SECONDS)
            # Slow, not forbidden: the model may retry later (unlike url_refused).
            return PageRead(None, media="pdf", refusal=FETCH_FAILED)
        except Exception as e:
            logger.warning("PDF parse failed (type=%s)", type(e).__name__)
            return PageRead(None, media="pdf", refusal=REFUSED)
        return PageRead(text, media="pdf", text_cut=cut, pages=pages)

    @staticmethod
    def _html_parser() -> bool:
        try:
            import bs4  # noqa: F401, PLC0415 — optional dependency probe
        except ImportError:
            return False
        return True

    @staticmethod
    def _html_text(body: bytes, charset: Optional[str]) -> str:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(body or b"", "html.parser", from_encoding=charset)
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)

    async def fetch_page(
        self,
        url: str,
        *,
        max_chars: int = PAGE_MAX_CHARS_DEFAULT,
        _transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> Optional[str]:
        """The readable text of one page cut at ``max_chars`` (head), or ``None``.

        ``max_chars`` is clamped into ``PAGE_MAX_CHARS_MIN..PAGE_MAX_CHARS_MAX``; every
        refusal of :meth:`read_page` (whatever its reason) reads as ``None`` here.
        """
        try:
            cap = int(max_chars)
        except (TypeError, ValueError):
            cap = PAGE_MAX_CHARS_DEFAULT
        cap = max(PAGE_MAX_CHARS_MIN, min(PAGE_MAX_CHARS_MAX, cap))
        page = await self.read_page(url, full_chars=cap, _transport=_transport)
        return None if page.text is None else page.text[:cap]

    @staticmethod
    def _media_type(resp: httpx.Response) -> str:
        declared = resp.headers.get("content-type", "")
        return declared.split(";", 1)[0].strip().lower()

    @classmethod
    def _readable_media_type(cls, resp: httpx.Response) -> bool:
        """True when the declared media type is one the reader turns into text."""
        media = cls._media_type(resp)
        return media in PAGE_CONTENT_TYPES or media in PDF_CONTENT_TYPES

    @staticmethod
    async def _read_bounded_cut(resp: httpx.Response) -> tuple[bytes, bool]:
        """Read at most ``PAGE_MAX_BYTES`` of the body; say whether the cap stopped it."""
        limit = PAGE_MAX_BYTES
        body = bytearray()
        cut = False
        async for chunk in resp.aiter_bytes(PAGE_READ_CHUNK_BYTES):
            room = limit - len(body)
            if room <= 0:
                cut = True
                break
            body.extend(chunk[:room])
            if len(chunk) > room or len(body) >= limit:
                logger.info("Page body cut at the byte cap (max_bytes=%d)", limit)
                cut = True
                break
        return bytes(body), cut

    @classmethod
    async def _read_bounded(cls, resp: httpx.Response) -> bytes:
        """Read at most ``PAGE_MAX_BYTES`` of the body, then stop pulling from the socket."""
        body, _cut = await cls._read_bounded_cut(resp)
        return body

    async def close(self):
        await self._client.close()
        await self._reader.close()
        for client in self._egress_clients.values():
            await client.close()
