"""SEC-B4: all plugin HTTP egress dials a resolver-validated pinned target."""

import sys
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.acquisition.research import WebSearchResearchBackend
from agents.core.http_client import PinnedTarget, PluginEgressError, PluginHTTPClient
from agents.core.security.ssrf import resolve_and_validate


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        return self.handler(request)


def _safe_resolver(host, *, mode):
    assert mode == "public"
    return (["93.184.216.34"], None)


async def test_request_and_research_stream_use_distinct_sni_pinned_pools_after_generic_client_exists():
    transports = []

    def make_transport(_target):
        transport = RecordingTransport(lambda request: httpx.Response(200, content=b"body", request=request))
        transports.append(transport)
        return transport

    client = PluginHTTPClient(
        "pinning-test",
        resolver=_safe_resolver,
        transport_factory=make_transport,
    )
    client._get_client()  # A pre-existing generic client must never receive egress I/O.

    response = await client.get("https://one.example.test/path")
    assert response.status_code == 200

    class Plugin:
        tavily_api_key = ""
        searxng_url = "https://search.example.test"
        _client = client

        async def search(self, *_args, **_kwargs):
            return []

    research = WebSearchResearchBackend(plugin=Plugin())
    stream = await research.fetch("https://two.example.test/page", "93.184.216.34")
    assert b"".join([chunk async for chunk in stream.aiter_bytes()]) == b"body"
    await stream.aclose()

    assert len(client._pinned_clients) == 2
    assert {target.sni_hostname for target in client._pinned_targets} == {
        "one.example.test",
        "two.example.test",
    }
    assert all(target.pool_key[1] == "93.184.216.34" for target in client._pinned_targets)
    for transport, target in zip(transports, client._pinned_targets, strict=True):
        [request] = transport.requests
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == target.host_header
        assert request.extensions["sni_hostname"] == target.sni_hostname
    assert client._client is not None
    await client.close()


async def test_redirect_rechecks_and_repins_each_hop_and_strips_sensitive_post_headers():
    seen = []

    def resolver(host, *, mode):
        assert mode == "public"
        return ({"origin.example.test": ["93.184.216.34"], "next.example.test": ["93.184.216.35"]}[host], None)

    def make_transport(_target):
        def handler(request):
            seen.append(request)
            if len(seen) == 1:
                return httpx.Response(302, headers={"location": "https://next.example.test/final"}, request=request)
            return httpx.Response(200, request=request)

        return RecordingTransport(handler)

    client = PluginHTTPClient("redirect-test", resolver=resolver, transport_factory=make_transport)
    response = await client.post(
        "https://origin.example.test/start",
        content=b"private",
        headers={
            "Authorization": "Bearer token",
            "Cookie": "session=secret",
            "Proxy-Authorization": "Basic secret",
            "Content-Type": "application/octet-stream",
            "Expect": "100-continue",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert [request.url.host for request in seen] == ["93.184.216.34", "93.184.216.35"]
    assert seen[1].method == "GET"
    assert all(header not in seen[1].headers for header in (
        "authorization", "cookie", "proxy-authorization", "content-length", "content-type", "transfer-encoding", "expect",
    ))
    assert len(client._pinned_clients) == 2
    await client.close()


async def test_unsafe_second_dns_answer_makes_zero_requests_even_when_strict_egress_is_downgraded(monkeypatch):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")
    calls = []

    def changed_answer(_host, *, mode):
        assert mode == "public"
        return ([], "URL resolves to unsafe address: 127.0.0.1")

    client = PluginHTTPClient(
        "unsafe-answer-test",
        resolver=changed_answer,
        transport_factory=lambda _target: RecordingTransport(lambda request: calls.append(request)),
    )
    client._get_client()

    with pytest.raises(PluginEgressError, match="unsafe"):
        await client.get("https://safe-looking.example.test/")

    assert calls == []
    assert client._pinned_clients == {}
    await client.close()


async def test_unsafe_address_returned_by_an_injected_resolver_makes_zero_requests():
    calls = []
    client = PluginHTTPClient(
        "unsafe-injected-answer-test",
        resolver=lambda _host, *, mode: (["127.0.0.1"], None),
        transport_factory=lambda _target: RecordingTransport(lambda request: calls.append(request)),
    )

    with pytest.raises(PluginEgressError, match="unsafe"):
        await client.get("https://safe-looking.example.test/")

    assert calls == []
    assert client._pinned_clients == {}
    await client.close()


async def test_mixed_addresses_returned_by_an_injected_resolver_make_zero_requests():
    calls = []
    client = PluginHTTPClient(
        "mixed-injected-answer-test",
        resolver=lambda _host, *, mode: (["93.184.216.34", "127.0.0.1"], None),
        transport_factory=lambda _target: RecordingTransport(lambda request: calls.append(request)),
    )

    with pytest.raises(PluginEgressError, match="unsafe"):
        await client.get("https://safe-looking.example.test/")

    assert calls == []
    assert client._pinned_clients == {}
    await client.close()


@pytest.mark.parametrize(
    "address",
    [
        "0.0.0.0",
        "10.0.0.1",
        "100.64.0.1",
        "127.0.0.1",
        "169.254.1.1",
        "192.0.2.1",
        "198.18.0.1",
        "224.0.0.1",
        "255.255.255.255",
        "::",
        "::1",
        "fc00::1",
        "fe80::1",
        "ff00::1",
        "::ffff:127.0.0.1",
    ],
)
def test_public_mode_rejects_non_global_and_ipv4_mapped_special_addresses(address):
    ips, error = resolve_and_validate(address, mode="public")
    assert ips == []
    assert error is not None


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "10.0.0.1", "172.16.0.1", "192.168.0.1"])
def test_lan_mode_accepts_only_loopback_and_rfc1918(address):
    assert resolve_and_validate(address, mode="lan") == ([address], None)


@pytest.mark.parametrize("address", ["8.8.8.8", "169.254.1.1", "100.64.0.1", "224.0.0.1"])
def test_lan_mode_rejects_non_lan_and_special_addresses(address):
    ips, error = resolve_and_validate(address, mode="lan")
    assert ips == []
    assert error is not None


def test_pinned_target_keeps_logical_identity_separate_from_dial_identity():
    target = PinnedTarget(
        logical_url="https://example.test/a",
        dial_url="https://93.184.216.34/a",
        host_header="example.test",
        sni_hostname="example.test",
        pool_key=("https", "93.184.216.34", 443, "example.test"),
    )
    assert target.logical_url != target.dial_url
