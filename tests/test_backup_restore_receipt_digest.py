"""Real temporary archives/staging; no services or external effects."""
from pathlib import Path

import pytest

from agents.core import backup, install_identity


@pytest.fixture()
def staged(tmp_path, monkeypatch):
    root = tmp_path / 'data'
    root.mkdir()
    (root / 'payload.txt').write_text('before')
    monkeypatch.setenv('JARVIS_HOME', str(root))
    monkeypatch.setattr(install_identity, 'hub_lock_held_elsewhere', lambda *_: False)
    monkeypatch.setattr(backup, 'wait_for_runtime_yield', lambda *a, **k: True)
    made = backup.create_backup(source_root=str(root))
    archive = Path(made['archive'])
    stage = backup.stage_restore(archive.name, source_root=str(root))
    assert stage['ok']
    (root / 'payload.txt').write_text('after')
    return root, archive, stage


@pytest.mark.parametrize('outcome', ['restored', 'failed', 'deferred', 'cancelled', 'expired'])
def test_exact_staged_digest_survives_real_outcome(staged, monkeypatch, outcome):
    root, archive, stage = staged
    if outcome == 'failed':
        archive.unlink()
    elif outcome == 'deferred':
        monkeypatch.setattr(install_identity, 'hub_lock_held_elsewhere', lambda *_: True)
    elif outcome == 'expired':
        marker = backup.default_backup_dir(root) / backup._PENDING_RESTORE
        backup._write_json(marker, {**stage, 'expires_at': '2000-01-01T00:00:00+00:00'})
    if outcome == 'cancelled':
        assert backup.cancel_staged_restore(source_root=str(root))['ok']
    else:
        result = backup.apply_pending_restore(source_root=str(root), runtime_wait=0, sleep=lambda _: None)
        assert result['status'] == ('failed' if outcome == 'expired' else outcome)
        assert result.get('sha256') == stage['sha256']
    record = backup.last_restore(root)
    assert record['name'] == stage['name']
    assert record['staged_at'] == stage['staged_at']
    assert record.get('sha256') == stage['sha256']
    if outcome == 'restored':
        assert record['ok'] is True
        assert (root / 'payload.txt').read_text() == 'before'
    else:
        assert (root / 'payload.txt').read_text() == 'after'
