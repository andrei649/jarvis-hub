"""Adversarial read-only review of native staged restore identity handling."""
from agents.core import backup as bk
from tests import test_h010_restore_archive_identity as identity_tests

root = identity_tests.root
_make_backup = identity_tests._make_backup


def test_disappearing_archive_after_resolution_is_recorded_without_stranding_journal(root, monkeypatch):
    archive = _make_backup(root, b'A' * 4096)
    assert bk.stage_restore(archive.name, source_root=str(root))['ok']
    original = bk.resolve_backup

    def resolve_then_remove(*args, **kwargs):
        resolved = original(*args, **kwargs)
        if resolved is not None:
            resolved.unlink()
        return resolved

    monkeypatch.setattr(bk, 'resolve_backup', resolve_then_remove)
    result = bk.apply_pending_restore(source_root=str(root), runtime_wait=0, sleep=lambda _: None)
    assert result['status'] == 'failed' and result['reason'] == 'backup_missing'
    assert not (bk.default_backup_dir(root) / bk._APPLYING).exists()


def test_approval_records_missing_archive_if_removed_between_resolution_and_stat(root, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    archive = _make_backup(root, b'A' * 4096)
    payload = bk.restore_request(archive.name)['payload']
    original = bk.resolve_backup

    def resolve_then_remove(*args, **kwargs):
        resolved = original(*args, **kwargs)
        if resolved is not None:
            resolved.unlink()
        return resolved

    monkeypatch.setattr(bk, 'resolve_backup', resolve_then_remove)
    result = asyncio.run(bk.apply_approved(SimpleNamespace(payload=payload, id=55), None))
    assert result == {'status': 'refused', 'reason': 'backup_missing'}
    assert bk.last_refused_restore(root)['reason'] == 'backup_missing'
    assert bk.pending_restore(root) is None


def test_approval_records_missing_archive_if_removed_before_staging(root, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from agents.core import hub_restart

    archive = _make_backup(root, b'A' * 4096)
    payload = bk.restore_request(archive.name)['payload']
    original = bk.stage_restore
    restart_requests = []

    def delete_before_stage(*args, **kwargs):
        archive.unlink()
        return original(*args, **kwargs)

    monkeypatch.setattr(bk, 'stage_restore', delete_before_stage)
    monkeypatch.setattr(hub_restart, 'request', lambda *args: restart_requests.append(args))
    result = asyncio.run(bk.apply_approved(SimpleNamespace(payload=payload, id=56), None))
    assert result == {'status': 'refused', 'reason': 'backup_missing'}
    assert bk.last_refused_restore(root)['reason'] == 'backup_missing'
    assert bk.pending_restore(root) is None
    assert restart_requests == []


def test_stage_failure_is_a_persisted_refusal_without_restart(root, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from agents.core import hub_restart

    archive = _make_backup(root, b'A' * 4096)
    payload = bk.restore_request(archive.name)['payload']
    restart_requests = []

    def unreadable_stage(*args, **kwargs):
        raise PermissionError('private detail')

    monkeypatch.setattr(bk, 'stage_restore', unreadable_stage)
    monkeypatch.setattr(hub_restart, 'request', lambda *args: restart_requests.append(args))
    result = asyncio.run(bk.apply_approved(SimpleNamespace(payload=payload, id=57), None))
    assert result == {'status': 'refused', 'reason': 'backup_changed'}
    assert bk.last_refused_restore(root)['reason'] == 'backup_changed'
    assert restart_requests == []


def test_approval_cancellation_still_propagates(root, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import pytest

    archive = _make_backup(root, b'A' * 4096)
    payload = bk.restore_request(archive.name)['payload']

    async def cancelled_to_thread(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(bk.asyncio, 'to_thread', cancelled_to_thread)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(bk.apply_approved(SimpleNamespace(payload=payload, id=58), None))
    assert bk.pending_restore(root) is None
