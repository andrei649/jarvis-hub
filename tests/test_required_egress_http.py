"""Mandatory scoped authorization retains the shared pinned transport boundary."""

import httpx
import pytest

from agents.core import http_client as hc


def _resolver(_host, *, mode):
    assert mode == "public"
    return ["93.184.216.34"], None


def _client(gate, seen, *, resolver=_resolver):
    def respond(request):
        seen.append(request)
        return httpx.Response(200, content=b"verified bytes", request=request)

    return hc.RequiredEgressHTTPClient(
        "required-egress-test",
        circuit_breaker=hc.CircuitBreaker(key="required-egress-test"),
        authorize_egress=gate,
        resolver=resolver,
        transport_factory=lambda target: httpx.MockTransport(respond),
    )


@pytest.mark.parametrize("flag", ["0", "1"])
async def test_explicit_authorization_required_independently_of_global_flag(monkeypatch, flag):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", flag)
    seen, decisions = [], []
    client = _client(lambda *args: decisions.append(args), seen)
    try:
        async with client.stream("GET", "https://upstream.example/skill") as response:
            assert await response.aread() == b"verified bytes"
        assert decisions == [("required-egress-test", "GET", "https://upstream.example/skill", "upstream.example")]
        assert len(seen) == 1
        assert seen[0].url.host == "93.184.216.34"
        assert seen[0].headers["host"] == "upstream.example"
        assert seen[0].extensions["sni_hostname"] == "upstream.example"
    finally:
        await client.close()


@pytest.mark.parametrize("result", [False, "", "denied", True, 0])
async def test_only_none_from_gate_permits_io(result):
    seen, ledger = [], []
    client = _client(lambda *_: result, seen)
    original = hc._record_egress
    try:
        hc._record_egress = lambda *args, **kw: ledger.append((args, kw))
        with pytest.raises(hc.PluginEgressError, match="required authorization"):
            await client.get("https://upstream.example/skill")
        assert seen == []
        assert len(ledger) == 1 and ledger[0][1]["allowed"] is False
    finally:
        hc._record_egress = original
        await client.close()


async def test_gate_exception_fails_closed_without_exposing_exception():
    def broken(*_):
        raise RuntimeError("private exception text")

    seen = []
    client = _client(broken, seen)
    try:
        with pytest.raises(hc.PluginEgressError) as caught:
            await client.get("https://upstream.example/skill")
        assert "private exception text" not in str(caught.value)
        assert seen == []
    finally:
        await client.close()


@pytest.mark.parametrize("gate", [None, False, "allow"])
def test_missing_or_noncallable_gate_refused_at_construction(gate):
    with pytest.raises(ValueError, match="callable"):
        _client(gate, [])


async def test_ssrf_refusal_precedes_gate_and_transport():
    seen, decisions = [], []
    client = _client(lambda *args: decisions.append(args), seen,
                     resolver=lambda *_args, **_kw: (["127.0.0.1"], None))
    try:
        with pytest.raises(hc.PluginEgressError):
            await client.get("https://upstream.example/skill")
        assert decisions == [] and seen == []
    finally:
        await client.close()


async def test_each_redirect_requires_a_fresh_decision():
    requests, decisions = [], []

    def gate(*args):
        decisions.append(args)
        return None if len(decisions) == 1 else "owner halted"

    def respond(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://next.example/skill"}, request=request)

    client = hc.RequiredEgressHTTPClient(
        "required-egress-redirect", authorize_egress=gate, resolver=_resolver,
        transport_factory=lambda target: httpx.MockTransport(respond),
    )
    try:
        with pytest.raises(hc.PluginEgressError, match="required authorization"):
            async with client.stream("GET", "https://upstream.example/skill", follow_redirects=True):
                pytest.fail("denied redirect must never yield a response")
        assert len(requests) == 1
        assert [row[3] for row in decisions] == ["upstream.example", "next.example"]
    finally:
        await client.close()
