"""Tests for hybrid LLM router: tokenizer, backend selection, agent policies."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.tokenizer import estimate_tokens, estimate_messages
from core.llm.hybrid_router import (
    HybridRouter, POLICY_LOCAL, POLICY_CLOUD, POLICY_AUTO,
    LOCAL_ONLY_AGENTS, CLOUD_ONLY_AGENTS, LOCAL_MAX_TOKENS,
)
from core.llm.base import LLMBackend


class FakeBackend(LLMBackend):
    async def generate(self, *a, **kw):
        return "fake"


# ── Tokenizer ──────────────────────────────────────────────────────────

def test_estimate_tokens_empty():
    assert estimate_tokens("") == 1


def test_estimate_tokens_short():
    count = estimate_tokens("hello world")
    assert count >= 1


def test_estimate_tokens_long():
    count = estimate_tokens("word " * 1000)
    assert count > 0


def test_estimate_tokens_different_inputs():
    short = estimate_tokens("test")
    medium = estimate_tokens("hello world this is a test" * 10)
    long_text = estimate_tokens("word " * 5000)
    assert short < medium
    assert medium < long_text


def test_estimate_messages_empty():
    assert estimate_messages([]) == 0


def test_estimate_messages_single():
    count = estimate_messages([{"role": "user", "content": "hello"}])
    assert count > 0


def test_estimate_messages_multiple():
    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    single = estimate_messages(msgs[:1])
    both = estimate_messages(msgs)
    assert both > single


# ── HybridRouter init ─────────────────────────────────────────────────

def test_hybrid_router_init():
    router = HybridRouter(gemini_api_key="")
    assert router.gemini_api_key == ""
    assert not router._local_available
    assert not router._cloud_available


def test_hybrid_router_init_with_key():
    router = HybridRouter(gemini_api_key="test-key")
    assert router.gemini_api_key == "test-key"


# ── Agent policies ────────────────────────────────────────────────────

def test_get_agent_policy_local():
    router = HybridRouter()
    for aid in LOCAL_ONLY_AGENTS:
        assert router.get_agent_policy(aid) == POLICY_LOCAL


def test_get_agent_policy_cloud():
    router = HybridRouter()
    for aid in CLOUD_ONLY_AGENTS:
        assert router.get_agent_policy(aid) == POLICY_CLOUD


def test_get_agent_policy_auto():
    router = HybridRouter()
    assert router.get_agent_policy("jarvis") == POLICY_AUTO
    assert router.get_agent_policy("unknown-agent") == POLICY_AUTO


# ── No backends available ─────────────────────────────────────────────

def test_name_no_backends():
    router = HybridRouter()
    assert router.name == "none"


def test_backend_raises_when_none():
    router = HybridRouter()
    with pytest.raises(RuntimeError):
        _ = router.backend


def test_select_backend_raises_when_none():
    router = HybridRouter()
    with pytest.raises(RuntimeError):
        router.select_backend("jarvis", "hello")


def test_select_backend_policy_local_no_local():
    router = HybridRouter()
    with pytest.raises(RuntimeError):
        router.select_backend("frigga", "hello")


def test_select_backend_policy_cloud_no_cloud():
    router = HybridRouter()
    with pytest.raises(RuntimeError):
        router.select_backend("vision", "hello")


# ── Only local available ──────────────────────────────────────────────

def test_select_backend_local_only_short_prompt(monkeypatch):
    router = HybridRouter()
    router._local_available = True
    router._backend = FakeBackend()
    router._backend_name = "lm-studio"
    backend, route = router.select_backend("jarvis", "short prompt")
    assert route == "local"


def test_select_backend_local_only_long_prompt_truncated(monkeypatch):
    router = HybridRouter()
    router._local_available = True
    router._backend = FakeBackend()
    router._backend_name = "lm-studio"
    long_prompt = "word " * (LOCAL_MAX_TOKENS * 4)
    backend, route = router.select_backend("jarvis", long_prompt)
    assert route == "local-fallback"


def test_select_backend_local_only_policy_local(monkeypatch):
    router = HybridRouter()
    router._local_available = True
    router._backend = FakeBackend()
    backend, route = router.select_backend("frigga", "hello")
    assert route == "local"


def test_select_backend_local_only_policy_cloud_fallback(monkeypatch):
    router = HybridRouter()
    router._local_available = True
    router._backend = FakeBackend()
    backend, route = router.select_backend("vision", "hello")
    assert route == "local-fallback"


# ── Only cloud available ──────────────────────────────────────────────

def test_select_backend_cloud_only_short_prompt(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    backend, route = router.select_backend("jarvis", "short")
    assert route == "cloud-flash"


def test_select_backend_cloud_only_long_prompt(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    long_prompt = "word " * (LOCAL_MAX_TOKENS * 4)
    backend, route = router.select_backend("jarvis", long_prompt)
    assert route == "cloud-flash"


def test_select_backend_cloud_only_policy_cloud(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    backend, route = router.select_backend("vision", "hello")
    assert route == "cloud"


def test_select_backend_cloud_only_policy_local_fallback(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    backend, route = router.select_backend("frigga", "hello")
    assert route == "cloud-fallback"


# ── Both backends available ───────────────────────────────────────────

def test_select_backend_both_short_prompt_uses_local(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._local_available = True
    router._backend = FakeBackend()
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    backend, route = router.select_backend("jarvis", "short")
    assert route == "local"


def test_select_backend_both_long_prompt_uses_cloud(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._local_available = True
    router._backend = FakeBackend()
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    long_prompt = "word " * (LOCAL_MAX_TOKENS * 4)
    backend, route = router.select_backend("jarvis", long_prompt)
    assert route == "cloud-flash"


# ── Route name ────────────────────────────────────────────────────────

def test_get_route_name(monkeypatch):
    router = HybridRouter()
    router._local_available = True
    router._backend = FakeBackend()
    assert router.get_route_name("jarvis", "hello") in ("local",)


def test_name_with_backends(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._backend_name = "lm-studio"
    router._local_available = True
    router._cloud_available = True
    assert "lm-studio" in router.name
    assert "gemini" in router.name


# ── Gemini backend unit tests (no network) ────────────────────────────

from core.llm.gemini import GeminiBackend


def test_gemini_build_url_generate():
    gb = GeminiBackend(api_key="test")
    url = gb._build_url(streaming=False)
    assert "generateContent" in url
    assert "key=test" in url


def test_gemini_build_url_stream():
    gb = GeminiBackend(api_key="test")
    url = gb._build_url(streaming=True)
    assert "streamGenerateContent" in url


def test_gemini_build_payload_with_system():
    gb = GeminiBackend(api_key="test")
    payload = gb._build_payload("hello", system="be helpful")
    assert "systemInstruction" in payload
    assert payload["systemInstruction"]["parts"][0]["text"] == "be helpful"


def test_gemini_build_payload_without_system():
    gb = GeminiBackend(api_key="test")
    payload = gb._build_payload("hello")
    assert "systemInstruction" not in payload


def test_gemini_build_payload_params():
    gb = GeminiBackend(api_key="test")
    payload = gb._build_payload("hello", max_tokens=2048, temperature=0.5)
    cfg = payload["generationConfig"]
    assert cfg["maxOutputTokens"] == 2048
    assert cfg["temperature"] == 0.5


def test_gemini_extract_text_normal():
    gb = GeminiBackend(api_key="test")
    data = {
        "candidates": [{
            "content": {"parts": [{"text": "Hello there"}]}
        }]
    }
    assert gb._extract_text(data) == "Hello there"


def test_gemini_extract_text_multiple_parts():
    gb = GeminiBackend(api_key="test")
    data = {
        "candidates": [{
            "content": {"parts": [{"text": "Hello"}, {"text": " world"}]}
        }]
    }
    assert gb._extract_text(data) == "Hello world"


def test_gemini_extract_text_no_candidates():
    gb = GeminiBackend(api_key="test")
    assert gb._extract_text({}) == ""


def test_gemini_extract_text_empty_candidates():
    gb = GeminiBackend(api_key="test")
    assert gb._extract_text({"candidates": []}) == ""


@pytest.mark.asyncio
async def test_gemini_generate_network_error(monkeypatch):
    async def mock_post(*a, **kw):
        raise Exception("connection refused")
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
    gb = GeminiBackend(api_key="test")
    result = await gb.generate("gemini-2.5-flash", "hello")
    assert "Gemini error" in result


@pytest.mark.asyncio
async def test_gemini_generate_stream_network_error(monkeypatch):
    class MockACM:
        async def __aenter__(self):
            raise Exception("stream failed")
        async def __aexit__(self, *a):
            pass
    monkeypatch.setattr("httpx.AsyncClient.stream", lambda *a, **kw: MockACM())
    gb = GeminiBackend(api_key="test")
    result = await gb.generate_stream("gemini-2.5-flash", "hello")
    assert "Gemini stream error" in result


# ── CloudLLMPlugin Gemini support ─────────────────────────────────────

from core.plugins.cloud_llm import CloudLLMPlugin


@pytest.mark.asyncio
async def test_cloud_llm_gemini_unavailable():
    plugin = CloudLLMPlugin()
    result = await plugin.generate("hello", agent_id="jarvis")
    assert "unavailable" in result


@pytest.mark.asyncio
async def test_cloud_llm_gemini_denied():
    plugin = CloudLLMPlugin(gemini_key="test")
    result = await plugin.generate("hello", agent_id="unknown")
    assert "denied" in result


@pytest.mark.asyncio
async def test_cloud_llm_gemini_network_error(monkeypatch):
    async def mock_post(*a, **kw):
        raise Exception("api error")
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
    plugin = CloudLLMPlugin(gemini_key="test")
    result = await plugin._call_gemini("hello", "", "gemini-2.5-flash", 1024)
    assert "Gemini error" in result


def test_cloud_llm_available_with_gemini():
    plugin = CloudLLMPlugin(gemini_key="test")
    assert plugin.available
