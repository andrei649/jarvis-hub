"""H135 narrow user preference surface over an isolated real Settings DB."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'agents')]
from agents import web
from agents.core import settings_db

PATH = '/api/preferences/appearance'
TOKEN = 'appearance-test-only'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    monkeypatch.setattr(settings_db, '_wal_set', False)
    monkeypatch.setattr(web.app, 'dependency_overrides', {})
    monkeypatch.setattr(web, 'USER_TOKEN', TOKEN)
    monkeypatch.setenv('JARVIS_USER_TOKEN', TOKEN)
    return TestClient(web.app, headers={'X-User-Token': TOKEN})


def test_new_instance_defaults_are_not_an_explicit_motion_override(client):
    response = client.get(PATH)
    assert response.status_code == 200
    assert response.json() == {'revision': '0', 'configured': False, 'preferences': {
        'accent': 'cyan', 'look': 'obsidian', 'density': 'normal',
        'motion': 'system', 'scanline': 'on', 'dotgrid': 'off'}}
    assert 'no-store' in response.headers['cache-control']


def test_explicit_choice_persists_for_a_fresh_client(client):
    saved = client.put(PATH, json={'accent': 'amber', 'density': 'compact'})
    assert saved.status_code == 200
    fresh = TestClient(web.app, headers={'X-User-Token': TOKEN}).get(PATH).json()
    assert fresh['preferences']['accent'] == 'amber'
    assert fresh['preferences']['density'] == 'compact'
    assert fresh['preferences']['motion'] == 'system'
    assert fresh['configured'] is True


def test_guard_denies_read_and_write_without_user_token(client):
    for method in ('get', 'put'):
        response = getattr(client, method)(PATH, headers={'X-User-Token': ''})
        assert response.status_code == 401


def test_unknown_values_coerce_but_unknown_keys_cannot_write_other_settings(client):
    assert client.put(PATH, json={'accent': 'stale-theme'}).status_code == 200
    assert client.get(PATH).json()['preferences']['accent'] == 'cyan'
    response = client.put(PATH, json={'cloud_fallback': 'always'})
    assert response.status_code == 422
    assert settings_db.get_value('llm', 'cloud_fallback') == 'on-demand'


def test_partial_updates_preserve_other_choices_and_motion_default(client):
    client.put(PATH, json={'accent':'violet', 'look':'graphite'})
    response = client.put(PATH, json={'density':'comfy'}).json()
    assert response['preferences']['accent'] == 'violet'
    assert response['preferences']['look'] == 'graphite'
    assert response['preferences']['motion'] == 'system'
    assert response['preferences']['density'] == 'comfy'


@pytest.mark.parametrize('body', [{'accent':'x'*33}, {'look':{'css':'body{}'}}, {'preferences':{'accent':'amber'}}, {'motion': True}])
def test_malformed_or_oversized_fields_are_refused(client, body):
    assert client.put(PATH, json=body).status_code == 422
    assert client.get(PATH).json()['configured'] is False


def test_stale_stored_document_cannot_expose_arbitrary_config(client):
    settings_db.put_category('appearance', {'preferences':{'accent':'retired', 'custom_css':'body{display:none}', 'motion':'lively'}})
    body = client.get(PATH).json()
    assert body['preferences']['accent'] == 'cyan'
    assert body['preferences']['motion'] == 'lively'
    assert 'custom_css' not in body['preferences']


def test_db_failure_is_unavailable_not_fake_default_success(client, monkeypatch):
    import sqlite3
    def fail():
        raise sqlite3.OperationalError('private storage path')
    monkeypatch.setattr(settings_db, 'get_conn', fail)
    for response in [client.get(PATH), client.put(PATH, json={'accent':'amber'})]:
        assert response.status_code == 503
        assert response.json() == {'error':'appearance preferences unavailable'}
        assert 'private storage path' not in response.text


def test_concurrent_partial_updates_keep_both_devices_choices(client):
    from concurrent.futures import ThreadPoolExecutor

    from agents.core.appearance import update_appearance
    client.get(PATH)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for _ in range(8):
            responses = list(pool.map(update_appearance, [{'accent':'violet'}, {'look':'graphite'}]))
            assert all(response['configured'] for response in responses)
    prefs = client.get(PATH).json()['preferences']
    assert prefs['accent'] == 'violet' and prefs['look'] == 'graphite'


def test_stale_revision_cannot_overwrite_an_acknowledged_newer_choice(client):
    revision = client.get(PATH).json()['revision']
    saved = client.put(PATH, json={'accent': 'violet', '_revision': revision})
    assert saved.status_code == 200
    stale = client.put(PATH, json={'accent': 'amber', '_revision': revision})
    assert stale.status_code == 409
    assert client.get(PATH).json()['preferences']['accent'] == 'violet'
    assert client.put(PATH, json={'look': 'graphite', '_revision': saved.json()['revision']}).status_code == 200
