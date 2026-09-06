"""Optional real Playwright actuator for :mod:`agents.core.browser_agent`.

This module owns no policy. Inject :class:`PlaywrightBrowserDriver` into
``GovernedBrowser`` so its existing allowlist, SSRF, and approval gates remain the only
path to browser actions. The host runtime is explicit and default-off.

Navigation additionally needs a bound transport (:meth:`set_transport`, see
:mod:`agents.core.browser_transport`): the resolver-validated IP is what Chromium
dials, every request — redirects and subresources included — is re-validated at the
route layer, the final URL is re-checked after ``goto``, and each run gets its own
throw-away profile directory, never the owner's browser profile. Observation is
accessibility-first: :meth:`observe_snapshot` returns a bounded, structured element
list before any pixel is looked at.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agents.core.browser_transport import (
    ALLOWED_SCHEMES,
    BrowserTransportRefused,
    PinnedResolver,
    is_private_host_literal,
)

logger = logging.getLogger("jarvis.browser.playwright")

SUPPORTED_BROWSERS = frozenset({"chromium", "firefox", "webkit"})
PROFILE_PREFIX = "nerva-browser-"
MAX_SNAPSHOT_ELEMENTS = 500
_BLOCK_LOG_SIZE = 50


class PlaywrightDriverError(RuntimeError):
    """Base class for bounded host-driver failures."""


class PlaywrightHostDisabled(PlaywrightDriverError):
    """The caller did not explicitly enable host browser actuation."""


class PlaywrightUnavailable(PlaywrightDriverError):
    """The optional Python runtime or its browser binary is unavailable."""


class PlaywrightTransportUnavailable(PlaywrightDriverError):
    """No transport-bound proxy exists for safe browser navigation."""


class PlaywrightOutputTooLarge(PlaywrightDriverError):
    """A browser observation exceeded its configured output budget."""


class PlaywrightEgressBlocked(PlaywrightDriverError):
    """The bound transport or the request layer refused a URL; ``reason`` is named."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = str(reason)
        self.detail = str(detail or "")
        super().__init__(self.reason if not self.detail else f"{self.reason}: {self.detail}")


class PlaywrightBrowserDriver:
    """Lazy async Playwright driver for injection behind ``GovernedBrowser``.

    ``playwright_factory`` mirrors ``playwright.async_api.async_playwright`` and exists
    for deterministic tests. Production callers normally use :meth:`from_env` after an
    owner explicitly enables ``JARVIS_PLAYWRIGHT_HOST=1``.
    """

    def __init__(
        self,
        *,
        host_enabled: bool = False,
        browser: str = "chromium",
        headless: bool = True,
        timeout_ms: int = 15_000,
        max_wait_ms: int = 30_000,
        max_extract_chars: int = 20_000,
        max_result_chars: int = 20_000,
        max_screenshot_bytes: int = 5_000_000,
        download_dir: str | Path | None = None,
        playwright_factory: Callable[[], Any] | None = None,
        allow_private_urls: bool = False,
    ) -> None:
        if browser not in SUPPORTED_BROWSERS:
            raise ValueError(f"unsupported Playwright browser: {browser}")
        for label, value in (
            ("timeout_ms", timeout_ms),
            ("max_wait_ms", max_wait_ms),
            ("max_extract_chars", max_extract_chars),
            ("max_result_chars", max_result_chars),
            ("max_screenshot_bytes", max_screenshot_bytes),
        ):
            if int(value) <= 0:
                raise ValueError(f"{label} must be positive")

        self.host_enabled = bool(host_enabled)
        self.browser_name = browser
        self.headless = bool(headless)
        self.timeout_ms = int(timeout_ms)
        self.max_wait_ms = int(max_wait_ms)
        self.max_extract_chars = int(max_extract_chars)
        self.max_result_chars = int(max_result_chars)
        self.max_screenshot_bytes = int(max_screenshot_bytes)
        self.download_dir = Path(download_dir).expanduser() if download_dir else None
        self.allow_private_urls = bool(allow_private_urls)
        self._factory = playwright_factory
        self._url_guard: Callable[[str], tuple[bool, str] | bool] | None = None
        self._transport: PinnedResolver | None = None
        self._launched_hosts: frozenset[str] = frozenset()
        self._profile_dir: Path | None = None
        self.blocked_requests: deque[dict] = deque(maxlen=_BLOCK_LOG_SIZE)
        self._start_lock = asyncio.Lock()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @classmethod
    def from_env(cls, **kwargs) -> PlaywrightBrowserDriver:
        """Build an explicitly host-enabled driver from bounded environment settings."""
        from agents.core.env_config import env_flag

        if not env_flag("JARVIS_PLAYWRIGHT_HOST"):
            raise PlaywrightHostDisabled(
                "Playwright host actuation is disabled; set JARVIS_PLAYWRIGHT_HOST=1"
            )
        transport = kwargs.pop("transport", None)
        kwargs.setdefault("host_enabled", True)
        kwargs.setdefault("browser", os.getenv("JARVIS_PLAYWRIGHT_BROWSER", "chromium"))
        kwargs.setdefault("headless", env_flag("JARVIS_PLAYWRIGHT_HEADLESS", True))
        kwargs.setdefault("allow_private_urls", env_flag("JARVIS_BROWSER_ALLOW_PRIVATE_URLS"))
        configured_downloads = os.getenv("JARVIS_PLAYWRIGHT_DOWNLOAD_DIR", "").strip()
        if configured_downloads:
            kwargs.setdefault("download_dir", configured_downloads)
        driver = cls(**kwargs)
        if transport is None and driver.browser_name == "chromium":
            transport = PinnedResolver(mode="lan" if driver.allow_private_urls else "public")
        if transport is not None:
            driver.set_transport(transport)
        return driver

    async def __aenter__(self) -> PlaywrightBrowserDriver:
        await self._ensure_started()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    def set_url_guard(self, guard: Callable[[str], tuple[bool, str] | bool]) -> None:
        """Bind the governance policy before startup so every request is checked."""
        if not callable(guard):
            raise ValueError("url guard must be callable")
        if self._page is not None:
            raise PlaywrightDriverError("url guard must be configured before browser startup")
        self._url_guard = guard

    def set_transport(self, resolver: PinnedResolver) -> None:
        """Bind the IP-pinning transport; navigation is refused until one is bound."""
        if not callable(getattr(resolver, "pin", None)) or not callable(
            getattr(resolver, "launch_args", None)
        ):
            raise ValueError("transport must expose pin() and launch_args()")
        if self._page is not None:
            raise PlaywrightDriverError("transport must be configured before browser startup")
        try:
            resolver.launch_args(self.browser_name)
        except BrowserTransportRefused as exc:
            raise PlaywrightTransportUnavailable(
                f"browser transport unavailable: {exc.reason}"
            ) from None
        self._transport = resolver

    @property
    def transport_bound(self) -> bool:
        """True once a pinning transport is bound (what ``GovernedBrowser`` may key on)."""
        return self._transport is not None

    @property
    def profile_dir(self) -> Path | None:
        """The per-run throw-away profile directory while the browser is up."""
        return self._profile_dir

    @property
    def launched_hosts(self) -> frozenset[str]:
        """Hosts the running browser can resolve (empty without a transport)."""
        return self._launched_hosts

    def _runtime_factory(self):
        if self._factory is not None:
            return self._factory
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise PlaywrightUnavailable(
                "Playwright is unavailable; run 'pip install playwright' and "
                "'python -m playwright install chromium'"
            ) from None
        return async_playwright

    async def _ensure_started(self):
        if self._page is not None:
            return self._page
        if not self.host_enabled:
            raise PlaywrightHostDisabled(
                "Playwright host actuation requires explicit host_enabled=True"
            )
        if self._url_guard is None:
            raise PlaywrightHostDisabled(
                "Playwright host actuation requires a per-request URL guard"
            )

        async with self._start_lock:
            if self._page is not None:
                return self._page
            try:
                manager = self._runtime_factory()()
                self._playwright = await manager.start()
                browser_type = getattr(self._playwright, self.browser_name)
                launch_args: list[str] = []
                if self._transport is not None:
                    launch_args = list(self._transport.launch_args(self.browser_name))
                    self._launched_hosts = frozenset(self._transport.pinned_hosts())
                # A fresh, dedicated profile per run: cookies, storage, and history
                # never touch (or leak from) the owner's own browser profile.
                self._profile_dir = Path(tempfile.mkdtemp(prefix=PROFILE_PREFIX))
                self._context = await browser_type.launch_persistent_context(
                    str(self._profile_dir),
                    headless=self.headless,
                    args=launch_args,
                    accept_downloads=True,
                    service_workers="block",
                )
                self._browser = getattr(self._context, "browser", None)
                if self._url_guard is not None:
                    await self._context.route("**/*", self._route_request)
                self._page = await self._context.new_page()
                self._page.set_default_timeout(self.timeout_ms)
                return self._page
            except (PlaywrightHostDisabled, PlaywrightUnavailable, BrowserTransportRefused):
                await self._close_resources()
                raise
            except Exception:
                await self._close_resources()
                raise PlaywrightUnavailable(
                    "Playwright could not start; verify the selected browser binary is installed"
                ) from None

    async def _route_request(self, route) -> None:
        """Re-validate every request (redirects and subresources too) before egress."""
        url = str(route.request.url)
        try:
            # The guard runs check_ssrf → getaddrinfo (blocking DNS) and fires per
            # subresource; offload it so a slow resolver can't stall the event loop.
            allowed, reason = await asyncio.to_thread(self._egress_verdict, url)
        except Exception:
            allowed, reason = False, "guard_error"
        if allowed:
            await route.continue_()
            return
        self._record_block(url, reason)
        await route.abort("blockedbyclient")

    def _egress_verdict(self, url: str, *, require_pinned: bool = True) -> tuple[bool, str]:
        """Scheme allowlist → private-range denial → policy guard → pinned-host check.

        Runs for the navigation target (``require_pinned=False``: the host is pinned
        right after), every routed request, and the final URL after ``goto``.
        Reasons are stable names so a block is inspectable.
        """
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower().rstrip(".")
        except ValueError:
            return False, "invalid_url"
        scheme = (parsed.scheme or "").lower()
        if scheme not in ALLOWED_SCHEMES:
            return False, f"unsupported_scheme:{scheme or 'none'}"
        if not host:
            return False, "no_hostname"
        if not self.allow_private_urls and is_private_host_literal(host):
            return False, "private_address_denied"
        if self._url_guard is None:
            return False, "no_url_guard"
        verdict = self._url_guard(url)
        if isinstance(verdict, tuple):
            allowed, why = bool(verdict[0]), str(verdict[1] if len(verdict) > 1 else "")
        else:
            allowed, why = bool(verdict), ""
        if not allowed:
            return False, f"policy_denied:{why or 'refused'}"
        if require_pinned and self._transport is not None and host not in self._launched_hosts:
            return False, "host_not_pinned"
        return True, ""

    def _record_block(self, url: str, reason: str) -> None:
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            host = ""
        # Host only — query strings can carry tokens, and a log is forever.
        logger.info("browser egress blocked host=%s reason=%s", host or "?", reason)
        self.blocked_requests.append({"host": host, "reason": reason, "ts": time.time()})

    async def close(self) -> None:
        """Idempotently release the fresh context, browser, and Playwright runtime."""
        async with self._start_lock:
            await self._close_resources()

    async def _close_resources(self) -> None:
        context, browser, playwright = self._context, self._browser, self._playwright
        profile_dir = self._profile_dir
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._profile_dir = None
        self._launched_hosts = frozenset()
        for resource, method_name in (
            (context, "close"),
            (browser, "close"),
            (playwright, "stop"),
        ):
            if resource is None:
                continue
            with contextlib.suppress(Exception):
                await getattr(resource, method_name)()
        if profile_dir is not None and profile_dir.name.startswith(PROFILE_PREFIX):
            await asyncio.to_thread(shutil.rmtree, profile_dir, True)

    async def navigate(self, *, url: str, wait_until: str = "domcontentloaded") -> dict:
        if not self.host_enabled:
            raise PlaywrightHostDisabled(
                "Playwright host actuation requires explicit host_enabled=True"
            )
        if self._url_guard is None:
            raise PlaywrightHostDisabled(
                "Playwright host actuation requires a per-request URL guard"
            )
        if self._transport is None:
            # Request interception alone runs after Playwright has already picked a
            # network transport, so it is not an egress boundary. Without a bound
            # IP-pinning transport, do not start the browser at all.
            raise PlaywrightTransportUnavailable("browser transport unavailable")
        # Policy first, so a denied host is never even resolved (no DNS leak).
        allowed, reason = await asyncio.to_thread(
            self._egress_verdict, url, require_pinned=False
        )
        if not allowed:
            self._record_block(url, reason)
            raise PlaywrightEgressBlocked(reason)
        try:
            target = await self._transport.pin_async(url)
        except BrowserTransportRefused as exc:
            self._record_block(url, exc.reason)
            raise PlaywrightEgressBlocked(exc.reason, exc.detail) from None
        if self._page is not None and target.host not in self._launched_hosts:
            # Chromium's resolver table is fixed at launch: a new host means a fresh
            # browser (and a fresh profile) launched with the enlarged pin table.
            await self.close()
        page = await self._ensure_started()
        response = await page.goto(url, wait_until=wait_until)
        final_url = str(page.url)
        allowed, reason = await asyncio.to_thread(self._egress_verdict, final_url)
        if not allowed:
            self._record_block(final_url, reason)
            with contextlib.suppress(Exception):
                await page.goto("about:blank")
            raise PlaywrightEgressBlocked("final_url_rejected", reason)
        title = await page.title()
        return {
            "url": self._bounded_text(final_url, 2_048),
            "title": self._bounded_text(str(title), 512),
            "status": getattr(response, "status", None),
            "pinned_ip": target.ip,
        }

    async def observe_snapshot(
        self, *, max_chars: int | None = None, selector: str = "body"
    ) -> dict:
        """Accessibility-tree observation: the STRUCTURED_UI route before any pixel.

        Uses Playwright's ``aria_snapshot`` (``boxes=True`` where the runtime
        supports it, so elements carry a rect) bounded by ``max_chars`` (defaults to
        ``max_extract_chars``) and :data:`MAX_SNAPSHOT_ELEMENTS`.
        """
        limit = self.max_extract_chars if max_chars is None else int(max_chars)
        if limit <= 0:
            raise ValueError("max_chars must be positive")
        page = await self._ensure_started()
        locator = page.locator(selector)
        try:
            raw = await locator.aria_snapshot(boxes=True)
        except TypeError:
            raw = await locator.aria_snapshot()
        text = str(raw or "")
        truncated = len(text) > limit
        elements, elements_truncated = parse_aria_snapshot(text[:limit])
        return {
            "observation": "structured_ui",
            "elements": elements,
            "count": len(elements),
            "truncated": truncated or elements_truncated,
            "chars": min(len(text), limit),
            "url": self._bounded_text(str(page.url), 2_048),
        }

    async def extract(self, *, selector: str = "body") -> dict:
        page = await self._ensure_started()
        text = str(await page.locator(selector).first.inner_text())
        return {
            "text": text[:self.max_extract_chars],
            "truncated": len(text) > self.max_extract_chars,
            "url": self._bounded_text(str(page.url), 2_048),
        }

    async def screenshot(self, *, full_page: bool = True) -> dict:
        page = await self._ensure_started()
        image = bytes(await page.screenshot(full_page=bool(full_page), type="png"))
        if len(image) > self.max_screenshot_bytes:
            raise PlaywrightOutputTooLarge("screenshot exceeds configured byte budget")
        return {
            "image_base64": base64.b64encode(image).decode("ascii"),
            "mime": "image/png",
            "bytes": len(image),
            "url": self._bounded_text(str(page.url), 2_048),
        }

    async def wait(self, *, selector: str | None = None, timeout_ms: int = 1_000) -> dict:
        timeout_ms = int(timeout_ms)
        if timeout_ms < 0 or timeout_ms > self.max_wait_ms:
            raise ValueError(f"wait exceeds configured maximum of {self.max_wait_ms}ms")
        page = await self._ensure_started()
        if selector:
            # Playwright treats timeout=0 as "disable timeout" (wait forever),
            # which would bypass max_wait_ms and hang a governed run — fall back
            # to the driver default so a bounded timeout always applies.
            effective = timeout_ms or self.timeout_ms
            await page.locator(selector).first.wait_for(timeout=effective)
            return {"waited": "selector", "selector": selector, "timeout_ms": effective}
        await page.wait_for_timeout(timeout_ms)
        return {"waited": "timer", "timeout_ms": timeout_ms}

    async def click(self, *, selector: str) -> dict:
        page = await self._ensure_started()
        await page.locator(selector).first.click()
        return {"clicked": selector}

    async def type(self, *, selector: str, text: str, clear: bool = True) -> dict:
        page = await self._ensure_started()
        locator = page.locator(selector).first
        if clear:
            await locator.fill(text)
        else:
            await locator.type(text)
        return {"typed": selector}

    async def submit(self, *, selector: str) -> dict:
        page = await self._ensure_started()
        await page.locator(selector).first.press("Enter")
        return {"submitted": selector}

    async def execute_js(self, *, script: str, arg: Any = None) -> dict:
        page = await self._ensure_started()
        value = await page.evaluate(script, arg)
        self._assert_result_budget(value)
        return {"value": value}

    async def upload(self, *, selector: str, paths: list[str] | str) -> dict:
        values = [paths] if isinstance(paths, str) else list(paths or [])
        resolved = []
        for raw_path in values:
            path = Path(raw_path).expanduser().resolve()
            if not path.is_file():
                raise ValueError(f"upload path is not a file: {path}")
            resolved.append(str(path))
        if not resolved:
            raise ValueError("upload path list is empty")
        page = await self._ensure_started()
        await page.locator(selector).first.set_input_files(resolved)
        return {"uploaded": len(resolved), "selector": selector}

    async def download(self, *, selector: str) -> dict:
        if self.download_dir is None:
            raise ValueError("download_dir must be configured before downloading")
        page = await self._ensure_started()
        root = self.download_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        async with page.expect_download() as download_info:
            await page.locator(selector).first.click()
        download = await download_info.value
        filename = self._safe_filename(getattr(download, "suggested_filename", ""))
        destination = self._unique_destination(root, filename)
        await download.save_as(destination)
        return {"saved_to": str(destination), "filename": destination.name}

    @staticmethod
    def _bounded_text(value: str, limit: int) -> str:
        return value[:limit]

    def _assert_result_budget(self, value: Any) -> None:
        try:
            encoded = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            raise PlaywrightOutputTooLarge("browser result is not serializable") from None
        if len(encoded) > self.max_result_chars:
            raise PlaywrightOutputTooLarge("browser result exceeds configured character budget")

    @staticmethod
    def _safe_filename(value: str) -> str:
        normalized = str(value or "").replace("\\", "/")
        name = Path(normalized).name
        name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
        return name or "download.bin"

    @staticmethod
    def _unique_destination(root: Path, filename: str) -> Path:
        candidate = (root / filename).resolve()
        if candidate.parent != root:
            raise ValueError("download destination escaped configured directory")
        if not candidate.exists():
            return candidate
        stem, suffix = candidate.stem, candidate.suffix
        for index in range(1, 10_000):
            alternate = (root / f"{stem}-{index}{suffix}").resolve()
            if not alternate.exists():
                return alternate
        raise PlaywrightDriverError("no free download destination available")


_ARIA_LINE = re.compile(
    r'^(?P<role>[A-Za-z][A-Za-z0-9_-]*)'
    r'(?:\s+"(?P<name>(?:[^"\\]|\\.)*)")?'
    r'(?P<attrs>(?:\s*\[[^\]]*\])*)'
    r'\s*(?::\s*(?P<inline>.*))?$'
)
_ARIA_ATTR = re.compile(r"\[([^\]]*)\]")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_RECT_KEYS = ("box", "rect", "bounds")


def _parse_attrs(raw: str) -> dict[str, str | bool]:
    attrs: dict[str, str | bool] = {}
    for chunk in _ARIA_ATTR.findall(raw or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, sep, value = chunk.partition("=")
        attrs[key.strip()] = value.strip() if sep else True
    return attrs


def _rect_from_attrs(attrs: dict[str, str | bool]) -> dict[str, float] | None:
    """Pop a bounding box out of ``attrs`` (``[box=x,y,w,h]`` or x/y/width/height)."""
    for key in _RECT_KEYS:
        value = attrs.get(key)
        if isinstance(value, str):
            numbers = [float(n) for n in _NUMBER.findall(value)]
            if len(numbers) == 4:
                attrs.pop(key)
                return {"x": numbers[0], "y": numbers[1], "w": numbers[2], "h": numbers[3]}
    try:
        rect = {
            "x": float(attrs["x"]), "y": float(attrs["y"]),
            "w": float(attrs["width"]), "h": float(attrs["height"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
    for key in ("x", "y", "width", "height"):
        attrs.pop(key)
    return rect


def parse_aria_snapshot(
    text: str, *, max_elements: int = MAX_SNAPSHOT_ELEMENTS
) -> tuple[list[dict], bool]:
    """Parse Playwright's YAML-ish aria snapshot into bounded element dicts.

    Each line is ``- role "name" [attr=value] [ref=eN]:`` (children indented) or a
    ``- text: ...`` leaf. Returns ``(elements, truncated)``; every element carries
    ``ref`` (Playwright's when present, else a stable ``n<index>``), ``role``,
    ``name``, ``depth``, ``rect`` (``None`` when the runtime emitted no box), and the
    remaining bracket attributes. Unparseable lines are kept as ``role="unknown"``
    so an observation never silently drops content.
    """
    elements: list[dict] = []
    truncated = False
    for line in str(text or "").splitlines():
        if not line.strip():
            continue
        if len(elements) >= int(max_elements):
            truncated = True
            break
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()
        if body.startswith("- "):
            body = body[2:].strip()
        elif body == "-":
            continue
        depth = indent // 2
        index = len(elements)
        element = {
            "ref": f"n{index}", "role": "unknown", "name": body[:256],
            "depth": depth, "rect": None, "attrs": {},
        }
        if body.startswith("text:"):
            element.update(role="text", name=body[5:].strip()[:256])
        else:
            match = _ARIA_LINE.match(body)
            if match:
                attrs = _parse_attrs(match.group("attrs") or "")
                name = match.group("name")
                if name is None and match.group("inline"):
                    name = match.group("inline").strip()
                ref = attrs.pop("ref", None)
                element.update(
                    role=match.group("role").lower(),
                    name=str(name or "").replace('\\"', '"')[:256],
                    rect=_rect_from_attrs(attrs),
                    attrs=attrs,
                )
                if isinstance(ref, str) and ref:
                    element["ref"] = ref[:64]
        elements.append(element)
    return elements, truncated
