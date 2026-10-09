"""H011 maintenance effects require live authority and an exact fresh preview."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from agents.core.checkpoint_inventory import CheckpointInventory
from agents.core.checkpoint_maintenance import CheckpointMaintenance
from agents.core.commands import Principal
from agents.core.file_checkpoint_history import FileCheckpointHistory, _locked
from agents.core.file_tools import FileScope, SnapshotStore

ADMIN = Principal(channel="web", admin=True)
GUEST = Principal(channel="web", admin=False)


def key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def environment(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("before")
    store = SnapshotStore(tmp_path / "store")
    scope = FileScope([root])
    return root, note, store, scope, FileCheckpointHistory(store, scope)


def add_file(root, note, store, history, *, status="applied", ident=None):
    generic = store.take(note)
    info = root.stat()
    with _locked(store.directory), history._connection() as db:
        if ident is None:
            cursor = db.execute("""INSERT INTO entries
                (path,root,root_dev,root_ino,op,pre_ref,status,post_existed,
                 post_sha,post_size,post_mode,source_kind,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(note), str(root), info.st_dev, info.st_ino, "write",
                 generic.ref, status, 1, key("after"), 5, 0o644, "filetools", 1.0))
            ident = cursor.lastrowid
        else:
            db.execute("""INSERT INTO entries
                (id,path,root,root_dev,root_ino,op,pre_ref,status,post_existed,
                 post_sha,post_size,post_mode,source_kind,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ident, str(note), str(root), info.st_dev, info.st_ino, "write",
                 generic.ref, status, 1, key("after"), 5, 0o644, "filetools", float(ident)))
        db.commit()
    return f"file:{ident}", generic.ref


def preview(store, scope, action="clear", *, keep_orphans=True):
    return CheckpointInventory(store, scope).maintenance_preview(
        ADMIN, action, limit=500, keep_orphans=keep_orphans,
    )


def apply(executor, plan, *, action="clear", op="one", project=None,
          keep_orphans=True, authority_check=lambda: True, candidates=None,
          generation=None, principal=ADMIN):
    return executor.apply(
        principal, action=action, project=project,
        generation=plan["generation"] if generation is None else generation,
        candidates=([row["id"] for row in plan["candidates"]]
                    if candidates is None else candidates),
        operation_key=key(op), keep_orphans=keep_orphans,
        authority_check=authority_check,
    )


def count(db_path, table):
    with sqlite3.connect(db_path) as db:
        return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_exact_approved_file_and_group_rows_removed_but_shared_data_retained(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    file_id, generic_ref = add_file(root, note, store, history)
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("after")
    assert history.finish_scope(capture["id"], reaped=True, run_id=capture["run_id"])["status"] == "finished"
    plan = preview(store, scope)
    assert {row["id"] for row in plan["candidates"]} == {file_id, "group:" + capture["id"]}
    result = apply(CheckpointMaintenance(store, scope), plan)
    assert result["ok"] is True and result["status"] == "ok"
    assert result["removed"] == [row["id"] for row in plan["candidates"]]
    assert result["removed_counts"] == {
        "entries": 1, "groups": 1, "group_files": 1,
        "group_exclusions": 0, "group_runs": 1,
    }
    assert result["retained_shared_data"] is True
    db_path = store.directory / "history.sqlite3"
    assert all(count(db_path, table) == 0 for table in
               ("entries", "groups", "group_files", "group_exclusions", "group_runs"))
    assert store.load(generic_ref) is not None
    assert note.read_text() == "after"


def test_nonadmin_and_missing_authority_refuse_before_probe(tmp_path, monkeypatch):
    root, note, store, scope, history = environment(tmp_path)
    executor = CheckpointMaintenance(store, scope)
    old_stat = os.stat
    def forbidden(path, *args, **kwargs):
        if str(path).startswith(str(tmp_path)):
            raise AssertionError("unauthorized path probe")
        return old_stat(path, *args, **kwargs)
    monkeypatch.setattr(os, "stat", forbidden)
    with pytest.raises(PermissionError, match="admin_required"):
        executor.apply(GUEST, action="clear", project=None, generation=key("g"),
                       candidates=[], operation_key=key("o"), authority_check=lambda: True)
    result = executor.apply(ADMIN, action="clear", project=None, generation=key("g"),
                            candidates=[], operation_key=key("o"), authority_check=None)
    assert result["status"] == "refused" and result["reason"] == "authority_required"
    monkeypatch.undo()
    assert not store.directory.exists()


def test_stale_index_and_added_candidate_refuse_without_deletion(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    first, _ = add_file(root, note, store, history)
    plan = preview(store, scope)
    second, _ = add_file(root, note, store, history)
    result = apply(CheckpointMaintenance(store, scope), plan)
    assert result["status"] == "refused" and result["reason"] == "stale_preview"
    assert count(store.directory / "history.sqlite3", "entries") == 2
    assert second != first


def test_changed_root_refuses_even_if_candidate_id_unchanged(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history)
    plan = preview(store, scope)
    root.rename(tmp_path / "moved")
    root.mkdir()
    result = apply(CheckpointMaintenance(store, scope), plan)
    assert result["status"] == "refused"
    assert count(store.directory / "history.sqlite3", "entries") == 1


def test_two_instances_replay_completed_key_and_reject_intent_collision(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history)
    plan = preview(store, scope)
    first = apply(CheckpointMaintenance(store, scope), plan, op="same")
    second = apply(CheckpointMaintenance(store, scope), plan, op="same")
    assert first["ok"] and second == first
    collision = apply(CheckpointMaintenance(store, scope), plan, op="same", action="prune")
    assert collision["status"] == "refused" and collision["reason"] == "operation_key_collision"
    assert count(store.directory / "history.sqlite3", "checkpoint_maintenance_ops") == 1


def test_two_concurrent_instances_share_one_completed_claim(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history)
    plan = preview(store, scope)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(apply, CheckpointMaintenance(store, scope), plan,
                               op="concurrent") for _ in range(2)]
        results = [future.result() for future in futures]
    assert results[0] == results[1] and results[0]["ok"] is True
    assert results[0]["removed"] == ["file:1"]
    assert count(store.directory / "history.sqlite3", "checkpoint_maintenance_ops") == 1


def test_revocation_after_claim_records_uncertain_and_never_deletes(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history)
    plan = preview(store, scope)
    calls = 0
    def authority():
        nonlocal calls
        calls += 1
        return calls == 1
    result = apply(CheckpointMaintenance(store, scope), plan, op="revoked", authority_check=authority)
    assert result["status"] == "partial" and result["journal_state"] == "uncertain"
    assert count(store.directory / "history.sqlite3", "entries") == 1
    again = apply(CheckpointMaintenance(store, scope), plan, op="revoked")
    assert again["status"] == "refused" and again["reason"] == "operation_uncertain"


def test_exception_after_claim_is_durable_uncertain_on_restart(tmp_path, monkeypatch):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history)
    plan = preview(store, scope)
    executor = CheckpointMaintenance(store, scope)
    def crash(*_args, **_kwargs):
        raise RuntimeError("synthetic crash")
    monkeypatch.setattr(executor, "_delete_rows", crash, raising=False)
    result = apply(executor, plan, op="crash")
    assert result["status"] == "partial" and result["journal_state"] == "uncertain"
    again = apply(CheckpointMaintenance(store, scope), plan, op="crash")
    assert again["status"] == "refused" and again["reason"] == "operation_uncertain"
    assert count(store.directory / "history.sqlite3", "entries") == 1


def test_prior_running_claim_refuses_after_restart(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history)
    plan = preview(store, scope)
    executor = CheckpointMaintenance(store, scope)
    ids = [row["id"] for row in plan["candidates"]]
    intent = executor._intent("clear", None, plan["generation"], ids, True)
    with _locked(store.directory), sqlite3.connect(store.directory / "history.sqlite3") as db:
        from agents.core.checkpoint_maintenance import _JOURNAL
        db.execute(_JOURNAL)
        db.execute("INSERT INTO checkpoint_maintenance_ops "
                   "(operation_key,intent_sha,state,created_at) VALUES (?,?,'running',1)",
                   (key("running"), intent))
    result = apply(CheckpointMaintenance(store, scope), plan, op="running")
    assert result["status"] == "refused" and result["reason"] == "operation_uncertain"
    assert count(store.directory / "history.sqlite3", "entries") == 1


def test_mutated_row_during_second_authority_check_becomes_uncertain(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history)
    plan = preview(store, scope)
    calls = 0
    def authority():
        nonlocal calls
        calls += 1
        if calls == 2:
            with sqlite3.connect(store.directory / "history.sqlite3") as db:
                db.execute("UPDATE entries SET pre_ref=? WHERE id=1", (key("changed"),))
        return True
    result = apply(CheckpointMaintenance(store, scope), plan, op="mutated",
                   authority_check=authority)
    assert result["status"] == "partial" and result["journal_state"] == "uncertain"
    assert count(store.directory / "history.sqlite3", "entries") == 1


def test_revocation_during_final_inventory_scan_refuses_before_deletion(
    tmp_path, monkeypatch,
):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history)
    plan = preview(store, scope)
    live = {"authorized": True}
    scans = 0
    original = CheckpointInventory._inventory

    def revoke_on_final_scan(self, project):
        nonlocal scans
        result = original(self, project)
        scans += 1
        if scans == 4:
            live["authorized"] = False
        return result

    monkeypatch.setattr(CheckpointInventory, "_inventory", revoke_on_final_scan)
    result = apply(CheckpointMaintenance(store, scope), plan, op="late-revoke",
                   authority_check=lambda: live["authorized"])
    assert scans >= 4
    assert result["status"] == "partial" and result["journal_state"] == "uncertain"
    assert count(store.directory / "history.sqlite3", "entries") == 1


def test_index_change_after_final_scan_is_detected_in_write_transaction(
    tmp_path, monkeypatch,
):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history)
    plan = preview(store, scope)
    scans = 0
    original = CheckpointInventory._inventory

    def mutate_after_final_scan(self, project):
        nonlocal scans
        result = original(self, project)
        scans += 1
        if scans == 4:
            with sqlite3.connect(store.directory / "history.sqlite3") as db:
                db.execute("UPDATE entries SET pre_ref=? WHERE id=1", (key("late"),))
        return result

    monkeypatch.setattr(CheckpointInventory, "_inventory", mutate_after_final_scan)
    result = apply(CheckpointMaintenance(store, scope), plan, op="late-index-change")
    assert scans >= 4
    assert result["status"] == "partial" and result["journal_state"] == "uncertain"
    assert count(store.directory / "history.sqlite3", "entries") == 1


def test_final_authority_checker_cannot_mutate_index_inside_write_transaction(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history)
    plan = preview(store, scope)
    calls = 0

    def authority():
        nonlocal calls
        calls += 1
        if calls == 3:
            with sqlite3.connect(store.directory / "history.sqlite3", timeout=0) as db:
                db.execute("UPDATE entries SET pre_ref=? WHERE id=1", (key("hook"),))
        return True

    result = apply(CheckpointMaintenance(store, scope), plan, op="hook-write",
                   authority_check=authority)
    assert calls == 3
    assert result["status"] == "partial" and result["journal_state"] == "uncertain"
    assert count(store.directory / "history.sqlite3", "entries") == 1


def test_prepared_file_and_active_group_block_clear(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history, status="prepared")
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="active")
    assert capture["status"] == "ready"
    plan = preview(store, scope)
    result = apply(CheckpointMaintenance(store, scope), plan)
    assert result["status"] == "refused" and result["reason"] == "incomplete_history"
    assert count(store.directory / "history.sqlite3", "entries") == 1
    assert count(store.directory / "history.sqlite3", "groups") == 1


def test_unreachable_orphan_needs_explicit_keep_orphans_false(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history)
    root.rename(tmp_path / "disconnected")
    plan = preview(store, scope, "prune", keep_orphans=False)
    assert [row["root_state"] for row in plan["candidates"]] == ["unreachable"]
    result = apply(CheckpointMaintenance(store, scope), plan, action="prune",
                   keep_orphans=False)
    assert result["ok"] is True and result["removed"] == ["file:1"]
    assert count(store.directory / "history.sqlite3", "entries") == 0


def test_fresh_changed_and_unconfigured_roots_refuse(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history)
    root.rename(tmp_path / "moved")
    root.mkdir()
    changed_plan = preview(store, scope)
    changed = apply(CheckpointMaintenance(store, scope), changed_plan, op="changed")
    assert changed["status"] == "refused" and changed["reason"] == "root_untrusted"

    other = tmp_path / "other"
    other.mkdir()
    other_note = other / "note.txt"
    other_note.write_text("other")
    add_file(other, other_note, store, history)
    unconfigured_plan = preview(store, scope)
    unconfigured = apply(CheckpointMaintenance(store, scope), unconfigured_plan,
                         op="unconfigured")
    assert unconfigured["status"] == "refused" and unconfigured["reason"] == "root_untrusted"
    assert count(store.directory / "history.sqlite3", "entries") == 2


def test_malformed_storage_refuses_and_retains_history(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    add_file(root, note, store, history)
    plan = preview(store, scope)
    outside = tmp_path / "outside"
    outside.write_text("private")
    (store.directory / "bad-link").symlink_to(outside)
    result = apply(CheckpointMaintenance(store, scope), plan)
    assert result["status"] == "refused"
    assert count(store.directory / "history.sqlite3", "entries") == 1
    assert outside.read_text() == "private"


def test_empty_absent_store_noop_does_not_create_directory(tmp_path):
    root, note, store, scope, history = environment(tmp_path)
    plan = preview(store, scope)
    result = apply(CheckpointMaintenance(store, scope), plan)
    assert result["ok"] is True and result["removed"] == []
    assert not store.directory.exists()


def test_invalid_key_refuses_before_probe(tmp_path, monkeypatch):
    root, note, store, scope, history = environment(tmp_path)
    executor = CheckpointMaintenance(store, scope)
    def unexpected(*_a, **_kw):
        raise AssertionError("invalid key probed storage")
    monkeypatch.setattr(sqlite3, "connect", unexpected)
    with pytest.raises(ValueError, match="invalid_operation_key"):
        executor.apply(ADMIN, action="clear", project=None, generation=key("g"),
                       candidates=[], operation_key="NOT-A-SHA", authority_check=lambda: True)
    with pytest.raises(ValueError, match="invalid_candidates"):
        executor.apply(ADMIN, action="clear", project=None, generation=key("g"),
                       candidates=["file:" + "9" * 500], operation_key=key("o"),
                       authority_check=lambda: True)
