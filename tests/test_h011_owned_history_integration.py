"""Checkpoint payload ownership follows real authorized effects, preserving undo."""

import hashlib
import os
import shutil
from pathlib import Path

import pytest

from agents.core import file_checkpoint_history as history_module
from agents.core.file_checkpoint_history import FileCheckpointHistory
from agents.core.file_tools import FileScope, FileTools, SnapshotStore


def _tools(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_bytes(b"before\n")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    return root, target, tools


def _owned(tools):
    return tools.snapshots.directory / "checkpoint_payloads-v1"


@pytest.mark.asyncio
async def test_authorized_file_effect_owns_payloads_and_preserves_generic_undo(tmp_path):
    _, target, tools = _tools(tmp_path)
    result = await tools.write_file({"path": str(target), "content": "after\n"}, approved=True)
    assert result["ok"]
    row = tools.history.list_entries()[0]
    generic = tools.snapshots.load(result["snapshot_ref"])
    assert generic is not None and generic.ref == row["pre_ref"]
    assert (_owned(tools) / "records" / f"{generic.ref}.json").read_bytes() == generic.canonical().encode()
    assert (_owned(tools) / "blobs" / generic.blob_sha).read_bytes() == b"before\n"
    assert (_owned(tools) / "blobs" / row["post_sha"]).read_bytes() == b"after\n"
    assert not (tools.snapshots.directory / "blobs" / row["post_sha"]).exists()
    # Existing FileTools returned references remain ordinary undo references.
    assert tools.restore_snapshot(result["snapshot_ref"]) is True
    assert target.read_bytes() == b"before\n"


@pytest.mark.asyncio
async def test_denied_file_effect_does_not_initialize_owned_payload_namespace(tmp_path):
    _, target, tools = _tools(tmp_path)
    tools._authorize = lambda *args, **kwargs: "synthetic_denial"
    result = await tools.write_file({"path": str(target), "content": "after\n"}, approved=True)
    assert result["ok"] is False and result["reason"] == "synthetic_denial"
    assert target.read_bytes() == b"before\n"
    assert not _owned(tools).exists()
    assert tools.history.list_entries() == []


def test_terminal_capture_and_restore_undo_are_owned_not_generic(tmp_path):
    root, target, tools = _tools(tmp_path)
    unrelated = tools.snapshots.take_captured(target, existed=True, data=b"unrelated", mode=0o644)
    generic_files = {str(p.relative_to(tools.snapshots.directory)): p.read_bytes()
                     for p in tools.snapshots.directory.rglob("*") if p.is_file()}
    capture = tools.history.begin_scope(root, source_kind="terminal_invocation", source_key="synthetic")
    assert capture["status"] == "ready"
    target.write_bytes(b"after\n")
    assert tools.history.finish_scope(capture["id"], reaped=True)["status"] == "finished"
    result = tools.history.restore_group(capture["id"])
    assert result["ok"] and result["restored"] == 1
    assert target.read_bytes() == b"before\n"
    assert result["undo_snapshot_refs"]
    for ref in result["undo_snapshot_refs"]:
        assert (_owned(tools) / "records" / f"{ref}.json").is_file()
        assert tools.snapshots.load(ref) is None
        snap = tools.history.load_snapshot(ref)
        assert snap is not None and tools.history.snapshot_blob(snap) == b"after\n"
    assert tools.snapshots.blob(unrelated) == b"unrelated"
    for path, data in generic_files.items():
        assert (tools.snapshots.directory / path).read_bytes() == data
    assert list(tools.snapshots.directory.glob("*.json")) == [
        tools.snapshots.directory / f"{unrelated.ref}.json"
    ]


@pytest.mark.asyncio
async def test_file_restore_undo_can_be_read_after_history_restart(tmp_path):
    _, target, tools = _tools(tmp_path)
    assert (await tools.write_file({"path": str(target), "content": "after\n"}, approved=True))["ok"]
    row = tools.history.list_entries()[0]
    result = tools.history.restore(row["id"])
    assert result["ok"] and target.read_bytes() == b"before\n"
    ref = result["undo_snapshot_ref"]
    assert (_owned(tools) / "records" / f"{ref}.json").is_file()
    restarted = FileCheckpointHistory(tools.snapshots, tools.scope)
    undo = restarted.load_snapshot(ref)
    assert undo is not None and restarted.snapshot_blob(undo) == b"after\n"


@pytest.mark.asyncio
async def test_legacy_index_can_restore_without_creating_owned_data(tmp_path):
    _, target, tools = _tools(tmp_path)
    assert (await tools.write_file({"path": str(target), "content": "after\n"}, approved=True))["ok"]
    row = tools.history.list_entries()[0]
    if _owned(tools).exists():
        # This is the persisted pre-upgrade layout, with no owned format marker.
        for record in (_owned(tools) / "records").glob("*.json"):
            if record.name != "format.json":
                shutil.copyfile(record, tools.snapshots.directory / record.name)
        for blob in (_owned(tools) / "blobs").iterdir():
            shutil.copyfile(blob, tools.snapshots.directory / "blobs" / blob.name)
        shutil.rmtree(_owned(tools))
    restarted = FileCheckpointHistory(tools.snapshots, tools.scope)
    assert restarted.diff(row["id"])["ok"]
    assert restarted.plan_restore(row["id"])["ok"]
    assert not _owned(tools).exists(), "read-only legacy preview must not migrate data"
    assert restarted.restore(row["id"])["ok"]
    assert target.read_bytes() == b"before\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["record", "record_symlink", "record_hardlink", "blob", "blob_oversize"])
async def test_invalid_owned_payload_is_never_masked_by_valid_generic_copy(tmp_path, damage):
    _, target, tools = _tools(tmp_path)
    result = await tools.write_file({"path": str(target), "content": "after\n"}, approved=True)
    assert result["ok"]
    row = tools.history.list_entries()[0]
    snap = tools.snapshots.load(row["pre_ref"])
    assert snap is not None and tools.snapshots.blob(snap) == b"before\n"
    record = _owned(tools) / "records" / f"{snap.ref}.json"
    blob = _owned(tools) / "blobs" / snap.blob_sha
    assert record.is_file() and blob.is_file()
    if damage == "record":
        record.write_bytes(b"{}")
    elif damage == "record_symlink":
        record.unlink()
        record.symlink_to(tools.snapshots.directory / record.name)
    elif damage == "record_hardlink":
        record.unlink()
        os.link(tools.snapshots.directory / record.name, record)
    elif damage == "blob":
        blob.write_bytes(b"forged\n")
    else:
        with blob.open("wb") as handle:
            handle.truncate(17 * 1024 * 1024)
    assert tools.history.diff(row["id"]) == {"ok": False, "reason": "snapshot_changed"}
    assert tools.history.restore(row["id"]) == {"ok": False, "reason": "snapshot_changed"}
    assert target.read_bytes() == b"after\n"


@pytest.mark.asyncio
async def test_unknown_owned_namespace_refuses_before_file_effect(tmp_path):
    _, target, tools = _tools(tmp_path)
    _owned(tools).mkdir(parents=True)
    unknown = _owned(tools) / "unknown-owner-data"
    unknown.write_bytes(b"retain me")
    result = await tools.write_file({"path": str(target), "content": "after\n"}, approved=True)
    assert result["ok"] is False
    assert target.read_bytes() == b"before\n"
    assert unknown.read_bytes() == b"retain me"
    assert tools.history.list_entries() == []


@pytest.mark.asyncio
async def test_legacy_corrupt_preimage_record_is_bounded_and_refused(tmp_path, monkeypatch):
    _, target, tools = _tools(tmp_path)
    assert (await tools.write_file({"path": str(target), "content": "after\n"}, approved=True))["ok"]
    row = tools.history.list_entries()[0]
    if _owned(tools).exists():
        shutil.rmtree(_owned(tools))
    record = tools.snapshots.directory / f"{row['pre_ref']}.json"
    with record.open("wb") as handle:
        handle.truncate(1024 * 1024)
    original = Path.read_text

    def refuse_unbounded_read(path, *args, **kwargs):
        if path == record:
            pytest.fail("legacy metadata was read through an unbounded path API")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", refuse_unbounded_read)
    assert tools.history.plan_restore(row["id"]) == {"ok": False, "reason": "snapshot_changed"}
    assert not _owned(tools).exists()


@pytest.mark.asyncio
async def test_postimage_hash_is_owned_and_deduplicated_across_files(tmp_path):
    root, target, tools = _tools(tmp_path)
    for path in (target, root / "second.txt"):
        assert (await tools.write_file({"path": str(path), "content": "shared"}, approved=True))["ok"]
    sha = hashlib.sha256(b"shared").hexdigest()
    assert (_owned(tools) / "blobs" / sha).read_bytes() == b"shared"
    assert [p.name for p in (_owned(tools) / "blobs").iterdir()].count(sha) == 1


def test_history_lock_cannot_create_lock_in_swapped_symlink_root(tmp_path, monkeypatch):
    store = tmp_path / "snapshots"
    store.mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    original = os.open
    swapped = False

    def swap_before_lock_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and Path(path).name == "history.lock":
            swapped = True
            store.rename(tmp_path / "original-store")
            store.symlink_to(unrelated, target_is_directory=True)
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(history_module.os, "open", swap_before_lock_open)
    entered = False
    try:
        with history_module._locked(store):
            entered = True
    except (OSError, history_module.CheckpointRefusal):
        pass
    assert swapped
    assert not (unrelated / "history.lock").exists()
    assert entered is False
