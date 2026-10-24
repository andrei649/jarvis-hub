"""Auxiliary model calls are unattended even when spawned by an owner turn."""
import asyncio
from contextlib import suppress
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from agents.core import settings_db
from agents.core.action_origin import bind_action_origin, current_action_origin, reset_action_origin
from agents.core.commands import Principal
from agents.core.llm.egress import llm_async_client
from agents.core.llm.providers import get_profile
from agents.core.llm.router import LLMRouter
from agents.core.orchestrator import bind_turn_principal, current_principal, reset_turn_principal
from agents.core.turn_notices import open_turn_notices, reset_turn_notices


@pytest.fixture
def dh(tmp_path, monkeypatch):
    from agents.core.llm import data_handling

    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(data_handling, '_scope_key', lambda: b'auxiliary-test-scope-key')
    return data_handling


def route(*, loopback=False):
    backend = SimpleNamespace(profile=get_profile('lm-studio'), api_key='synthetic',
                              base_url='http://127.0.0.1:1234' if loopback else 'https://gateway.invalid')
    router = LLMRouter()
    router._backend = backend
    router._backend_name = 'lm-studio'
    router._local_model = 'synthetic-model'
    return router, backend


class Audit:
    def log(self, event):
        pass


def consent(dh, router, *, acknowledged=True):
    row = dh.posture(router)['providers'][0]
    return dh.acknowledge(router, row['provider'], acknowledged, row['scope'], Audit())


@pytest.mark.parametrize('role', ['session_title', 'query_rewrite', 'review', 'compression_summary'])
def test_inherited_owner_and_inbound_context_cannot_authorize_auxiliary_dispatch(dh, role):
    router, backend = route()
    owner = Principal(channel='web', admin=True)
    principal_token = bind_turn_principal(owner)
    origin_token = bind_action_origin('inbound')
    sent = []
    try:
        # The interactive boundary permits a warned call; the auxiliary boundary
        # must classify its own actual request as unattended instead.
        assert dh.authorize(router, backend, 'synthetic-model')['warning']
        with pytest.raises(dh.DataHandlingRefused, match='audited acknowledgment'), dh.auxiliary_request_scope(
                router, backend, 'synthetic-model', role=role):
            sent.append('generation')
        assert sent == []
        assert current_principal() is owner and current_action_origin() == 'inbound'
    finally:
        reset_action_origin(origin_token)
        reset_turn_principal(principal_token)


async def test_base_router_loopback_preflight_and_physical_requests_succeed(dh, monkeypatch):
    router, backend = route(loopback=True)
    checked = []
    original = dh.authorize

    def record(*args, **kwargs):
        checked.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(dh, 'authorize', record)
    sent = []
    client = llm_async_client('lm-studio', transport=httpx.MockTransport(
        lambda request: sent.append(request) or httpx.Response(200)))
    try:
        with dh.auxiliary_request_scope(router, backend, 'synthetic-model', role='review'):
            await client.post(backend.base_url + '/first')
            await client.post(backend.base_url + '/retry')
        assert len(sent) == 2 and len(checked) == 3
        assert not hasattr(router, 'check_data_handling')
        assert all(args[1] is backend and args[2] == 'synthetic-model' for args, _ in checked)
        assert all(kwargs['principal'] == Principal(channel='internal', admin=False)
                   and kwargs['origin'] == 'generated' for _, kwargs in checked)
    finally:
        await client.aclose()


@pytest.mark.parametrize('change', ['revoke', 'endpoint', 'credential', 'declaration'])
async def test_fresh_scope_changes_between_attempts_block_actual_retry(dh, change):
    router, backend = route()
    consent(dh, router)
    sent = []

    def transport(request):
        sent.append(request)
        if change == 'revoke':
            consent(dh, router, acknowledged=False)
        elif change == 'endpoint':
            backend.base_url = 'https://replacement.invalid'
        elif change == 'credential':
            backend.api_key = 'replacement-key'
        else:
            backend.profile = replace(backend.profile, data_policy='trains-on-inputs')
        return httpx.Response(503)

    client = llm_async_client('lm-studio', transport=httpx.MockTransport(transport))
    try:
        with pytest.raises(dh.DataHandlingRefused), dh.auxiliary_request_scope(
                router, backend, 'synthetic-model', role='query_rewrite'):
            await client.post(backend.base_url + '/first')
            await client.post(backend.base_url + '/retry')
        assert len(sent) == 1
    finally:
        await client.aclose()


async def test_swallowed_physical_refusal_is_rethrown_at_auxiliary_scope_exit(dh):
    router, backend = route()
    consent(dh, router)
    sent = []
    client = llm_async_client('lm-studio', transport=httpx.MockTransport(
        lambda request: sent.append(request) or httpx.Response(200)))
    try:
        with pytest.raises(dh.DataHandlingRefused), dh.auxiliary_request_scope(
                router, backend, 'synthetic-model', role='compression_summary'):
            consent(dh, router, acknowledged=False)
            with suppress(dh.DataHandlingRefused):
                await client.post(backend.base_url + '/hidden')
        assert sent == []
    finally:
        await client.aclose()


@pytest.mark.parametrize('streaming', [False, True])
async def test_copied_child_cannot_send_after_generation_scope_closes(dh, streaming):
    router, backend = route(loopback=True)
    release = asyncio.Event()
    sent = []
    client = llm_async_client('lm-studio', transport=httpx.MockTransport(
        lambda request: sent.append(request) or httpx.Response(200)))

    async def child():
        await release.wait()
        if streaming:
            async with client.stream('POST', backend.base_url + '/late'):
                pass
        else:
            await client.post(backend.base_url + '/late')

    try:
        with dh.auxiliary_request_scope(router, backend, 'synthetic-model', role='review'):
            task = asyncio.create_task(child())
        release.set()
        with pytest.raises(dh.DataHandlingRefused, match='scope is closed'):
            await task
        assert sent == []
    finally:
        await client.aclose()


def test_acknowledged_unknown_auxiliary_route_keeps_warning_visible(dh):
    router, backend = route()
    consent(dh, router)
    notices, token = open_turn_notices()
    try:
        with dh.auxiliary_request_scope(router, backend, 'synthetic-model', role='session_title'):
            pass
    finally:
        reset_turn_notices(token)
    assert len(notices) == 1 and 'unknown' in notices[0]['text']


def test_unknown_provider_never_uses_optional_router_bypass(dh):
    router = SimpleNamespace(check_data_handling=lambda *args: None)
    with pytest.raises(ValueError, match='provider is unknown'), dh.auxiliary_request_scope(
            router, object(), 'synthetic-model', role='review'):
        pytest.fail('unknown backend cannot dispatch')


# ── H414: run_oneshot — one stateless call on the same rail ───────────────────────
#
# Hermes' ``run_oneshot()`` is a public helper for an arbitrary side call that never
# touches history. Nerva's version is the same rail the fixed tasks use: the strict-local
# backend, the auxiliary data-handling scope, the job-pin exclusion and the model usage
# scope all come from ``prepare_local_auxiliary``; nothing here opens a second route.


@pytest.fixture
def oneshot(monkeypatch):
    from agents.core.llm import auxiliary_text

    monkeypatch.delenv('JARVIS_AUX_ONESHOT_MODEL', raising=False)
    monkeypatch.setattr(auxiliary_text, '_ONESHOT_USAGE', {})
    calls = []

    async def generate(**kwargs):
        calls.append(('generate', kwargs))
        return 'local answer'

    async def generate_stream(**kwargs):
        calls.append(('stream', kwargs))
        await kwargs['on_token']('local ')
        await kwargs['on_token']('answer')
        return 'local answer'

    backend = SimpleNamespace(profile=get_profile('lm-studio'), base_url='http://127.0.0.1:1234',
                              generate=generate, generate_stream=generate_stream)
    router = SimpleNamespace(local_backend=backend, active_model='active-local',
                             _backend=backend, _local_model='active-local')
    return SimpleNamespace(router=router, backend=backend, calls=calls, module=auxiliary_text)


async def test_run_oneshot_runs_on_the_local_rail_and_records_its_purpose(oneshot):
    from agents.core.llm.model_config import DEFAULT_LOCAL_MODEL

    answer = await oneshot.module.run_oneshot(
        oneshot.router, 'private prompt', system='side system', purpose='btw',
        max_tokens=64, temperature=0.1)
    assert answer == 'local answer'
    # Like the other side tasks (not the cosmetic title), a one-shot runs on the local
    # model already loaded for chat unless its own override names another.
    assert oneshot.calls == [('generate', {
        'model': 'active-local', 'system': 'side system', 'prompt': 'private prompt',
        'max_tokens': 64, 'temperature': 0.1,
    })]
    usage = oneshot.module.oneshot_usage()
    assert usage['btw']['calls'] == 1 and usage['btw']['answered'] == 1
    assert usage['btw']['prompt_chars'] == len('side system') + len('private prompt')
    assert usage['btw']['max_tokens'] == 64 and usage['btw']['model'] == 'active-local'
    # The ledger is a copy: a caller cannot edit the record it was shown.
    usage['btw']['calls'] = 99
    assert oneshot.module.oneshot_usage()['btw']['calls'] == 1
    oneshot.router.active_model = None
    await oneshot.module.run_oneshot(oneshot.router, 'p', purpose='btw', max_tokens=8)
    assert oneshot.calls[-1][1]['model'] == DEFAULT_LOCAL_MODEL
    assert oneshot.module.oneshot_usage()['btw']['calls'] == 2


async def test_run_oneshot_honours_its_own_model_override_not_the_active_chat_model(oneshot, monkeypatch):
    oneshot.router.active_model = 'large-chat-70b'
    await oneshot.module.run_oneshot(oneshot.router, 'p', purpose='plugin:probe', max_tokens=8)
    assert oneshot.calls[-1][1]['model'] == 'large-chat-70b'
    monkeypatch.setenv('JARVIS_AUX_ONESHOT_MODEL', 'configured-oneshot')
    await oneshot.module.run_oneshot(oneshot.router, 'p', purpose='plugin:probe', max_tokens=8)
    assert oneshot.calls[-1][1]['model'] == 'configured-oneshot'
    assert oneshot.router.active_model == 'large-chat-70b'
    assert oneshot.module.oneshot_usage()['plugin:probe']['calls'] == 2


async def test_run_oneshot_streams_through_the_same_rail_when_asked(oneshot):
    seen = []

    async def hook(text):
        seen.append(text)

    answer = await oneshot.module.run_oneshot(
        oneshot.router, 'p', purpose='plugin:probe', max_tokens=8, on_token=hook)
    assert answer == 'local answer' and seen == ['local ', 'answer']
    assert oneshot.calls[0][0] == 'stream' and oneshot.calls[0][1]['on_token'] is hook


@pytest.mark.parametrize('bad', [
    {'purpose': ''}, {'purpose': 'Side Question'}, {'purpose': 'x' * 65}, {'purpose': 7},
    {'max_tokens': 0}, {'max_tokens': 'many'}, {'max_tokens': True},
    {'prompt': ''}, {'prompt': 'x' * 48_001}, {'prompt': None},
    {'system': 'x' * 48_001}, {'temperature': -1}, {'temperature': 2.5},
])
async def test_run_oneshot_refuses_an_unbounded_or_mislabelled_call_before_dispatch(oneshot, bad):
    from agents.core.llm.auxiliary_text import AuxiliaryConfigError

    kwargs = {'prompt': 'p', 'purpose': 'btw', 'max_tokens': 8, 'temperature': 0.2, 'system': None}
    kwargs.update(bad)
    prompt = kwargs.pop('prompt')
    with pytest.raises(AuxiliaryConfigError):
        await oneshot.module.run_oneshot(oneshot.router, prompt, **kwargs)
    assert oneshot.calls == [] and oneshot.module.oneshot_usage() == {}


async def test_run_oneshot_caps_the_output_budget(oneshot):
    from agents.core.llm.auxiliary_text import MAX_ONESHOT_TOKENS, AuxiliaryConfigError

    with pytest.raises(AuxiliaryConfigError):
        await oneshot.module.run_oneshot(oneshot.router, 'p', purpose='btw', max_tokens=MAX_ONESHOT_TOKENS + 1)
    assert oneshot.calls == []
    await oneshot.module.run_oneshot(oneshot.router, 'p', purpose='btw', max_tokens=MAX_ONESHOT_TOKENS)
    assert oneshot.calls[0][1]['max_tokens'] == MAX_ONESHOT_TOKENS


async def test_run_oneshot_is_excluded_by_a_job_model_pin(oneshot):
    from agents.core.llm.job_selection import SelectionError, selection_scope

    with selection_scope({'model': 'pinned-model'}), pytest.raises(SelectionError):
        await oneshot.module.run_oneshot(oneshot.router, 'p', purpose='btw', max_tokens=8)
    assert oneshot.calls == []
    row = oneshot.module.oneshot_usage()['btw']
    assert row == {'calls': 1, 'answered': 0, 'refused': 1, 'prompt_chars': 1,
                   'max_tokens': 8, 'model': None, 'last_at': row['last_at']}


async def test_run_oneshot_never_falls_through_to_a_cloud_backend(oneshot):
    class Router:
        active_model = None

        @property
        def local_backend(self):
            raise RuntimeError('No local LLM backend available (strict-local path).')

    with pytest.raises(RuntimeError, match='strict-local'):
        await oneshot.module.run_oneshot(Router(), 'p', purpose='btw', max_tokens=8)
    assert oneshot.calls == []


async def test_run_oneshot_inherits_the_auxiliary_consent_boundary(dh):
    """An owner turn cannot authorize an unattended one-shot on a warned route."""
    from agents.core.llm.auxiliary_text import run_oneshot

    router, backend = route()
    sent = []

    async def generate(**kwargs):
        sent.append(kwargs)
        return 'answer'

    backend.generate = generate
    principal_token = bind_turn_principal(Principal(channel='web', admin=True))
    try:
        with pytest.raises(dh.DataHandlingRefused, match='audited acknowledgment'):
            await run_oneshot(router, 'private prompt', purpose='btw', max_tokens=8)
    finally:
        reset_turn_principal(principal_token)
    assert sent == []


async def test_run_oneshot_keeps_the_purpose_ledger_bounded(oneshot):
    from agents.core.llm.auxiliary_text import MAX_ONESHOT_PURPOSES

    for index in range(MAX_ONESHOT_PURPOSES + 5):
        await oneshot.module.run_oneshot(oneshot.router, 'p', purpose=f'plugin:p{index}', max_tokens=8)
    usage = oneshot.module.oneshot_usage()
    assert len(usage) == MAX_ONESHOT_PURPOSES and f'plugin:p{MAX_ONESHOT_PURPOSES + 4}' in usage
