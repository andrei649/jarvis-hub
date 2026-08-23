"""HF-4: SSRF — DNS-rebinding / TOCTOU hardening.

resolve_and_validate resolves a host once and rejects it if *any* resolved IP is
private (defeating split-horizon / multi-record rebinding); fetch_page pins the
connection to that validated IP (Host + TLS SNI preserved) and follows redirects
manually so every hop is checked before we connect.
"""
import socket
import sys
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.security.ssrf import check_ssrf, is_private_ip, resolve_and_validate  # noqa: E402
from core.plugins import websearch as ws  # noqa: E402


def _gai(*ips):
    """Fake socket.getaddrinfo returning the given IP strings."""
    def fake(host, *a, **k):
        out = []
        for ip in ips:
            fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
            sockaddr = (ip, 0, 0, 0) if ":" in ip else (ip, 0)
            out.append((fam, socket.SOCK_STREAM, 0, "", sockaddr))
        return out
    return fake


# ── resolve_and_validate ──────────────────────────────────────────

def test_literal_ips():
    assert resolve_and_validate("8.8.8.8") == (["8.8.8.8"], None)
    ips, err = resolve_and_validate("127.0.0.1")
    assert ips == [] and "unsafe" in err
    ips, err = resolve_and_validate("169.254.169.254")
    assert ips == [] and "metadata" in err


def test_resolves_public(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _gai("93.184.216.34"))
    assert resolve_and_validate("example.com") == (["93.184.216.34"], None)


def test_rejects_if_any_resolved_ip_is_private(monkeypatch):
    # Split-horizon rebinding: one public + one private record → reject the host.
    monkeypatch.setattr(socket, "getaddrinfo", _gai("93.184.216.34", "127.0.0.1"))
    ips, err = resolve_and_validate("rebind.evil")
    assert ips == [] and "unsafe" in err


def test_dns_failure_is_error(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    ips, err = resolve_and_validate("nope.invalid")
    assert ips == [] and "DNS resolution failed" in err


def test_check_ssrf_delegates_and_rejects_dns_failure(monkeypatch):
    assert "unsafe" in check_ssrf("http://10.0.0.1/x")
    assert check_ssrf("not a url") == "No hostname in URL"
    def boom(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert "DNS resolution failed" in check_ssrf("http://nope.invalid/")


# ── fetch_page: pinning + manual redirect validation ──────────────

@pytest.fixture
def pin_resolver(monkeypatch):
    """Make resolve_and_validate deterministic per-host for fetch_page tests."""
    table = {}
    def fake(host, *args, **kwargs):
        return table.get(host, ([], f"URL resolves to private IP: {host}"))
    monkeypatch.setattr(ws, "resolve_and_validate", fake)
    return table


@pytest.mark.asyncio
async def test_fetch_pins_validated_ip_and_extracts_text(pin_resolver):
    pin_resolver["example.com"] = (["93.184.216.34"], None)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host_in_url"] = request.url.host
        seen["host_header"] = request.headers.get("host")
        return httpx.Response(200, text="<html><body><p>Hello world</p></body></html>")

    plugin = ws.WebSearchPlugin()
    out = await plugin.fetch_page("http://example.com/p", _transport=httpx.MockTransport(handler))
    assert "Hello world" in out
    # Dialed the *pinned IP*, not the hostname; Host header preserved.
    assert seen["host_in_url"] == "93.184.216.34"
    assert seen["host_header"] == "example.com"


@pytest.mark.asyncio
async def test_fetch_blocks_redirect_to_private_host(pin_resolver):
    pin_resolver["example.com"] = (["93.184.216.34"], None)
    # internal.host intentionally absent from the table → resolves to "private".
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(302, headers={"location": "http://internal.host/secret"})

    plugin = ws.WebSearchPlugin()
    out = await plugin.fetch_page("http://example.com/p", _transport=httpx.MockTransport(handler))
    assert out is None              # the private redirect target was blocked
    assert calls["n"] == 1          # blocked before dialing the second hop


@pytest.mark.asyncio
async def test_fetch_blocks_redirect_loop(pin_resolver):
    pin_resolver["a.example"] = (["93.184.216.34"], None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(302, headers={"location": "http://a.example/again"})

    plugin = ws.WebSearchPlugin()
    out = await plugin.fetch_page("http://a.example/", _transport=httpx.MockTransport(handler))
    assert out is None
    assert calls["n"] == 6          # initial + 5 redirects, then give up


# ── IPv6-mapped / embedded-IPv4 bypass surface (covers ssrf.py:38,41,52,80-82,98-99) ──
# Attackers wrap a private/metadata IPv4 in IPv6 notation (::ffff:a.b.c.d) to slip past a
# naive host filter; these pin that resolve unwraps and blocks it while a mapped PUBLIC
# address still passes. Behaviour confirmed correct — these lock it against regression.

def test_is_private_ip_unwraps_ipv4_mapped_ipv6():
    assert is_private_ip("::ffff:127.0.0.1") is True        # mapped loopback
    assert is_private_ip("::ffff:169.254.169.254") is True   # mapped cloud metadata
    assert is_private_ip("::ffff:10.0.0.1") is True          # mapped RFC1918
    assert is_private_ip("::127.0.0.1") is True              # IPv4-compatible (deprecated) form
    assert is_private_ip("::ffff:8.8.8.8") is False          # mapped PUBLIC must pass


def test_is_private_ip_is_false_on_garbage():
    assert is_private_ip("not-an-ip") is False               # ssrf.py:47-48
    assert is_private_ip("") is False


def test_resolve_blocks_ipv6_mapped_metadata_and_private():
    ips, err = resolve_and_validate("::ffff:169.254.169.254")  # embedded metadata → :80-82
    assert ips == [] and "metadata" in err
    ips, err = resolve_and_validate("::ffff:127.0.0.1")        # embedded private → :52 path
    assert ips == [] and "unsafe" in err
    assert resolve_and_validate("::ffff:8.8.8.8") == (["8.8.8.8"], None)  # normalized public mapped IP


def test_check_ssrf_blocks_bracketed_ipv6_mapped_urls():
    assert "metadata" in check_ssrf("http://[::ffff:169.254.169.254]/latest/meta-data/")
    assert "unsafe" in check_ssrf("http://[::ffff:127.0.0.1]:8080/admin")
    assert check_ssrf("http://[::ffff:8.8.8.8]/") is None


def test_empty_getaddrinfo_is_dns_failure(monkeypatch):
    # getaddrinfo returns zero records → fail closed (ssrf.py:98-99)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    ips, err = resolve_and_validate("empty.invalid")
    assert ips == [] and "DNS resolution failed" in err


async def test_websearch_fetch_page_uses_its_pinned_plugin_client(monkeypatch):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text="<html><body><p>Pinned page</p></body></html>",
            request=request,
        )
    )
    plugin = ws.WebSearchPlugin()
    plugin._client = __import__("core.http_client", fromlist=["PluginHTTPClient"]).PluginHTTPClient(
        "websearch",
        resolver=lambda _host, *, mode: (["93.184.216.34"], None),
        transport_factory=lambda _target: transport,
    )
    direct_creations = []
    real_async_client = httpx.AsyncClient

    def guarded_async_client(*args, **kwargs):
        if kwargs.get("transport") is None:
            direct_creations.append(True)
            pytest.fail("direct websearch client")
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(
        ws.httpx,
        "AsyncClient",
        guarded_async_client,
    )

    text = await plugin.fetch_page("https://docs.example.test/page")

    assert "Pinned page" in text
    assert direct_creations == []
    await plugin.close()


async def test_websearch_unsafe_dns_answer_creates_no_direct_or_pinned_transport(monkeypatch):
    plugin = ws.WebSearchPlugin()
    plugin._client = __import__("core.http_client", fromlist=["PluginHTTPClient"]).PluginHTTPClient(
        "websearch",
        resolver=lambda _host, *, mode: (["127.0.0.1"], None),
        transport_factory=lambda _target: pytest.fail("unsafe DNS must not open transport"),
    )
    direct_creations = []
    real_async_client = httpx.AsyncClient

    def guarded_async_client(*args, **kwargs):
        if kwargs.get("transport") is None:
            direct_creations.append(True)
            pytest.fail("direct websearch client")
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(
        ws.httpx,
        "AsyncClient",
        guarded_async_client,
    )

    assert await plugin.fetch_page("https://docs.example.test/page") is None
    assert direct_creations == []
    assert plugin._client._pinned_clients == {}
    await plugin.close()
