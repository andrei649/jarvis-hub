import base64
import json
from pathlib import Path

import pytest


def store(tmp_path, **kwargs):
    from agents.core.artifact_store import BinaryArtifactStore
    return BinaryArtifactStore(tmp_path, **kwargs)

PNG = b'\x89PNG\r\n\x1a\n' + b'payload'
PDF = b'%PDF-1.7\nminimal test document\n%%EOF'


def test_magic_rejects_active_spoof_before_disk(tmp_path):
    s = store(tmp_path)
    with pytest.raises(ValueError, match='unsupported'):
        s.put(b'<html>not png</html>', mime='image/png', agent='owner')
    assert not list(tmp_path.iterdir())


def test_upload_cap_is_before_disk(tmp_path):
    s = store(tmp_path, max_upload=16)
    with pytest.raises(ValueError, match='too_large'):
        s.put(PDF, agent='owner')
    assert not list(tmp_path.iterdir())


def test_quota_pin_and_remove(tmp_path):
    s = store(tmp_path, max_items=2, max_bytes=100)
    first = s.put(PDF, agent='owner', now=1)
    s.pin(first['id'], True)
    second = s.put(PDF, agent='owner', now=2)
    third = s.put(PDF, agent='owner', now=3)
    assert {r['id'] for r in s.all()} == {first['id'], third['id']}
    assert not (tmp_path / 'artifacts' / second['id']).exists()
    assert s.read(first['id'])[1] == PDF
    assert 'path' not in first
    assert s.remove(first['id'])
    assert s.get_meta(first['id']) is None


def test_symlinks_and_traversal_refused(tmp_path):
    s = store(tmp_path)
    row = s.put(PDF, agent='owner')
    path = tmp_path / 'artifacts' / row['id']
    path.unlink()
    target = tmp_path / 'secret'
    target.write_bytes(PDF)
    path.symlink_to(target)
    for value in (row['id'], '../secret'):
        with pytest.raises(ValueError):
            s.read(value)
    assert target.read_bytes() == PDF


def test_export_retention_and_no_stale_index(tmp_path):
    from agents.core.data_export import export_data
    from agents.core.retention import run_retention
    s = store(tmp_path)
    row = s.put(PDF, agent='owner', now=1)
    exported = json.loads(Path(export_data(str(tmp_path))['export']).read_text())
    blob = exported['binary_artifacts']['items'][0]
    assert base64.b64decode(blob['base64']) == PDF
    assert blob['sha256'] == row['sha256']
    run_retention(lambda k, d: {'retention.enabled': True, 'retention.artifact_ttl_days': 1}.get(k, d), root=tmp_path, now=200000)
    assert s.all() == []


def test_forget_removes_binary_before_backup(tmp_path, monkeypatch):
    from agents.core import data_purge
    s = store(tmp_path)
    row = s.put(PDF)
    def backup(**kwargs):
        assert not (tmp_path / 'artifacts' / row['id']).exists()
        assert s.all() == []
        raise RuntimeError('backup observed erased binaries')
    monkeypatch.setattr(data_purge._backup, 'create_backup', backup)
    with pytest.raises(RuntimeError, match='backup observed'):
        data_purge.purge_data(str(tmp_path))


def test_forget_clears_orphan_and_refuses_concurrent_upload_during_backup(tmp_path, monkeypatch):
    from agents.core import data_purge
    s = store(tmp_path)
    s.put(PDF)
    orphan = tmp_path / 'artifacts' / ('ba-' + 'a' * 32)
    orphan.write_bytes(PDF)
    def backup(**kwargs):
        assert not list((tmp_path / 'artifacts').iterdir())
        assert s.all() == []
        with pytest.raises(ValueError, match='artifact_store_busy'):
            store(tmp_path).put(PDF)
        raise RuntimeError('snapshot protected')
    monkeypatch.setattr(data_purge._backup, 'create_backup', backup)
    with pytest.raises(RuntimeError, match='snapshot protected'):
        data_purge.purge_data(str(tmp_path))
    assert store(tmp_path).put(PDF)['size'] == len(PDF)


def test_retention_respects_pin_committed_after_enumeration(tmp_path, monkeypatch):
    s = store(tmp_path)
    row = s.put(PDF, now=1)
    original = s.all
    def snapshot_then_pin():
        rows = original()
        store(tmp_path).pin(row['id'], True)
        return rows
    monkeypatch.setattr(s, 'all', snapshot_then_pin)
    assert s.retain(1, now=200000)['deleted'] == []
    assert store(tmp_path).get_meta(row['id'])['pinned'] is True


def test_real_settings_can_enable_artifact_retention(tmp_path, monkeypatch):
    from agents.core import settings_db
    from agents.core.retention import run_retention
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    monkeypatch.setattr(settings_db, '_wal_set', False)
    settings_db.init_db()
    assert settings_db.put_category('retention', {'enabled': True, 'artifact_ttl_days': 1}) == (2, [])
    s = store(tmp_path)
    s.put(PDF, now=1)
    def get_setting(key, default):
        category, name = key.split('.', 1)
        return settings_db.get_value(category, name, default)
    assert run_retention(get_setting, root=tmp_path, now=200000)['artifacts']['deleted']
    assert s.all() == []


def test_interrupted_put_is_reclaimed_before_next_quota_decision(tmp_path):
    import os
    import subprocess
    import sys
    code = '''import os, sqlite3, sys
from agents.core.artifact_store import BinaryArtifactStore
class Interrupted(sqlite3.Connection):
    def execute(self, sql, *args, **kwargs):
        if sql.startswith('INSERT INTO artifacts'):
            os._exit(77)
        return super().execute(sql, *args, **kwargs)
connect = sqlite3.connect
sqlite3.connect = lambda *a, **k: connect(*a, factory=Interrupted, **k)
BinaryArtifactStore(sys.argv[1]).put(b'%PDF-1.7\\ncrash fixture\\n%%EOF')
'''
    child = subprocess.run([sys.executable, '-c', code, str(tmp_path)], env={**os.environ, 'JARVIS_HOME':str(tmp_path)}, timeout=15, capture_output=True)
    assert child.returncode == 77, child.stderr
    orphan = next((tmp_path / 'artifacts').iterdir())
    assert store(tmp_path).all() == []
    row = store(tmp_path, max_items=1, max_bytes=len(PDF)).put(PDF)
    assert not orphan.exists()
    assert [p.name for p in (tmp_path / 'artifacts').iterdir()] == [row['id']]


def test_forget_lock_excludes_another_process(tmp_path):
    import os
    import subprocess
    import sys
    s = store(tmp_path)
    s.put(PDF)
    with s.forget():
        code = '''import sys
from agents.core.artifact_store import BinaryArtifactStore
try:
    BinaryArtifactStore(sys.argv[1]).put(b'%PDF-1.7\\nfixture\\n%%EOF')
except ValueError as e:
    assert str(e) == 'artifact_store_busy'
    sys.exit(0)
sys.exit(1)
'''
        child = subprocess.run([sys.executable, '-c', code, str(tmp_path)], env={**os.environ,'JARVIS_HOME':str(tmp_path)}, timeout=15, capture_output=True)
        assert child.returncode == 0, child.stderr
