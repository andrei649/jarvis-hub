"""Signed hook parsing and built-in construction; physical sends use selected-owner tests."""
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from agents.core.llm.backend_factory import BackendUnavailable, construct_backend
from agents.core.llm.providers import ProviderProfile, ProviderRegistry
from agents.core.llm.providers.admitted_profiles import (
    AdmittedProviderProfile,
    prepare_admitted_profile,
)


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
    admitted = profile(runtime)
    assert not runtime.calls
    prepared = await prepare_admitted_profile(
        admitted, model='test-model', messages=[{'role': 'user', 'content': 'hello'}])
    assert len(runtime.calls) == 1 and runtime.send_checks == 0
    assert prepared.get_max_tokens('test-model') == 7
    assert prepared.build_extra_body(session_id=None, model='test-model',
                                     reasoning_config=None) == {'plugin_marker': 'applied'}
    worker = json.dumps(runtime.calls)
    assert 'synthetic-host-key' not in worker and 'synthetic.invalid' not in worker
    assert runtime.calls[0][1]['package_hash'] == 'a' * 64
    assert runtime.calls[0][1]['home'] == 'synthetic-home'


@pytest.mark.asyncio
@pytest.mark.parametrize('mutate', [
    lambda r: r['extra_body'].update(model='stolen'),
    lambda r: r['prepared_messages'][0].update(role='developer'),
    lambda r: r.update(reasoning_vocabulary=['low', 'high']),
    lambda r: r.update(max_tokens=True),
])
async def test_untrusted_worker_cannot_change_owned_wire_or_reasoning(mutate):
    runtime = Runtime(mutate=mutate)
    with pytest.raises(ValueError):
        await prepare_admitted_profile(
            profile(runtime), model='test-model',
            messages=[{'role': 'user', 'content': 'hello'}])


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


def test_no_auth_admitted_profile_requires_owner_selection_despite_ambient_secret(monkeypatch):
    monkeypatch.setenv('SYNTHETIC_UNRELATED_SECRET', 'unrelated-host-secret')
    native = ProviderProfile(id='synthetic-addon', display_name='Synthetic',
                             backend_kind='openai-compatible', auth_type='none',
                             auth_env='SYNTHETIC_UNRELATED_SECRET',
                             default_base_url='https://synthetic.invalid/v1',
                             capabilities=frozenset({'chat', 'cloud'}))
    record = SimpleNamespace(profile=native, package_hash='a' * 64, home='synthetic-home')
    admitted = AdmittedProviderProfile.from_record(record, Runtime())
    with pytest.raises(BackendUnavailable, match='owner selected capability'):
        construct_backend('synthetic-addon', registry=ProviderRegistry((admitted,)))
    status = admitted.status(environ={'SYNTHETIC_UNRELATED_SECRET': 'unrelated-host-secret'})
    assert status['configured'] is True  # no credential is required
    assert status['selection_required'] is True and status['routable'] is False


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
