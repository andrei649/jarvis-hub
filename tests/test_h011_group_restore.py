"""A scoped terminal observation may undo only unchanged postimages."""

from __future__ import annotations

from agents.core.file_checkpoint_history import FileCheckpointHistory
from agents.core.file_tools import FileScope, SnapshotStore


def _history(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    return root, FileCheckpointHistory(
        SnapshotStore(tmp_path / "snapshots"), FileScope([root])
    )


def test_group_restore_skips_later_user_edit_and_keeps_pre_undo(tmp_path):
    root, history = _history(tmp_path)
    modified = root / "modified.txt"
    deleted = root / "deleted.txt"
    created = root / "created.txt"
    modified.write_text("old", encoding="utf-8")
    deleted.write_text("recover me", encoding="utf-8")
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    modified.write_text("command", encoding="utf-8")
    deleted.unlink()
    created.write_text("new", encoding="utf-8")
    finished = history.finish_scope(capture["id"], reaped=True)
    assert (finished["modified"], finished["created"], finished["deleted"]) == (1, 1, 1)

    modified.write_text("later user edit", encoding="utf-8")
    plan = history.plan_group_restore(capture["id"])
    assert plan["ok"] is True and plan["eligible"] == 2 and plan["skipped"] == 1
    result = history.restore_group(capture["id"])
    assert result["ok"] is True and result["status"] == "partial"
    assert result["restored"] == 2 and result["skipped"] == 1
    assert modified.read_text() == "later user edit"
    assert deleted.read_text() == "recover me"
    assert not created.exists()
    assert len(result["undo_group_id"]) == 32
    assert len(result["undo_snapshot_refs"]) == 2
    assert all(history.load_snapshot(ref) is not None for ref in result["undo_snapshot_refs"])


def test_group_restore_refuses_replaced_root_even_with_same_bytes(tmp_path):
    root, history = _history(tmp_path)
    note = root / "note.txt"
    note.write_text("old", encoding="utf-8")
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("new", encoding="utf-8")
    assert history.finish_scope(capture["id"], reaped=True)["status"] == "finished"
    root.rename(tmp_path / "original-root")
    root.mkdir()
    note.write_text("new", encoding="utf-8")
    assert history.plan_group_restore(capture["id"])["reason"] == "scope_changed"
    assert history.restore_group(capture["id"])["reason"] == "scope_changed"
    assert note.read_text() == "new"


def test_group_diff_is_redacted_and_utf8_byte_bounded(tmp_path):
    root, history = _history(tmp_path)
    note = root / "note.txt"
    note.write_text("salut\n", encoding="utf-8")
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("parolă password=abcdefghijk\n", encoding="utf-8")
    history.finish_scope(capture["id"], reaped=True)
    preview = history.diff_group(capture["id"], max_bytes=48)
    assert preview["ok"] is True
    assert "abcdefghijk" not in preview["diff"]
    assert len(preview["diff"].encode("utf-8")) <= 48


def test_unknown_group_and_corrupt_postblob_cannot_restore(tmp_path):
    root, history = _history(tmp_path)
    note = root / "note.txt"
    note.write_text("old", encoding="utf-8")
    assert history.plan_group_restore("0" * 32)["reason"] == "unknown_checkpoint"
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("new", encoding="utf-8")
    history.finish_scope(capture["id"], reaped=True)
    rows = history._connection()
    with rows as db:
        post_sha = db.execute("""SELECT post_sha FROM group_files
            WHERE group_id=? AND path='note.txt'""", (capture["id"],)).fetchone()[0]
    (history.payloads.directory / "blobs" / post_sha).write_bytes(b"forged")
    plan = history.plan_group_restore(capture["id"])
    assert plan["eligible"] == 0 and plan["skipped"] == 1
    result = history.restore_group(capture["id"])
    assert result["restored"] == 0 and result["status"] == "partial"
    assert note.read_text() == "new"
