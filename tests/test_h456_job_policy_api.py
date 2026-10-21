"""H456 authoring through the existing jobs CLI and guarded API."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents.cli.nerva import EXIT_OK, EXIT_USAGE
from agents.core.autonomy.jobs import JobRunner, JobStore
from tests.test_nerva_cli import JOB, _FakeHub, _run


def test_cli_create_edit_and_default_reasoning_preserve_other_options():
    hub = _FakeHub({'POST /api/jobs': {'ok': True, 'job': JOB},
                    'PATCH /api/jobs/j1': {'ok': True, 'job': JOB}})
    create = ['jobs', 'create', '--name', 'report', '--when', 'daily',
              '--action', '{"type":"ask","prompt":"report"}']
    code, _, err, _ = _run(create + ['--options', '{"repeat":2}', '--reasoning-effort', 'low'], hub)
    assert code == EXIT_OK, err
    assert hub.calls[-1][2]['options'] == {'repeat': 2, 'reasoning_effort': 'low'}
    code, _, err, _ = _run(['jobs', 'edit', 'j1', '--options',
                           '{"repeat":2,"reasoning_effort":"low"}',
                           '--reasoning-effort', 'default'], hub)
    assert code == EXIT_OK, err
    assert hub.calls[-1][2]['options'] == {'repeat': 2}
    code, _, err, _ = _run(create + ['--options', '{"repeat":2}',
                                     '--reasoning-effort', 'ultra'], hub)
    assert code == EXIT_OK, err
    assert hub.calls[-1][2]['options']['reasoning_effort'] == 'ultra'


def test_cli_reasoning_flag_never_replaces_options_implicitly():
    hub = _FakeHub({'PATCH /api/jobs/j1': {'ok': True, 'job': JOB}})
    code, _, err, _ = _run(['jobs', 'edit', 'j1', '--reasoning-effort', 'low'], hub)
    assert code == EXIT_USAGE and 'complete --options' in err
    assert hub.calls == []
    code, _, err, _ = _run(['jobs', 'create', '--blueprint', 'inbox_watch',
                           '--reasoning-effort', 'low'], hub)
    assert code == EXIT_USAGE and 'complete --options' in err
    assert hub.calls == []


@pytest.mark.asyncio
async def test_admin_job_api_persists_reasoning_pin_and_refuses_invalid_values(tmp_path, monkeypatch):
    from agents import web
    from agents.core.routers import jobs

    store = JobStore(tmp_path / 'jobs.db')
    runner = JobRunner(store, orch=SimpleNamespace(), scheduler=lambda: None)
    orch = SimpleNamespace(jobs=runner)
    monkeypatch.setattr(jobs, 'get_orch', lambda: orch)
    monkeypatch.setattr(web, 'ADMIN_TOKEN', 'owner-fixture')
    app = FastAPI()
    app.include_router(jobs.router)
    base = {'name': 'report', 'schedule_text': '0 9 * * *',
            'action': {'type': 'ask', 'prompt': 'report', 'deliver': False}}
    headers = {'X-Admin-Token': 'owner-fixture'}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
            assert (await client.post('/api/jobs', json={**base, 'options': {'reasoning_effort': 'low'}})).status_code in (401, 403)
            created = await client.post('/api/jobs', json={**base, 'options': {'reasoning_effort': 'low'}}, headers=headers)
            assert created.status_code == 201, created.text
            job_id = created.json()['job']['id']
            assert store.get(job_id).options == {'reasoning_effort': 'low'}
            for invalid in (None, '', 'HIGH', True, 'off'):
                refused = await client.patch(f'/api/jobs/{job_id}', json={'options': {'reasoning_effort': invalid}}, headers=headers)
                assert refused.status_code == 422, (invalid, refused.text)
                assert store.get(job_id).options == {'reasoning_effort': 'low'}
            cleared = await client.patch(f'/api/jobs/{job_id}', json={'options': {}}, headers=headers)
            assert cleared.status_code == 200, cleared.text
            assert store.get(job_id).options == {}
            non_model = await client.post('/api/jobs', json={**base, 'action': {'type':'remind','message':'hi'}, 'options': {'reasoning_effort':'low'}}, headers=headers)
            assert non_model.status_code == 422, non_model.text
    finally:
        store.close()
