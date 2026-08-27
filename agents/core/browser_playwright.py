"""Optional real Playwright actuator for :mod:`agents.core.browser_agent`.

This module owns no policy. Inject :class:`PlaywrightBrowserDriver` into
``GovernedBrowser`` so its existing allowlist, SSRF, and approval gates remain the only
path to browser actions. The host runtime is explicit and default-off.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

SUPPORTED_BROWSERS = frozenset({"chromium", "firefox", "webkit"})


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
        self._factory = playwright_factory
        self._url_guard: Callable[[str], tuple[bool, str] | bool] | None = None
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
        kwargs.setdefault("host_enabled", True)
        kwargs.setdefault("browser", os.getenv("JARVIS_PLAYWRIGHT_BROWSER", "chromium"))
        kwargs.setdefault("headless", env_flag("JARVIS_PLAYWRIGHT_HEADLESS", True))
        configured_downloads = os.getenv("JARVIS_PLAYWRIGHT_DOWNLOAD_DIR", "").strip()
        if configured_downloads:
            kwargs.setdefault("download_dir", configured_downloads)
        return cls(**kwargs)

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
                self._browser = await browser_type.launch(headless=self.headless)
                self._context = await self._browser.new_context(
                    accept_downloads=True,
                    service_workers="block",
                )
                if self._url_guard is not None:
                    await self._context.route("**/*", self._route_request)
                self._page = await self._context.new_page()
                self._page.set_default_timeout(self.timeout_ms)
                return self._page
            except (PlaywrightHostDisabled, PlaywrightUnavailable):
                await self._close_resources()
                raise
            except Exception:
                await self._close_resources()
                raise PlaywrightUnavailable(
                    "Playwright could not start; verify the selected browser binary is installed"
                ) from None

    async def _route_request(self, route) -> None:
        """Apply the allowlist/SSRF guard to redirects and subresources too."""
        allowed = False
        try:
            # The guard runs check_ssrf → getaddrinfo (blocking DNS) and fires per
            # subresource; offload it so a slow resolver can't stall the event loop.
            verdict = (await asyncio.to_thread(self._url_guard, str(route.request.url))
                       if self._url_guard else False)
            allowed = bool(verdict[0]) if isinstance(verdict, tuple) else bool(verdict)
        except Exception:
            allowed = False
        if allowed:
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    async def close(self) -> None:
        """Idempotently release the fresh context, browser, and Playwright runtime."""
        async with self._start_lock:
            await self._close_resources()

    async def _close_resources(self) -> None:
        context, browser, playwright = self._context, self._browser, self._playwright
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        for resource, method_name in (
            (context, "close"),
            (browser, "close"),
            (playwright, "stop"),
        ):
            if resource is None:
                continue
            with contextlib.suppress(Exception):
                await getattr(resource, method_name)()

    async def navigate(self, *, url: str, wait_until: str = "domcontentloaded") -> dict:
        if not self.host_enabled:
            raise PlaywrightHostDisabled(
                "Playwright host actuation requires explicit host_enabled=True"
            )
        if self._url_guard is None:
            raise PlaywrightHostDisabled(
                "Playwright host actuation requires a per-request URL guard"
            )
        # Browser request interception happens after Playwright has already selected
        # a network transport, so it is not an egress boundary. Do not start it.
        raise PlaywrightTransportUnavailable("browser transport unavailable")
        page = await self._ensure_started()
        response = await page.goto(url, wait_until=wait_until)
        title = await page.title()
        return {
            "url": self._bounded_text(str(page.url), 2_048),
            "title": self._bounded_text(str(title), 512),
            "status": getattr(response, "status", None),
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
