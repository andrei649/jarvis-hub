"""Selected checkpoint undo and explicit current-state-bound overwrite."""

from __future__ import annotations

import pytest

from agents.core.file_checkpoint_history import FileCheckpointHistory
from agents.core.file_tools import FileScope, FileTools, SnapshotStore


def group(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    store = SnapshotStore(tmp_path / "snapshots")
    return root, FileCheckpointHistory(store, FileScope([root]))


@pytest.mark.asyncio
async def test_real_filetools_safe_skip_and_force_exact_edited_preundo(tmp_path):
    root, history = group(tmp_path)
    target = root / "note.txt"
    target.write_text("owner before", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=history.snapshots)
    assert (await tools.write_file({"path": str(target), "content": "agent"}, approved=True))["ok"]
    entry_id = tools.history.list_entries()[0]["id"]
    target.write_text("later owner edit", encoding="utf-8")
    assert tools.history.plan_restore(entry_id)["reason"] == "changed_since_checkpoint"
    plan = tools.history.plan_restore(entry_id, force=True)
    assert plan["ok"] is True and plan["current"][0] is True
    assert plan["current"][2] == len(b"later owner edit")
    assert tools.history.restore(entry_id, force=True)["reason"] == "expected_current_required"
    assert tools.history.restore(entry_id, force=True,
                                 expected_current=[True, "0" * 64, 1, 0o644])["ok"] is False
    assert target.read_text() == "later owner edit"
    restored = tools.history.restore(entry_id, force=True,
                                     expected_current=plan["current"],
                                     effect_check=lambda: True)
    assert restored["ok"] is True and target.read_text() == "owner before"
    undo = tools.history.load_snapshot(restored["undo_snapshot_ref"])
    assert undo is not None and tools.history.snapshot_blob(undo) == b"later owner edit"


def test_group_selection_force_then_remaining_preserves_prior_undo(tmp_path):
    root, history = group(tmp_path)
    modified = root / "modified.txt"
    deleted = root / "deleted.txt"
    created = root / "created.txt"
    modified.write_text("old", encoding="utf-8")
    deleted.write_text("recover", encoding="utf-8")
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    modified.write_text("agent", encoding="utf-8")
    deleted.unlink()
    created.write_text("agent-created", encoding="utf-8")
    assert history.finish_scope(capture["id"], reaped=True)["status"] == "finished"
    modified.write_text("owner-edited", encoding="utf-8")
    plan = history.plan_group_restore(capture["id"], paths=["modified.txt"], force=True)
    assert plan["ok"] is True and set(plan["current"]) == {"modified.txt"}
    first = history.restore_group(capture["id"], paths=["modified.txt"], force=True,
                                  expected_current=plan["current"], effect_check=lambda: True)
    assert first["ok"] is True and first["status"] == "partial"
    assert first["remaining"] == 2 and modified.read_text() == "old"
    first_ref = first["undo_snapshot_refs"][0]
    assert history.snapshot_blob(history.load_snapshot(first_ref)) == b"owner-edited"
    assert deleted.exists() is False and created.read_text() == "agent-created"
    assert history.restore_group(capture["id"], paths=["modified.txt"])["ok"] is False
    second = history.restore_group(capture["id"], paths=["deleted.txt", "created.txt"])
    assert second["ok"] is True and second["status"] == "restored"
    assert second["remaining"] == 0 and second["restored"] == 2
    assert deleted.read_text() == "recover" and not created.exists()
    assert history.snapshot_blob(history.load_snapshot(first_ref)) == b"owner-edited"


@pytest.mark.parametrize("selection", [
    ["modified.txt", "modified.txt"], ["/modified.txt"], ["../modified.txt"],
    ["./modified.txt"], ["modified.txt/"], ["missing.txt"],
    ["modified.txt", "missing.txt"], ["modified.txt"] * 501,
    [], "modified.txt",
])
def test_invalid_group_selection_refuses_all_effects(tmp_path, selection):
    root, history = group(tmp_path)
    target = root / "modified.txt"
    target.write_text("old", encoding="utf-8")
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    target.write_text("new", encoding="utf-8")
    history.finish_scope(capture["id"], reaped=True)
    plan = history.plan_group_restore(capture["id"], paths=selection)
    assert plan["ok"] is False
    result = history.restore_group(capture["id"], paths=selection)
    assert result["ok"] is False and target.read_text() == "new"


def test_force_group_plan_drift_and_revoked_effect_check_never_overwrite(tmp_path):
    root, history = group(tmp_path)
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("agent", encoding="utf-8")
    history.finish_scope(capture["id"], reaped=True)
    note.write_text("owner one", encoding="utf-8")
    plan = history.plan_group_restore(capture["id"], paths=["note.txt"], force=True)
    note.write_text("owner two", encoding="utf-8")
    assert history.restore_group(capture["id"], paths=["note.txt"], force=True,
                                 expected_current=plan["current"])["ok"] is False
    fresh = history.plan_group_restore(capture["id"], paths=["note.txt"], force=True)
    blocked = history.restore_group(capture["id"], paths=["note.txt"], force=True,
                                    expected_current=fresh["current"],
                                    effect_check=lambda: False)
    assert blocked["ok"] is False and note.read_text() == "owner two"


def test_force_refuses_root_swap_symlink_hardlink_oversize_and_incomplete(tmp_path):
    root, history = group(tmp_path)
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("agent", encoding="utf-8")
    history.finish_scope(capture["id"], reaped=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    note.unlink()
    note.symlink_to(outside)
    assert history.plan_group_restore(capture["id"], force=True)["eligible"] == 0
    note.unlink()
    note.write_text("owner", encoding="utf-8")
    (root / "second-link.txt").hardlink_to(note)
    assert history.plan_group_restore(capture["id"], force=True)["eligible"] == 0
    (root / "second-link.txt").unlink()
    with note.open("wb") as handle:
        handle.truncate(17 * 1024 * 1024)
    assert history.plan_group_restore(capture["id"], force=True)["eligible"] == 0
    note.write_text("agent", encoding="utf-8")
    moved = tmp_path / "moved"
    root.rename(moved)
    root.mkdir()
    (root / "note.txt").write_text("agent", encoding="utf-8")
    assert history.plan_group_restore(capture["id"], force=True)["reason"] == "scope_changed"
    assert history.restore_group(capture["id"], force=True, expected_current={})["ok"] is False
    assert outside.read_text() == "outside"


def test_force_requires_exact_bool_and_current_fingerprint_shape(tmp_path):
    root, history = group(tmp_path)
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("agent", encoding="utf-8")
    history.finish_scope(capture["id"], reaped=True)
    for invalid in (0, 1, None, "true"):
        assert history.plan_group_restore(capture["id"], force=invalid)["ok"] is False
        assert history.restore_group(capture["id"], force=invalid)["ok"] is False
    plan = history.plan_group_restore(capture["id"], force=True)
    for invalid in (None, {}, {"note.txt": [True, "0" * 64, 0, 0o644]},
                    {**plan["current"], "extra.txt": plan["current"]["note.txt"]}):
        assert history.restore_group(capture["id"], force=True,
                                     expected_current=invalid)["ok"] is False
    assert note.read_text() == "agent"


def test_partial_group_with_uncertain_prepared_row_cannot_resume(tmp_path):
    root, history = group(tmp_path)
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("agent", encoding="utf-8")
    history.finish_scope(capture["id"], reaped=True)
    with history._connection() as db:
        db.execute("UPDATE groups SET status='partial' WHERE id=?", (capture["id"],))
        db.execute("""UPDATE group_files SET restore_status='prepared'
            WHERE group_id=? AND path='note.txt'""", (capture["id"],))
        db.commit()
    assert history.plan_group_restore(capture["id"])["reason"] == "uncertain_restore"
    assert history.restore_group(capture["id"])["reason"] == "uncertain_restore"
    assert note.read_text() == "agent"


def test_group_effect_checker_revocation_after_first_file_is_partial_and_resumable(tmp_path):
    root, history = group(tmp_path)
    first, second = root / "a.txt", root / "b.txt"
    first.write_text("old-a", encoding="utf-8")
    second.write_text("old-b", encoding="utf-8")
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    first.write_text("new-a", encoding="utf-8")
    second.write_text("new-b", encoding="utf-8")
    history.finish_scope(capture["id"], reaped=True)
    calls = []

    def current():
        calls.append(True)
        return len(calls) == 1

    partial = history.restore_group(capture["id"], effect_check=current)
    assert partial["ok"] is False and partial["reason"] == "effect_check_failed"
    assert partial["status"] == "partial" and partial["restored"] == 1
    assert partial["remaining"] == 1 and len(calls) == 2
    assert first.read_text() == "old-a" and second.read_text() == "new-b"
    remaining = history.restore_group(capture["id"], paths=["b.txt"],
                                      effect_check=lambda: True)
    assert remaining["status"] == "restored" and remaining["remaining"] == 0
    assert second.read_text() == "old-b"


def test_force_accepts_bounded_larger_owner_edit_and_preserves_mode(tmp_path):
    root, history = group(tmp_path)
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    note.chmod(0o600)
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("agent", encoding="utf-8")
    note.chmod(0o644)
    history.finish_scope(capture["id"], reaped=True)
    owner_bytes = b"owner" * 200_000
    note.write_bytes(owner_bytes)
    note.chmod(0o700)
    plan = history.plan_group_restore(capture["id"], paths=["note.txt"], force=True)
    assert plan["eligible"] == 1 and plan["current"]["note.txt"][2] == len(owner_bytes)
    assert plan["current"]["note.txt"][3] == 0o700
    restored = history.restore_group(capture["id"], paths=["note.txt"], force=True,
                                     expected_current=plan["current"], effect_check=lambda: True)
    assert restored["ok"] is True and note.read_text() == "before"
    assert note.stat().st_mode & 0o777 == 0o600
    undo = history.load_snapshot(restored["undo_snapshot_refs"][0])
    assert undo is not None and undo.mode == 0o700
    assert history.snapshot_blob(undo) == owner_bytes


@pytest.mark.asyncio
async def test_single_force_drift_and_effect_revocation_leave_applied_state(tmp_path):
    root, history = group(tmp_path)
    target = root / "note.txt"
    target.write_text("before", encoding="utf-8")
    tools = FileTools(FileScope([root]), snapshots=history.snapshots)
    assert (await tools.write_file({"path": str(target), "content": "agent"}, approved=True))["ok"]
    entry_id = tools.history.list_entries()[0]["id"]
    target.write_text("owner one", encoding="utf-8")
    plan = tools.history.plan_restore(entry_id, force=True)
    target.write_text("owner two", encoding="utf-8")
    assert tools.history.restore(entry_id, force=True,
                                 expected_current=plan["current"])["reason"] == "changed_since_plan"
    fresh = tools.history.plan_restore(entry_id, force=True)
    denied = tools.history.restore(entry_id, force=True,
                                   expected_current=fresh["current"],
                                   effect_check=lambda: False)
    assert denied["reason"] == "effect_check_failed"
    assert target.read_text() == "owner two"
    assert tools.history.plan_restore(entry_id, force=True)["ok"] is True
