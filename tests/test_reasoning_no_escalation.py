"""Known lower requests must never buy stronger/default provider reasoning."""
import httpx
import pytest

from agents.core.llm.reasoning_effort import ReasoningEffortRefused, clamp_vocabulary, resolve
from agents.core.llm.usage_context import text_usage_scope


def test_canonical_resolution_never_floors_upward():
    assert resolve('minimal', ('high', 'max')) == (None, 'below-minimum')
    assert clamp_vocabulary(('high', 'max'), 'minimal') == (None, 'below-minimum')
    assert clamp_vocabulary(('high', 'max'), 'none') == (None, 'below-minimum')


@pytest.mark.asyncio
@pytest.mark.parametrize('vendor', ['openrouter', 'compatible', 'gemini', 'anthropic'])
@pytest.mark.parametrize('method', ['generate', 'generate_stream', 'generate_tool_turn'])
@pytest.mark.parametrize('effort', ['minimal', 'none'])
async def test_actual_calls_refuse_before_http(vendor, method, effort):
    from agents.core.llm.anthropic import ClaudeBackend
    from agents.core.llm.gemini import GeminiBackend
    from agents.core.llm.openrouter import OpenRouterBackend
    from agents.core.llm.providers import ProviderProfile
    requests, callbacks, usage = [], [], []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='https://fixture.invalid')
    model = 'm'
    if vendor == 'gemini':
        backend = GeminiBackend('fixture', reasoning_effort=effort, effort_declarations={'m':['high']})
    elif vendor == 'anthropic':
        model = 'claude-fable-5-1'
        backend = ClaudeBackend('fixture', reasoning_effort=effort)
    else:
        profile = ProviderProfile(vendor, vendor, 'openai-compatible', capabilities={'reasoning-effort'})
        backend = OpenRouterBackend(client=client, profile=profile, reasoning_effort=effort,
                                    effort_declarations={'m':['high']})
    if backend.client is not client:
        await backend.client.aclose()
        backend.client = client
    kwargs = {'model':model, 'max_tokens':4096}
    if method == 'generate_tool_turn':
        kwargs.update(messages=[], tools=[])
    else:
        kwargs['prompt'] = 'hello'
        if method == 'generate_stream':
            kwargs['on_token'] = callbacks.append
    try:
        with text_usage_scope(usage.append), pytest.raises(ReasoningEffortRefused, match='reasoning effort'):
            await getattr(backend, method)(**kwargs)
        assert not requests and not callbacks and not usage
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['generate','generate_stream','generate_tool_turn'])
async def test_gemini_budget_cannot_fall_back_to_default(method):
    from agents.core.llm.gemini import GeminiBackend
    requests = []
    backend = GeminiBackend('fixture', reasoning_effort='low')
    await backend.client.aclose()
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: requests.append(req) or httpx.Response(200,json={})))
    kwargs = {'model':'gemini-2.5-flash', 'max_tokens':256}
    kwargs.update({'messages':[], 'tools':[]} if method=='generate_tool_turn' else {'prompt':'hello'})
    try:
        with pytest.raises(ValueError, match='reasoning effort'):
            await getattr(backend, method)(**kwargs)
        assert not requests
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['generate','generate_stream','generate_tool_turn'])
async def test_refusal_does_not_rotate_auth_or_invalidate_cache(method):
    from types import SimpleNamespace

    from agents.core.llm.gemini import GeminiBackend
    from tests.test_gemini_request_context import _binding
    backend = GeminiBackend('fixture', reasoning_effort='minimal', effort_declarations={'m':['high']})
    await backend.client.aclose()
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _:pytest.fail('local refusal dialed provider')))
    binding = _binding(cache_name='cachedContents/fixture', invalidate_cache=lambda *_:pytest.fail('cache invalidated'))
    backend._capture_binding = lambda: binding
    backend.auth_pool = SimpleNamespace(size=3)
    backend._rotate_after_failure = lambda *a, **k: pytest.fail('credential rotated')
    backend._report_success = lambda *_: pytest.fail('refusal counted as provider success')
    kwargs = {'model':'m', 'max_tokens':4096}
    kwargs.update({'messages':[], 'tools':[]} if method=='generate_tool_turn' else {'prompt':'hello'})
    try:
        with pytest.raises(ReasoningEffortRefused):
            await getattr(backend, method)(**kwargs)
    finally:
        await backend.client.aclose()


def test_disabled_mode_requires_a_supported_companion_without_payload_mutation():
    from agents.core.llm.reasoning_effort import WireCapability, plan
    with pytest.raises(ReasoningEffortRefused):
        plan(WireCapability(efforts=('max',), thinking='adaptive', thinking_default_on=True,
                            disable_max='high'), 'none')


def test_refused_anthropic_fit_does_not_partially_mutate_payload():
    from agents.core.llm.reasoning_effort import apply_anthropic
    payload = {'model':'claude-fable-5-1','temperature':0.5,'max_tokens':4096}
    before = dict(payload)
    with pytest.raises(ReasoningEffortRefused):
        apply_anthropic(payload, payload['model'], 'minimal')
    assert payload == before


@pytest.mark.parametrize('vocabulary,expected', [(None,(None,'undeclared')), ((),(None,'unsupported'))])
def test_unknown_and_explicit_unsupported_keep_tri_state(vocabulary, expected):
    assert clamp_vocabulary(vocabulary, 'minimal') == expected
    assert clamp_vocabulary(vocabulary, 'none') == expected


@pytest.mark.parametrize('requested,expected', [('high',('high','exact')),('ultra',('high','clamped'))])
def test_supported_or_weaker_mapping_is_unchanged(requested, expected):
    assert resolve(requested, ('low','high')) == expected
