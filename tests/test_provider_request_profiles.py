import json

import httpx
import pytest

from agents.core.llm.gemini import GeminiBackend
from agents.core.llm.openrouter import OpenRouterBackend
from agents.core.llm.providers import ProviderProfile
from agents.core.llm.request_context import session_scope


@pytest.mark.asyncio
async def test_cache_key_requires_explicit_profile_and_is_session_stable():
    bodies = []
    def handler(req):
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='https://example.invalid')
    profile = ProviderProfile('custom', 'Custom', 'openai-compatible', capabilities={'prompt-cache-key', 'reasoning-effort'})
    backend = OpenRouterBackend(client=client, profile=profile, reasoning_effort='ultra',
                                effort_declarations={'m': ['low', 'high'], 'flat': []})
    with session_scope('private-session-one'):
        await backend.generate('m', 'one')
        await backend.generate_tool_turn('m', [], [])
    with session_scope('two'):
        await backend.generate('flat', 'three')
    assert bodies[0]['prompt_cache_key'] == bodies[1]['prompt_cache_key']
    assert bodies[0]['prompt_cache_key'] != bodies[2]['prompt_cache_key']
    assert 'private-session' not in bodies[0]['prompt_cache_key']
    assert bodies[0]['reasoning_effort'] == 'high'
    assert 'reasoning_effort' not in bodies[2]
    backend = OpenRouterBackend(client=client)
    with session_scope('one'):
        await backend.generate('m', 'four')
    assert 'prompt_cache_key' not in bodies[-1]
    assert 'reasoning_effort' not in bodies[-1]
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_effort_is_normalized_on_actual_model_all_payloads():
    backend = GeminiBackend('test', model='gemini-3.1-pro', reasoning_effort='ultra')
    payload = backend._build_payload('hi')
    assert payload['generationConfig']['thinkingConfig'] == {'thinkingLevel': 'high'}
    payload = backend._build_tool_payload([], [], 1024, .7, model='unknown')
    assert 'thinkingConfig' not in payload['generationConfig']
    assert backend.profile.supported_reasoning_efforts('gemini-3.1-pro') == ('low', 'medium', 'high')
    await backend.close()


def test_cloud_override_preserves_local_only_and_model_pins(monkeypatch):
    from agents.core.llm.hybrid_router import HybridRouter
    router = HybridRouter()
    local, compatible = object(), object()
    router._compatible_backend = compatible
    router._compatible_model = 'chosen'
    monkeypatch.setattr(router, '_select_backend_inner', lambda agent, prompt: (local, 'm', 'local' if agent == 'frigga' else 'cloud'))
    checked = []
    monkeypatch.setattr(router, '_enforce_approved_models', lambda *args: checked.append(args))
    assert router.select_backend('frigga', '') == (local, 'm', 'local')
    assert router.select_backend('jarvis', '') == (compatible, 'chosen', 'cloud-compatible')
    assert checked[-1] == ('jarvis', 'chosen', 'cloud-compatible')


@pytest.mark.asyncio
async def test_gemini_25_budget_does_not_exceed_output_ceiling():
    backend = GeminiBackend('test', model='gemini-2.5-pro', reasoning_effort='high')
    payload = backend._build_payload('hi', max_tokens=1000)
    assert payload['generationConfig']['thinkingConfig'] == {'thinkingBudget': 999}
    payload = backend._build_payload('hi', max_tokens=100)
    assert 'thinkingConfig' not in payload['generationConfig']
    await backend.close()


@pytest.mark.asyncio
async def test_admin_selection_constructs_usable_compatible_route(monkeypatch):
    from unittest.mock import AsyncMock

    from agents.core.llm.hybrid_router import HybridRouter, LocalBackendUnavailableError
    from agents.core.llm.router import LLMRouter
    settings = {'compatible_provider': 'openai-compatible', 'compatible_model': 'm',
                'compatible_prompt_cache_key': True, 'compatible_reasoning_enabled': True,
                'compatible_effort_declarations': '{"m": ["low", "high"]}',
                'reasoning_effort': 'ultra'}
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.setattr(LLMRouter, 'detect', AsyncMock())
    monkeypatch.setattr(HybridRouter, '_check', AsyncMock(return_value=False))
    monkeypatch.setattr(HybridRouter, '_admin_setting', staticmethod(lambda k, d: settings.get(k, d)))
    router = HybridRouter()
    await router.detect()
    backend, model, route = router.select_backend('athena', '')
    assert model == 'm'
    assert route == 'cloud-compatible'
    assert backend.profile.supports_prompt_cache_key
    assert backend.profile.supported_reasoning_efforts('m') == ('low', 'high')
    assert router.backend is backend
    assert 'compatible' in router.name
    with pytest.raises(LocalBackendUnavailableError):
        router.select_backend('frigga', '')
    await router.aclose()
