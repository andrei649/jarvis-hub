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
