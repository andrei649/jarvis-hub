"""H368 — refuse to speak the wrong protocol to a lookalike (or a vendor) host.

Some hosts accept exactly one wire protocol: ``api.anthropic.com`` speaks Anthropic
Messages, the official OpenAI host family (``api.openai.com`` and its regional
``<region>.api.openai.com``) speaks OpenAI's own wire, and
``bedrock-runtime.<region>.amazonaws.com`` speaks Bedrock Converse. The host decides,
never the configuration: a backend whose protocol differs is refused *before* the
request — and the credential in its auth header — leaves the machine. Matching is on
the parsed hostname, never a substring, so ``api.openai.com.attacker.test`` and
``proxy.test/api.openai.com/v1`` are not the vendor.

All traffic goes through ``httpx.MockTransport``; no socket is opened.
"""

from __future__ import annotations

import httpx
import pytest

from agents.core.llm.egress import llm_async_client
from agents.core.llm.host_protocol import (
    ANTHROPIC_MESSAGES,
    BEDROCK_CONVERSE,
    OPENAI,
    HostProtocolRefused,
    backend_protocol,
    host_mandated_protocol,
    protocol_refusal,
)
from agents.core.observability.egress_monitor import EGRESS_MONITOR


@pytest.fixture(autouse=True)
def _clean_monitor():
    EGRESS_MONITOR.reset()
    yield
    EGRESS_MONITOR.reset()


# ── the table ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("url, protocol", [
    ("https://api.anthropic.com/v1", ANTHROPIC_MESSAGES),
    ("https://API.Anthropic.com./v1/messages", ANTHROPIC_MESSAGES),
    ("https://api.anthropic.com:443/v1", ANTHROPIC_MESSAGES),
    ("https://api.openai.com/v1", OPENAI),
    ("https://eu.api.openai.com/v1", OPENAI),
    ("https://us.api.openai.com/v1", OPENAI),
    ("api.openai.com", OPENAI),
    (httpx.URL("https://api.openai.com/v1/chat/completions"), OPENAI),
    ("https://bedrock-runtime.us-east-1.amazonaws.com", BEDROCK_CONVERSE),
    ("https://bedrock-runtime-fips.us-gov-west-1.amazonaws.com/model/x/converse", BEDROCK_CONVERSE),
    # IDNA dot equivalents: httpx (the wire) folds them to "." — so must the table.
    ("https://api．anthropic．com/v1", ANTHROPIC_MESSAGES),     # FULLWIDTH FULL STOP
    ("https://api。anthropic。com/v1", ANTHROPIC_MESSAGES),     # IDEOGRAPHIC FULL STOP
    ("https://api｡openai｡com/v1", OPENAI),                   # HALFWIDTH IDEOGRAPHIC FULL STOP
    ("api．openai．com", OPENAI),                              # …bare, no scheme
    ("https://api.anthropic.com。/v1", ANTHROPIC_MESSAGES),        # trailing ideographic dot
])
def test_vendor_hosts_mandate_their_protocol(url, protocol):
    assert host_mandated_protocol(url) == protocol


@pytest.mark.parametrize("url", [
    "https://api.openai.com.attacker.test/v1",        # lookalike suffix
    "https://proxy.test/api.openai.com/v1",           # vendor host in the path
    "proxy.test/api.openai.com/v1",                   # …with no scheme
    "https://api.openai.com@attacker.test/v1",        # vendor host as userinfo
    "https://attacker.test/?next=https://api.anthropic.com",
    "https://api.anthropic.com.evil.test/v1",
    "https://xapi.anthropic.com/v1",
    "https://notapi.openai.com/v1",
    "https://a.b.api.openai.com/v1",
    "https://bedrock-runtime.us-east-1.amazonaws.com.attacker.test",
    "https://bedrock-runtime.attacker.test",
    "https://openrouter.ai/api/v1",
    "http://localhost:1234",
    "",
    None,
])
def test_lookalikes_and_other_hosts_mandate_nothing(url):
    assert host_mandated_protocol(url) is None


def test_backends_declare_the_protocol_they_speak():
    assert backend_protocol("anthropic") == ANTHROPIC_MESSAGES
    for name in ("openrouter", "openai-compatible", "openai-responses", "xai", "lm-studio", "vlm"):
        assert backend_protocol(name) == OPENAI
    assert backend_protocol("gemini") not in (None, OPENAI, ANTHROPIC_MESSAGES)
    assert backend_protocol("no-such-backend") is None


def test_refusal_names_host_and_both_protocols():
    reason = protocol_refusal("openrouter", "https://api.anthropic.com/v1")
    assert "api.anthropic.com" in reason and ANTHROPIC_MESSAGES in reason and OPENAI in reason
    assert protocol_refusal("anthropic", "https://api.anthropic.com/v1") == ""
    assert protocol_refusal("openai-compatible", "https://api.openai.com/v1") == ""
    # An undeclared backend cannot prove it speaks the mandated protocol.
    assert protocol_refusal("no-such-backend", "https://api.openai.com/v1")
    # A host with no mandate constrains nobody.
    assert protocol_refusal("anthropic", "https://api.openai.com.attacker.test") == ""


# ── the wire: next to the egress ledger ─────────────────────────────────────


def _client(backend, seen, **kwargs):
    """The real egress client for *backend* over an in-memory transport that records."""

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    return llm_async_client(backend, transport=httpx.MockTransport(handler), **kwargs)


@pytest.mark.asyncio
async def test_openai_protocol_aimed_at_anthropic_sends_nothing():
    """The credential never leaves: the transport sees zero requests."""
    from agents.core.llm.openrouter import OpenRouterBackend
    from agents.core.llm.providers import DEFAULT_REGISTRY

    seen = []
    base_url = "https://api.anthropic.com/v1"
    backend = OpenRouterBackend(api_key="sk-secret", base_url=base_url,
                                profile=DEFAULT_REGISTRY.get("openai-compatible"),
                                client=_client("openrouter", seen, base_url=base_url))
    out = await backend.generate("m", "hi")
    turn = await backend.generate_tool_turn("m", [{"role": "user", "content": "hi"}], [])
    await backend.aclose()
    assert seen == []
    assert out == "[OpenRouter error]" and turn.content == "[OpenRouter error]"
    row = EGRESS_MONITOR.snapshot()["plugins"]["llm:openrouter"]
    assert row["blocked"] == 2 and row["allowed"] == 0 and row["external"] == 0
    recent = EGRESS_MONITOR.snapshot()["recent"][0]
    assert recent["allowed"] is False and ANTHROPIC_MESSAGES in recent["reason"]


@pytest.mark.asyncio
async def test_the_client_raises_before_dispatch():
    seen = []
    client = _client("openrouter", seen, base_url="https://api.anthropic.com/v1")
    with pytest.raises(HostProtocolRefused):
        await client.post("/chat/completions", json={}, headers={"Authorization": "Bearer sk-x"})
    await client.aclose()
    assert seen == []


@pytest.mark.asyncio
async def test_matching_protocol_and_unmandated_hosts_still_flow():
    seen = []
    ok = _client("openrouter", seen, base_url="https://api.openai.com/v1")
    await ok.post("/chat/completions", json={})
    lookalike = _client("anthropic", seen, base_url="https://api.openai.com.attacker.test")
    await lookalike.post("/v1/messages", json={})
    await ok.aclose()
    await lookalike.aclose()
    assert [r.url.host for r in seen] == ["api.openai.com", "api.openai.com.attacker.test"]
    assert EGRESS_MONITOR.snapshot()["plugins"]["llm:openrouter"]["allowed"] == 1


@pytest.mark.asyncio
async def test_a_redirect_onto_a_vendor_host_is_checked_per_hop():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://api.openai.com/v1/chat/completions"})

    client = llm_async_client("ollama", base_url="http://localhost:11434", follow_redirects=True,
                              transport=httpx.MockTransport(handler))
    with pytest.raises(HostProtocolRefused):
        await client.post("/api/chat", json={})
    await client.aclose()
    assert [r.url.host for r in seen] == ["localhost"]


# ── the router refuses the mismatched backend at detect() ───────────────────


async def _detect(monkeypatch, env):
    from unittest.mock import AsyncMock

    from agents.core.llm.hybrid_router import HybridRouter
    from agents.core.llm.router import LLMRouter

    env = dict(env)
    settings = {"compatible_provider": env.pop("_provider"), "compatible_model": "m"}
    for name in ("OPENAI_BASE_URL", "OPENROUTER_BASE_URL", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(LLMRouter, "detect", AsyncMock())
    monkeypatch.setattr(HybridRouter, "_check", AsyncMock(return_value=False))
    monkeypatch.setattr(HybridRouter, "_admin_setting",
                        staticmethod(lambda k, d: settings.get(k, d) or d))
    router = HybridRouter()
    await router.detect()
    return router


@pytest.mark.asyncio
async def test_router_refuses_an_openai_compatible_base_url_on_the_anthropic_host(monkeypatch, caplog):
    router = await _detect(monkeypatch, {"_provider": "openai-compatible", "OPENAI_API_KEY": "k",
                                         "OPENAI_BASE_URL": "https://api.anthropic.com/v1"})
    assert router._compatible_backend is None
    assert "api.anthropic.com" in caplog.text and ANTHROPIC_MESSAGES in caplog.text
    await router.aclose()


@pytest.mark.asyncio
async def test_router_refuses_openrouter_pointed_at_bedrock(monkeypatch):
    router = await _detect(monkeypatch, {
        "_provider": "openrouter", "OPENROUTER_API_KEY": "k",
        "OPENROUTER_BASE_URL": "https://bedrock-runtime.eu-west-1.amazonaws.com"})
    assert router._compatible_backend is None
    await router.aclose()


@pytest.mark.asyncio
async def test_router_keeps_the_default_and_custom_endpoints(monkeypatch):
    router = await _detect(monkeypatch, {"_provider": "openai-compatible", "OPENAI_API_KEY": "k"})
    assert router._compatible_backend is not None          # api.openai.com speaks OpenAI
    await router.aclose()
    router = await _detect(monkeypatch, {"_provider": "openai-compatible", "OPENAI_API_KEY": "k",
                                         "OPENAI_BASE_URL": "https://proxy.test/api.anthropic.com/v1"})
    assert router._compatible_backend is not None          # a custom endpoint, not the vendor
    await router.aclose()


@pytest.mark.parametrize("dot", ["．", "。"])
@pytest.mark.asyncio
async def test_router_refuses_an_idna_dot_spelling_of_the_anthropic_host(monkeypatch, caplog, dot):
    """detect() parses the host the way the wire does, so the refusal happens at build."""
    router = await _detect(monkeypatch, {
        "_provider": "openai-compatible", "OPENAI_API_KEY": "k",
        "OPENAI_BASE_URL": f"https://api{dot}anthropic{dot}com/v1"})
    assert router._compatible_backend is None
    assert "api.anthropic.com" in caplog.text
    await router.aclose()


# ── a refusal degrades the way a failed request does ────────────────────────


def test_a_refusal_is_not_a_transport_failure():
    """No `except OSError` connection handler may read a refusal as 'backend down'."""
    refusal = HostProtocolRefused("api.openai.com accepts only openai")
    assert not isinstance(refusal, (OSError, httpx.HTTPError))


@pytest.mark.asyncio
async def test_ollama_context_probe_on_a_mandated_host_degrades_to_unknown(caplog):
    """The compaction / route-planning probe gets None, as it does for any failed probe."""
    from agents.core.llm.base import OllamaBackend

    seen = []
    backend = OllamaBackend(base_url="https://api.openai.com")
    await backend.client.aclose()
    backend.client = _client("ollama", seen, base_url="https://api.openai.com")
    assert await backend.resolve_context_window("local-model") is None
    await backend.aclose()
    assert seen == []
    assert "api.openai.com" in caplog.text
    assert EGRESS_MONITOR.snapshot()["plugins"]["llm:ollama"]["blocked"] == 1
