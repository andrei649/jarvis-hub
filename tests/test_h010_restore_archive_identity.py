"""V52 acceptance and apply bind restore authority to one exact archive byte stream."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import secrets
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import archive_safe, hub_restart, install_identity
from agents.core import backup as bk


@pytest.fixture()
def root(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "payload.bin").write_bytes(b"L" * 4096)
    monkeypatch.setenv("JARVIS_HOME", str(data))
    monkeypatch.setenv("JARVIS_RESTORE_RUNTIME_WAIT_SECONDS", "0")
    monkeypatch.setattr(install_identity, "hub_lock_held_elsewhere", lambda *_: False)
    monkeypatch.setattr(bk, "wait_for_runtime_yield", lambda *_args, **_kwargs: True)
    hub_restart.reset()
    yield data
    hub_restart.reset()


def _make_backup(root, value: bytes):
    source = root.parent / f"source-{secrets.token_hex(4)}"
    source.mkdir()
    (source / "payload.bin").write_bytes(value)
    made = bk.create_backup(source_root=str(source), out_dir=str(bk.default_backup_dir(root)))
    return Path(made["archive"])


def _replacement_no_larger(root, accepted: Path):
    candidate = _make_backup(root, b"B" * 512)
    # Gzip metadata varies slightly by timestamp/name. Pad the accepted fixture
    # before approval so the valid replacement can always preserve its byte size.
    gap = candidate.stat().st_size - accepted.stat().st_size
    if gap > 0:
        with accepted.open("ab") as stream:
            stream.write(b"\0" * gap)
    return candidate


def _same_size_mtime_replace(path: Path, replacement: Path):
    original_stat = path.stat()
    body = replacement.read_bytes()
    if len(body) < original_stat.st_size:
        # A gzip tar permits bounded zero padding after the end marker; this keeps the
        # replacement a valid drillable archive while preserving the source byte count.
        body += b"\0" * (original_stat.st_size - len(body))
    assert len(body) == original_stat.st_size
    path.write_bytes(body)
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    now = path.stat()
    assert now.st_size == original_stat.st_size
    assert now.st_mtime_ns == original_stat.st_mtime_ns
    return body


def _rollback_names(root):
    return {p.name for p in bk.default_backup_dir(root).glob("jarvis-backup-prerestore-*.tar.gz*")}


def test_restore_accept_rejects_same_size_mtime_archive_swap(root):
    accepted = _make_backup(root, b"A" * 4096)
    replacement = _replacement_no_larger(root, accepted)
    card = bk.restore_request(accepted.name)
    original_digest = card["payload"]["sha256"]
    _same_size_mtime_replace(accepted, replacement)
    assert card["payload"]["sha256"] == original_digest

    task = SimpleNamespace(payload=card["payload"], id=42, decided_by="owner")
    result = asyncio.run(bk.apply_approved(task, None))

    assert result == {"status": "refused", "reason": "backup_changed"}
    assert bk.pending_restore(root) is None
    assert bk.last_refused_restore(root)["reason"] == "backup_changed"


def test_apply_rejects_same_size_mtime_swap_before_rollback_or_live_write(root):
    accepted = _make_backup(root, b"A" * 4096)
    replacement = _replacement_no_larger(root, accepted)
    (root / "payload.bin").write_bytes(b"L" * 4096)
    staged = bk.stage_restore(accepted.name, source_root=str(root))
    assert staged["ok"] and staged["sha256"]
    rollbacks_before = _rollback_names(root)
    _same_size_mtime_replace(accepted, replacement)

    result = bk.apply_pending_restore(source_root=str(root), runtime_wait=0, sleep=lambda _: None)

    assert result["status"] == "failed" and result["reason"] == "backup_changed"
    assert (root / "payload.bin").read_bytes() == b"L" * 4096
    assert _rollback_names(root) == rollbacks_before


def test_apply_uses_frozen_snapshot_if_source_changes_after_hash_validation(root, monkeypatch):
    accepted = _make_backup(root, b"A" * 4096)
    replacement = _replacement_no_larger(root, accepted)
    (root / "payload.bin").write_bytes(b"L" * 4096)
    staged = bk.stage_restore(accepted.name, source_root=str(root))
    assert staged["ok"]
    original_snapshot = archive_safe.snapshot_archive
    swaps = []
    replacement_bytes = []

    @contextlib.contextmanager
    def swap_after_snapshot(path, *, max_bytes, expected_sha256=None):
        with original_snapshot(path, max_bytes=max_bytes,
                               expected_sha256=expected_sha256) as snapshot:
            if Path(path) == accepted and not swaps:
                replacement_bytes.append(_same_size_mtime_replace(accepted, replacement))
                swaps.append(True)
            yield snapshot

    monkeypatch.setattr(archive_safe, "snapshot_archive", swap_after_snapshot)
    result = bk.apply_pending_restore(source_root=str(root), runtime_wait=0, sleep=lambda _: None)

    assert swaps == [True]
    assert result["status"] == "restored"
    assert (root / "payload.bin").read_bytes() == b"A" * 4096
    assert accepted.read_bytes() == replacement_bytes[0]


def test_legacy_accepted_task_without_digest_is_refused(root):
    accepted = _make_backup(root, b"A" * 4096)
    task = SimpleNamespace(payload={"name": accepted.name,
                                    "bytes": accepted.stat().st_size,
                                    "mtime": accepted.stat().st_mtime},
                           id=43, decided_by="owner")

    result = asyncio.run(bk.apply_approved(task, None))

    assert result == {"status": "refused", "reason": "backup_changed"}
    assert bk.pending_restore(root) is None


def test_legacy_staged_marker_without_digest_is_rejected(root):
    accepted = _make_backup(root, b"A" * 4096)
    (root / "payload.bin").write_bytes(b"L" * 4096)
    assert bk.stage_restore(accepted.name, source_root=str(root))["ok"]
    marker = bk.default_backup_dir(root) / bk._PENDING_RESTORE
    legacy = bk._read_json(marker)
    legacy.pop("sha256")
    bk._write_json(marker, legacy)
    rollbacks_before = _rollback_names(root)

    result = bk.apply_pending_restore(source_root=str(root), runtime_wait=0, sleep=lambda _: None)

    assert result["status"] == "failed" and result["reason"] == "backup_changed"
    assert (root / "payload.bin").read_bytes() == b"L" * 4096
    assert _rollback_names(root) == rollbacks_before


def test_snapshot_bound_covers_local_full_and_encrypted_backup_inputs(monkeypatch):
    default_bound = bk._archive_snapshot_max_bytes()
    assert default_bound > bk.UPLOAD_MAX_BYTES
    monkeypatch.setattr(bk, "backup_limits", lambda: archive_safe.ArchiveLimits(
        max_members=1_000_000, max_bytes=64 * 1024 ** 3))
    expanded_with_headers = 64 * 1024 ** 3 + 1_000_000 * 1024 + 320 * 1024 ** 2
    assert bk._archive_snapshot_max_bytes() == expanded_with_headers * 2


def test_encrypted_archive_stage_and_apply_keep_enc_snapshot_suffix(root, monkeypatch):
    key = base64.urlsafe_b64encode(b"v52-backup-encrypted-test-key!!").decode()
    monkeypatch.setenv("JARVIS_BACKUP_KEY", key)
    monkeypatch.setenv("JARVIS_KEY_DIR", str(root.parent / "keys"))
    source = root.parent / "encrypted-source"
    source.mkdir()
    (source / "payload.bin").write_bytes(b"E" * 4096)
    made = bk.create_backup(source_root=str(source), out_dir=str(bk.default_backup_dir(root)),
                            key=key)
    archive = Path(made["archive"])
    assert archive.name.endswith(".tar.gz.enc")
    observed_suffixes = []
    original_snapshot = archive_safe.snapshot_archive

    @contextlib.contextmanager
    def record_snapshot_suffix(path, *, max_bytes, expected_sha256=None):
        with original_snapshot(path, max_bytes=max_bytes,
                               expected_sha256=expected_sha256) as snapshot:
            observed_suffixes.append(snapshot.path.name.endswith(".tar.gz.enc"))
            yield snapshot

    monkeypatch.setattr(archive_safe, "snapshot_archive", record_snapshot_suffix)
    card = bk.restore_request(archive.name)
    staged = bk.stage_restore(archive.name, source_root=str(root), key=key,
                              expected_sha256=card["payload"]["sha256"])
    assert staged["ok"] and staged["sha256"] == card["payload"]["sha256"]
    result = bk.apply_pending_restore(source_root=str(root), key=key,
                                      runtime_wait=0, sleep=lambda _: None)

    assert result["status"] == "restored"
    assert (root / "payload.bin").read_bytes() == b"E" * 4096
    assert observed_suffixes and all(observed_suffixes)
