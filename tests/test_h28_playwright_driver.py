import builtins
import os
from pathlib import Path

import pytest

from agents.core.browser_agent import BrowserPolicy, GovernedBrowser
from agents.core.browser_playwright import (
    PlaywrightBrowserDriver,
    PlaywrightHostDisabled,
    PlaywrightOutputTooLarge,
    PlaywrightTransportUnavailable,
    PlaywrightUnavailable,
)


class FakeResponse:
    status = 200


class FakeDownload:
    suggested_filename = "../../report.txt"

    def __init__(self):
        self.saved_as = None

    async def save_as(self, path):
        self.saved_as = Path(path)


class FakeDownloadInfo:
    def __init__(self, download):
        self.value = _AwaitableValue(download)


class _AwaitableValue:
    def __init__(self, value):
        self.value = value

    def __await__(self):
        async def _get():
            return self.value

        return _get().__await__()


class FakeDownloadContext:
    def __init__(self, download):
        self.info = FakeDownloadInfo(download)

    async def __aenter__(self):
        return self.info

    async def __aexit__(self, *_exc):
        return False


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector
        self.first = self

    async def inner_text(self):
        self.page.calls.append(("inner_text", self.selector))
        return "abcdefghij"

    async def wait_for(self, **kwargs):
        self.page.calls.append(("locator.wait_for", self.selector, kwargs))

    async def click(self):
        self.page.calls.append(("click", self.selector))

    async def fill(self, text):
        self.page.calls.append(("fill", self.selector, text))

    async def type(self, text):
        self.page.calls.append(("type", self.selector, text))

    async def press(self, key):
        self.page.calls.append(("press", self.selector, key))

    async def set_input_files(self, paths):
        self.page.calls.append(("set_input_files", self.selector, paths))


class FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.calls = []
        self.default_timeout = None
        self.screenshot_bytes = b"PNG"
        self.evaluate_result = {"value": 7}
        self.download = FakeDownload()

    def set_default_timeout(self, value):
        self.default_timeout = value

    async def goto(self, url, **kwargs):
        self.url = url
        self.calls.append(("goto", url, kwargs))
        return FakeResponse()

    async def title(self):
        return "Example title"

    def locator(self, selector):
        return FakeLocator(self, selector)

    async def screenshot(self, **kwargs):
        self.calls.append(("screenshot", kwargs))
        return self.screenshot_bytes

    async def wait_for_timeout(self, value):
        self.calls.append(("wait_for_timeout", value))

    async def evaluate(self, script, arg=None):
        self.calls.append(("evaluate", script, arg))
        return self.evaluate_result

    def expect_download(self):
        return FakeDownloadContext(self.download)


class FakeContext:
    def __init__(self, page):
        self.page = page
        self.closed = 0
        self.routes = []

    async def route(self, pattern, handler):
        self.routes.append((pattern, handler))

    async def new_page(self):
        return self.page

    async def close(self):
        self.closed += 1


class FakeBrowser:
    def __init__(self, context):
        self.context = context
        self.context_kwargs = None
        self.closed = 0

    async def new_context(self, **kwargs):
        self.context_kwargs = kwargs
        return self.context

    async def close(self):
        self.closed += 1


class FakeRequest:
    def __init__(self, url):
        self.url = url


class FakeRoute:
    def __init__(self, url):
        self.request = FakeRequest(url)
        self.continued = 0
        self.aborted = []

    async def continue_(self):
        self.continued += 1

    async def abort(self, error_code=None):
        self.aborted.append(error_code)


class FakeBrowserType:
    def __init__(self, browser, error=None):
        self.browser = browser
        self.error = error
        self.launch_kwargs = None
        self.persistent_kwargs = None
        self.user_data_dir = None

    async def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        if self.error:
            raise self.error
        return self.browser

    async def launch_persistent_context(self, user_data_dir, **kwargs):
        self.user_data_dir = user_data_dir
        self.persistent_kwargs = kwargs
        if self.error:
            raise self.error
        return self.browser.context


class FakePlaywright:
    def __init__(self):
        self.page = FakePage()
        self.context = FakeContext(self.page)
        self.browser = FakeBrowser(self.context)
        self.chromium = FakeBrowserType(self.browser)
        self.firefox = FakeBrowserType(self.browser)
        self.webkit = FakeBrowserType(self.browser)
        self.stopped = 0

    async def stop(self):
        self.stopped += 1


class FakeManager:
    def __init__(self, playwright=None, error=None):
        self.playwright = playwright or FakePlaywright()
        self.error = error
        self.started = 0

    async def start(self):
        self.started += 1
        if self.error:
            raise self.error
        return self.playwright


def _driver(tmp_path, **kwargs):
    manager = FakeManager()
    driver = PlaywrightBrowserDriver(
        host_enabled=True,
        playwright_factory=lambda: manager,
        download_dir=tmp_path / "downloads",
        **kwargs,
    )
    driver.set_url_guard(lambda _url: True)
    return driver, manager


@pytest.mark.asyncio
async def test_host_consent_is_required_before_playwright_starts(tmp_path, monkeypatch):
    manager = FakeManager()
    driver = PlaywrightBrowserDriver(playwright_factory=lambda: manager)

    with pytest.raises(PlaywrightHostDisabled):
        await driver.navigate(url="https://example.com")
    assert manager.started == 0

    monkeypatch.delenv("JARVIS_PLAYWRIGHT_HOST", raising=False)
    with pytest.raises(PlaywrightHostDisabled):
        PlaywrightBrowserDriver.from_env()
    monkeypatch.setenv("JARVIS_PLAYWRIGHT_HOST", "1")
    assert PlaywrightBrowserDriver.from_env(playwright_factory=lambda: manager).host_enabled is True


@pytest.mark.parametrize("url", ["https://example.com", "data:text/html,hello", "file:///C:/secret.txt"])
async def test_navigation_refuses_without_transport_bound_proxy_before_playwright_starts(url):
    manager = FakeManager()
    driver = PlaywrightBrowserDriver(host_enabled=True, playwright_factory=lambda: manager)
    driver.set_url_guard(lambda _url: pytest.fail("navigation must not invoke the URL guard"))

    with pytest.raises(PlaywrightTransportUnavailable, match="transport unavailable"):
        await driver.navigate(url=url)

    assert manager.started == 0


@pytest.mark.asyncio
async def test_host_driver_refuses_to_start_without_a_per_request_url_guard():
    manager = FakeManager()
    driver = PlaywrightBrowserDriver(host_enabled=True, playwright_factory=lambda: manager)

    with pytest.raises(PlaywrightHostDisabled, match="URL guard"):
        await driver.navigate(url="https://example.com")

    assert manager.started == 0


@pytest.mark.asyncio
async def test_missing_or_broken_runtime_is_bounded_and_partial_startup_is_cleaned(
    tmp_path, monkeypatch
):
    real_import = builtins.__import__

    def _without_playwright(name, *args, **kwargs):
        if name == "playwright.async_api":
            raise ImportError("forced missing optional runtime")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _without_playwright)
    driver = PlaywrightBrowserDriver(host_enabled=True)
    driver.set_url_guard(lambda _url: True)
    with pytest.raises(PlaywrightTransportUnavailable, match="transport unavailable"):
        await driver.navigate(url="https://example.com")

    manager = FakeManager(error=RuntimeError("raw host detail"))
    broken = PlaywrightBrowserDriver(
        host_enabled=True, playwright_factory=lambda: manager, download_dir=tmp_path
    )
    broken.set_url_guard(lambda _url: True)
    with pytest.raises(PlaywrightTransportUnavailable) as exc:
        await broken.navigate(url="https://example.com")
    assert "raw host detail" not in str(exc.value)
    await broken.close()

    partial_manager = FakeManager()
    partial_manager.playwright.chromium = FakeBrowserType(
        partial_manager.playwright.browser, error=RuntimeError("binary failed")
    )
    partial = PlaywrightBrowserDriver(
        host_enabled=True, playwright_factory=lambda: partial_manager
    )
    partial.set_url_guard(lambda _url: True)
    with pytest.raises(PlaywrightTransportUnavailable):
        await partial.navigate(url="https://example.com")
    assert partial_manager.playwright.stopped == 0


@pytest.mark.asyncio
async def test_lazy_fresh_context_navigation_extract_screenshot_wait_and_close(tmp_path):
    driver, manager = _driver(tmp_path, max_extract_chars=5, max_screenshot_bytes=8)
    assert manager.started == 0

    extracted = await driver.extract(selector="main")
    shot = await driver.screenshot(full_page=True)
    waited = await driver.wait(selector="#ready", timeout_ms=400)

    assert extracted == {
        "text": "abcde", "truncated": True, "url": "about:blank"
    }
    assert shot["mime"] == "image/png" and shot["image_base64"] == "UE5H"
    assert waited == {"waited": "selector", "selector": "#ready", "timeout_ms": 400}
    chromium = manager.playwright.chromium
    # Isolated per-run profile: a throw-away temp dir, never the owner's profile.
    assert chromium.persistent_kwargs == {
        "headless": True,
        "args": [],
        "accept_downloads": True,
        "service_workers": "block",
    }
    assert chromium.launch_kwargs is None
    profile = Path(chromium.user_data_dir)
    assert profile.name.startswith("nerva-browser-") and profile.is_dir()
    assert driver.profile_dir == profile
    assert manager.playwright.page.default_timeout == 15_000
    assert manager.started == 1

    await driver.close()
    await driver.close()
    assert manager.playwright.context.closed == 1
    assert manager.playwright.stopped == 1
    assert not profile.exists()
    assert driver.profile_dir is None


@pytest.mark.asyncio
async def test_output_and_wait_budgets_fail_closed(tmp_path):
    driver, manager = _driver(
        tmp_path, max_screenshot_bytes=2, max_wait_ms=500, max_result_chars=5
    )
    with pytest.raises(PlaywrightOutputTooLarge):
        await driver.screenshot()
    with pytest.raises(ValueError, match="wait exceeds"):
        await driver.wait(timeout_ms=501)
    manager.playwright.page.evaluate_result = "too large"
    with pytest.raises(PlaywrightOutputTooLarge):
        await driver.execute_js(script="'too large'")
    assert not any(call[0] == "wait_for_timeout" for call in manager.playwright.page.calls)
    await driver.close()


@pytest.mark.asyncio
async def test_mutating_primitives_and_file_boundaries(tmp_path):
    upload = tmp_path / "upload.txt"
    upload.write_text("safe")
    driver, manager = _driver(tmp_path)

    assert await driver.click(selector="#go") == {"clicked": "#go"}
    assert await driver.type(selector="#q", text="hello") == {"typed": "#q"}
    assert await driver.type(selector="#q", text="!", clear=False) == {"typed": "#q"}
    assert await driver.submit(selector="form") == {"submitted": "form"}
    assert await driver.execute_js(script="arg => arg", arg={"x": 1}) == {
        "value": {"value": 7}
    }
    assert await driver.upload(selector="input", paths=[str(upload)]) == {
        "uploaded": 1, "selector": "input"
    }
    downloaded = await driver.download(selector="#download")

    page = manager.playwright.page
    assert ("fill", "#q", "hello") in page.calls
    assert ("type", "#q", "!") in page.calls
    assert page.download.saved_as == (tmp_path / "downloads" / "report.txt").resolve()
    assert downloaded == {
        "saved_to": str(page.download.saved_as), "filename": "report.txt"
    }

    with pytest.raises(ValueError, match="upload path"):
        await driver.upload(selector="input", paths=[str(tmp_path / "missing")])
    await driver.close()


@pytest.mark.asyncio
async def test_governed_browser_blocks_before_real_driver_and_null_default_is_unchanged(tmp_path):
    driver, manager = _driver(tmp_path)
    governed = GovernedBrowser(driver=driver, policy=BrowserPolicy(["example.com"]))

    offlist = await governed.run_step({"action": "navigate", "url": "https://evil.com"})
    denied = await governed.run_step({"action": "click", "selector": "#buy"})

    assert offlist["status"] == "blocked"
    assert denied["status"] == "denied"
    assert manager.started == 0

    allowed = await governed.run_step({
        "action": "navigate", "url": "https://example.com"
    })
    assert allowed == {
        "action": "navigate",
        "status": "blocked",
        "reason": "browser transport not configured",
    }
    assert manager.started == 0

    default_governed = GovernedBrowser(policy=BrowserPolicy(["example.com"]))
    assert default_governed.driver.__class__.__name__ == "NullBrowserDriver"
    await driver.close()


@pytest.mark.asyncio
async def test_governed_policy_blocks_redirects_and_subresources_inside_playwright(tmp_path):
    driver, manager = _driver(tmp_path)
    policy = BrowserPolicy(["example.com"])
    driver.set_url_guard(policy.domain_allowed)
    governed = GovernedBrowser(driver=driver, policy=policy)

    result = await governed.run_step({"action": "navigate", "url": "https://example.com/start"})

    assert result["status"] == "blocked"
    await driver.extract(selector="body")
    [(pattern, handler)] = manager.playwright.context.routes
    assert pattern == "**/*"

    allowed = FakeRoute("https://cdn.example.com/app.js")
    await handler(allowed)
    assert allowed.continued == 0 and allowed.aborted == ["blockedbyclient"]

    blocked = FakeRoute("https://evil.com/redirected")
    await handler(blocked)
    assert blocked.continued == 0 and blocked.aborted == ["blockedbyclient"]
    reasons = [entry["reason"] for entry in driver.blocked_requests]
    assert len(reasons) == 2 and all(r.startswith("policy_denied:") for r in reasons)
    assert "evil.com not in egress allowlist" in reasons[1]
    await driver.close()


@pytest.mark.asyncio
async def test_live_setting_does_not_claim_navigation_without_a_transport_proxy(monkeypatch):
    monkeypatch.setenv("JARVIS_PLAYWRIGHT_LIVE", "1")
    driver = PlaywrightBrowserDriver(host_enabled=True)
    driver.set_url_guard(lambda url: str(url).startswith("data:text/html,"))
    try:
        with pytest.raises(PlaywrightTransportUnavailable, match="transport unavailable"):
            await driver.navigate(url="data:text/html,<main>Jarvis Playwright</main>")
    finally:
        await driver.close()
