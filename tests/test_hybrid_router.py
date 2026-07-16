"""Tests for hybrid LLM router: tokenizer, backend selection, agent policies."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.tokenizer import estimate_tokens, estimate_messages
from core.llm.hybrid_router import (
    DEFAULT_DEEP_MODEL,
    HybridRouter,
    LocalBackendUnavailableError,
    POLICY_LOCAL,
    POLICY_CLOUD,
    POLICY_CLAUDE,
    POLICY_AUTO,
    LOCAL_ONLY_AGENTS,
    CLOUD_ONLY_AGENTS,
    CLAUDE_AGENTS,
    LOCAL_MAX_TOKENS,
    FLASH_MAX_TOKENS,
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


@pytest.mark.asyncio
async def test_local_backend_aclose_closes_pool():
    """BUG-7: local backends close their httpx pool via aclose()."""
    from core.llm.base import LMStudioBackend, OllamaBackend

    b = LMStudioBackend()
    await b.aclose()
    assert b.client.is_closed
    o = OllamaBackend()
    await o.aclose()
    assert o.client.is_closed


@pytest.mark.asyncio
async def test_router_aclose_closes_active_backend():
    """BUG-7: LLMRouter.aclose() closes the active backend's client pool."""
    from core.llm.router import LLMRouter
    from core.llm.base import LMStudioBackend

    r = LLMRouter()
    r._backend = LMStudioBackend()
    client = r._backend.client
    await r.aclose()
    assert client.is_closed and r._backend is None


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
    with pytest.raises(LocalBackendUnavailableError):
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
    # O26-P0.5 (F5): the deep slot needs EVIDENCE the model is actually served —
    # a deep-think agent on a box without it falls through to normal routing.
    router._served_models = {DEFAULT_DEEP_MODEL}
    backend, model, route = router.select_backend("frigga", "hello")
    # frigga is a deep-think agent — routes to local-deep slot (model present)
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


def test_select_backend_strict_local_never_cloud(monkeypatch):
    """NON-NEGOTIABLE (MOONSHOT §5.1): strict-local agents fail closed — even with a
    cloud backend ready, frigga must never be routed off the machine."""
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    with pytest.raises(LocalBackendUnavailableError, match="strict-local"):
        router.select_backend("frigga", "hello")


def test_registry_llm_policy_is_honored(monkeypatch):
    """agents.yaml is the canonical registry — its llm_policy must drive routing
    (argus is registered `claude` but is absent from the in-code CLAUDE_AGENTS set)."""
    router = HybridRouter(anthropic_api_key="test")
    assert router.get_agent_policy("argus") == "claude"
    router._claude_available = True
    router._claude_backend = FakeBackend()
    backend, model, route = router.select_backend("argus", "hello")
    assert route == "claude"


def test_registry_cannot_override_local_only(monkeypatch):
    """The LOCAL_ONLY security floor is code-enforced: a (mis)edited registry entry
    can never pull a strict-local agent to the cloud."""
    import agents.core.llm.hybrid_router as hr

    monkeypatch.setattr(hr, "_registry_policies", lambda: {"frigga": "cloud"})
    router = HybridRouter()
    assert router.get_agent_policy("frigga") == "local"


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
    from core.llm.auth_rotation import AuthLease
    from core.llm.gemini_context import GeminiRequestBinding

    gb = GeminiBackend(api_key="test")
    binding = GeminiRequestBinding(
        lease=AuthLease(profile_id="gemini-test", api_key="test"),
        cache_name="cachedContents/abc123",
    )
    with gb.request_scope(binding):
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
from core.llm.provider_errors import GEMINI_DEGRADED_REPLY


def test_gemini_build_url_generate():
    gb = GeminiBackend(api_key="test")
    url = gb._build_url("gemini-2.5-flash", streaming=False)
    assert "generateContent" in url
    assert "?key=" not in url


def test_gemini_build_url_stream():
    gb = GeminiBackend(api_key="test")
    url = gb._build_url("gemini-2.5-flash", streaming=True)
    assert "streamGenerateContent" in url
    assert url.endswith("?alt=sse")
    assert "?key=" not in url


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
    data = {"candidates": [{"content": {"parts": [{"text": "Hello there"}]}}]}
    assert gb._extract_text(data) == "Hello there"


def test_gemini_extract_text_multiple_parts():
    gb = GeminiBackend(api_key="test")
    data = {"candidates": [{"content": {"parts": [{"text": "Hello"}, {"text": " world"}]}}]}
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
    assert result == GEMINI_DEGRADED_REPLY


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
    assert result == GEMINI_DEGRADED_REPLY


@pytest.mark.asyncio
async def test_gemini_generate_stream_http_error(monkeypatch):
    """S4: stream should handle HTTP errors without crashing."""

    class MockResponse:
        status_code = 403

        async def aiter_lines(self):
            yield 'data: {"error": "forbidden"}'
            if False:
                yield

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
    assert result == GEMINI_DEGRADED_REPLY


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
    assert result == GEMINI_DEGRADED_REPLY


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


# ── Strict-local Howard + the llm.cloud_fallback knob (2026-06-10 audit) ──────


def test_howard_strict_local_never_cloud():
    """Howard (the digital twin) is LOCAL_ONLY — with both local backends down and
    cloud ready, routing must fail closed, never spill the archive to Gemini."""
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    with pytest.raises(LocalBackendUnavailableError, match="strict-local"):
        router.select_backend("howard", "hello")


def test_cloud_fallback_never_keeps_oversize_local():
    """/admin llm.cloud_fallback=never: auto agents must not spill to cloud even
    when the prompt outgrows the local window — degrade locally instead."""
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    router._local_available = True
    router._backend = FakeBackend()
    router.set_cloud_fallback_mode("never")
    long_prompt = "word " * (LOCAL_MAX_TOKENS * 4)
    backend, model, route = router.select_backend("jarvis", long_prompt)
    assert route == "local-fallback"


def test_cloud_fallback_never_without_local_raises():
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    router.set_cloud_fallback_mode("never")
    with pytest.raises(RuntimeError):
        router.select_backend("jarvis", "hello")


def test_cloud_fallback_always_prefers_cloud():
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    router._local_available = True
    router._backend = FakeBackend()
    router.set_cloud_fallback_mode("always")
    backend, model, route = router.select_backend("jarvis", "short prompt")
    assert route == "cloud-flash"


def test_cloud_fallback_on_demand_is_default_and_unchanged():
    router = HybridRouter(gemini_api_key="test")
    router._cloud_available = True
    router._gemini_backend = FakeBackend()
    router._local_available = True
    router._backend = FakeBackend()
    assert router._cloud_fallback_mode == "on-demand"
    backend, model, route = router.select_backend("jarvis", "short prompt")
    assert route == "local"


def test_cloud_fallback_mode_validates_input():
    router = HybridRouter()
    router.set_cloud_fallback_mode("bogus")
    assert router._cloud_fallback_mode == "on-demand"
    router.set_cloud_fallback_mode("NEVER ")
    assert router._cloud_fallback_mode == "never"


# ── Configurable routing thresholds (/admin: hybrid_local_max / hybrid_flash_max)


def test_routing_thresholds_default_to_constants():
    router = HybridRouter()
    assert router._local_max == LOCAL_MAX_TOKENS
    assert router._flash_max == FLASH_MAX_TOKENS


def test_set_local_max_positive():
    router = HybridRouter()
    router.set_local_max(200000)
    assert router._local_max == 200000


def test_set_local_max_zero_means_unlimited():
    router = HybridRouter()
    router.set_local_max(0)
    assert router._local_max == sys.maxsize
    router.set_flash_max(-5)
    assert router._flash_max == sys.maxsize


def test_set_local_max_bad_value_falls_back_to_default():
    router = HybridRouter()
    router.set_local_max("not-a-number")
    assert router._local_max == LOCAL_MAX_TOKENS
    router.set_flash_max(None)
    assert router._flash_max == FLASH_MAX_TOKENS


def _mock_net(monkeypatch, router, *, respond, model="loaded-model"):
    """Mock the network probes used by detect(): respond(url)->bool."""
    checked = []

    async def fake_check(url):
        checked.append(url)
        return respond(url)

    async def fake_fetch(url, kind):
        return model

    monkeypatch.setattr(router, "_check", fake_check)
    monkeypatch.setattr(router, "_fetch_loaded_model", fake_fetch)
    return checked


@pytest.mark.asyncio
async def test_detect_honors_custom_lm_studio_url(monkeypatch):
    monkeypatch.delenv("JARVIS_LM_STUDIO_URL", raising=False)
    monkeypatch.delenv("JARVIS_OLLAMA_URL", raising=False)
    router = HybridRouter(gemini_api_key="")
    monkeypatch.setattr(
        router,
        "_admin_setting",
        lambda key, default: {"lm_studio_url": "http://box:9999", "backend_type": "auto"}.get(
            key, default
        ),
    )
    checked = _mock_net(monkeypatch, router, respond=lambda u: "box:9999" in u)
    await router.detect()
    assert router.lm_studio_url == "http://box:9999"
    assert router._backend_name == "lm-studio"
    assert router._backend.base_url == "http://box:9999"
    assert any("box:9999/v1/models" in u for u in checked)


@pytest.mark.asyncio
async def test_detect_env_urls_override_admin_settings_and_howard(monkeypatch):
    """Process env can isolate every local backend, including Howard's Ollama."""
    monkeypatch.setenv("JARVIS_LM_STUDIO_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("JARVIS_OLLAMA_URL", "http://127.0.0.1:10")
    router = HybridRouter(gemini_api_key="")
    monkeypatch.setattr(
        router,
        "_admin_setting",
        lambda key, default: {
            "lm_studio_url": "http://live-admin:1234",
            "ollama_url": "http://live-admin:11434",
            "backend_type": "auto",
        }.get(key, default),
    )
    checked = _mock_net(monkeypatch, router, respond=lambda _url: False)

    await router.detect()

    assert router.lm_studio_url == "http://127.0.0.1:9"
    assert router.ollama_url == "http://127.0.0.1:10"
    assert router._ollama_backend.base_url == "http://127.0.0.1:10"
    assert "http://127.0.0.1:9/v1/models" in checked
    assert checked.count("http://127.0.0.1:10/api/tags") == 2
    assert not any("live-admin" in url for url in checked)


@pytest.mark.asyncio
async def test_backend_type_pins_ollama_skips_lm_studio(monkeypatch):
    router = HybridRouter(gemini_api_key="")
    monkeypatch.setattr(
        router, "_admin_setting", lambda key, default: {"backend_type": "ollama"}.get(key, default)
    )
    checked = _mock_net(monkeypatch, router, respond=lambda u: True)  # everything would respond
    await router.detect()
    assert router._backend_name == "ollama"
    # LM Studio must not even be probed for backend selection when pinned to ollama
    assert not any("/v1/models" in u for u in checked)


@pytest.mark.asyncio
async def test_gemini_model_wired_into_backend_and_route(monkeypatch):
    router = HybridRouter(gemini_api_key="test-key")
    monkeypatch.setattr(
        router,
        "_admin_setting",
        lambda key, default: {"gemini_model": "gemini-2.5-pro"}.get(key, default),
    )
    _mock_net(monkeypatch, router, respond=lambda u: False)  # no local backend
    await router.detect()
    assert router._gemini_model == "gemini-2.5-pro"
    assert router._gemini_backend is not None
    assert router._gemini_backend.model == "gemini-2.5-pro"
    # a cloud-policy agent's route carries the configured model
    _, model, route = router.select_backend("athena", "hi")
    assert route == "cloud" and model == "gemini-2.5-pro"


def test_unlimited_local_keeps_long_prompt_on_local():
    # With the local threshold lifted (0 = unlimited), a prompt that would
    # normally exceed LOCAL_MAX_TOKENS stays on the clean local path instead of
    # degrading to the truncated "local-fallback" tier.
    router = HybridRouter()
    router._local_available = True
    router._backend = FakeBackend()
    router._backend_name = "lm-studio"
    long_prompt = "word " * (LOCAL_MAX_TOKENS * 4)
    # default threshold → fallback tier
    _, _, route_default = router.select_backend("jarvis", long_prompt)
    assert route_default == "local-fallback"
    # unlimited → clean local tier
    router.set_local_max(0)
    _, _, route_unlimited = router.select_backend("jarvis", long_prompt)
    assert route_unlimited in ("local", "local-deep")
