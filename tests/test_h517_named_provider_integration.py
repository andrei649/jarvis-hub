"""Named registration through admin HTTP, signed decisions and actual speech I/O."""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents import web
from agents.core import settings_db
from agents.core.routers import _component, admin, autonomy, voice
from agents.core.voice import provider_store
from agents.core.voice import stt as sm
from tests.test_h517_voice_kernel import make_rig
from tests.test_h613_piper_command_voice import WAV, _fake, _py, _records
from tests.test_h613_piper_command_voice import env as env

OWNER = {'X-User-Token': 'named-user', 'X-Admin-Token': 'named-owner'}
PATH = '/api/admin/voice/commands'


@pytest.fixture
def http_rig(env, monkeypatch):
    rig = make_rig(env.tmp, monkeypatch)
    for module in (voice, admin, autonomy, _component):
        monkeypatch.setattr(module, 'get_orch', lambda: rig.orch)
    monkeypatch.setattr(web, 'USER_TOKEN', OWNER['X-User-Token'])
    monkeypatch.setattr(web, 'ADMIN_TOKEN', OWNER['X-Admin-Token'])
    monkeypatch.setattr(voice, '_caps_cache', {'has_whisper': False, 'has_edge': False,
                                            'has_kokoro': False, 'consent_fn': None})
    engine = sm.STTEngine.__new__(sm.STTEngine)
    engine._model, engine.beam_size = None, 1
    monkeypatch.setattr(voice, '_STT_ENGINE', engine)
    app = FastAPI()
    for router in (voice.router, admin.router, autonomy.router):
        app.include_router(router)
    value = SimpleNamespace(rig=rig, env=env, app=app)
    value.client = lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app, client=('198.51.100.2', 5000)),
                                           base_url='http://test', headers=OWNER)
    yield value
    rig.q.close()


async def propose(value, client, side, name):
    program = _fake(value.env.tmp / f'{side}-{name}.py', value.env.tmp)
    argv = [_py(), str(program)] + (['--out', '{output}'] if side == 'tts' else ['--audio', '{audio}'])
    response = await client.post(PATH, json={'side': side, 'provider_id': name, 'argv': argv})
    assert response.status_code == 202, response.text
    tid = response.json()['pending']
    assert value.rig.q.get(tid).mediation_receipt['effective_tier'] == 3
    assert not provider_store.load(side, name).get('argv')
    return tid


async def accept(value, client, tid):
    response = await client.post(f'/autonomy/tasks/{tid}/decision', json={'action': 'accept'})
    assert response.status_code == 200, response.text
    await value.rig.worker.tick()


@pytest.mark.parametrize('side', ['tts', 'stt'])
async def test_http_signed_named_registration_selection_speech_and_revocation(http_rig, side):
    value = http_rig
    async with value.client() as client:
        tid = await propose(value, client, side, 'speech')
        status = (await client.get(PATH)).json()
        assert status['providers'][side][0]['pending_task'] == tid
        assert _records(value.env.tmp) == []
        await accept(value, client, tid)
        assert value.rig.q.get(tid).status == 'done'
        status = (await client.get(PATH)).json()
        row = status['providers'][side][0]
        assert row['provider_id'] == 'speech' and row['provider_revision'] == 1 and row['ready']
        assert settings_db.get_value('voice', f'{side}_command', {}) == {}
        if side == 'tts':
            caps = (await client.get('/api/voice/capabilities')).json()
            assert 'provider:speech' in caps['voices']
            response = await client.post('/tts', json={'text': 'hello world', 'voice': 'provider:speech', 'lang': 'en'})
            assert response.status_code == 200, response.text
            assert response.content == WAV and response.headers['content-type'] == 'audio/wav'
        else:
            selected = await client.put('/api/admin/settings/voice', json={'values': {
                'stt_engine': 'command', 'stt_command_provider': 'speech'}})
            assert selected.status_code == 200, selected.text
            assert (await client.get(PATH)).json()['selected_stt_provider'] == 'speech'
            response = await client.post('/api/voice/stt?lang=en', content=WAV)
            assert response.status_code == 200 and response.json()['text'] == 'salut lume', response.text
        assert len(_records(value.env.tmp)) == 1
        cleared = await client.post(PATH, json={'side': side, 'provider_id': 'speech', 'clear': True})
        assert cleared.status_code == 200
        assert provider_store.load(side, 'speech')['provider_revision'] == 2
        if side == 'tts':
            response = await client.post('/tts', json={'text': 'hello world', 'voice': 'provider:speech'})
        else:
            response = await client.post('/api/voice/stt', content=WAV)
        assert response.status_code == 503
        assert len(_records(value.env.tmp)) == 1
        assert value.rig.q.verified_mediation_stats()['valid']


async def test_pending_http_clear_cannot_be_reinstalled_by_old_human_accept(http_rig):
    async with http_rig.client() as client:
        tid = await propose(http_rig, client, 'tts', 'speech')
        assert (await client.post(PATH, json={'side': 'tts', 'provider_id': 'speech', 'clear': True})).status_code == 200
        await accept(http_rig, client, tid)
        assert http_rig.rig.q.get(tid).result['reason'] == 'provider_revision_conflict'
        assert not provider_store.load('tts', 'speech').get('argv')
        assert _records(http_rig.env.tmp) == []


async def test_nonadmin_http_cannot_write_named_authority(http_rig):
    async with http_rig.client() as client:
        response = await client.post(PATH, json={'side': 'tts', 'provider_id': 'speech', 'clear': True},
                                     headers={'X-Admin-Token': 'wrong'})
        assert response.status_code in {401, 403}
        assert provider_store.load('tts', 'speech')['provider_revision'] == 0
