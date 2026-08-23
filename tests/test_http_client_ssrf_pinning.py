"""HF-4 — SSRF resolve-and-pin at the ``PluginHTTPClient`` _guard seam.

Every manifested-plugin verb funnels through ``_guard``; the pinning preflight
resolves the target host ONCE (``resolve_and_validate``) and fails closed when
ANY answer is private/link-local/metadata, when DNS fails, or when a host hands
out one public and one private A record (split-horizon rebinding). Fully
offline: scripted ``socket.getaddrinfo`` + ``httpx.MockTransport``; the doc-range
addresses (203.0.113.0/24, RFC 5737) are never dialed.
"""
import socket
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import http_client as hc  # noqa: E402
from agents.core.http_client import (  # noqa: E402
    PluginEgressError,
    PluginHTTPClient,
    PluginSSRFError,
)
import agents.core.plugin_gate as pg  # noqa: E402

PUBLIC_IP = "203.0.113.10"  # TEST-NET-3 doc range — validated, never routed


@pytest.fixture()
def pinned_plugin(monkeypatch):
    """A manifested plugin with FULL network access, so ONLY the pinning gate is exercised."""
    name = "ssrf_pin_probe"
    full = replace(pg.BUILTIN_PLUGINS["weather"], network_access=pg.NetworkAccess.FULL)
    monkeypatch.setitem(pg.BUILTIN_PLUGINS, name, full)
    return name


_OPEN_CLIENTS: list[PluginHTTPClient] = []


@pytest.fixture(autouse=True)
async def _drain_clients():
    yield
    while _OPEN_CLIENTS:
        await _OPEN_CLIENTS.pop().close()


class _ScriptedDNS:
    """Sticky scripted ``getaddrinfo``: every call answers the same address list."""

    def __init__(self, *ips_or_exc):
        self.answers = list(ips_or_exc)
        self.calls = 0

    def __call__(self, host, *args, **kwargs):
        self.calls += 1
        first = self.answers[0]
        if isinstance(first, Exception):
            raise first
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in self.answers]


def _client(plugin_name: str):
    """PluginHTTPClient wired to a MockTransport; records every request that is DIALED."""
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True})

    c = PluginHTTPClient(plugin_name=plugin_name)
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    _OPEN_CLIENTS.append(c)
    return c, sent


# ── (a) split-horizon rebinding: one public + one private A record ────────────────
async def test_rebind_multi_record_rejected(pinned_plugin, monkeypatch):
    dns = _ScriptedDNS(PUBLIC_IP, "127.0.0.5")  # second answer is loopback
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    client, sent = _client(pinned_plugin)

    with pytest.raises(PluginEgressError) as excinfo:  # supertype: existing callers keep working
        await client.get("https://rebind.example/x")
    assert isinstance(excinfo.value, PluginSSRFError)  # …and the documented new subtype
    assert "127.0.0.5" in str(excinfo.value)
    assert sent == []  # fail-closed BEFORE any dial attempt


# ── (b) clean public resolution still succeeds end-to-end (even under strict) ────
async def test_clean_public_resolution_passes_end_to_end(monkeypatch):
    dns = _ScriptedDNS("203.0.113.99")
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "1")
    client, sent = _client("weather")  # RESTRICTED manifest; wttr.in is allowlisted

    resp = await client.get("https://wttr.in/Bucharest?format=j1")

    assert resp.status_code == 200
    assert len(sent) == 1
    assert dns.calls >= 1  # pinning actually resolved the host


# ── (c) resolver failure blocks the request (fail closed) ─────────────────────────
async def test_resolver_failure_blocks_fail_closed(pinned_plugin, monkeypatch):
    def broken(host, *args, **kwargs):
        raise socket.gaierror(11001, "getaddrinfo failed")

    monkeypatch.setattr(socket, "getaddrinfo", broken)
    client, sent = _client(pinned_plugin)

    with pytest.raises(PluginSSRFError, match="DNS resolution failed"):
        await client.get("https://unreachable.invalid/x")
    assert sent == []


# ── cloud-metadata literal is rejected even though link-local looks 'local' ───────
async def test_metadata_literal_blocked_even_though_link_local(pinned_plugin, monkeypatch):
    dns = _ScriptedDNS(PUBLIC_IP)
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    client, sent = _client(pinned_plugin)

    with pytest.raises(PluginSSRFError, match="169.254.169.254"):
        await client.get("http://169.254.169.254/latest/meta-data/")
    assert dns.calls == 0  # rejected without needing DNS at all
    assert sent == []


# ── local-first preserved: LAN/RFC1918 literals bypass pinning (manifest governs) ─
async def test_lan_literal_skips_dns_pinning(pinned_plugin, monkeypatch):
    dns = _ScriptedDNS(PUBLIC_IP)
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    client, sent = _client(pinned_plugin)

    resp = await client.get("http://192.168.1.50:8080/x")

    assert resp.status_code == 200
    assert dns.calls == 0  # no resolution leak for LAN-shaped targets


# ── compatibility lock: unmanifested ad-hoc clients keep the legacy no-op guard ───
def test_unmanifested_client_keeps_legacy_guard(monkeypatch):
    dns = _ScriptedDNS(PUBLIC_IP)
    monkeypatch.setattr(socket, "getaddrinfo", dns)

    hc.PluginHTTPClient(plugin_name="bare_probe_xyz")._guard(
        "GET", f"https://{PUBLIC_IP}/x"
    )

    assert dns.calls == 0  # mirrors the kernel-wave/egress probe contracts
