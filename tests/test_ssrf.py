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

from core.security.ssrf import resolve_and_validate, check_ssrf  # noqa: E402
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
    assert ips == [] and "private IP" in err
    ips, err = resolve_and_validate("169.254.169.254")
    assert ips == [] and "metadata" in err


def test_resolves_public(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _gai("93.184.216.34"))
    assert resolve_and_validate("example.com") == (["93.184.216.34"], None)


def test_rejects_if_any_resolved_ip_is_private(monkeypatch):
    # Split-horizon rebinding: one public + one private record → reject the host.
    monkeypatch.setattr(socket, "getaddrinfo", _gai("93.184.216.34", "127.0.0.1"))
    ips, err = resolve_and_validate("rebind.evil")
    assert ips == [] and "private IP" in err


def test_dns_failure_is_error(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    ips, err = resolve_and_validate("nope.invalid")
    assert ips == [] and "DNS resolution failed" in err


def test_check_ssrf_delegates_and_is_lenient_on_dns_failure(monkeypatch):
    assert check_ssrf("http://10.0.0.1/x").startswith("URL resolves to private IP")
    assert check_ssrf("not a url") == "No hostname in URL"
    def boom(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    # DNS failure is not a hard block in the pre-flight filter (fetch fails anyway).
    assert check_ssrf("http://nope.invalid/") is None


# ── fetch_page: pinning + manual redirect validation ──────────────

@pytest.fixture
def pin_resolver(monkeypatch):
    """Make resolve_and_validate deterministic per-host for fetch_page tests."""
    table = {}
    def fake(host):
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
