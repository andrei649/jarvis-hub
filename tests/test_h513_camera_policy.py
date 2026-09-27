"""Camera role policy and original privacy lease bind native offline requests."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.cameras import vlm as cv
from agents.core.llm import data_handling as dh
from agents.core.llm import vision_policy as vp
from agents.core.llm import vlm
from tests.test_h31_camera_pipeline import _event, _frame, _policy, _SnapshotSource
from tests.test_h513_data_handling import Audit, router
from tests.test_h513_interactive_local_vision import rig

TARGET = 'role:camera_descriptions'


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path/'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(dh, '_scope_key', lambda: b'synthetic-camera-key')
    settings = {'camera.enabled':True,'camera.vlm_enabled':True,'camera.vlm_describe_events':True,
                'camera.vlm_endpoint':'http://localhost:8000/v1','camera.vlm_model':'camera-vision'}
    orch = SimpleNamespace(get_setting=lambda key, default=None: settings.get(key, default))
    wire = rig(monkeypatch, config=vlm.VLMConfig('custom',settings['camera.vlm_endpoint'],settings['camera.vlm_model'],'',True),
               text='{"description":"An anonymous person is standing by the door."}')
    return SimpleNamespace(orch=orch, settings=settings, wire=wire)


def grant(state, audit=None):
    target = vp.describe_camera_data_target(state.orch)
    return dh.acknowledge(router(),target.provider,True,dh.role_target_scope(target),audit or Audit(),
                          target=TARGET,role_context=state.orch)


def native(state):
    config = cv.resolve_camera_vlm_config(state.orch)
    return cv.LocalCameraVLM.from_native(config,resolve_config=lambda:cv.resolve_camera_vlm_config(state.orch))


def test_posture_pure_optional_context_and_secretless(state, monkeypatch):
    monkeypatch.setattr(vlm,'VLMBackend',lambda **kw:pytest.fail('posture constructed runtime'))
    assert not any(row['target_id']==TARGET for row in dh.posture(router())['targets'])
    row = next(row for row in dh.posture(router(),role_context=state.orch)['targets'] if row['target_id']==TARGET)
    assert row['label']=='Camera descriptions' and row['policy']=='unknown' and row['mode']=='dedicated'
    assert not any(key in row for key in ('binding','endpoint','base_url','authorization'))
    assert not state.wire.built


@pytest.mark.asyncio
async def test_native_camera_requires_own_grant_then_sends_and_closes(state):
    reader = native(state)
    assert await reader.describe(_frame(),_event()) is None
    assert not state.wire.built
    grant(state)
    assert await reader.describe(_frame(),_event()) == 'An anonymous person is standing by the door.'
    assert len(state.wire.sent)==1 and state.wire.built[0].client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize('key,value',[('camera.enabled',False),('camera.vlm_enabled',False),('camera.vlm_describe_events',False),
    ('camera.vlm_model','new-model'),('camera.vlm_endpoint','http://localhost:9000/v1')])
async def test_cached_runtime_refuses_live_change(state,key,value):
    grant(state)
    reader = native(state)
    state.settings[key]=value
    assert await reader.describe(_frame(),_event()) is None
    assert not state.wire.sent and not state.wire.built


def test_camera_audit_race_grants_nothing(state):
    class Race(Audit):
        def log(self,event):
            super().log(event)
            state.settings['camera.vlm_model']='new-model'
    with pytest.raises(dh.ConsentUnavailable):
        grant(state,Race())
    assert settings_db.get_value(*dh.ROLE_SETTING)=={}


def test_disabled_or_remote_target_cannot_be_acknowledged(state):
    state.settings['camera.vlm_endpoint']='https://remote.invalid/v1'
    assert vp.describe_camera_data_target(state.orch) is None
    with pytest.raises(ValueError):
        dh.acknowledge(router(),'openai-compatible',True,'a'*64,Audit(),target=TARGET,role_context=state.orch)
    state.settings['camera.enabled']=False
    assert vp.describe_camera_data_target(state.orch) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('retry',[False,True])
async def test_original_household_lease_rechecked_in_physical_hook(state,monkeypatch,retry):
    import httpx

    from agents.core.cameras.pipeline import CameraPipeline
    from agents.core.cameras.privacy import CameraPrivacyError
    from agents.core.cameras.rules import CameraRuleEngine
    grant(state)
    policy = _policy()
    factory = vlm.VLMBackend
    transmitted=[]
    def hooked(**kwargs):
        backend=factory(**kwargs)
        checked=backend.generate_vision_checked
        if retry:
            def first(request):
                transmitted.append(request)
                policy.revoke('synthetic revocation')
                return httpx.Response(503)
            backend.client._transport=httpx.MockTransport(first)
            async def retry_call(*args,**kwargs):
                try:
                    return await checked(*args,**kwargs)
                except httpx.HTTPStatusError:
                    return await checked(*args,**kwargs)
            backend.generate_vision_checked=retry_call
        else:
            async def revoke(request):
                policy.revoke('synthetic revocation')
            backend.client.event_hooks['request'].insert(0,revoke)
        return backend
    monkeypatch.setattr(vlm,'VLMBackend',hooked)
    stored=[]
    pipeline=CameraPipeline(rules=CameraRuleEngine(),privacy_policy=policy,snapshots=_SnapshotSource(_frame()),
                            vlm=native(state),store_masked=lambda *args:stored.append(args))
    with pytest.raises(CameraPrivacyError):
        await pipeline.process(_event(),describe=True)
    assert not stored and state.wire.sent==[]
    assert len(transmitted)==int(retry) and state.wire.built[0].client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['config','role','household'])
async def test_awaited_cleanup_cannot_publish_stale_description(state,monkeypatch,change):
    grant(state)
    policy=_policy()
    lease=policy.begin('front-door')
    factory=vlm.VLMBackend
    def changing(**kwargs):
        backend=factory(**kwargs)
        close=backend.aclose
        async def close_and_change():
            await close()
            if change=='config':
                state.settings['camera.vlm_model']='new'
            elif change=='household':
                policy.revoke('synthetic revocation')
            else:
                target=vp.describe_camera_data_target(state.orch)
                dh.acknowledge(router(),target.provider,False,dh.role_target_scope(target),Audit(),
                               target=TARGET,role_context=state.orch)
        backend.aclose=close_and_change
        return backend
    monkeypatch.setattr(vlm,'VLMBackend',changing)
    out=await native(state).describe(_frame(),_event(),privacy_check=lambda:policy.recheck(lease,'inference'))
    assert out is None and len(state.wire.sent)==1 and state.wire.built[0].client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['config','role','proxy','selector','auth','model'])
async def test_physical_mutations_refuse_before_transport(state,monkeypatch,change):
    import json

    import httpx
    grant(state)
    factory=vlm.VLMBackend
    def changing(**kwargs):
        backend=factory(**kwargs)
        async def mutate(request):
            if change=='config':
                state.settings['camera.enabled']=False
            elif change=='role':
                target=vp.describe_camera_data_target(state.orch)
                dh.acknowledge(router(),target.provider,False,dh.role_target_scope(target),Audit(),
                               target=TARGET,role_context=state.orch)
            elif change=='proxy':
                backend.client._mounts={httpx._utils.URLPattern('http://'):
                    httpx.AsyncHTTPTransport(proxy='http://proxy.invalid:8888')}
            elif change=='selector':
                backend.client._transport_for_url=lambda url:backend.client._transport
            elif change=='auth':
                request.headers['Authorization']='Bearer other'
            else:
                payload=json.loads(request.content)
                payload['model']='other'
                request._content=json.dumps(payload).encode()
        backend.client.event_hooks['request'].insert(0,mutate)
        return backend
    monkeypatch.setattr(vlm,'VLMBackend',changing)
    assert await native(state).describe(_frame(),_event()) is None
    assert not state.wire.sent and state.wire.built[0].client.is_closed


@pytest.mark.asyncio
async def test_scope_entry_refusal_closes_owned_client(state,monkeypatch):
    grant(state)
    factory=vlm.VLMBackend
    def changing(**kwargs):
        backend=factory(**kwargs)
        state.settings['camera.vlm_model']='new'
        return backend
    monkeypatch.setattr(vlm,'VLMBackend',changing)
    assert await native(state).describe(_frame(),_event()) is None
    assert not state.wire.sent and state.wire.built[0].client.is_closed


def test_role_separation_camera_revoke_keeps_existing_judge_media(state,monkeypatch):
    from agents.core.autonomy import approval_judge
    camera=vp.describe_camera_data_target(state.orch)
    judge=replace(camera,target_id='role:approval_judge',binding=('judge-wire',))
    monkeypatch.setattr(approval_judge,'describe_data_target',lambda *_:judge)
    media=vp.describe_media_data_target()
    for target in (judge,media):
        dh.acknowledge(router(),target.provider,True,dh.role_target_scope(target),Audit(),target=target.target_id)
    # Neither existing grant authorizes the camera role.
    with pytest.raises(dh.DataHandlingRefused):
        dh.authorize_role_target(None,camera,actual_use=False)
    grant(state)
    dh.acknowledge(router(),camera.provider,False,dh.role_target_scope(camera),Audit(),target=TARGET,role_context=state.orch)
    for target in (judge,media):
        assert dh.authorize_role_target(None,target,actual_use=False)['acknowledged']
    assert set(settings_db.get_value(*dh.ROLE_SETTING))=={'approval_judge','telegram_media_reader'}


@pytest.mark.asyncio
@pytest.mark.parametrize('borrowed', [False, True])
async def test_real_runtime_uses_lazy_guarded_camera_wiring(state,tmp_path,borrowed):
    from agents.core.cameras.runtime import build_camera_runtime
    from tests.test_h31_camera_api import _Orch, _settings
    values=_settings()
    values.update(state.settings)
    orch=_Orch(values,root=tmp_path)
    backend = vlm.VLMBackend(base_url=state.settings['camera.vlm_endpoint'], api_key='', composer_auth=True) if borrowed else None
    runtime=build_camera_runtime(orch,root=tmp_path/'camera',resolver=lambda *_:('192.168.1.40',), vlm_backend=backend)
    assert runtime.enabled and len(state.wire.built) == int(borrowed)
    state.orch=orch
    grant(state)
    try:
        runtime.pipeline._snapshots=_SnapshotSource(_frame())
        result=await runtime.pipeline.process(_event(),describe=True,point=(0.3,0.5))
        assert result.status=='described' and len(state.wire.sent)==1
        assert state.wire.built[0].client.is_closed is (not borrowed)
        if borrowed:
            lease = runtime.privacy_policy.begin('front-door')
            assert await runtime.pipeline._vlm.describe(_frame(), _event('second'),
                privacy_check=lambda:runtime.privacy_policy.recheck(lease,'inference'))
            assert len(state.wire.sent) == 2 and not backend.client.is_closed
    finally:
        runtime.feed_publisher.close()
        if backend is not None:
            await backend.aclose()



@pytest.mark.asyncio
async def test_borrowed_native_backend_remains_open_for_two_descriptions(state):
    grant(state)
    config=cv.resolve_camera_vlm_config(state.orch)
    backend=vlm.VLMBackend(base_url=config.endpoint,api_key='',composer_auth=True)
    reader=cv.LocalCameraVLM.from_native(config,resolve_config=lambda:cv.resolve_camera_vlm_config(state.orch),
                                        backend_factory=lambda:backend,owns_backend=False)
    try:
        for event in (_event('one'),_event('two')):
            assert await reader.describe(_frame(),event)=='An anonymous person is standing by the door.'
        assert len(state.wire.sent)==2 and not backend.client.is_closed
    finally:
        await backend.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['[VLM error]','{"description":"Alice is at the door."}','{"description":"License plate ABC-123."}',''])
async def test_native_output_sanitization_still_rejects_sensitive_or_failed_text(state,monkeypatch,text):
    import httpx
    grant(state)
    factory=vlm.VLMBackend
    def responding(**kwargs):
        backend=factory(**kwargs)
        backend.client._transport=httpx.MockTransport(lambda request:httpx.Response(200,
            json={'choices':[{'message':{'content':text}}]}))
        return backend
    monkeypatch.setattr(vlm,'VLMBackend',responding)
    assert await native(state).describe(_frame(),_event()) is None
    assert state.wire.built[0].client.is_closed


@pytest.mark.parametrize('bad',['https://remote.invalid/v1','http://local.invalid/v1','http://user:secret@localhost/v1',
    'http://localhost/v1?token=secret','http://localhost/other','http://localhost:invalid-port'])
def test_pure_camera_target_preserves_exact_local_validation(state,bad):
    state.settings['camera.vlm_endpoint']=bad
    assert vp.describe_camera_data_target(state.orch) is None
    assert not state.wire.built


def test_camera_api_threads_owner_context_and_never_enables_disabled_camera(state,monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    monkeypatch.setattr(web,'ADMIN_TOKEN','synthetic-admin')
    state.orch.llm_router=router()
    state.orch.audit=Audit()
    monkeypatch.setattr(web,'orch',state.orch)
    target=vp.describe_camera_data_target(state.orch)
    body={'provider':target.provider,'scope':dh.role_target_scope(target),'acknowledged':True,'target':TARGET}
    headers={'X-Admin-Token':'synthetic-admin'}
    client=TestClient(web.app)
    assert client.post('/api/security/data-handling/ack',json=body).status_code in (401,403)
    result=client.post('/api/security/data-handling/ack',json=body,headers=headers)
    assert result.status_code==200 and result.json()['target']==TARGET
    state.settings['camera.enabled']=False
    assert client.post('/api/security/data-handling/ack',json=body,headers=headers).status_code==422
    assert state.settings['camera.enabled'] is False


def test_missing_context_cannot_grant_camera_scope_and_failed_audit_is_atomic(state):
    target=vp.describe_camera_data_target(state.orch)
    scope=dh.role_target_scope(target)
    with pytest.raises(ValueError):
        dh.acknowledge(router(),target.provider,True,scope,Audit(),target=TARGET)
    class Broken(Audit):
        def log(self,event):
            raise RuntimeError('synthetic audit unavailable')
    with pytest.raises(dh.ConsentUnavailable):
        grant(state,Broken())
    assert settings_db.get_value(*dh.ROLE_SETTING)=={}


@pytest.mark.asyncio
async def test_camera_notice_is_separate_and_no_ambient_owner_grant(state):
    from agents.core.commands import Principal
    from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
    from agents.core.turn_notices import open_turn_notices, reset_turn_notices
    reader=native(state)
    token=bind_turn_principal(Principal(channel='web',admin=True))
    try:
        assert await reader.describe(_frame(),_event()) is None
    finally:
        reset_turn_principal(token)
    grant(state)
    sink,notice_token=open_turn_notices()
    try:
        assert await reader.describe(_frame(),_event())
    finally:
        reset_turn_notices(notice_token)
    assert [row['code'] for row in sink]==['data_handling:role:camera_descriptions']
