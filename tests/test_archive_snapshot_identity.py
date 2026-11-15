"""Snapshot identity covers pathname replacement and in-place source mutation."""
from __future__ import annotations

import hashlib
import io
import os
import stat
import tarfile
from pathlib import Path

import pytest

from agents.core import archive_safe as safe


def _tar(path: Path, content: bytes):
    with tarfile.open(path, 'w') as archive:
        info = tarfile.TarInfo('config.txt')
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))


def test_same_private_bytes_are_validated_and_extracted_after_source_path_swap(tmp_path):
    source = tmp_path / 'backup.tar.gz'
    _tar(source, b'old')
    original = source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    with safe.snapshot_archive(source, max_bytes=len(original), expected_sha256=digest) as snapshot:
        assert snapshot.sha256 == digest and snapshot.size == len(original)
        assert snapshot.path.name == source.name
        _, listed = safe.tar_listing(snapshot.path, compression='*')
        assert listed == [('config.txt', 'file', 0o644)]
        replacement = tmp_path / 'replacement'
        _tar(replacement, b'new')
        os.replace(replacement, source)
        target = tmp_path / 'target'
        safe.extract_tar_path(snapshot.path, target)
        assert (target / 'config.txt').read_bytes() == b'old'
        snapshot_path = snapshot.path
    assert not snapshot_path.exists()
    assert source.exists()


def test_in_place_write_to_original_after_validation_does_not_change_snapshot(tmp_path):
    source = tmp_path / 'backup.tar'
    _tar(source, b'old')
    before = source.stat()
    with safe.snapshot_archive(source, max_bytes=source.stat().st_size) as snapshot:
        safe.tar_listing(snapshot.path, compression='*')
        replacement = tmp_path / 'replacement.tar'
        _tar(replacement, b'new')
        with source.open('r+b') as output:
            output.write(replacement.read_bytes())
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert source.stat().st_size == before.st_size
        assert source.stat().st_mtime_ns == before.st_mtime_ns
        safe.extract_tar_path(snapshot.path, tmp_path / 'target')
        assert (tmp_path / 'target/config.txt').read_bytes() == b'old'


def test_expected_digest_rejects_equal_size_equal_mtime_substitution_before_use(tmp_path):
    source = tmp_path / 'backup.tar'
    _tar(source, b'old')
    before = source.stat()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    _tar(source, b'new')
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert source.stat().st_size == before.st_size
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    with pytest.raises(safe.ArchiveRejected, match='expected digest'), \
            safe.snapshot_archive(source, max_bytes=before.st_size, expected_sha256=digest):
        pytest.fail('changed archive must not reach validation/use')


def test_snapshot_keeps_encryption_suffix_and_private_permissions(tmp_path):
    source = tmp_path / 'jarvis-backup-test.tar.gz.enc'
    source.write_bytes(b'ciphertext')
    with safe.snapshot_archive(source, max_bytes=10) as snapshot:
        assert snapshot.path.name == source.name and snapshot.path.suffix == '.enc'
        assert snapshot.path.read_bytes() == b'ciphertext'
        if os.name != 'nt':
            assert stat.S_IMODE(snapshot.path.stat().st_mode) == 0o600
            assert stat.S_IMODE(snapshot.path.parent.stat().st_mode) == 0o700


def test_snapshot_rejects_declared_oversize(tmp_path):
    source = tmp_path / 'archive'
    source.write_bytes(b'123')
    with pytest.raises(safe.ArchiveRejected, match='bytes cap'), \
            safe.snapshot_archive(source, max_bytes=2):
        pytest.fail('oversize snapshot was exposed')


@pytest.mark.parametrize('maximum', [-1, True, 1.5, float('nan'), '3'])
def test_snapshot_requires_nonnegative_integer_byte_limit(tmp_path, maximum):
    source = tmp_path / 'archive'
    source.write_bytes(b'')
    with pytest.raises(ValueError, match='byte limit'), \
            safe.snapshot_archive(source, max_bytes=maximum):
        pass


@pytest.mark.parametrize('digest', ['', 'f'*63, 'G'*64, b'a'*64, 5])
def test_snapshot_requires_exact_lowercase_hex_digest(tmp_path, digest):
    source = tmp_path / 'archive'
    source.write_bytes(b'')
    with pytest.raises(ValueError, match='digest'), \
            safe.snapshot_archive(source, max_bytes=0, expected_sha256=digest):
        pass


def test_snapshot_accepts_empty_file_with_zero_cap(tmp_path):
    source = tmp_path / 'empty'
    source.write_bytes(b'')
    with safe.snapshot_archive(source, max_bytes=0) as snapshot:
        assert snapshot.size == 0
        assert snapshot.sha256 == hashlib.sha256(b'').hexdigest()


def test_snapshot_refuses_symlink_and_directory_sources(tmp_path):
    source = tmp_path / 'archive'
    source.write_bytes(b'x')
    link = tmp_path / 'link'
    link.symlink_to(source)
    for path in (link, tmp_path):
        with pytest.raises(safe.ArchiveRejected, match='regular file'), \
                safe.snapshot_archive(path, max_bytes=1):
            pass


@pytest.mark.skipif(os.name == 'nt', reason='POSIX FIFO API')
def test_snapshot_refuses_fifo_without_blocking(tmp_path):
    source = tmp_path / 'fifo'
    os.mkfifo(source)
    with pytest.raises(safe.ArchiveRejected, match='regular file'), \
            safe.snapshot_archive(source, max_bytes=1):
        pass


def test_snapshot_detects_in_place_mutation_during_copy(tmp_path, monkeypatch):
    source = tmp_path / 'archive'
    source.write_bytes(b'abcd')
    monkeypatch.setattr(safe, '_CHUNK', 2)
    original_read = safe.os.read
    calls = []

    def mutate_after_first_read(descriptor, count):
        block = original_read(descriptor, count)
        if not calls:
            with source.open('r+b') as output:
                output.seek(2)
                output.write(b'zz')
            calls.append(True)
        return block

    monkeypatch.setattr(safe.os, 'read', mutate_after_first_read)
    with pytest.raises(safe.ArchiveRejected, match='changed while copying'), \
            safe.snapshot_archive(source, max_bytes=4):
        pass


def test_snapshot_cleans_up_when_consumer_raises(tmp_path):
    source = tmp_path / 'archive'
    source.write_bytes(b'abc')
    with pytest.raises(RuntimeError, match='consumer'), \
            safe.snapshot_archive(source, max_bytes=3) as snapshot:
        captured = snapshot.path.parent
        raise RuntimeError('consumer')
    assert not captured.exists()
    assert source.read_bytes() == b'abc'


def test_growth_during_copy_hits_streamed_cap_and_removes_private_copy(tmp_path, monkeypatch):
    source = tmp_path / 'archive'
    source.write_bytes(b'ab')
    monkeypatch.setattr(safe, '_CHUNK', 1)
    original_read = safe.os.read
    original_temporary = safe.tempfile.TemporaryDirectory
    private_dirs = []
    mutated = []

    def private_directory(**kwargs):
        context = original_temporary(dir=tmp_path, **kwargs)
        private_dirs.append(Path(context.name))
        return context

    def grow_after_read(descriptor, count):
        block = original_read(descriptor, count)
        if not mutated:
            with source.open('ab') as output:
                output.write(b'c')
            mutated.append(True)
        return block

    monkeypatch.setattr(safe.tempfile, 'TemporaryDirectory', private_directory)
    monkeypatch.setattr(safe.os, 'read', grow_after_read)
    with pytest.raises(safe.ArchiveRejected, match='bytes cap'), \
            safe.snapshot_archive(source, max_bytes=2):
        pytest.fail('growing source must not yield a snapshot')
    assert private_dirs and all(not path.exists() for path in private_dirs)
