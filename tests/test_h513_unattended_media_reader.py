"""Unattended image dispatch uses exact audited role consent, entirely offline."""
from dataclasses import replace

import pytest

from agents.core import settings_db
from agents.core.channels.media_reader import InboundImageReader
from agents.core.llm import data_handling as dh
from agents.core.llm import vision_policy as vp
from agents.core.llm import vlm
from tests.test_h513_data_handling import Audit, router
from tests.test_h513_interactive_local_vision import rig

TARGET = 'role:telegram_media_reader'


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(dh, '_scope_key', lambda: b'synthetic-media-role-key')
    return rig(monkeypatch, config=vlm.VLMConfig('custom', 'http://localhost:1234/v1', 'vision', 'secret', True))


def grant(state, audit=None):
    target = vp.describe_media_data_target()
    return dh.acknowledge(router(), target.provider, True, dh.role_target_scope(target), audit or Audit(), target=TARGET)


def test_media_target_pure_secretless_and_separate(state, monkeypatch):
    monkeypatch.setattr(vlm, 'VLMBackend', lambda **kw: pytest.fail('status constructed client'))
    target = vp.describe_media_data_target()
    assert target.target_id == TARGET and target.mode == 'dedicated'
    assert target.policy == 'unknown' and 'secret' not in repr(target)
    row = next(row for row in dh.posture(router())['targets'] if row['target_id'] == TARGET)
    assert row['label'] == 'Telegram image descriptions' and not row['acknowledged']
    assert 'secret' not in str(row)
    other = replace(target, target_id='role:approval_judge')
    assert dh.role_target_scope(other) != row['scope']


def test_predownload_refusal_does_not_inherit_other_grant(state):
    reader = InboundImageReader.from_env()
    assert reader.refusal().reason == 'vision_owner_configuration_required'
    assert state.built == [] and state.sent == []
    grant(state)
    assert reader.refusal() is None
    scope = dh.role_target_scope(vp.describe_media_data_target())
    dh.acknowledge(router(), 'openai-compatible', False, scope, Audit(), target=TARGET)
    assert reader.refusal().reason == 'vision_owner_configuration_required'


@pytest.mark.asyncio
async def test_audited_read_uses_native_wire_and_closes(state):
    grant(state)
    out = await InboundImageReader.from_env()(b'image')
    assert out.ok and '<<UNTRUSTED' in out.text
    assert len(state.sent) == 1 and state.built[0].client.is_closed
    assert state.built[0]._composer_auth


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('api_key','rotated'),('model','new'),('base_url','http://localhost:4321/v1'),('backend','lmstudio')])
async def test_old_reader_live_rotation_refuses_before_construction(state, field, value):
    grant(state)
    reader = InboundImageReader.from_env()
    state.current[0] = replace(state.current[0], **{field:value})
    # lmstudio changes the policy to safe local, so it can run against the new live target.
    result = await reader(b'image')
    if field == 'backend':
        assert result.ok and len(state.sent) == 1
    else:
        assert not result.ok and result.reason == 'vision_owner_configuration_required'
        assert state.built == [] and state.sent == []


@pytest.mark.asyncio
async def test_physical_revocation_is_remembered_when_adapter_swallows(state, monkeypatch):
    grant(state)
    async def revoke(request):
        dh.acknowledge(router(), 'openai-compatible', False,
                       dh.role_target_scope(vp.describe_media_data_target()), Audit(), target=TARGET)
    # Factory hook executes before the native egress hook.
    factory = vlm.VLMBackend
    def hooked_factory(**kwargs):
        backend = factory(**kwargs)
        backend.client.event_hooks['request'].insert(0, revoke)
        return backend
    monkeypatch.setattr(vlm, 'VLMBackend', hooked_factory)
    result = await InboundImageReader.from_env()(b'image')
    assert not result.ok and result.reason == 'vision_owner_configuration_required'
    assert state.sent == [] and state.built[0].client.is_closed


def test_audit_race_cannot_grant_changed_scope(state):
    class RacingAudit(Audit):
        def log(self, event):
            super().log(event)
            state.current[0] = replace(state.current[0], api_key='new-key')
    with pytest.raises(dh.ConsentUnavailable):
        grant(state, RacingAudit())
    assert settings_db.get_value(*dh.ROLE_SETTING) == {}


def test_role_schema_accepts_only_finite_media_target():
    from agents.core.routers.security import DataHandlingAck
    assert DataHandlingAck(provider='openai-compatible', acknowledged=True, scope='a'*64, target=TARGET).target == TARGET
    with pytest.raises(ValueError):
        DataHandlingAck(provider='openai-compatible', acknowledged=True, scope='a'*64, target='role:camera')


def test_media_revoke_preserves_judge_and_provider_scopes(state, monkeypatch):
    from agents.core.autonomy import approval_judge
    media = vp.describe_media_data_target()
    judge = replace(media, target_id='role:approval_judge', binding=('distinct-judge-wire',))
    monkeypatch.setattr(approval_judge, 'describe_data_target', lambda *_: judge)
    dh.acknowledge(router(), judge.provider, True, dh.role_target_scope(judge), Audit(), target=judge.target_id)
    grant(state)
    dh.acknowledge(router(), media.provider, False, dh.role_target_scope(media), Audit(), target=TARGET)
    assert dh.authorize_role_target(None, judge, actual_use=False)['acknowledged']
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize_role_target(None, media, actual_use=False)
    assert settings_db.get_value(*dh.ROLE_SETTING) == {'approval_judge': dh.role_target_scope(judge)}


@pytest.mark.parametrize('raw', [[], {'camera': 'a'*64}, {'telegram_media_reader': 'malformed'}])
def test_corrupt_consent_fails_closed_before_download(state, monkeypatch, raw):
    read = settings_db.read_setting
    monkeypatch.setattr(settings_db, 'read_setting', lambda category, key:
                        (True, raw) if (category, key) == dh.ROLE_SETTING else read(category, key))
    assert InboundImageReader.from_env().refusal().reason == 'vision_owner_configuration_required'
    assert not state.built and not state.sent


def test_scope_secret_unavailable_safe_local_only(state, monkeypatch):
    monkeypatch.setattr(dh, '_scope_key', lambda: (_ for _ in ()).throw(RuntimeError('unavailable')))
    assert InboundImageReader.from_env().refusal().reason == 'vision_owner_configuration_required'
    state.current[0] = replace(state.current[0], backend='lmstudio')
    assert InboundImageReader.from_env().refusal() is None


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['key', 'model', 'authorization', 'cookies', 'proxy', 'selector'])
async def test_earlier_hook_mutation_refuses_before_transport(state, monkeypatch, change):
    import httpx
    grant(state)
    factory = vlm.VLMBackend
    def hooked(**kwargs):
        backend = factory(**kwargs)
        async def mutate(request):
            if change == 'key':
                backend.api_key = 'new'
            elif change == 'model':
                import json
                payload = json.loads(request.content)
                payload['model'] = 'different'
                request._content = json.dumps(payload).encode()
            elif change == 'authorization':
                request.headers['Authorization'] = 'Bearer other'
            elif change == 'cookies':
                request.headers['Cookie'] = 'session=other'
            elif change == 'proxy':
                backend.client._mounts = {httpx._utils.URLPattern('http://'):
                    httpx.AsyncHTTPTransport(proxy='http://proxy.invalid:8888')}
            else:
                backend.client._transport_for_url = lambda url: backend.client._transport
        backend.client.event_hooks['request'].insert(0, mutate)
        return backend
    monkeypatch.setattr(vlm, 'VLMBackend', hooked)
    out = await InboundImageReader.from_env()(b'image')
    assert not out.ok and out.reason == 'vision_owner_configuration_required'
    assert state.sent == [] and state.built[0].client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['config', 'consent'])
async def test_awaited_cleanup_revocation_discards_description(state, monkeypatch, change):
    grant(state)
    factory = vlm.VLMBackend
    def changing(**kwargs):
        backend = factory(**kwargs)
        close = backend.aclose
        async def close_and_mutate():
            await close()
            if change == 'config':
                state.current[0] = replace(state.current[0], api_key='new')
            else:
                dh.acknowledge(router(), 'openai-compatible', False,
                    dh.role_target_scope(vp.describe_media_data_target()), Audit(), target=TARGET)
        backend.aclose = close_and_mutate
        return backend
    monkeypatch.setattr(vlm, 'VLMBackend', changing)
    out = await InboundImageReader.from_env()(b'image')
    assert not out.ok and not out.text and out.reason == 'vision_owner_configuration_required'
    assert len(state.sent) == 1 and state.built[0].client.is_closed


@pytest.mark.asyncio
async def test_scope_entry_refusal_closes_owned_client(state, monkeypatch):
    grant(state)
    factory = vlm.VLMBackend
    def changing(**kwargs):
        backend = factory(**kwargs)
        state.current[0] = replace(state.current[0], api_key='new')
        return backend
    monkeypatch.setattr(vlm, 'VLMBackend', changing)
    out = await InboundImageReader.from_env()(b'image')
    assert not out.ok and out.reason == 'vision_owner_configuration_required'
    assert not state.sent and state.built[0].client.is_closed


@pytest.mark.asyncio
async def test_policy_swallow_still_denies_at_scope_exit(state, monkeypatch):
    grant(state)
    factory = vlm.VLMBackend
    def swallowing(**kwargs):
        backend = factory(**kwargs)
        checked = backend.generate_vision_checked
        async def swallowed(*args, **kwargs):
            try:
                return await checked(*args, **kwargs)
            except dh.DataHandlingRefused:
                return '[VLM error]'
        async def revoke(request):
            dh.acknowledge(router(), 'openai-compatible', False,
                dh.role_target_scope(vp.describe_media_data_target()), Audit(), target=TARGET)
        backend.generate_vision_checked = swallowed
        backend.client.event_hooks['request'].insert(0, revoke)
        return backend
    monkeypatch.setattr(vlm, 'VLMBackend', swallowing)
    out = await InboundImageReader.from_env()(b'image')
    assert not out.ok and out.reason == 'vision_owner_configuration_required'
    assert not state.sent and state.built[0].client.is_closed


@pytest.mark.asyncio
async def test_actual_local_dispatch_without_scope_secret(state, monkeypatch):
    state.current[0] = replace(state.current[0], backend='lmstudio')
    monkeypatch.setattr(dh, '_scope_key', lambda: (_ for _ in ()).throw(RuntimeError('unavailable')))
    out = await InboundImageReader.from_env()(b'image')
    assert out.ok and len(state.sent) == 1 and state.built[0].client.is_closed


def test_nonlocal_or_malformed_never_offers_role_pregrant(state):
    for url, local in [('https://remote.invalid/v1',False), ('http://localhost:invalid-port',True)]:
        state.current[0] = replace(state.current[0], base_url=url, is_local=local)
        assert vp.describe_media_data_target() is None
        assert not any(row['target_id'] == TARGET for row in dh.posture(router())['targets'])
        assert InboundImageReader.from_env().refusal() is not None
    assert not state.built


@pytest.mark.asyncio
async def test_unattended_warning_has_own_role_notice(state):
    from agents.core.turn_notices import open_turn_notices, reset_turn_notices
    grant(state)
    sink, token = open_turn_notices()
    try:
        assert (await InboundImageReader.from_env()(b'image')).ok
    finally:
        reset_turn_notices(token)
    assert [row['code'] for row in sink] == ['data_handling:role:telegram_media_reader']


def test_role_usage_entries_remain_independent_and_bounded(state):
    media = vp.describe_media_data_target()
    judge = replace(media, target_id='role:approval_judge', policy='local')
    grant(state)
    owner_router = router()
    dh.authorize_role_target(owner_router, judge)
    dh.authorize_role_target(owner_router, media)
    assert set(owner_router._data_handling_role_used) == {'role:approval_judge', TARGET}


@pytest.mark.asyncio
async def test_retry_rechecks_after_first_actual_request(state, monkeypatch):
    import httpx
    grant(state)
    factory = vlm.VLMBackend
    def retrying(**kwargs):
        backend = factory(**kwargs)
        sent = []
        def first_response(request):
            sent.append(request)
            dh.acknowledge(router(), 'openai-compatible', False,
                dh.role_target_scope(vp.describe_media_data_target()), Audit(), target=TARGET)
            return httpx.Response(503)
        backend.client._transport = httpx.MockTransport(first_response)
        checked = backend.generate_vision_checked
        async def retry(*args, **kwargs):
            try:
                return await checked(*args, **kwargs)
            except httpx.HTTPStatusError:
                return await checked(*args, **kwargs)
        backend.generate_vision_checked = retry
        backend._test_sent = sent
        return backend
    monkeypatch.setattr(vlm, 'VLMBackend', retrying)
    out = await InboundImageReader.from_env()(b'image')
    assert not out.ok and out.reason == 'vision_owner_configuration_required'
    assert len(state.built[0]._test_sent) == 1 and state.built[0].client.is_closed


@pytest.mark.asyncio
async def test_provider_grant_and_copied_owner_cannot_authorize_download(state, monkeypatch):
    from types import SimpleNamespace

    from agents.core.channels.telegram import TelegramChannel
    from agents.core.commands import Principal
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
    primary = router()
    row = dh.posture(primary)['providers'][0]
    dh.acknowledge(primary, row['provider'], True, row['scope'], Audit())
    channel = TelegramChannel(token='synthetic')
    async def forbidden(*args):
        pytest.fail('unauthorized image downloaded')
    monkeypatch.setattr(channel, '_download_file', forbidden)
    token = bind_turn_principal(Principal(channel='web', admin=True))
    try:
        result = await channel._read_image(SimpleNamespace(file_id='photo', caption='untrusted caption'))
    finally:
        reset_turn_principal(token)
    assert result.reason == 'vision_owner_configuration_required'
    assert not state.built and not state.sent


def test_media_api_authority_and_exact_scope(state, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from agents import web
    monkeypatch.setattr(web, 'ADMIN_TOKEN', 'synthetic-admin')
    monkeypatch.setattr(web, 'orch', SimpleNamespace(llm_router=router(), audit=Audit()))
    client = TestClient(web.app)
    target = vp.describe_media_data_target()
    body = {'provider': target.provider, 'scope': dh.role_target_scope(target), 'acknowledged': True, 'target': TARGET}
    headers = {'X-Admin-Token': 'synthetic-admin'}
    assert client.post('/api/security/data-handling/ack', json=body).status_code in (401,403)
    assert client.post('/api/security/data-handling/ack', json={**body,'provider':'gemini'}, headers=headers).status_code == 422
    assert client.post('/api/security/data-handling/ack', json={**body,'scope':'0'*64}, headers=headers).status_code == 409
    response = client.post('/api/security/data-handling/ack', json=body, headers=headers)
    assert response.status_code == 200 and response.json()['target'] == TARGET
    state.current[0] = replace(state.current[0], api_key='rotated')
    assert client.post('/api/security/data-handling/ack', json=body, headers=headers).status_code == 409


def test_media_audit_failure_and_sql_abort_grant_nothing(state):
    class BrokenAudit(Audit):
        def log(self, event):
            raise RuntimeError('audit failed')
    with pytest.raises(dh.ConsentUnavailable):
        grant(state, BrokenAudit())
    assert settings_db.get_value(*dh.ROLE_SETTING) == {}
    conn = settings_db.get_conn()
    try:
        conn.execute("CREATE TRIGGER refuse_media_update BEFORE UPDATE ON settings "
                     "WHEN NEW.category='security' AND NEW.key='data_training_role_ack' "
                     "BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(dh.ConsentUnavailable):
        grant(state)
    assert settings_db.get_value(*dh.ROLE_SETTING) == {}


@pytest.mark.asyncio
async def test_selection_refusal_happens_before_download(state, monkeypatch):
    from agents.core.llm import selection_guards as sg
    grant(state)
    finding = sg.Finding('synthetic', 'owner_selection', sg.Choice('vision.model', 'openai-compatible', 'vision'), 'synthetic refusal')
    monkeypatch.setattr(sg, 'evaluate', lambda choices: [finding])
    assert InboundImageReader.from_env().refusal().reason == 'vision_owner_configuration_required'
    assert not state.built and not state.sent
