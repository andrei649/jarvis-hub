"""H492: address classification and actual outgoing redirect headers."""

import asyncio
import threading

import httpx
import pytest

from agents.core.http_client import PluginEgressError, PluginHTTPClient, RequiredEgressHTTPClient
from agents.core.security import website_policy
from agents.core.security.ssrf import is_private_ip, resolve_and_validate


@pytest.mark.parametrize("address", [
    "100.64.1.2", "198.18.1.2",
    "::ffff:100.64.1.2", "::ffff:198.18.1.2",
    "::ffff:0:100.64.1.2", "::ffff:0:198.18.1.2",
    "::ffff:0:169.254.169.254",
])
def test_special_ipv4_and_its_wrappers_are_explicitly_private(address):
    assert is_private_ip(address)
    assert resolve_and_validate(address, mode="public")[0] == []
    assert resolve_and_validate(address, mode="lan")[0] == []


def test_translated_loopback_keeps_explicit_lan_opt_in():
    address = "::ffff:0:127.0.0.1"
    assert is_private_ip(address)
    assert resolve_and_validate(address, mode="public")[0] == []
    assert resolve_and_validate(address, mode="lan") == (["127.0.0.1"], None)


@pytest.mark.parametrize("address,expected", [
    ("8.8.8.8", "8.8.8.8"),
    ("::ffff:8.8.8.8", "8.8.8.8"),
    ("::ffff:0:8.8.8.8", "8.8.8.8"),
])
def test_routable_ipv4_wrappers_retain_public_access(address, expected):
    assert not is_private_ip(address)
    assert resolve_and_validate(address, mode="public") == ([expected], None)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("status", [302, 307, 308])
async def test_cross_origin_redirect_sanitizes_actual_wire_after_httpx_auth_and_cookies(stream, status):
    requests = []

    def resolver(host, *, mode):
        assert mode == "public"
        return ([{"origin.example.test": "93.184.216.34",
                  "next.example.test": "93.184.216.35"}[host]], None)

    def transport_factory(_target):
        def respond(request):
            requests.append(request)
            if request.url.path == "/prime":
                return httpx.Response(200, headers={"set-cookie": "pooled=secret; Path=/"})
            if request.url.path == "/start":
                return httpx.Response(
                    status, headers={"location": "https://next.example.test/final?target=ok"})
            return httpx.Response(200, content=b"done")

        return httpx.MockTransport(respond)

    client = PluginHTTPClient(
        "h492-final-wire", resolver=resolver, transport_factory=transport_factory)
    try:
        assert (await client.get("https://next.example.test/prime")).status_code == 200
        assert (await client.get("https://next.example.test/verify")).status_code == 200
        assert "pooled=secret" in requests[-1].headers["cookie"]
        kwargs = {
            "follow_redirects": True,
            "headers": {"X-Api-Key": "header-secret", "Accept": "text/plain",
                        "User-Agent": "h492-test"},
            "auth": httpx.BasicAuth("owner", "auth-secret"),
            "cookies": {"caller": "cookie-secret"},
            "params": {"caller_token": "query-secret"},
        }
        if stream:
            async with client.stream("POST", "https://origin.example.test/start",
                                     content=b"private-body", **kwargs) as response:
                assert await response.aread() == b"done"
        else:
            response = await client.post("https://origin.example.test/start",
                                         content=b"private-body", **kwargs)
            assert response.content == b"done"
        first, final = requests[-2:]
        assert first.headers["x-api-key"] == "header-secret"
        assert first.headers["authorization"] == "Basic b3duZXI6YXV0aC1zZWNyZXQ="
        assert "caller_token=query-secret" in str(first.url)
        assert final.headers["host"] == "next.example.test"
        assert final.headers["accept"] == "text/plain"
        assert final.headers["user-agent"] == "h492-test"
        assert set(final.headers) <= {"host", "accept", "user-agent"}
        assert "caller_token" not in str(final.url)
        assert "target=ok" in str(final.url)
        assert final.content == b""
        assert final.method == ("GET" if status == 302 else "POST")
    finally:
        await client.close()


@pytest.mark.parametrize("stream", [False, True])
async def test_same_origin_redirect_keeps_caller_auth_cookies_and_query(stream):
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, content=b"done")

    client = PluginHTTPClient(
        "h492-same-origin",
        resolver=lambda _host, *, mode: (["93.184.216.34"], None),
        transport_factory=lambda _target: httpx.MockTransport(respond),
    )
    try:
        kwargs = {"follow_redirects": True, "headers": {"X-Api-Key": "same-secret"},
                  "auth": httpx.BasicAuth("owner", "same-secret"),
                  "cookies": {"owner": "same-cookie"}, "params": {"owner_key": "same-query"}}
        if stream:
            async with client.stream("GET", "https://origin.example.test/start", **kwargs) as response:
                assert await response.aread() == b"done"
        else:
            assert (await client.get("https://origin.example.test/start", **kwargs)).content == b"done"
        assert len(requests) == 2
        assert requests[1].headers["x-api-key"] == "same-secret"
        assert requests[1].headers["authorization"].startswith("Basic ")
        assert "owner=same-cookie" in requests[1].headers["cookie"]
        assert "owner_key=same-query" in str(requests[1].url)
    finally:
        await client.close()


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("blocked_hop", ["initial", "redirect"])
async def test_owner_website_refusal_precedes_dns_transport_and_kernel(
    monkeypatch, stream, blocked_hop,
):
    monkeypatch.setenv("JARVIS_STRICT_EGRESS", "0")
    policy_calls, dns_calls, kernel_calls, requests = [], [], [], []

    def policy(url):
        policy_calls.append(url)
        return "website_blocked" if (
            (blocked_hop == "initial" and "origin.example.test" in url)
            or (blocked_hop == "redirect" and "next.example.test" in url)
        ) else None

    def resolver(host, *, mode):
        dns_calls.append(host)
        return ["93.184.216.34"], None

    def respond(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://next.example.test/final"})

    monkeypatch.setattr(website_policy, "website_refusal", policy)
    client = RequiredEgressHTTPClient(
        "h492-owner-refusal", authorize_egress=lambda *args: kernel_calls.append(args),
        resolver=resolver, transport_factory=lambda _target: httpx.MockTransport(respond),
    )
    try:
        with pytest.raises(PluginEgressError, match="website_blocked"):
            if stream:
                async with client.stream("GET", "https://origin.example.test/start",
                                         follow_redirects=True):
                    pytest.fail("blocked website yielded a response")
            else:
                await client.get("https://origin.example.test/start", follow_redirects=True)
        if blocked_hop == "initial":
            assert dns_calls == kernel_calls == requests == []
            assert len(policy_calls) == 1
        else:
            assert dns_calls == ["origin.example.test"]
            assert len(kernel_calls) == len(requests) == 1
            assert len(policy_calls) == 2
    finally:
        await client.close()


@pytest.mark.parametrize("failure", ["returned", "raised", "invalid"])
async def test_unavailable_website_policy_fails_closed_before_dns(monkeypatch, failure):
    def policy(_url):
        if failure == "raised":
            raise RuntimeError("private policy failure")
        if failure == "invalid":
            return ["unexpected unhashable verdict"]
        return "website_policy_unavailable"

    monkeypatch.setattr(website_policy, "website_refusal", policy)
    dns_calls, requests = [], []
    client = PluginHTTPClient(
        "h492-unavailable-policy",
        resolver=lambda host, *, mode: (dns_calls.append(host) or ["93.184.216.34"], None),
        transport_factory=lambda _target: httpx.MockTransport(
            lambda request: (requests.append(request) or httpx.Response(200))),
    )
    try:
        with pytest.raises(PluginEgressError, match="website_policy_unavailable") as caught:
            await client.get("https://origin.example.test/start")
        assert "private policy failure" not in str(caught.value)
        assert dns_calls == requests == []
    finally:
        await client.close()


async def test_website_policy_file_read_keeps_async_loop_schedulable(monkeypatch):
    entered, heartbeat, release = threading.Event(), threading.Event(), threading.Event()
    observed = []
    resolver_calls = []

    def waiting_policy(_url):
        entered.set()
        assert release.wait(4), "policy fixture was not released"
        return None

    def observer():
        if not entered.wait(4):
            observed.append("policy_not_entered")
        else:
            observed.append(heartbeat.wait(2))
        release.set()

    def resolver(host, *, mode):
        assert release.is_set(), "DNS ran before the website decision"
        resolver_calls.append(host)
        return ["93.184.216.34"], None

    monkeypatch.setattr(website_policy, "website_refusal", waiting_policy)
    watcher = threading.Thread(target=observer, daemon=True)
    client = PluginHTTPClient(
        "h492-policy-loop", resolver=resolver,
        transport_factory=lambda _target: httpx.MockTransport(
            lambda _request: httpx.Response(200)),
    )
    watcher.start()
    request = asyncio.create_task(client.get("https://origin.example.test/start"))
    try:
        assert await asyncio.to_thread(entered.wait, 4)
        heartbeat.set()
        assert (await request).status_code == 200
        await asyncio.to_thread(watcher.join, 4)
        assert observed == [True]
        assert resolver_calls == ["origin.example.test"]
    finally:
        release.set()
        await asyncio.gather(request, return_exceptions=True)
        await asyncio.to_thread(watcher.join, 4)
        await client.close()
