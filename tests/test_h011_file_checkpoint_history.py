"""H011 history is produced by real governed FileTools effects."""

import asyncio
import hashlib
import os
from pathlib import Path

import pytest

from agents.core import file_checkpoint_history as history_module
from agents.core.file_tools import FileScope, FileTools, SnapshotStore


@pytest.mark.asyncio
async def test_real_write_and_delete_are_browsable_with_bounded_diff(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("before\n", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))

    write = await tools.write_file({"path": str(target), "content": "after\n"}, approved=True)
    assert write["ok"] is True
    delete = await tools.delete_file({"path": str(target)}, approved=True)
    assert delete["ok"] is True

    entries = tools.history.list_entries()
    assert [(row["op"], row["status"]) for row in entries] == [
        ("delete", "applied"), ("write", "applied")
    ]
    assert entries[0]["pre_ref"] == delete["snapshot_ref"]
    assert entries[1]["pre_ref"] == write["snapshot_ref"]
    assert [row["id"] for row in tools.history.list_entries(path=str(target))] == [
        row["id"] for row in entries
    ]
    assert tools.history.list_entries(path="../outside.txt") == []
    diff = tools.history.diff(entries[1]["id"])
    assert diff["ok"] is True
    assert "-before" in diff["diff"] and "+after" in diff["diff"]


@pytest.mark.asyncio
@pytest.mark.parametrize("image", ["before", "after"])
async def test_diff_rejects_oversized_stored_blob_before_bulk_read(tmp_path, monkeypatch, image):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("before", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    assert (await tools.write_file({"path": str(target), "content": "after"}, approved=True))["ok"]
    row = tools.history.list_entries()[0]
    sha = tools.snapshots.load(row["pre_ref"]).blob_sha if image == "before" else row["post_sha"]
    blob = tools.snapshots.directory / "blobs" / sha
    with blob.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024)
    original = Path.read_bytes

    def refuse_bulk_read(path):
        if path == blob:
            pytest.fail("oversized stored blob was read without a size bound")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", refuse_bulk_read)
    assert tools.history.diff(row["id"]) == {"ok": False, "reason": "snapshot_changed"}


@pytest.mark.asyncio
async def test_capture_rejects_oversized_existing_blob_before_bulk_read(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_bytes(b"before")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    blob = tools.snapshots.directory / "blobs" / hashlib.sha256(b"before").hexdigest()
    blob.parent.mkdir(parents=True)
    with blob.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024)
    original = Path.read_bytes

    def refuse_bulk_read(path):
        if path == blob:
            pytest.fail("capture read a corrupt stored blob without a size bound")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", refuse_bulk_read)
    result = await tools.write_file({"path": str(target), "content": "after"}, approved=True)
    assert result["ok"] is False and result["reason"] == "snapshot_failed"
    assert target.read_bytes() == b"before"
    assert tools.history.list_entries() == []


@pytest.mark.asyncio
async def test_real_created_file_is_in_history(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    result = await tools.write_file({"path": "new.txt", "content": "created"}, approved=True)
    assert result["ok"] is True
    assert tools.history.list_entries()[0]["post_sha"]


@pytest.mark.asyncio
async def test_change_after_snapshot_refuses_physical_write(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("before", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))

    def change_after_snapshot(op, path, payload, *, approved):
        target.write_text("owner intervened", encoding="utf-8")
        return None

    tools._authorize = change_after_snapshot
    result = await tools.write_file({"path": str(target), "content": "agent"}, approved=True)
    assert result["ok"] is False and result["reason"] == "changed_since_snapshot"
    assert target.read_text(encoding="utf-8") == "owner intervened"
    assert tools.history.list_entries()[0]["status"] == "prepared"


@pytest.mark.asyncio
async def test_root_replaced_during_authorization_refuses_same_bytes_write(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("original", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    moved = tmp_path / "original-root"

    def replace_root_after_snapshot(op, path, payload, *, approved):
        root.rename(moved)
        root.mkdir()
        target.write_text("original", encoding="utf-8")
        return None

    tools._authorize = replace_root_after_snapshot
    result = await tools.write_file({"path": str(target), "content": "agent"}, approved=True)
    assert result["ok"] is False and result["reason"] == "root_changed"
    assert target.read_text(encoding="utf-8") == "original"
    assert (moved / "note.txt").read_text(encoding="utf-8") == "original"


@pytest.mark.asyncio
async def test_effect_failure_remains_incomplete_not_restorable(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("before", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))

    def fail_replace(*args):
        raise OSError("synthetic physical failure")

    monkeypatch.setattr("agents.core.file_checkpoint_history._replace", fail_replace)
    result = await tools.write_file({"path": str(target), "content": "agent"}, approved=True)
    assert result["ok"] is False
    entry = tools.history.list_entries()[0]
    assert entry["status"] == "prepared"
    assert tools.history.restore(entry["id"]) == {"ok": False, "reason": "unknown_checkpoint"}
    assert target.read_text(encoding="utf-8") == "before"


@pytest.mark.asyncio
async def test_effect_after_replace_with_failed_fsync_is_reported_uncertain(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("before", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    real_replace = history_module._replace

    def replace_then_fail(*args):
        real_replace(*args)
        raise OSError("synthetic fsync failure after replacement")

    monkeypatch.setattr(history_module, "_replace", replace_then_fail)
    result = await tools.write_file({"path": str(target), "content": "after"}, approved=True)
    assert result["ok"] is False and result["reason"] == "effect_state_incomplete"
    assert target.read_text(encoding="utf-8") == "after"
    assert tools.history.list_entries()[0]["status"] == "prepared"


@pytest.mark.asyncio
async def test_replaced_large_file_is_refused_before_read(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("small", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))

    real_fdopen = history_module.os.fdopen

    def refuse_bulk_read(fd, *args, **kwargs):
        if "r" in args[0] and os.fstat(fd).st_size > history_module.MAX_CAPTURE_BYTES:
            pytest.fail("large replacement was opened for a bulk read")
        return real_fdopen(fd, *args, **kwargs)

    def replace_after_snapshot(op, path, payload, *, approved):
        with target.open("wb") as handle:
            handle.truncate(64 * 1024 * 1024)
        monkeypatch.setattr(history_module.os, "fdopen", refuse_bulk_read)
        return None

    tools._authorize = replace_after_snapshot
    result = await tools.write_file({"path": str(target), "content": "agent"}, approved=True)
    assert result["ok"] is False
    assert target.stat().st_size == 64 * 1024 * 1024


@pytest.mark.asyncio
async def test_diff_redacts_secrets_and_honors_utf8_byte_bound(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("password=beforesecret\nowner@example.com\n", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    result = await tools.write_file({"path": str(target),
                                    "content": "password=aftersecret\nowner@example.com\n"
                                    + "é" * 20}, approved=True)
    assert result["ok"]
    entry_id = tools.history.list_entries()[0]["id"]
    diff = tools.history.diff(entry_id, max_bytes=120)
    assert diff["ok"] is True
    assert "beforesecret" not in diff["diff"] and "aftersecret" not in diff["diff"]
    assert "owner@example.com" not in diff["diff"]
    assert len(diff["diff"].encode("utf-8")) <= 120


@pytest.mark.asyncio
async def test_oversized_preimage_refuses_without_effect(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "large.txt"
    with target.open("wb") as handle:
        handle.truncate(history_module.MAX_CAPTURE_BYTES + 1)
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    result = await tools.write_file({"path": str(target), "content": "agent"}, approved=True)
    assert result == {"ok": False, "reason": "checkpoint_too_large"}
    assert target.stat().st_size == history_module.MAX_CAPTURE_BYTES + 1
    assert tools.history.list_entries() == []


@pytest.mark.asyncio
async def test_unsupported_history_platform_keeps_governed_file_write(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("old", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    monkeypatch.setattr(history_module, "HISTORY_SUPPORTED", False)
    result = await tools.write_file({"path": str(target), "content": "new"}, approved=True)
    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "new"
    assert tools.history.list_entries() == []


@pytest.mark.asyncio
async def test_fifo_preimage_refuses_without_blocking(tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO unavailable")
    root = tmp_path / "workspace"
    root.mkdir()
    fifo = root / "pipe"
    os.mkfifo(fifo)
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    result = await asyncio.wait_for(
        tools.delete_file({"path": str(fifo)}, approved=True), timeout=2
    )
    assert result == {"ok": False, "reason": "not_a_file"}
    assert fifo.exists() and tools.history.list_entries() == []
