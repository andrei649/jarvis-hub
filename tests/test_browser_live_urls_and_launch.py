"""Three browser review findings on #1321, each pinned at the point it failed.

* A live page URL with a fragment (an in-page anchor, a hash route) failed the egress
  policy, so the final-URL check blanked the page and snapshot skipped the main frame.
  A fragment never leaves the browser; intake still refuses one in a requested URL.
* Readiness accepted a Chromium-only Linux host, but every launch asked for
  ``channel='chrome'``, which Playwright resolves only to Google Chrome's fixed install.
* get_images minted fresh refs on every call and never retired them, so a gallery
  polled a few times filled MAX_REFS and later snapshots minted no ref at all.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import browser_runtime
from agents.core.browser_agent import BrowserPolicy, FixtureBrowserPolicy

# ── live URLs with a fragment ─────────────────────────────────────────────────────

@pytest.fixture
def no_dns(monkeypatch):
    from agents.core.security import ssrf

    monkeypatch.setattr(ssrf, "check_ssrf", lambda _url: None)


@pytest.mark.parametrize("url", ["https://docs.example.com/guide#install",
                                 "https://example.com/#/home"])
def test_a_live_page_url_with_a_fragment_passes_the_egress_policy(no_dns, url):
    assert BrowserPolicy(["example.com"]).domain_allowed(url) == (True, "")


def test_the_fixture_policy_accepts_a_fragment_on_its_own_origin():
    policy = FixtureBrowserPolicy("http://fixture.browser.test:4321")
    assert policy.domain_allowed("http://fixture.browser.test:4321/page#details") == (True, "")
    assert policy.domain_allowed("http://elsewhere.test:4321/#x")[0] is False


def test_the_policy_still_refuses_what_a_fragment_cannot_excuse(no_dns):
    policy = BrowserPolicy(["example.com"])
    assert policy.domain_allowed("https://evil.test/#example.com")[0] is False
    assert policy.domain_allowed("https://user@example.com/#x")[0] is False
    assert policy.domain_allowed("ftp://example.com/#x")[0] is False


def test_intake_still_refuses_a_fragment_in_a_requested_url():
    with pytest.raises(browser_runtime.BrowserPlanRefused):
        browser_runtime.validate_browser_request({"mode": "start", "steps": [
            {"action": "navigate", "url": "https://example.com/page#section"}]})


# ── what the driver launches ──────────────────────────────────────────────────────

def test_a_chromium_only_linux_host_launches_the_chromium_it_was_found_ready_with(
        monkeypatch, tmp_path):
    monkeypatch.setattr(browser_runtime.sys, "platform", "linux")
    monkeypatch.setattr(browser_runtime, "_CHROME_CHANNEL_LINUX", tmp_path / "absent")
    monkeypatch.setattr(browser_runtime, "_chrome_binary", lambda: "/usr/bin/chromium")
    assert browser_runtime._launch_target() == {"executable_path": "/usr/bin/chromium"}


def test_an_installed_google_chrome_keeps_the_chrome_channel(monkeypatch, tmp_path):
    chrome = tmp_path / "chrome"
    chrome.write_text("")
    monkeypatch.setattr(browser_runtime.sys, "platform", "linux")
    monkeypatch.setattr(browser_runtime, "_CHROME_CHANNEL_LINUX", chrome)
    monkeypatch.setattr(browser_runtime, "_chrome_binary", lambda: "/usr/bin/chromium")
    assert browser_runtime._launch_target() == {"channel": "chrome"}
    monkeypatch.setattr(browser_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(browser_runtime, "_CHROME_CHANNEL_LINUX", tmp_path / "absent")
    assert browser_runtime._launch_target() == {"channel": "chrome"}


@pytest.mark.asyncio
async def test_the_driver_launches_the_given_executable(tmp_path):
    from agents.core.browser_playwright import PlaywrightBrowserDriver
    from tests.test_h28_playwright_driver import FakeManager

    manager = FakeManager()
    driver = PlaywrightBrowserDriver(host_enabled=True, playwright_factory=lambda: manager,
                                     executable_path="/usr/bin/chromium")
    driver.set_url_guard(lambda _url: True)
    try:
        await driver.extract(selector="body")
        kwargs = manager.playwright.chromium.persistent_kwargs
        assert kwargs["executable_path"] == "/usr/bin/chromium" and "channel" not in kwargs
    finally:
        await driver.close()


# ── get_images refs ───────────────────────────────────────────────────────────────

def _gallery_session(images: int):
    from agents.core.browser_session import BrowserSession

    class Handle:
        def __init__(self, index, kind):
            self.index, self.kind = index, kind

        async def is_visible(self):
            return True

        async def evaluate(self, _script):
            semantics = {"connected": True, "hidden": False, "disabled": False,
                         "role": self.kind, "name": f"{self.kind}{self.index}", "target": "",
                         "focus": False}
            if self.kind == "button":
                return semantics
            return {"connected": True, "hidden": False, "alt": f"a{self.index}",
                    "src": f"https://example.test/{self.index}.png", "src_truncated": False,
                    "width": 10, "height": 10, "semantics": semantics}

    class Locator:
        def __init__(self, kind, index=None):
            self.kind, self.index = kind, index

        async def count(self):
            return images if self.kind == "img" else 10

        def nth(self, index):
            return Locator(self.kind, index)

        async def element_handle(self):
            return Handle(self.index, self.kind)

    class Frame:
        url = "https://example.test/gallery"

        def locator(self, selector):
            return Locator("img" if selector == "img" else "button")

    main = Frame()
    page = SimpleNamespace(frames=[main], main_frame=main, on=lambda *_args: None)

    class Driver:
        async def _ensure_started(self):
            return page

        async def observe_snapshot(self):
            return {"observation": "structured_ui"}

        def _assert_execution_current(self):
            return None

    return BrowserSession("c" * 32, Driver(),
                          SimpleNamespace(domain_allowed=lambda _url: (True, "")),
                          SimpleNamespace(pinned_hosts=lambda: {"example.test"}),
                          "agent", "owner", None, "head", "registration")


@pytest.mark.asyncio
async def test_polling_a_gallery_never_exhausts_the_ref_inventory():
    from agents.core.browser_session import MAX_REFS, SessionRefused

    session = _gallery_session(24)
    counts, first = [], None
    for _ in range(6):
        result = await session.get_images()
        refs = [row["ref"] for row in result["images"] if "ref" in row]
        counts.append(len(refs))
        first = first or refs[0]
        assert len(session.refs) <= MAX_REFS
    assert counts[0] > 0 and min(counts) == counts[0], counts
    # A superseded image ref refuses as stale; a snapshot taken now still mints refs.
    with pytest.raises(SessionRefused):
        await session.resolve_ref(first, "click")
    assert (await session.snapshot())["refs"]
