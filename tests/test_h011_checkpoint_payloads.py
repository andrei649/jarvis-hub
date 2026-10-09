"""Owned checkpoint bytes are bounded, private, identifiable and independent of generic refs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agents.core.checkpoint_payloads import CheckpointPayloadStore, PayloadRefusal
from agents.core.file_checkpoint_history import _locked
from agents.core.file_tools import SnapshotStore


def owned(tmp_path):
    generic = SnapshotStore(tmp_path / "snapshots")
    service = CheckpointPayloadStore(generic)
    return generic, service, generic.directory / "checkpoint_payloads-v1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def test_real_captured_bytes_roundtrip_and_complete_physical_inventory(tmp_path):
    generic, service, directory = owned(tmp_path)
    target = tmp_path / "workspace" / "note.txt"
    snap = service.take_captured(target, existed=True, data=b"private preimage", mode=0o640,
                                 now=123.5)
    assert snap.path == str(target) and snap.ref == sha(snap.canonical().encode())
    assert service.load(snap.ref) == snap
    assert service.blob(snap.blob_sha, snap.size) == b"private preimage"
    view = service.inventory()
    assert view["complete"] is True and view["state"] == "ready"
    assert view["records"][snap.ref]["blob_sha"] == snap.blob_sha
    assert view["records"][snap.ref]["path"] == str(target)
    assert view["records"][snap.ref]["created_at"] == 123.5
    assert view["blobs"][snap.blob_sha]["physical_size"] == snap.size
    assert view["physical_bytes"] == (directory / "format.json").stat().st_size + sum(
        p.stat().st_size for part in ("records", "blobs") for p in (directory / part).iterdir())
    assert set(view["identity"]) == {"generic", "namespace", "records", "blobs", "marker"}
    assert (directory / "records" / f"{snap.ref}.json").is_file()
    assert (directory / "blobs" / snap.blob_sha).is_file()
    assert not (generic.directory / f"{snap.ref}.json").exists()
    assert not (generic.directory / "blobs" / snap.blob_sha).exists()
    for path in (directory / "format.json", directory / "records" / f"{snap.ref}.json",
                 directory / "blobs" / snap.blob_sha):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_nlink == 1


def test_absent_preimage_and_deduplicated_blob(tmp_path):
    _generic, service, directory = owned(tmp_path)
    first = service.take_captured(tmp_path / "one.txt", existed=False, data=b"", mode=0,
                                  now=1.0)
    second = service.take_captured(tmp_path / "two.txt", existed=False, data=b"", mode=0,
                                   now=2.0)
    assert not first.existed and first.size == 0 and first.mode == 0
    assert service.load(first.ref) == first and service.load(second.ref) == second
    assert first.ref != second.ref and first.blob_sha == second.blob_sha == sha(b"")
    assert service.blob(sha(b""), 0) == b""
    assert len(list((directory / "blobs").iterdir())) == 1
    assert len(service.inventory()["records"]) == 2
    assert service.put_blob(b"same") == service.put_blob(b"same") == sha(b"same")
    assert len(list((directory / "blobs").iterdir())) == 2


def test_readonly_absent_load_blob_inventory_create_nothing(tmp_path):
    generic, service, _directory = owned(tmp_path)
    assert service.load("a" * 64) is None
    assert service.blob("b" * 64, 3) is None
    assert service.inventory() == {"complete": True, "state": "absent", "physical_bytes": 0,
                                   "record_bytes": 0, "blob_bytes": 0, "marker_bytes": 0,
                                   "records": {}, "blobs": {}, "identity": {}}
    assert not generic.directory.exists()


@pytest.mark.parametrize("kwargs", [
    {"existed": True, "data": "text", "mode": 0o600},
    {"existed": 1, "data": b"x", "mode": 0o600},
    {"existed": False, "data": b"x", "mode": 0},
    {"existed": False, "data": b"", "mode": 0o600},
    {"existed": True, "data": b"x", "mode": True},
    {"existed": True, "data": b"x", "mode": 0o10000},
    {"existed": True, "data": b"x", "mode": 0o600, "now": float("nan")},
    {"existed": True, "data": b"x", "mode": 0o600, "now": float("inf")},
    {"existed": True, "data": b"x" * (16 * 1024 * 1024 + 1), "mode": 0o600},
])
def test_invalid_capture_refuses_before_any_store_effect(tmp_path, kwargs):
    generic, service, _directory = owned(tmp_path)
    with pytest.raises(PayloadRefusal):
        service.take_captured(tmp_path / "target", **kwargs)
    assert not generic.directory.exists()


def test_invalid_refs_and_blob_inputs_are_refusals_not_absence(tmp_path):
    generic, service, _directory = owned(tmp_path)
    for bad in ("bad", "A" * 64, None, True):
        with pytest.raises(PayloadRefusal):
            service.load(bad)
        with pytest.raises(PayloadRefusal):
            service.blob(bad, 1)
    for bad in (-1, True, 16 * 1024 * 1024 + 1):
        with pytest.raises(PayloadRefusal):
            service.blob("a" * 64, bad)
    with pytest.raises(PayloadRefusal):
        service.put_blob("not bytes")
    assert not generic.directory.exists()


def test_unmarked_unknown_namespace_and_invalid_marker_refuse(tmp_path):
    _generic, service, directory = owned(tmp_path)
    directory.mkdir(parents=True, mode=0o700)
    (directory / "unknown").write_bytes(b"untrusted")
    with pytest.raises(PayloadRefusal):
        service.put_blob(b"hello")
    assert not (directory / "format.json").exists()
    (directory / "unknown").unlink()
    assert service.put_blob(b"hello") == sha(b"hello")
    (directory / "format.json").write_bytes(b'{}')
    with pytest.raises(PayloadRefusal):
        service.inventory()
    with pytest.raises(PayloadRefusal):
        service.blob(sha(b"hello"), 5)


def test_corrupt_record_blob_and_oversize_are_not_reported_absent(tmp_path):
    _generic, service, directory = owned(tmp_path)
    snap = service.take_captured(tmp_path / "target", existed=True, data=b"true", mode=0o600)
    record = directory / "records" / f"{snap.ref}.json"
    record.write_bytes(b"{")
    with pytest.raises(PayloadRefusal):
        service.load(snap.ref)
    with pytest.raises(PayloadRefusal):
        service.inventory()
    record.write_bytes(snap.canonical().encode())
    blob = directory / "blobs" / snap.blob_sha
    blob.write_bytes(b"fake")
    with pytest.raises(PayloadRefusal):
        service.blob(snap.blob_sha, snap.size)
    with pytest.raises(PayloadRefusal):
        service.put_blob(b"true")
    blob.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    with pytest.raises(PayloadRefusal):
        service.blob(snap.blob_sha, snap.size)
    record.write_bytes(b"x" * (64 * 1024 + 1))
    with pytest.raises(PayloadRefusal):
        service.load(snap.ref)


def test_symlink_and_hardlink_assets_refuse_without_touching_outside(tmp_path):
    _generic, service, directory = owned(tmp_path)
    snap = service.take_captured(tmp_path / "target", existed=True, data=b"payload", mode=0o600)
    blob = directory / "blobs" / snap.blob_sha
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    blob.unlink()
    blob.symlink_to(outside)
    with pytest.raises(PayloadRefusal):
        service.blob(snap.blob_sha, snap.size)
    with pytest.raises(PayloadRefusal):
        service.put_blob(b"payload")
    assert outside.read_bytes() == b"outside"
    blob.unlink()
    blob.write_bytes(b"payload")
    extra = tmp_path / "extra-link"
    os.link(blob, extra)
    with pytest.raises(PayloadRefusal):
        service.blob(snap.blob_sha, snap.size)
    extra.unlink()
    record = directory / "records" / f"{snap.ref}.json"
    os.link(record, extra)
    with pytest.raises(PayloadRefusal):
        service.load(snap.ref)


def test_generic_root_and_owned_child_symlinks_refuse_before_write(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    generic = SnapshotStore(tmp_path / "snapshots")
    generic.directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PayloadRefusal):
        CheckpointPayloadStore(generic).put_blob(b"secret")
    assert list(outside.iterdir()) == []
    generic.directory.unlink()
    generic.directory.mkdir()
    (generic.directory / "checkpoint_payloads-v1").symlink_to(outside,
                                                                 target_is_directory=True)
    with pytest.raises(PayloadRefusal):
        CheckpointPayloadStore(generic).put_blob(b"secret")
    assert list(outside.iterdir()) == []


def test_root_and_child_identity_swap_refuse_even_with_copied_valid_bytes(tmp_path):
    generic, service, directory = owned(tmp_path)
    service.put_blob(b"one")
    moved_root = tmp_path / "old-snapshots"
    generic.directory.rename(moved_root)
    shutil.copytree(moved_root, generic.directory)
    with pytest.raises(PayloadRefusal):
        service.put_blob(b"two")
    assert not (generic.directory / "checkpoint_payloads-v1" / "blobs" / sha(b"two")).exists()

    # A fresh instance accepts the current marked root but pins its child identities.
    fresh = CheckpointPayloadStore(generic)
    assert fresh.blob(sha(b"one"), 3) == b"one"
    blobs = directory / "blobs"
    moved_blobs = directory / "old-blobs"
    blobs.rename(moved_blobs)
    shutil.copytree(moved_blobs, blobs)
    with pytest.raises(PayloadRefusal):
        fresh.put_blob(b"three")
    assert not (blobs / sha(b"three")).exists()


def test_existing_history_lock_serializes_owned_writes(tmp_path):
    generic, service, _directory = owned(tmp_path)
    began = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with _locked(generic.directory):
            def worker():
                began.set()
                return service.put_blob(b"delayed")

            future = pool.submit(worker)
            assert began.wait(timeout=2)
            time.sleep(0.05)
            assert not future.done()
        assert future.result(timeout=2) == sha(b"delayed")


def test_child_swap_during_write_cannot_redirect_blob_outside_owned_dir(tmp_path, monkeypatch):
    from agents.core import checkpoint_payloads as module

    _generic, service, directory = owned(tmp_path)
    service.put_blob(b"initial")
    outside = tmp_path / "outside"
    outside.mkdir()
    original = module._install
    swapped = False

    def swap_before_install(parent, name, data, *, cap):
        nonlocal swapped
        if not swapped and name == sha(b"next"):
            swapped = True
            (directory / "blobs").rename(directory / "old-blobs")
            (directory / "blobs").symlink_to(outside, target_is_directory=True)
        return original(parent, name, data, cap=cap)

    monkeypatch.setattr(module, "_install", swap_before_install)
    with pytest.raises(PayloadRefusal):
        service.put_blob(b"next")
    assert swapped and list(outside.iterdir()) == []
    assert (directory / "old-blobs" / sha(b"next")).read_bytes() == b"next"


def test_negative_timestamp_is_rejected_before_initialization(tmp_path):
    _generic, service, directory = owned(tmp_path)
    with pytest.raises(PayloadRefusal):
        service.take_captured(tmp_path / "note.txt", existed=True, data=b"note",
                              mode=0o644, now=-1)
    assert not directory.exists()


@pytest.mark.parametrize("timestamp", [-1.0, 10 ** 400])
def test_invalid_stored_timestamp_is_a_payload_refusal(tmp_path, timestamp):
    _generic, service, directory = owned(tmp_path)
    snap = service.take_captured(tmp_path / "note.txt", existed=True, data=b"note", mode=0o644)
    raw = json.loads(snap.canonical())
    raw["created_at"] = timestamp
    data = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ref = sha(data)
    record = directory / "records" / f"{ref}.json"
    record.write_bytes(data)
    record.chmod(0o600)
    with pytest.raises(PayloadRefusal):
        service.load(ref)
