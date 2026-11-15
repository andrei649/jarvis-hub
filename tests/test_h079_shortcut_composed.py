"""HTTP discovery uses real skill gates/resolution without loading a prompt."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import agents.web as web
from agents.core import settings_db
from agents.core.commands import build_default_registry
from agents.core.routers._deps import user_guard
from agents.core.routers.commands import router
from agents.core.skills.loader import SkillLoader
from tests.test_h026_skill_bundles import _md_skill, _write, isolated  # noqa: F401


def test_http_catalog_respects_real_web_gate_and_bundle_precedence_without_prompt_load(tmp_path, monkeypatch):
    skills = [_md_skill(name) for name in ('weather', 'news', 'notes', 'athena only')]
    loader = SkillLoader.__new__(SkillLoader)
    loader.skills = {skill.name: skill for skill in skills}
    # No file bodies are available: metadata discovery must not need them.
    for skill in skills:
        skill.view_files = {}
    settings_db.put_category('skills', {'channel_disabled': {'web': ['weather']}})
    settings_db.put_category('commands', {'quick_commands': {
        'report': {'type': 'exec', 'command': 'echo private-fixed-command'},
    }})
    _write(tmp_path, 'news.yaml', 'name: News\nskills: [notes]\ninstruction: private-bundle-instruction\n')
    monkeypatch.setattr(web, 'orch', SimpleNamespace(commands=build_default_registry(), skills=loader))
    monkeypatch.setattr(web, '_admin_configured', lambda: True)
    monkeypatch.setattr(web, '_admin_credential_ok', lambda value: value == 'owner-token')
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[user_guard] = lambda: None
    client = TestClient(app)

    owner = client.get('/api/commands', headers={'X-Admin-Token': 'owner-token'})
    assert owner.status_code == 200
    entries = {(row['kind'], row['command']) for row in owner.json()['shortcuts']}
    assert entries == {('quick', '/report'), ('skill', '/athena-only'),
                       ('skill', '/notes'), ('bundle', '/bundle news')}
    assert 'private-fixed-command' not in owner.text
    assert 'private-bundle-instruction' not in owner.text
    assert 'no-store' in owner.headers['cache-control']
    assert client.get('/api/commands').json()['shortcuts'] == []
    # Settings are read again; no startup-only snapshot can keep a revoked skill visible.
    settings_db.put_category('skills', {'channel_disabled': {'web': ['weather', 'notes']}})
    refreshed = client.get('/api/commands', headers={'X-Admin-Token': 'owner-token'}).json()
    assert ('skill', '/notes') not in {(row['kind'], row['command']) for row in refreshed['shortcuts']}
