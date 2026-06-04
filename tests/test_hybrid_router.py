"""Tests for hybrid LLM router: tokenizer, backend selection, agent policies."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.tokenizer import estimate_tokens, estimate_messages
from core.llm.hybrid_router import (
    HybridRouter, POLICY_LOCAL, POLICY_CLOUD, POLICY_CLAUDE, POLICY_AUTO,
    LOCAL_ONLY_AGENTS, CLOUD_ONLY_AGENTS, CLAUDE_AGENTS, LOCAL_MAX_TOKENS,
)
from core.llm.base import LLMBackend


class FakeBackend(LLMBackend):
    async def generate(self, *a, **kw):
        return "fake"


# ── Tokenizer ──────────────────────────────────────────────────────────

def test_estimate_tokens_empty():
    # "" → 0 tokens with a real tokenizer (tiktoken), 1 with the char fallback (len//4 + 1)
    assert estimate_tokens("") in (0, 1)


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


def test_get_agent_policy_claude():
    router = HybridRouter()
    for aid in CLAUDE_AGENTS:
        assert router.get_agent_policy(aid) == POLICY_CLAUDE


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
    backend, model, route = router.select_backend("jarvis", "short prompt")
    assert route == "local"


def test_select_backend_local_only_long_prompt_truncated(monkeypatch):
    router = HybridRouter()
    router._local_available = True
    router._backend = FakeBackend()
    router._backend_name = "lm-studio"
    long_prompt = "word " * (LOCAL_MAX_TOKENS * 4)
    backend, model, route = router.select_backend("jarvis", long_prompt)
    assert route == "local-fallback"


def test_select_backend_local_only_policy_local(monkeypatch):
    router = HybridRouter()
    router._local_available = True
    router._backend = FakeBackend()
    backend, model, route = router.select_backend("frigga", "hello")
    # frigga is a deep-think agent — routes to local-deep slot
    assert route == "local-deep"


def test_select_backend_local_only_policy_cloud_fallback(monkeypatch):
    router = HybridRouter()
    router._local_available = True
    router._backend = FakeBackend()
    backend, model, route = router.select_backend("vision", "hello")
    assert route == "local-fallback"


# ── Only cloud available ──────────────────────────────────────────────

def test_select_backend_cloud_only_short_prompt(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    backend, model, route = router.select_backend("jarvis", "short")
    assert route == "cloud-flash"


def test_select_backend_cloud_only_long_prompt(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    long_prompt = "word " * (LOCAL_MAX_TOKENS * 4)
    backend, model, route = router.select_backend("jarvis", long_prompt)
    assert route == "cloud-flash"


def test_select_backend_cloud_only_policy_cloud(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    backend, model, route = router.select_backend("athena", "hello")
    assert route == "cloud"


def test_select_backend_cloud_only_policy_local_fallback(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    backend, model, route = router.select_backend("frigga", "hello")
    assert route == "cloud-fallback"


# ── Both backends available ───────────────────────────────────────────

def test_select_backend_both_short_prompt_uses_local(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._local_available = True
    router._backend = FakeBackend()
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    backend, model, route = router.select_backend("jarvis", "short")
    assert route == "local"


def test_select_backend_both_long_prompt_uses_cloud(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._local_available = True
    router._backend = FakeBackend()
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    long_prompt = "word " * (LOCAL_MAX_TOKENS * 4)
    backend, model, route = router.select_backend("jarvis", long_prompt)
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


# ── Gemini caching integration ────────────────────────────────────────

def test_gemini_build_payload_with_cache():
    gb = GeminiBackend(api_key="test")
    gb._use_cache = "cachedContents/abc123"
    payload = gb._build_payload("hello", system="be helpful")
    assert "cachedContent" in payload
    assert payload["cachedContent"] == "cachedContents/abc123"
    assert "systemInstruction" not in payload


def test_gemini_build_payload_without_cache():
    gb = GeminiBackend(api_key="test")
    payload = gb._build_payload("hello", system="be helpful")
    assert "cachedContent" not in payload
    assert "systemInstruction" in payload


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


@pytest.mark.asyncio
async def test_gemini_generate_stream_http_error(monkeypatch):
    """S4: stream should handle HTTP errors without crashing."""
    class MockResponse:
        status_code = 403
        async def aiter_lines(self):
            yield 'data: {"error": "forbidden"}'
            if False: yield
        def raise_for_status(self):
            raise Exception("HTTP 403 Forbidden")

    def mock_stream(*a, **kw):
        class MockACM:
            async def __aenter__(self):
                return MockResponse()
            async def __aexit__(self, *a):
                pass
            async def aclose(self):
                pass
        return MockACM()

    monkeypatch.setattr("httpx.AsyncClient.stream", mock_stream)
    gb = GeminiBackend(api_key="test")
    result = await gb.generate_stream("gemini-2.5-flash", "hello")
    assert "error" in result.lower() or "gemini stream error" in result.lower()


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
    result = await plugin.generate("hello", "", agent_id="jarvis")
    assert "Cloud LLM error" in result


def test_cloud_llm_available_with_gemini():
    plugin = CloudLLMPlugin(gemini_key="test")
    assert plugin.available


# ── S0.1 Model Tiering: Claude API for heavy agents ────────────────────

def test_claude_init():
    router = HybridRouter(anthropic_api_key="sk-ant-test")
    assert router.anthropic_api_key == "sk-ant-test"
    assert not router._claude_available


def test_claude_available_after_detect(monkeypatch):
    router = HybridRouter(anthropic_api_key="sk-ant-test")
    router._local_available = True
    router._backend = FakeBackend()
    router._backend_name = "lm-studio"
    router._claude_available = True
    router._claude_backend = FakeBackend()
    assert router._claude_available


def test_claude_agent_policy():
    router = HybridRouter()
    assert router.get_agent_policy("vision") == POLICY_CLAUDE
    assert router.get_agent_policy("steve") == POLICY_CLAUDE


def test_claude_select_backend_for_vision(monkeypatch):
    router = HybridRouter(anthropic_api_key="sk-ant-test")
    router._local_available = True
    router._backend = FakeBackend()
    router._backend_name = "lm-studio"
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    router._claude_available = True
    router._claude_backend = FakeBackend()
    backend, model, route = router.select_backend("vision", "research task")
    assert route == "claude"
    assert model == "claude-sonnet-4-20250514"


def test_claude_select_backend_for_steve(monkeypatch):
    router = HybridRouter(anthropic_api_key="sk-ant-test")
    router._local_available = True
    router._backend = FakeBackend()
    router._claude_available = True
    router._claude_backend = FakeBackend()
    backend, model, route = router.select_backend("steve", "system check")
    assert route == "claude"


def test_claude_unavailable_falls_back_to_cloud(monkeypatch):
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    router._claude_available = False
    backend, model, route = router.select_backend("vision", "research")
    assert route == "cloud-fallback"
    assert model == "gemini-2.5-flash"


def test_claude_unavailable_falls_back_to_local(monkeypatch):
    router = HybridRouter()
    router._local_available = True
    router._backend = FakeBackend()
    router._backend_name = "lm-studio"
    router._claude_available = False
    router._cloud_available = False
    backend, model, route = router.select_backend("steve", "system check")
    assert route == "local-fallback"


def test_get_model_claude_agent():
    router = HybridRouter(anthropic_api_key="sk-ant-test")
    router._claude_available = True
    router._local_available = True
    assert router.get_model("vision") == "claude-sonnet-4-20250514"
    assert router.get_model("steve") == "claude-sonnet-4-20250514"


def test_get_model_light_agent():
    router = HybridRouter()
    router._local_available = True
    assert router.get_model("jarvis") == "qwen3:7b"
    assert router.get_model("friday") == "qwen3:7b"


def test_get_model_claude_unavailable():
    router = HybridRouter()
    router._claude_available = False
    router._local_available = True
    assert router.get_model("vision") == "qwen3:7b"


def test_name_includes_claude():
    router = HybridRouter(anthropic_api_key="sk-ant-test")
    router._backend_name = "lm-studio"
    router._local_available = True
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    router._claude_available = True
    router._claude_backend = FakeBackend()
    assert "lm-studio" in router.name
    assert "claude" in router.name
    assert "gemini" in router.name


# ── Anthropic backend unit tests (no network) ──────────────────────────

from core.llm.anthropic import ClaudeBackend


def test_claude_backend_headers():
    cb = ClaudeBackend(api_key="sk-ant-test")
    headers = cb._headers()
    assert headers["x-api-key"] == "sk-ant-test"
    assert "anthropic-version" in headers


def test_claude_backend_build_messages():
    cb = ClaudeBackend(api_key="sk-ant-test")
    msgs = cb._build_messages("hello", system="be helpful")
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hello"


@pytest.mark.asyncio
async def test_claude_generate_network_error(monkeypatch):
    async def mock_post(*a, **kw):
        raise Exception("connection refused")
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
    cb = ClaudeBackend(api_key="sk-ant-test")
    result = await cb.generate("claude-sonnet-4-20250514", "hello")
    assert "Claude API error" in result


@pytest.mark.asyncio
async def test_claude_generate_stream_network_error(monkeypatch):
    class MockACM:
        async def __aenter__(self):
            raise Exception("stream failed")
        async def __aexit__(self, *a):
            pass
    monkeypatch.setattr("httpx.AsyncClient.stream", lambda *a, **kw: MockACM())
    cb = ClaudeBackend(api_key="sk-ant-test")
    result = await cb.generate_stream("claude-sonnet-4-20250514", "hello")
    assert "Claude API stream error" in result
