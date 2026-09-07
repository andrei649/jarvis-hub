"""SEC-B4 closure: the browser dials only the resolver-validated IP.

Hermetic: a fake resolver stands in for ``resolve_and_validate`` (pytest-socket
blocks DNS anyway), a fake Playwright runtime records launch args, routes, and
navigations. No real browser, no network, no OS permissions.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.browser_agent import BrowserPolicy  # noqa: E402
from agents.core.browser_playwright import (  # noqa: E402
    PROFILE_PREFIX,
    PlaywrightBrowserDriver,
    PlaywrightEgressBlocked,
    PlaywrightTransportUnavailable,
    PlaywrightUnavailable,
    parse_aria_snapshot,
)
from agents.core.browser_transport import (  # noqa: E402
    PINNED_TRANSPORT_REQUIRES_CHROMIUM,
    BrowserTransportRefused,
    PinnedResolver,
    PinnedTarget,
    is_private_host_literal,
    transport_from_env,
)

PUBLIC_IP = "93.184.216.34"
SNAPSHOT = """\
- banner [ref=e1]:
  - heading "Nerva" [level=1] [ref=e2] [box=10,20,300,40]
  - link "Docs" [ref=e3]
- main:
  - text: Welcome home
  - button "Sign in" [ref=e4] [x=1] [y=2] [width=30] [height=10]
  - textbox "Search \\"quoted\\"" [ref=e5]
  - paragraph: Inline paragraph text
- ??? not a node
"""


class RecordingResolver:
    """Mirrors ``resolve_and_validate(host, *, mode)`` with a scripted table."""

    def __init__(self, table=None):
        self.table = dict(table or {})
        self.calls: list[tuple[str, str]] = []

    def __call__(self, host, *, mode):
        self.calls.append((host, mode))
        answer = self.table.get((host, mode))
        if answer is None:
            return [], f"DNS resolution failed for {host}"
        if isinstance(answer, str):
            return [], answer
        return list(answer), None


# --- fake Playwright runtime ---------------------------------------------------


class FakeResponse:
    status = 200


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector
        self.first = self

    async def aria_snapshot(self, **kwargs):
        self.page.calls.append(("aria_snapshot", self.selector, kwargs))
        if kwargs and not self.page.supports_boxes:
            raise TypeError("aria_snapshot() got an unexpected keyword argument 'boxes'")
        return self.page.snapshot_text

    async def inner_text(self):
        return "body text"


class FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.calls = []
        self.default_timeout = None
        self.snapshot_text = SNAPSHOT
        self.supports_boxes = True
        self.redirect_to = None

    def set_default_timeout(self, value):
        self.default_timeout = value

    async def goto(self, url, **kwargs):
        self.calls.append(("goto", url, kwargs))
        self.url = self.redirect_to or url
        return FakeResponse()

    async def title(self):
        return "Example title"

    def locator(self, selector):
        return FakeLocator(self, selector)


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


class FakeBrowserType:
    def __init__(self, context, error=None):
        self.context = context
        self.error = error
        self.launches: list[tuple[str, dict]] = []

    async def launch_persistent_context(self, user_data_dir, **kwargs):
        self.launches.append((user_data_dir, kwargs))
        if self.error:
            raise self.error
        return self.context


class FakePlaywright:
    def __init__(self, error=None):
        self.page = FakePage()
        self.context = FakeContext(self.page)
        self.chromium = FakeBrowserType(self.context, error=error)
        self.firefox = FakeBrowserType(self.context, error=error)
        self.stopped = 0

    async def stop(self):
        self.stopped += 1


class FakeManager:
    def __init__(self, error=None):
        self.playwright = FakePlaywright(error=error)
        self.started = 0
        self.events: list[str] = []

    async def start(self):
        self.started += 1
        self.events.append("start")
        return self.playwright


class FakeRoute:
    def __init__(self, url):
        self.request = type("Req", (), {"url": url})()
        self.continued = 0
        self.aborted = []

    async def continue_(self):
        self.continued += 1

    async def abort(self, error_code=None):
        self.aborted.append(error_code)


def _resolver(**extra):
    table = {("example.com", "public"): [PUBLIC_IP], ("www.example.com", "public"): [PUBLIC_IP]}
    table.update(extra)
    return RecordingResolver(table)


def _suffix_guard(allowlist):
    """BrowserPolicy's suffix allowlist without its DNS-bound check_ssrf half —
    the hermetic resolver stands in for DNS, so the guard stays pure."""
    allow = BrowserPolicy(list(allowlist)).allowlist

    def guard(url):
        host = (urlparse(url).hostname or "").lower()
        ok = any(host == d or host.endswith("." + d) for d in allow)
        return ok, "" if ok else "not in egress allowlist"

    return guard


def _driver(resolver=None, allowlist=("example.com",), **kwargs):
    manager = FakeManager()
    driver = PlaywrightBrowserDriver(
        host_enabled=True, playwright_factory=lambda: manager, **kwargs
    )
    driver.set_url_guard(_suffix_guard(allowlist))
    transport = PinnedResolver(resolver=resolver or _resolver())
    driver.set_transport(transport)
    return driver, manager, transport


# --- PinnedResolver ------------------------------------------------------------


def test_pin_validates_scheme_host_and_keeps_first_ip_against_rebind():
    resolver = _resolver()
    pinned = PinnedResolver(resolver=resolver)

    target = pinned.pin("https://Example.com./path?q=1")
    assert target == PinnedTarget(
        host="example.com", ip=PUBLIC_IP, scheme="https", port=443,
        logical_url="https://Example.com./path?q=1", mode="public",
    )
    assert resolver.calls == [("example.com", "public")]

    # A later, different DNS answer must never replace what the browser dialed.
    resolver.table[("example.com", "public")] = ["10.0.0.9"]
    again = pinned.pin("http://example.com:8080/")
    assert again.ip == PUBLIC_IP and again.port == 8080
    assert resolver.calls == [("example.com", "public")]
    assert pinned.pinned_hosts() == frozenset({"example.com"})
    assert pinned.pinned_ip("EXAMPLE.com") == PUBLIC_IP
    assert pinned.is_pinned("https://example.com/x") and not pinned.is_pinned("https://other.test/")
    assert pinned.snapshot() == {"mode": "public", "pins": {"example.com": PUBLIC_IP}, "max_pins": 64}

    for url, reason in (
        ("file:///etc/passwd", "unsupported_scheme"),
        ("data:text/html,hi", "unsupported_scheme"),
        ("https:///nohost", "no_hostname"),
        ("https://127.0.0.1/", "private_address_denied"),
        ("https://localhost/", "private_address_denied"),
        ("https://[::1]/", "private_address_denied"),
        ("https://unknown.test/", "resolver_refused"),
    ):
        with pytest.raises(BrowserTransportRefused) as exc:
            pinned.pin(url)
        assert exc.value.reason == reason, url
    # The blocked scheme/literal refusals never touched the resolver.
    assert resolver.calls == [("example.com", "public"), ("unknown.test", "public")]


def test_resolver_refusal_and_private_answers_are_not_pinned():
    resolver = RecordingResolver({
        ("evil.test", "public"): "URL resolves to unsafe address for public mode: 10.0.0.5",
    })
    pinned = PinnedResolver(resolver=resolver)
    with pytest.raises(BrowserTransportRefused) as exc:
        pinned.pin("https://evil.test/")
    assert exc.value.reason == "resolver_refused" and "10.0.0.5" in exc.value.detail
    assert pinned.pinned_hosts() == frozenset()


def test_lan_mode_admits_house_lan_only_after_public_validation_fails():
    resolver = RecordingResolver({
        ("printer.lan", "public"): "URL resolves to unsafe address for public mode: 192.168.1.20",
        ("printer.lan", "lan"): ["192.168.1.20"],
        ("example.com", "public"): [PUBLIC_IP],
        ("192.168.1.7", "public"): "URL resolves to unsafe address for public mode: 192.168.1.7",
        ("192.168.1.7", "lan"): ["192.168.1.7"],
    })
    strict = PinnedResolver(resolver=resolver, mode="public")
    with pytest.raises(BrowserTransportRefused):
        strict.pin("http://printer.lan/")

    lan = PinnedResolver(resolver=resolver, mode="lan")
    assert lan.pin("http://printer.lan/").ip == "192.168.1.20"
    assert lan.pin("https://example.com/").ip == PUBLIC_IP
    assert lan.pin("http://192.168.1.7/").ip == "192.168.1.7"
    assert resolver.calls[1:3] == [("printer.lan", "public"), ("printer.lan", "lan")]


def test_launch_args_pin_every_host_and_deny_everything_else():
    pinned = PinnedResolver(resolver=RecordingResolver({
        ("b.example", "public"): [PUBLIC_IP],
        ("a.example", "public"): ["2001:db8::1"],
    }))
    assert pinned.launch_args() == ["--host-resolver-rules=MAP * ~NOTFOUND"]
    pinned.pin("https://b.example/")
    pinned.pin("https://a.example/")
    assert pinned.launch_args("chromium") == [
        "--host-resolver-rules=MAP a.example [2001:db8::1], MAP b.example "
        f"{PUBLIC_IP}, MAP * ~NOTFOUND"
    ]
    for browser in ("firefox", "webkit"):
        with pytest.raises(BrowserTransportRefused) as exc:
            pinned.launch_args(browser)
        assert exc.value.reason == PINNED_TRANSPORT_REQUIRES_CHROMIUM


def test_pin_table_is_bounded_and_contracts_validate():
    pinned = PinnedResolver(resolver=_resolver(), max_pins=1)
    pinned.pin("https://example.com/")
    with pytest.raises(BrowserTransportRefused) as exc:
        pinned.pin("https://www.example.com/")
    assert exc.value.reason == "pin_table_full"

    with pytest.raises(ValueError):
        PinnedResolver(mode="anything")
    with pytest.raises(ValueError):
        PinnedResolver(max_pins=0)
    for bad in (
        {"host": "Example.com"}, {"ip": "not-an-ip"}, {"scheme": "ftp"},
        {"port": 0}, {"mode": "wild"},
    ):
        fields = {
            "host": "example.com", "ip": PUBLIC_IP, "scheme": "https", "port": 443,
            "logical_url": "https://example.com/", "mode": "public", **bad,
        }
        with pytest.raises(ValueError):
            PinnedTarget(**fields)
    assert is_private_host_literal("10.1.2.3") and is_private_host_literal("LOCALHOST")
    assert not is_private_host_literal(PUBLIC_IP) and not is_private_host_literal("example.com")


def test_from_env_mode_and_transport_follow_owner_flags(monkeypatch):
    monkeypatch.delenv("JARVIS_BROWSER_ALLOW_PRIVATE_URLS", raising=False)
    monkeypatch.delenv("JARVIS_PLAYWRIGHT_HOST", raising=False)
    monkeypatch.delenv("JARVIS_PLAYWRIGHT_BROWSER", raising=False)
    assert PinnedResolver.from_env().mode == "public"
    assert transport_from_env() is None  # host never enabled → no transport at all

    monkeypatch.setenv("JARVIS_BROWSER_ALLOW_PRIVATE_URLS", "1")
    monkeypatch.setenv("JARVIS_PLAYWRIGHT_HOST", "1")
    assert PinnedResolver.from_env().mode == "lan"
    assert transport_from_env().mode == "lan"
    monkeypatch.setenv("JARVIS_PLAYWRIGHT_BROWSER", "firefox")
    assert transport_from_env() is None


# --- driver + transport ----------------------------------------------------------


async def test_navigate_pins_before_launch_and_dials_only_the_validated_ip(monkeypatch):
    driver, manager, transport = _driver()
    resolver = transport._resolver
    original_pin = transport.pin

    def pin_and_mark(url):
        manager.events.append("pin")
        return original_pin(url)

    monkeypatch.setattr(transport, "pin", pin_and_mark)
    assert driver.transport_bound is True and manager.started == 0

    result = await driver.navigate(url="https://example.com/start")

    assert manager.events == ["pin", "start"]
    assert resolver.calls == [("example.com", "public")]
    [(user_data_dir, launch_kwargs)] = manager.playwright.chromium.launches
    assert launch_kwargs["args"] == [
        f"--host-resolver-rules=MAP example.com {PUBLIC_IP}, MAP * ~NOTFOUND"
    ]
    assert launch_kwargs["headless"] is True and launch_kwargs["service_workers"] == "block"
    profile = Path(user_data_dir)
    assert profile.name.startswith(PROFILE_PREFIX) and profile.is_dir()
    assert driver.profile_dir == profile and driver.launched_hosts == frozenset({"example.com"})
    assert manager.playwright.page.calls == [
        ("goto", "https://example.com/start", {"wait_until": "domcontentloaded"})
    ]
    assert result == {
        "url": "https://example.com/start", "title": "Example title",
        "status": 200, "pinned_ip": PUBLIC_IP,
    }
    await driver.close()
    assert not profile.exists() and driver.profile_dir is None
    assert manager.playwright.context.closed == 1 and manager.playwright.stopped == 1


async def test_without_a_bound_transport_navigation_still_refuses_before_startup():
    manager = FakeManager()
    driver = PlaywrightBrowserDriver(host_enabled=True, playwright_factory=lambda: manager)
    driver.set_url_guard(lambda _url: True)
    assert driver.transport_bound is False
    with pytest.raises(PlaywrightTransportUnavailable, match="transport unavailable"):
        await driver.navigate(url="https://example.com")
    assert manager.started == 0

    firefox = PlaywrightBrowserDriver(
        host_enabled=True, browser="firefox", playwright_factory=lambda: manager
    )
    with pytest.raises(PlaywrightTransportUnavailable, match=PINNED_TRANSPORT_REQUIRES_CHROMIUM):
        firefox.set_transport(PinnedResolver(resolver=_resolver()))
    assert firefox.transport_bound is False
    with pytest.raises(ValueError, match="pin"):
        driver.set_transport(object())


async def test_policy_denied_and_private_targets_are_never_resolved_or_launched():
    driver, manager, transport = _driver()
    resolver = transport._resolver

    with pytest.raises(PlaywrightEgressBlocked) as exc:
        await driver.navigate(url="https://evil.test/")
    assert exc.value.reason.startswith("policy_denied:")
    with pytest.raises(PlaywrightEgressBlocked) as exc:
        await driver.navigate(url="https://127.0.0.1/admin")
    assert exc.value.reason == "private_address_denied"
    with pytest.raises(PlaywrightEgressBlocked) as exc:
        await driver.navigate(url="file:///etc/passwd")
    assert exc.value.reason == "unsupported_scheme:file"

    assert resolver.calls == []  # denied hosts never leak to DNS
    assert manager.started == 0
    assert [e["reason"] for e in driver.blocked_requests] == [
        "policy_denied:not in egress allowlist", "private_address_denied",
        "unsupported_scheme:file",
    ]
    assert all("evil" not in e["host"] or e["host"] == "evil.test" for e in driver.blocked_requests)


async def test_resolver_refusal_surfaces_as_named_egress_block():
    driver, manager, _ = _driver(
        resolver=RecordingResolver({("example.com", "public"): "resolves to unsafe 10.0.0.1"})
    )
    with pytest.raises(PlaywrightEgressBlocked) as exc:
        await driver.navigate(url="https://example.com/")
    assert exc.value.reason == "resolver_refused" and "10.0.0.1" in exc.value.detail
    assert manager.started == 0


async def test_route_layer_revalidates_redirects_subresources_and_private_ranges():
    driver, manager, _ = _driver()
    await driver.navigate(url="https://example.com/")
    [(pattern, handler)] = manager.playwright.context.routes
    assert pattern == "**/*"

    same_host = FakeRoute("https://example.com/app.js")
    await handler(same_host)
    assert same_host.continued == 1 and same_host.aborted == []

    cases = {
        "https://evil.com/redirected": "policy_denied:not in egress allowlist",
        "https://www.example.com/iframe": "host_not_pinned",  # on-list, not pinned
        "http://10.0.0.5/": "private_address_denied",
        "http://localhost:8080/": "private_address_denied",
        "data:text/html,hi": "unsupported_scheme:data",
        "ftp://example.com/": "unsupported_scheme:ftp",
    }
    for url in cases:
        route = FakeRoute(url)
        await handler(route)
        assert route.continued == 0 and route.aborted == ["blockedbyclient"], url
    assert [e["reason"] for e in driver.blocked_requests] == list(cases.values())
    await driver.close()


async def test_allow_private_urls_opt_in_admits_lan_literals_at_the_route_layer():
    resolver = RecordingResolver({
        ("192.168.1.7", "public"): "unsafe for public", ("192.168.1.7", "lan"): ["192.168.1.7"],
    })
    manager = FakeManager()
    driver = PlaywrightBrowserDriver(
        host_enabled=True, playwright_factory=lambda: manager, allow_private_urls=True
    )
    driver.set_url_guard(lambda _url: True)
    driver.set_transport(PinnedResolver(resolver=resolver, mode="lan"))
    result = await driver.navigate(url="http://192.168.1.7/status")
    assert result["pinned_ip"] == "192.168.1.7"
    [(_, handler)] = manager.playwright.context.routes
    lan = FakeRoute("http://192.168.1.7/style.css")
    await handler(lan)
    assert lan.continued == 1
    other = FakeRoute("http://10.9.9.9/")
    await handler(other)
    assert other.aborted == ["blockedbyclient"]
    assert driver.blocked_requests[-1]["reason"] == "host_not_pinned"
    await driver.close()


async def test_final_url_is_revalidated_after_goto():
    driver, manager, _ = _driver()
    page = manager.playwright.page
    page.redirect_to = "https://evil.com/landed"
    with pytest.raises(PlaywrightEgressBlocked) as exc:
        await driver.navigate(url="https://example.com/")
    assert exc.value.reason == "final_url_rejected"
    assert exc.value.detail == "policy_denied:not in egress allowlist"
    assert page.calls[-1][1] == "about:blank"
    assert driver.blocked_requests[-1] == {
        **driver.blocked_requests[-1], "host": "evil.com",
        "reason": "policy_denied:not in egress allowlist",
    }
    await driver.close()


async def test_new_host_relaunches_the_browser_with_the_enlarged_pin_table():
    driver, manager, _ = _driver()
    await driver.navigate(url="https://example.com/")
    first_profile = Path(manager.playwright.chromium.launches[0][0])
    await driver.navigate(url="https://example.com/second")  # same host → no relaunch
    assert manager.started == 1

    await driver.navigate(url="https://www.example.com/")
    assert manager.started == 2
    assert not first_profile.exists()
    launches = manager.playwright.chromium.launches
    assert len(launches) == 2 and launches[1][0] != launches[0][0]
    assert launches[1][1]["args"] == [
        f"--host-resolver-rules=MAP example.com {PUBLIC_IP}, "
        f"MAP www.example.com {PUBLIC_IP}, MAP * ~NOTFOUND"
    ]
    assert driver.launched_hosts == frozenset({"example.com", "www.example.com"})
    await driver.close()


async def test_broken_launch_with_transport_is_bounded_and_profile_dir_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    import tempfile

    tempfile.tempdir = None  # honour the patched TMPDIR
    try:
        manager = FakeManager(error=RuntimeError("raw host detail"))
        driver = PlaywrightBrowserDriver(host_enabled=True, playwright_factory=lambda: manager)
        driver.set_url_guard(lambda _url: True)
        driver.set_transport(PinnedResolver(resolver=_resolver()))
        with pytest.raises(PlaywrightUnavailable) as exc:
            await driver.navigate(url="https://example.com/")
        assert "raw host detail" not in str(exc.value)
        assert not list(tmp_path.glob(f"{PROFILE_PREFIX}*"))
        assert driver.profile_dir is None and manager.playwright.stopped == 1
    finally:
        tempfile.tempdir = None


# --- accessibility-first observation -----------------------------------------------


async def test_observe_snapshot_is_structured_and_bounded():
    driver, manager, _ = _driver(max_extract_chars=60)
    await driver.navigate(url="https://example.com/")
    page = manager.playwright.page

    full = await driver.observe_snapshot(max_chars=10_000)
    assert full["observation"] == "structured_ui" and full["truncated"] is False
    assert full["url"] == "https://example.com/" and full["count"] == 9
    assert page.calls[-1] == ("aria_snapshot", "body", {"boxes": True})
    by_ref = {el["ref"]: el for el in full["elements"]}
    assert by_ref["e2"]["role"] == "heading" and by_ref["e2"]["name"] == "Nerva"
    assert by_ref["e2"]["rect"] == {"x": 10.0, "y": 20.0, "w": 300.0, "h": 40.0}
    assert by_ref["e2"]["attrs"] == {"level": "1"} and by_ref["e2"]["depth"] == 1
    assert by_ref["e4"]["rect"] == {"x": 1.0, "y": 2.0, "w": 30.0, "h": 10.0}
    assert by_ref["e4"]["attrs"] == {}
    assert by_ref["e5"]["name"] == 'Search "quoted"'
    assert by_ref["e3"]["rect"] is None
    roles = [el["role"] for el in full["elements"]]
    assert roles == [
        "banner", "heading", "link", "main", "text", "button", "textbox", "paragraph", "unknown",
    ]
    assert full["elements"][4]["name"] == "Welcome home"
    assert full["elements"][7]["name"] == "Inline paragraph text"
    assert full["elements"][8]["name"] == "??? not a node"

    bounded = await driver.observe_snapshot()  # max_extract_chars=60 governs
    assert bounded["truncated"] is True and bounded["chars"] == 60
    assert bounded["count"] < full["count"]

    page.supports_boxes = False
    fallback = await driver.observe_snapshot(max_chars=10_000)
    assert page.calls[-1] == ("aria_snapshot", "body", {})
    assert fallback["count"] == 9
    with pytest.raises(ValueError):
        await driver.observe_snapshot(max_chars=0)
    await driver.close()


def test_parse_aria_snapshot_bounds_elements():
    elements, truncated = parse_aria_snapshot("- a\n- b\n- c\n", max_elements=2)
    assert truncated is True and [e["ref"] for e in elements] == ["n0", "n1"]
    assert parse_aria_snapshot("") == ([], False)


async def test_from_env_binds_the_pinned_transport_for_chromium_only(monkeypatch):
    monkeypatch.setenv("JARVIS_PLAYWRIGHT_HOST", "1")
    monkeypatch.setenv("JARVIS_BROWSER_ALLOW_PRIVATE_URLS", "1")
    monkeypatch.delenv("JARVIS_PLAYWRIGHT_BROWSER", raising=False)
    manager = FakeManager()
    driver = PlaywrightBrowserDriver.from_env(playwright_factory=lambda: manager)
    assert driver.transport_bound and driver.allow_private_urls is True
    assert driver._transport.mode == "lan"

    monkeypatch.delenv("JARVIS_BROWSER_ALLOW_PRIVATE_URLS", raising=False)
    monkeypatch.setenv("JARVIS_PLAYWRIGHT_BROWSER", "firefox")
    firefox = PlaywrightBrowserDriver.from_env(playwright_factory=lambda: manager)
    assert firefox.transport_bound is False and firefox.allow_private_urls is False
    firefox.set_url_guard(lambda _url: True)
    with pytest.raises(PlaywrightTransportUnavailable):
        await firefox.navigate(url="https://example.com/")
    assert manager.started == 0
