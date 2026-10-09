"""Group retention shares generic SnapshotStore refs without deleting them."""

from __future__ import annotations

import pytest

from agents.core.file_checkpoint_history import FileCheckpointHistory
from agents.core.file_tools import FileScope, SnapshotStore


def test_excluded_tree_is_never_a_restore_deletion_candidate(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    vendor = root / "vendor"
    vendor.mkdir()
    (vendor / "package.txt").write_text("original", encoding="utf-8")
    normal = root / "normal.txt"
    normal.write_text("original", encoding="utf-8")
    history = FileCheckpointHistory(SnapshotStore(tmp_path / "store"), FileScope([root]))
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    (vendor / "package.txt").unlink()
    normal.unlink()
    result = history.finish_scope(capture["id"], reaped=True)
    assert result["deleted"] == 1 and result["excluded"] >= 1
    plan = history.plan_group_restore(capture["id"])
    assert [item["path"] for item in plan["paths"]] == ["normal.txt"]
    restored = history.restore_group(capture["id"])
    assert restored["status"] == "partial" and normal.read_text() == "original"
    assert not (vendor / "package.txt").exists()


def test_group_prune_keeps_generic_refs_and_remaining_group_postblobs(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("original", encoding="utf-8")
    store = SnapshotStore(tmp_path / "store")
    history = FileCheckpointHistory(store, FileScope([root]))
    generic = store.take(note)
    first = history.begin_scope(root, source_kind="terminal_invocation", source_key="first")
    note.write_text("first post", encoding="utf-8")
    assert history.finish_scope(first["id"], reaped=True)["status"] == "finished"
    second = history.begin_scope(root, source_kind="terminal_invocation", source_key="second")
    note.write_text("second post", encoding="utf-8")
    assert history.finish_scope(second["id"], reaped=True)["status"] == "finished"
    dry = history.prune_groups([first["id"]], dry_run=True)
    assert dry["removed_groups"] == 1
    assert len(history.list_groups()) == 2
    actual = history.prune_groups([first["id"]], dry_run=False)
    assert actual["removed_groups"] == 1
    assert store.load(generic.ref) is not None
    assert history.plan_group_restore(second["id"])["ok"] is True


def test_oversized_hardlinked_and_symlinked_preimages_never_become_created(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    large = root / "large.txt"
    with large.open("wb") as handle:
        handle.truncate(17 * 1024 * 1024)
    linked = root / "linked.txt"
    linked.write_text("shared", encoding="utf-8")
    (root / "other-link.txt").hardlink_to(linked)
    target = tmp_path / "outside.txt"
    target.write_text("outside", encoding="utf-8")
    (root / "symlink.txt").symlink_to(target)
    history = FileCheckpointHistory(SnapshotStore(tmp_path / "store"), FileScope([root]))
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    large.write_text("small now", encoding="utf-8")
    linked.write_text("changed", encoding="utf-8")
    (root / "symlink.txt").unlink()
    result = history.finish_scope(capture["id"], reaped=True)
    assert result["created"] == 0 and result["excluded"] >= 3
    assert history.plan_group_restore(capture["id"])["paths"] == []


def test_overlapping_same_turn_groups_refuse_composed_restore(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    history = FileCheckpointHistory(SnapshotStore(tmp_path / "store"), FileScope([root]))
    first = history.begin_scope(root, source_kind="terminal_turn", source_key="same-turn")
    second = history.begin_scope(root, source_kind="terminal_turn", source_key="same-turn")
    assert first["id"] != second["id"]
    note.write_text("after", encoding="utf-8")
    assert history.finish_scope(first["id"], reaped=True)["status"] == "finished"
    assert history.finish_scope(second["id"], reaped=True)["status"] == "finished"
    assert history.plan_group_restore(first["id"])["reason"] == "overlapping_scope"
    assert history.plan_group_restore(second["id"])["reason"] == "overlapping_scope"


def test_checkpoint_store_and_runtime_subtrees_are_never_undo_targets(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    runtime = root / "runtime"
    runtime.mkdir()
    sentinel = runtime / "session.txt"
    sentinel.write_text("runtime state", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(runtime))
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    store = SnapshotStore(root / "checkpoints")
    generic = store.take(note)
    history = FileCheckpointHistory(store, FileScope([root]))
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("after", encoding="utf-8")
    finished = history.finish_scope(capture["id"], reaped=True)
    assert finished["status"] == "finished"
    with history._connection() as db:
        rows = db.execute("SELECT path FROM group_files WHERE group_id=?",
                          (capture["id"],)).fetchall()
        exclusions = db.execute("SELECT path FROM group_exclusions WHERE group_id=?",
                                (capture["id"],)).fetchall()
    paths = [row[0] for row in rows]
    assert paths == ["note.txt"]
    assert {"checkpoints", "runtime"}.issubset({row[0] for row in exclusions})
    assert history.restore_group(capture["id"])["status"] == "partial"
    assert note.read_text() == "before"
    assert store.load(generic.ref) is not None
    assert sentinel.read_text() == "runtime state"
    assert (store.directory / "history.sqlite3").is_file()


def test_private_root_refusal_preserves_dedicated_runtime_workspace(tmp_path, monkeypatch):
    from agents.core.file_checkpoint_history import CheckpointRefusal

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(runtime))
    store = SnapshotStore(runtime / "file_tools" / "snapshots")
    private = FileCheckpointHistory(store, FileScope([runtime]))
    with pytest.raises(CheckpointRefusal, match="private_scope"):
        private.begin_scope(runtime, source_kind="terminal_invocation", source_key="test")
    store_child = store.directory / "nested"
    store_child.mkdir(parents=True)
    inside_store = FileCheckpointHistory(store, FileScope([store_child]))
    with pytest.raises(CheckpointRefusal, match="private_scope"):
        inside_store.begin_scope(store_child, source_kind="terminal_invocation",
                                 source_key="test")

    workspace = runtime / "workspace"
    workspace.mkdir()
    note = workspace / "note.txt"
    note.write_text("before", encoding="utf-8")
    allowed = FileCheckpointHistory(store, FileScope([workspace]))
    capture = allowed.begin_scope(workspace, source_kind="terminal_invocation",
                                  source_key="test")
    note.write_text("after", encoding="utf-8")
    assert allowed.finish_scope(capture["id"], reaped=True)["status"] == "finished"
