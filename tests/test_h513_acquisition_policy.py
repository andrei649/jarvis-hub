"""Actual acquisition model attempts share the unattended data-policy boundary."""
import json
from contextlib import suppress

import httpx
import pytest

from agents.core.acquisition.llm_synth import draft_plan, generate_capability
from agents.core.commands import Principal
from agents.core.llm.egress import llm_async_client
from agents.core.llm.providers import get_profile
from agents.core.llm.router import LLMRouter
from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
from tests.test_h32_llm_synth import _PACKAGE_JSON, _PROMPT, _REFERENCES, _STEPS_JSON
from tests.test_h513_auxiliary_policy import consent
from tests.test_h513_auxiliary_policy import dh as dh


class Backend:
    def __init__(self, *, loopback=False, kind='capability', after_attempt=None):
        self.profile = get_profile('lm-studio')
        self.base_url = 'http://127.0.0.1:1234' if loopback else 'https://acquisition.invalid'
        self.kind, self.after_attempt = kind, after_attempt
        self.calls = []

    async def generate(self, model, prompt, **kwargs):
        self.calls.append({'model': model, 'prompt': prompt, **kwargs})
        if self.after_attempt is not None:
            self.after_attempt()
            return 'not JSON'
        return _PACKAGE_JSON if self.kind == 'capability' else _STEPS_JSON


def router(backend):
    r = LLMRouter()
    r._backend, r._backend_name, r._detected_model = backend, 'lm-studio', 'actual-acquisition-model'
    r._local_model = r._detected_model
    return r


async def call(kind, r):
    if kind == 'capability':
        return await generate_capability(_PROMPT, router=r)
    return await draft_plan('parse Acme API items', _REFERENCES, router=r)


@pytest.mark.parametrize('kind', ['capability', 'draft'])
async def test_copied_owner_unknown_endpoint_refuses_before_model_io(dh, kind):
    backend = Backend(kind=kind)
    r = router(backend)
    token = bind_turn_principal(Principal(channel='web', admin=True))
    try:
        with pytest.raises(dh.DataHandlingRefused, match='audited acknowledgment'):
            await call(kind, r)
        assert backend.calls == []
    finally:
        reset_turn_principal(token)


@pytest.mark.parametrize('kind', ['capability', 'draft'])
@pytest.mark.parametrize('loopback', [False, True])
async def test_loopback_or_existing_audited_consent_preserves_actual_limits(dh, kind, loopback):
    backend = Backend(kind=kind, loopback=loopback)
    r = router(backend)
    if not loopback:
        consent(dh, r)
    out = await call(kind, r)
    assert out and len(backend.calls) == 1
    actual = backend.calls[0]
    assert actual['model'] == 'actual-acquisition-model'
    assert actual['temperature'] == 0.2
    assert actual['max_tokens'] == (2048 if kind == 'capability' else 1024)


@pytest.mark.parametrize('kind', ['capability', 'draft'])
async def test_revocation_between_json_attempts_is_denial_not_json_retry(dh, kind):
    backend = Backend(kind=kind)
    r = router(backend)
    consent(dh, r)
    backend.after_attempt = lambda: consent(dh, r, acknowledged=False)
    with pytest.raises(dh.DataHandlingRefused):
        await call(kind, r)
    assert len(backend.calls) == 1


@pytest.mark.parametrize('kind', ['capability', 'draft'])
@pytest.mark.parametrize('swallow', [False, True])
async def test_revocation_blocks_physical_retry_even_if_adapter_swallows_it(dh, kind, swallow):
    backend = Backend(kind=kind)
    r = router(backend)
    consent(dh, r)
    sent = []

    def transport(request):
        sent.append(request)
        consent(dh, r, acknowledged=False)
        return httpx.Response(503)

    client = llm_async_client('lm-studio', transport=httpx.MockTransport(transport))

    async def generate(model, prompt, **kwargs):
        backend.calls.append(kwargs)
        await client.post(backend.base_url + '/first')
        if swallow:
            with suppress(dh.DataHandlingRefused):
                await client.post(backend.base_url + '/retry')
        else:
            await client.post(backend.base_url + '/retry')
        return _PACKAGE_JSON if kind == 'capability' else _STEPS_JSON

    backend.generate = generate
    try:
        with pytest.raises(dh.DataHandlingRefused):
            await call(kind, r)
        assert len(sent) == len(backend.calls) == 1
    finally:
        await client.aclose()


async def test_real_drive_keeps_blocked_failure_and_never_proposes_on_policy_denial(dh, tmp_path, monkeypatch):
    from agents.core.routers import acquisition
    from tests.test_h32_acquisition_drive_route import _body
    from tests.test_h32_synthesis_pipeline import (
        _FakeResearch,
        _fresh_request,
        _runtime,
        _verified_sequence,
    )

    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)
    backend = Backend()
    r = router(backend)

    async def generate(prompt):
        return await generate_capability(prompt, router=r)

    monkeypatch.setattr(acquisition, '_get_runtime', lambda: runtime)
    monkeypatch.setattr(acquisition, '_drive_seams', lambda: (_FakeResearch(), generate, None))
    monkeypatch.setattr(acquisition, '_sandbox_runner', _verified_sequence)
    token = bind_turn_principal(Principal(channel='web', admin=True))
    try:
        response = await acquisition.acquisition_drive(request.request_id, _body())
    finally:
        reset_turn_principal(token)
    payload = json.loads(response.body)
    assert response.status_code == 409 and payload['reason'] == 'synthesis_failed'
    assert payload['request_status'] == 'blocked'
    assert runtime.request_store.get(request.request_id).status.value == 'blocked'
    assert backend.calls == []
