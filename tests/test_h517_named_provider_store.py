"""Named speech approval storage is bounded, read-only on lookup and revision-CAS."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from agents.core import settings_db


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    from agents.core.voice import provider_store
    return provider_store


def test_read_absent_is_metadata_only_without_creating_database(store):
    assert store.load('tts', 'studio') == {'provider_id': 'studio', 'provider_revision': 0}
    assert store.list_records('tts') == []
    assert not settings_db.DB_PATH.exists()


def test_independent_sides_and_names_with_atomic_same_name_cas(store):
    value = {'argv': ['/bin/echo'], 'approved_task': 42}
    assert store.save_approved('tts', 'studio', value, expected_revision=0) == 1
    assert store.save_approved('stt', 'studio', value, expected_revision=0) == 1
    assert store.save_approved('tts', 'other', value, expected_revision=0) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(store.save_approved, 'tts', 'studio', value, expected_revision=1) for _ in range(2)]
    results = []
    for future in futures:
        try:
            results.append(future.result())
        except store.ProviderConflict:
            results.append('conflict')
    assert sorted(map(str, results)) == ['2', 'conflict']
    assert store.load('stt', 'studio')['provider_revision'] == 1
    assert len(store.list_records('tts')) == 2


def test_clear_keeps_tombstone_and_never_recreates_pending_zero_authority(store):
    assert store.clear('tts', 'studio') == 1
    with pytest.raises(store.ProviderConflict):
        store.save_approved('tts', 'studio', {'argv': ['x']}, expected_revision=0)
    assert store.clear('tts', 'studio') == 2
    assert store.load('tts', 'studio') == {'provider_id': 'studio', 'provider_revision': 2}
    assert store.list_records('tts') == []


@pytest.mark.parametrize('name', ['', 'Studio', ' studio', 'a.b', 'a'*33, 'piper', 'auto', None, 1])
def test_invalid_or_reserved_identity_refuses_without_write(store, name):
    assert not store.valid_provider_id(name)
    with pytest.raises(store.ProviderStoreError):
        store.clear('tts', name)
    assert not settings_db.DB_PATH.exists()


def test_active_and_historical_bounds_preserve_rows(store):
    for n in range(16):
        store.save_approved('tts', f'n{n}', {'argv': ['x']}, expected_revision=0)
    with pytest.raises(store.ProviderLimit):
        store.save_approved('tts', 'overflow', {'argv': ['x']}, expected_revision=0)
    assert len(store.list_records('tts')) == 16
    for n in range(128 - 16):
        store.clear('tts', f't{n}')
    with pytest.raises(store.ProviderLimit):
        store.clear('tts', 'too_many')
    assert store.load('tts', 'too_many')['provider_revision'] == 0
    assert len(store.list_records('tts')) == 16


def test_json_bound_corruption_and_overflow_fail_closed(store):
    with pytest.raises(store.ProviderStoreError):
        store.save_approved('tts', 'studio', {'argv': ['x'], 'large': 'x'*300000}, expected_revision=0)
    store.clear('tts', 'studio')
    with sqlite3.connect(settings_db.DB_PATH) as conn:
        conn.execute("UPDATE voice_command_providers SET approved_json='not-json'")
    with pytest.raises(store.ProviderStoreError):
        store.load('tts', 'studio')
    with pytest.raises(store.ProviderStoreError):
        store.list_records('tts')
    with sqlite3.connect(settings_db.DB_PATH) as conn:
        conn.execute("UPDATE voice_command_providers SET approved_json='{}', revision=?", (2**63-1,))
    with pytest.raises(store.ProviderStoreError):
        store.clear('tts', 'studio')


def test_existing_database_without_table_is_readonly_empty(store):
    with sqlite3.connect(settings_db.DB_PATH) as conn:
        conn.execute('CREATE TABLE unrelated (value TEXT)')
    before = settings_db.DB_PATH.read_bytes()
    assert store.list_records('stt') == []
    assert store.load('stt', 'studio')['provider_revision'] == 0
    assert settings_db.DB_PATH.read_bytes() == before


@pytest.mark.parametrize('raw', ['{"argv":["x"],"argv":["y"]}', '{"argv":[]}', '{"argv":[false]}'])
def test_malformed_approved_json_is_not_a_usable_catalog(store, raw):
    store.clear('tts', 'studio')
    with sqlite3.connect(settings_db.DB_PATH) as conn:
        conn.execute('UPDATE voice_command_providers SET approved_json=?', (raw,))
    with pytest.raises(store.ProviderStoreError):
        store.list_records('tts')


def test_sql_abort_rolls_back_revision_and_other_names(store):
    store.save_approved('tts', 'studio', {'argv': ['original']}, expected_revision=0)
    with sqlite3.connect(settings_db.DB_PATH) as conn:
        conn.execute("CREATE TRIGGER fail_voice_update BEFORE UPDATE ON voice_command_providers BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(store.ProviderStoreError):
        store.save_approved('tts', 'studio', {'argv': ['changed']}, expected_revision=1)
    assert store.load('tts', 'studio')['argv'] == ['original']
    assert store.load('tts', 'studio')['provider_revision'] == 1
    assert store.save_approved('tts', 'other', {'argv': ['independent']}, expected_revision=0) == 1


def test_concurrent_independent_names_both_commit(store):
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(store.save_approved, 'stt', name, {'argv': ['x']}, expected_revision=0)
                   for name in ['studio', 'other']]
        assert [f.result() for f in futures] == [1, 1]
    assert {r['provider_id'] for r in store.list_records('stt')} == {'studio', 'other'}


def test_nonexistent_expected_revision_refuses_without_creating_store(store):
    with pytest.raises(store.ProviderConflict):
        store.save_approved('tts', 'studio', {'argv': ['x']}, expected_revision=1)
    assert not settings_db.DB_PATH.exists()
