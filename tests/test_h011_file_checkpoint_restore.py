"""H011 safe lower-level restore preserves intervening owner edits."""

import pytest

from agents.core.file_tools import FileScope, FileTools, SnapshotStore


@pytest.mark.asyncio
async def test_restore_real_write_captures_preundo_and_skips_later_edit(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("original", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    assert (await tools.write_file({"path": str(target), "content": "agent"}, approved=True))["ok"]
    entry_id = tools.history.list_entries()[0]["id"]
    assert tools.history.plan_restore(entry_id)["ok"] is True

    target.write_text("owner edit", encoding="utf-8")
    assert tools.history.plan_restore(entry_id) == {
        "ok": False, "reason": "changed_since_checkpoint"
    }
    skipped = tools.history.restore(entry_id)
    assert skipped == {"ok": False, "reason": "changed_since_checkpoint"}
    assert target.read_text(encoding="utf-8") == "owner edit"

    target.write_text("agent", encoding="utf-8")
    # Undo must persist the descriptor-verified bytes, not re-open a path that
    # could be swapped to a symlink after the current-state check.
    monkeypatch.setattr(tools.snapshots, "take", lambda path: pytest.fail("path reopened"))
    restored = tools.history.restore(entry_id)
    assert restored["ok"] is True
    assert target.read_text(encoding="utf-8") == "original"
    undo = tools.history.load_snapshot(restored["undo_snapshot_ref"])
    assert undo is not None and tools.history.snapshot_blob(undo) == b"agent"


@pytest.mark.asyncio
async def test_restore_real_delete_and_creation(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("original", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    assert (await tools.delete_file({"path": str(target)}, approved=True))["ok"]
    deleted_id = tools.history.list_entries()[0]["id"]
    assert tools.history.restore(deleted_id)["ok"] is True
    assert target.read_text(encoding="utf-8") == "original"

    created = root / "created.txt"
    assert (await tools.write_file({"path": str(created), "content": "new"}, approved=True))["ok"]
    created_id = tools.history.list_entries()[0]["id"]
    assert tools.history.restore(created_id)["ok"] is True
    assert not created.exists()


@pytest.mark.asyncio
async def test_restore_refuses_replaced_scope_root(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("before", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snapshots"))
    assert (await tools.write_file({"path": str(target), "content": "after"}, approved=True))["ok"]
    entry_id = tools.history.list_entries()[0]["id"]
    moved = tmp_path / "moved"
    root.rename(moved)
    root.mkdir()
    (root / "note.txt").write_text("after", encoding="utf-8")
    assert tools.history.restore(entry_id) == {"ok": False, "reason": "scope_changed"}
    assert (root / "note.txt").read_text(encoding="utf-8") == "after"
