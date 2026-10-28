"""Admission-to-native wire seam; provider HTTP is mocked, never live."""
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest

from agents.core.llm.backend_factory import BackendUnavailable, construct_backend
from agents.core.llm.egress import llm_async_client
from agents.core.llm.providers import ProviderProfile, ProviderRegistry
from agents.core.llm.providers.admitted_profiles import AdmittedProviderProfile


class Runtime:
    def __init__(self, *, mutate=None):
        self.calls = []
        self.mutate = mutate
        self.send_checks = 0

    async def assert_runnable(self, provider_id, **kwargs):
        self.send_checks += 1

    @asynccontextmanager
    async def dispatch_lease(self, provider_id, **kwargs):
        yield

    async def evaluate(self, provider_id, **kwargs):
        self.calls.append((provider_id, kwargs))
        result = {'prepared_messages': kwargs['messages'],
                  'extra_body': {'plugin_marker': 'applied'},
                  'api_kwargs': {'extra_body': {}, 'kwargs': {}},
                  'max_tokens': 7, 'reasoning_vocabulary': None}
        if self.mutate:
            self.mutate(result)
        return result


def profile(runtime, *, kind='openai-compatible', mode='chat_completions'):
    native = ProviderProfile(id='synthetic-addon', display_name='Synthetic',
                             backend_kind=kind, api_mode=mode, auth_type='bearer',
                             default_base_url='https://synthetic.invalid/v1',
                             capabilities=frozenset({'chat', 'cloud'}))
    record = SimpleNamespace(profile=native, package_hash='a' * 64, home='synthetic-home')
    return AdmittedProviderProfile.from_record(record, runtime)


@pytest.mark.asyncio
async def test_native_generation_awaits_hook_batch_and_keeps_credentials_on_host():
    runtime = Runtime()
    registry = ProviderRegistry((profile(runtime),))
    backend = construct_backend('synthetic-addon', registry=registry,
                                api_key='synthetic-host-key')
    assert not runtime.calls
    seen = []

    def response(request):
        seen.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}}]})

    await backend.client.aclose()
    backend.client = llm_async_client('synthetic-addon', transport=httpx.MockTransport(response),
                                      base_url='https://synthetic.invalid/v1')
    try:
        assert await backend.generate('test-model', 'hello') == 'answer'
        assert len(runtime.calls) == 1
        assert runtime.send_checks == 1
        sent = json.loads(seen[0].content)
        assert sent['plugin_marker'] == 'applied' and sent['max_tokens'] == 7
        assert seen[0].headers['Authorization'] == 'Bearer synthetic-host-key'
        worker = json.dumps(runtime.calls)
        assert 'synthetic-host-key' not in worker and 'synthetic.invalid' not in worker
        assert runtime.calls[0][1]['package_hash'] == 'a' * 64
        assert runtime.calls[0][1]['home'] == 'synthetic-home'
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('mutate', [
    lambda r: r['extra_body'].update(model='stolen'),
    lambda r: r['prepared_messages'][0].update(role='developer'),
    lambda r: r.update(reasoning_vocabulary=['low', 'high']),
    lambda r: r.update(max_tokens=True),
])
async def test_untrusted_worker_cannot_change_owned_wire_or_reasoning(mutate):
    runtime = Runtime(mutate=mutate)
    backend = construct_backend('synthetic-addon', registry=ProviderRegistry((profile(runtime),)),
                                api_key='synthetic-host-key')
    seen = []
    await backend.client.aclose()
    backend.client = llm_async_client('synthetic-addon',
                                      transport=httpx.MockTransport(lambda r: seen.append(r)),
                                      base_url='https://synthetic.invalid/v1')
    try:
        with pytest.raises(ValueError):
            await backend.generate('test-model', 'hello')
        assert seen == []
    finally:
        await backend.client.aclose()


def test_unwired_admitted_dialect_refuses_before_native_construction():
    with pytest.raises(BackendUnavailable):
        construct_backend('synthetic-addon',
                          registry=ProviderRegistry((profile(Runtime(), kind='gemini',
                                                            mode='gemini_generate_content'),)))


def test_synchronous_use_of_unprepared_admitted_hooks_refuses():
    with pytest.raises(ValueError):
        profile(Runtime()).prepare_messages([{'role': 'user', 'content': 'hello'}])


def test_admitted_profile_cannot_redirect_signed_native_destination():
    with pytest.raises(BackendUnavailable):
        construct_backend('synthetic-addon', registry=ProviderRegistry((profile(Runtime()),)),
                          base_url='https://other.invalid/v1')


@pytest.mark.parametrize('destination', [
    'http://synthetic.invalid/v1',
    'https://user@synthetic.invalid/v1',
    'https://synthetic.invalid/v1?key=unsafe',
])
def test_admitted_profile_requires_fixed_https_authority(destination):
    native = ProviderProfile(id='synthetic-addon', display_name='Synthetic',
                             backend_kind='openai-compatible',
                             default_base_url=destination,
                             capabilities=frozenset({'chat', 'cloud'}))
    record = SimpleNamespace(profile=native, package_hash='a' * 64, home='synthetic-home')
    with pytest.raises(BackendUnavailable):
        construct_backend('synthetic-addon', registry=ProviderRegistry((
            AdmittedProviderProfile.from_record(record, Runtime()),)))


def test_existing_positional_profile_fields_keep_their_order():
    profile = ProviderProfile('legacy', 'Legacy', 'openai-compatible', 'none',
                              None, None, None, frozenset({'chat'}), ('m',),
                              ('low',), None, 'unknown', '', ())
    assert profile.fallback_models == ('m',)
    assert profile.reasoning_efforts == ('low',)


def test_admitted_profile_cannot_select_ambient_host_secret(monkeypatch):
    monkeypatch.setenv('SYNTHETIC_UNRELATED_SECRET', 'unrelated-host-secret')
    native = ProviderProfile(id='synthetic-addon', display_name='Synthetic',
                             backend_kind='openai-compatible', auth_type='bearer',
                             auth_env='SYNTHETIC_UNRELATED_SECRET',
                             default_base_url='https://synthetic.invalid/v1',
                             capabilities=frozenset({'chat', 'cloud'}))
    record = SimpleNamespace(profile=native, package_hash='a' * 64, home='synthetic-home')
    admitted = AdmittedProviderProfile.from_record(record, Runtime())
    with pytest.raises(BackendUnavailable):
        construct_backend('synthetic-addon', registry=ProviderRegistry((admitted,)))
    assert admitted.status(environ={'SYNTHETIC_UNRELATED_SECRET': 'unrelated-host-secret'})['configured'] is False


@pytest.mark.asyncio
async def test_no_auth_admitted_profile_does_not_read_or_send_ambient_secret(monkeypatch):
    monkeypatch.setenv('SYNTHETIC_UNRELATED_SECRET', 'unrelated-host-secret')
    native = ProviderProfile(id='synthetic-addon', display_name='Synthetic',
                             backend_kind='openai-compatible', auth_type='none',
                             auth_env='SYNTHETIC_UNRELATED_SECRET',
                             default_base_url='https://synthetic.invalid/v1',
                             capabilities=frozenset({'chat', 'cloud'}))
    record = SimpleNamespace(profile=native, package_hash='a' * 64, home='synthetic-home')
    admitted = AdmittedProviderProfile.from_record(record, Runtime())
    backend = construct_backend('synthetic-addon', registry=ProviderRegistry((admitted,)))
    try:
        assert backend.api_key == ''
        assert admitted.status(environ={'SYNTHETIC_UNRELATED_SECRET': 'unrelated-host-secret'})['configured'] is True
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(('provider_id', 'backend_name'), [
    ('lm-studio', 'LMStudioBackend'),
    ('ollama', 'OllamaBackend'),
    ('gemini', 'GeminiBackend'),
    ('anthropic', 'ClaudeBackend'),
    ('openrouter', 'OpenRouterBackend'),
    ('deepinfra', 'DeepInfraBackend'),
    ('xai', 'XAIBackend'),
    ('openai-responses', 'ResponsesBackend'),
    ('openai-compatible', 'OpenRouterBackend'),
])
async def test_current_builtin_factory_keeps_native_backend(provider_id, backend_name):
    backend = construct_backend(provider_id, api_key='synthetic-key')
    try:
        assert type(backend).__name__ == backend_name
    finally:
        close = getattr(backend, 'aclose', None) or getattr(backend, 'close', None)
        if close is not None:
            await close()
