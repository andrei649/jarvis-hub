"""Synthetic H011 retention and owned-payload collection contracts."""

from __future__ import annotations

import hashlib
import os
import sqlite3

import pytest

from agents.core.checkpoint_commands import _parse
from agents.core.checkpoint_inventory import CheckpointInventory
from agents.core.checkpoint_maintenance import CheckpointMaintenance
from agents.core.checkpoint_operations import CheckpointOperationStore
from agents.core.checkpoint_payloads import CheckpointPayloadStore
from agents.core.commands import Principal
from agents.core.file_checkpoint_history import FileCheckpointHistory, _locked
from agents.core.file_tools import FileScope, SnapshotStore

OWNER = Principal(channel="web", admin=True)


def _key(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _add(history, payloads, root, ident, *, status="applied", data=b"shared", now=None):
    note = root / f"note-{ident}.txt"
    note.write_bytes(data)
    snap = payloads.take_captured(note, existed=True, data=data, mode=0o600,
                                  now=float(ident if now is None else now))
    post_sha = payloads.put_blob(b"post")
    info = root.stat()
    with _locked(history.snapshots.directory), history._connection() as db:
        db.execute("""INSERT INTO entries
            (id,path,root,root_dev,root_ino,op,pre_ref,status,post_existed,
             post_sha,post_size,post_mode,source_kind,created_at)
             VALUES (?,?,?,?,?,?,?,?,1,?,4,384,'filetools',?)""",
             (ident, str(note), str(root), info.st_dev, info.st_ino, "write",
              snap.ref, status, post_sha, float(ident if now is None else now)))
        db.commit()
    return snap


def _setup(tmp_path, *, two_roots=False):
    roots = [tmp_path / "one"]
    if two_roots:
        roots.append(tmp_path / "two")
    for root in roots:
        root.mkdir()
    store = SnapshotStore(tmp_path / "snapshots")
    scope = FileScope(roots)
    return roots, store, scope, FileCheckpointHistory(store, scope), CheckpointPayloadStore(store)


def test_shared_owned_blob_is_one_global_bucket_and_logical_bytes_are_not_post_bytes(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path, two_roots=True)
    first = _add(history, payloads, roots[0], 1)
    second = _add(history, payloads, roots[1], 2)
    store.take(roots[0] / "note-1.txt")
    CheckpointOperationStore(store).prepare({"kind": "synthetic_accounting"})
    view = CheckpointInventory(store, scope).status(OWNER)
    by_root = {row["root"]: row for row in view["projects"]}
    assert view["ok"] is True
    assert first.blob_sha == second.blob_sha
    assert view["owned_payloads"]["shared_bytes"] == len(b"shared") + len(b"post")
    for root, snap in zip(roots, (first, second), strict=True):
        project = by_root[str(root)]
        assert project["logical_checkpoint_bytes"] > project["observed_post_bytes"]
        assert project["unique_owned_bytes"] == payloads.inventory()["records"][snap.ref]["physical_size"]
    assert view["store"]["categories"]["index_bytes"] > 0
    assert view["store"]["categories"]["owned_payload_bytes"] == payloads.inventory()["physical_bytes"]
    assert view["store"]["categories"]["generic_snapshot_bytes"] > 0
    assert view["store"]["categories"]["operation_journal_bytes"] > 0
    assert sum(view["store"]["categories"].values()) == view["store"]["bytes"]


def test_explicit_retention_keeps_newest_and_protects_uncertain_or_changed_roots(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path)
    for ident in (1, 2, 3):
        _add(history, payloads, roots[0], ident)
    inventory = CheckpointInventory(store, scope)
    assert inventory.maintenance_preview(OWNER, "prune")["candidates"] == []
    one = inventory.maintenance_preview(OWNER, "prune", keep_last=1)
    assert [row["id"] for row in one["candidates"]] == ["file:2", "file:1"]
    assert one["generation"] != inventory.maintenance_preview(OWNER, "prune", keep_last=2)["generation"]
    with sqlite3.connect(store.directory / "history.sqlite3") as db:
        db.execute("UPDATE entries SET status='restore_incomplete' WHERE id=2")
    later = inventory.maintenance_preview(OWNER, "prune", keep_last=1)
    assert [row["id"] for row in later["candidates"]] == ["file:1"]
    assert later["protected_rows"] >= 2
    roots[0].rename(tmp_path / "moved")
    roots[0].mkdir()
    changed = inventory.maintenance_preview(OWNER, "prune", keep_last=1,
                                            include_orphans=True)
    assert changed["candidates"] == []
    assert changed["protected_rows"] == 3


def test_no_argument_prune_is_terminal_only_and_keeps_last_complete(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path)
    _add(history, payloads, roots[0], 1, status="restored")
    inventory = CheckpointInventory(store, scope)
    assert inventory.maintenance_preview(OWNER, "prune")["candidates"] == []
    _add(history, payloads, roots[0], 2, status="restored")
    preview = inventory.maintenance_preview(OWNER, "prune")
    assert [row["id"] for row in preview["candidates"]] == ["file:1"]


def test_orphan_flag_selects_unreachable_or_unconfigured_complete_only(tmp_path, monkeypatch):
    roots, store, scope, history, payloads = _setup(tmp_path)
    _add(history, payloads, roots[0], 1)
    roots[0].rename(tmp_path / "moved")
    inventory = CheckpointInventory(store, scope)
    assert inventory.maintenance_preview(OWNER, "prune")["candidates"] == []
    selected = inventory.maintenance_preview(OWNER, "prune", include_orphans=True)
    assert [row["root_state"] for row in selected["candidates"]] == ["unreachable"]
    other = tmp_path / "configured"
    other.mkdir()
    unconfigured = CheckpointInventory(store, FileScope([other]))
    original_stat = os.stat

    def no_unconfigured_probe(path, *args, **kwargs):
        if str(path) == str(roots[0]):
            raise AssertionError("unconfigured project path was probed")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", no_unconfigured_probe)
    assert unconfigured.maintenance_preview(OWNER, "prune")["candidates"] == []
    selected = unconfigured.maintenance_preview(OWNER, "prune", include_orphans=True)
    assert [row["root_state"] for row in selected["candidates"]] == ["unconfigured"]


def test_owned_gc_reclaims_only_unreferenced_assets_after_approved_clear(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path)
    first = _add(history, payloads, roots[0], 1)
    generic = store.take(roots[0] / "note-1.txt")
    inventory = CheckpointInventory(store, scope)
    plan = inventory.maintenance_preview(OWNER, "clear")
    assert plan["owned_gc"]["records"] == [first.ref]
    assert first.blob_sha in plan["owned_gc"]["blobs"]
    assert plan["reclaimable_bytes"] > 0
    result = CheckpointMaintenance(store, scope).apply(
        OWNER, action="clear", project=None, generation=plan["generation"],
        candidates=[row["id"] for row in plan["candidates"]],
        operation_key=_key("clear"), authority_check=lambda: True)
    assert result["ok"] is True, result
    assert result["removed_assets"]["records"] == [first.ref]
    assert first.blob_sha in result["removed_assets"]["blobs"]
    assert payloads.load(first.ref) is None
    assert payloads.blob(first.blob_sha, first.size) is None
    assert store.load(generic.ref) is not None
    assert (store.directory / "history.sqlite3").exists()
    assert (store.directory / "checkpoint_operations.sqlite3").exists() is False


def test_unreferenced_owned_assets_need_fresh_manual_preview_and_authority(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path)
    orphan = payloads.take_captured(roots[0] / "unused.txt", existed=True,
                                    data=b"orphan", mode=0o600, now=1)
    preview = CheckpointInventory(store, scope).maintenance_preview(OWNER, "prune")
    assert preview["candidates"] == []
    assert preview["owned_gc"]["records"] == [orphan.ref]
    refused = CheckpointMaintenance(store, scope).apply(
        OWNER, action="prune", project=None, generation=preview["generation"], candidates=[],
        operation_key=_key("orphan"), authority_check=lambda: False)
    assert refused["status"] == "refused"
    assert payloads.load(orphan.ref) is not None


def test_owned_gc_candidate_cap_refuses_incomplete_preview(tmp_path, monkeypatch):
    roots, store, scope, _history, payloads = _setup(tmp_path)
    orphan = payloads.take_captured(roots[0] / "unused.txt", existed=True,
                                    data=b"orphan", mode=0o600, now=1)
    monkeypatch.setattr("agents.core.checkpoint_inventory.MAX_GC_CANDIDATES", 1)
    preview = CheckpointInventory(store, scope).maintenance_preview(OWNER, "prune")
    assert preview["ok"] is False and preview["complete"] is False
    assert preview["owned_gc"]["complete"] is False
    assert preview["owned_gc"]["omitted"] == 1
    assert preview["reclaimable_bytes"] is None
    assert payloads.load(orphan.ref) is not None


def test_project_filter_cannot_collect_another_projects_shared_blob(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path, two_roots=True)
    old = _add(history, payloads, roots[0], 1, data=b"shared")
    _add(history, payloads, roots[0], 2, data=b"newest")
    _add(history, payloads, roots[1], 3, data=b"shared")
    preview = CheckpointInventory(store, scope).maintenance_preview(
        OWNER, "prune", project=str(roots[0]), keep_last=1)
    assert [row["id"] for row in preview["candidates"]] == ["file:1"]
    assert old.ref in preview["owned_gc"]["records"]
    assert old.blob_sha not in preview["owned_gc"]["blobs"]
    result = CheckpointMaintenance(store, scope).apply(
        OWNER, action="prune", project=str(roots[0]), generation=preview["generation"],
        candidates=["file:1"], operation_key=_key("filtered"), keep_last=1,
        authority_check=lambda: True)
    assert result["ok"] is True, result
    assert payloads.load(old.ref) is None
    assert payloads.blob(old.blob_sha, old.size) == b"shared"


def test_byte_budget_reports_unattainable_minimum_checkpoint(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path)
    for ident in (1, 2, 3):
        _add(history, payloads, roots[0], ident)
    inventory = CheckpointInventory(store, scope)
    accounting, _ = inventory._accounting(inventory._inventory(None))
    one_oldest = sum(accounting["row_logical"].values()) - accounting["row_logical"]["file:1"]
    assert [row["id"] for row in inventory.maintenance_preview(
        OWNER, "prune", max_bytes=one_oldest)["candidates"]] == ["file:1"]
    preview = inventory.maintenance_preview(OWNER, "prune", max_bytes=1)
    assert [row["id"] for row in preview["candidates"]] == ["file:2", "file:1"]
    assert preview["retention"]["bytes_basis"] == "logical_checkpoint_bytes"
    assert preview["retention"]["budget_unattainable"] is True
    assert preview["retention"]["remaining_over_bytes"] > 0


def test_post_row_unlink_failure_is_uncertain_and_fresh_preview_can_collect_leftovers(tmp_path, monkeypatch):
    roots, store, scope, history, payloads = _setup(tmp_path)
    snap = _add(history, payloads, roots[0], 1)
    executor = CheckpointMaintenance(store, scope)
    preview = CheckpointInventory(store, scope).maintenance_preview(OWNER, "clear")
    original_unlink = os.unlink

    def fail_record(path, *args, **kwargs):
        if (isinstance(path, str) and len(path) == 64 and path != snap.blob_sha
                and kwargs.get("dir_fd") is not None):
            raise OSError("synthetic unlink failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", fail_record)
    failed = executor.apply(OWNER, action="clear", project=None,
                            generation=preview["generation"], candidates=["file:1"],
                            operation_key=_key("failed"), authority_check=lambda: True)
    assert failed["status"] == "partial" and failed["journal_state"] == "uncertain"
    assert failed["removed"] == ["file:1"] and failed["removed_assets"] is None
    with sqlite3.connect(store.directory / "history.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0
    assert (payloads.directory / "records" / f"{snap.ref}.json").exists() is False
    replay = executor.apply(OWNER, action="clear", project=None,
                            generation=preview["generation"], candidates=["file:1"],
                            operation_key=_key("failed"), authority_check=lambda: True)
    assert replay["status"] == "refused" and replay["reason"] == "operation_uncertain"
    monkeypatch.setattr(os, "unlink", original_unlink)
    # The failed target is retained under an unlistable quarantine. An owner
    # manually restores this synthetic record before requesting fresh GC.
    quarantine = next(payloads.directory.glob(".nerva-gc-*"))
    quarantine.chmod(0o700)
    claimed = next(quarantine.iterdir())
    claimed.rename(payloads.directory / "records" / f"{snap.ref}.json")
    quarantine.rmdir()
    fresh = CheckpointInventory(store, scope).maintenance_preview(OWNER, "prune")
    assert fresh["candidates"] == [] and snap.ref in fresh["owned_gc"]["records"]
    completed = executor.apply(OWNER, action="prune", project=None,
                               generation=fresh["generation"], candidates=[],
                               operation_key=_key("fresh"), authority_check=lambda: True)
    assert completed["ok"] is True and snap.ref in completed["removed_assets"]["records"]


def test_missing_referenced_owned_record_keeps_blob_and_unknown_reclaimable_bytes(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path)
    snap = _add(history, payloads, roots[0], 1)
    (payloads.directory / "records" / f"{snap.ref}.json").unlink()
    preview = CheckpointInventory(store, scope).maintenance_preview(OWNER, "clear")
    assert preview["ok"] is False and preview["complete"] is False
    assert preview["reclaimable_bytes"] is None
    result = CheckpointMaintenance(store, scope).apply(
        OWNER, action="clear", project=None, generation=preview["generation"],
        candidates=["file:1"], operation_key=_key("missing-record"),
        authority_check=lambda: True)
    assert result["status"] == "refused" and result["reason"] == "inventory_incomplete"
    assert payloads.blob(snap.blob_sha, snap.size) == b"shared"


def test_revoked_authority_after_row_commit_retains_owned_assets_and_is_uncertain(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path)
    snap = _add(history, payloads, roots[0], 1)
    plan = CheckpointInventory(store, scope).maintenance_preview(OWNER, "clear")

    def current():
        with sqlite3.connect(store.directory / "history.sqlite3") as db:
            return db.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 1

    result = CheckpointMaintenance(store, scope).apply(
        OWNER, action="clear", project=None, generation=plan["generation"],
        candidates=["file:1"], operation_key=_key("revoked-after-row"),
        authority_check=current)
    assert result["status"] == "partial" and result["journal_state"] == "uncertain"
    assert result["removed"] == ["file:1"] and result["removed_assets"] is None
    assert payloads.load(snap.ref) is not None
    with sqlite3.connect(store.directory / "history.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0


def test_owner_command_retention_options_are_exact_and_bounded():
    query = _parse("prune --keep-last 2 --max-bytes 4096 --include-orphans --dry-run", rollback=False)
    assert query["keep_last"] == 2 and query["max_bytes"] == 4096
    assert query["include_orphans"] is True and query["execute"] is False
    for bad in ("prune --keep-last 0", "prune --max-bytes 1099511627777",
                "prune --keep-last 2 --keep-last 3", "clear --include-orphans",
                "prune --force --execute", "prune --keep-last nope"):
        with pytest.raises(ValueError):
            _parse(bad, rollback=False)


@pytest.mark.parametrize("kind", ["record", "blob"])
def test_interposed_target_replacement_cannot_be_counted_as_verified_gc(tmp_path, monkeypatch, kind):
    roots, store, scope, history, payloads = _setup(tmp_path)
    snap = _add(history, payloads, roots[0], 1)
    plan = CheckpointInventory(store, scope).maintenance_preview(OWNER, "clear")
    parent = payloads.directory / ("records" if kind == "record" else "blobs")
    name = snap.ref + ".json" if kind == "record" else snap.blob_sha
    original = (parent / name).read_bytes()
    original_rename, original_unlink = os.rename, os.unlink
    interposed = False

    def swap():
        nonlocal interposed
        if interposed:
            return
        interposed = True
        original_rename(parent / name, parent / (name + ".aside"))
        (parent / name).write_bytes(b"unverified replacement")

    def rename(src, dst, *args, **kwargs):
        if src == name and kwargs.get("src_dir_fd") is not None:
            swap()
        return original_rename(src, dst, *args, **kwargs)

    def unlink(path, *args, **kwargs):
        if path == name and kwargs.get("dir_fd") is not None:
            swap()
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "rename", rename)
    monkeypatch.setattr(os, "unlink", unlink)
    result = CheckpointMaintenance(store, scope).apply(
        OWNER, action="clear", project=None, generation=plan["generation"],
        candidates=["file:1"], operation_key=_key(f"swap-{kind}"),
        authority_check=lambda: True)
    assert interposed
    assert result["status"] == "partial" and result["journal_state"] == "uncertain"
    assert (parent / (name + ".aside")).read_bytes() == original
    assert result["removed_assets"] is None
    monkeypatch.setattr(os, "rename", original_rename)
    monkeypatch.setattr(os, "unlink", original_unlink)
    quarantine = next(payloads.directory.glob(".nerva-gc-*"))
    quarantine.chmod(0o700)
    next(quarantine.iterdir()).unlink()  # explicit synthetic owner recovery
    quarantine.rmdir()
    (parent / (name + ".aside")).rename(parent / name)
    assert CheckpointInventory(store, scope).maintenance_preview(OWNER, "prune")["ok"] is True


def test_orphan_group_child_makes_inventory_incomplete_and_retains_its_ref(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path)
    snap = payloads.take_captured(roots[0] / "group.txt", existed=True,
                                  data=b"group", mode=0o600, now=1)
    with history._connection() as db:
        db.execute("""INSERT INTO group_files
            (group_id,path,pre_ref,pre_existed,post_existed) VALUES (?,?,?,1,0)""",
                   ("missing-group", "group.txt", snap.ref))
        db.commit()
    plan = CheckpointInventory(store, scope).maintenance_preview(OWNER, "prune")
    assert plan["ok"] is False and plan["reclaimable_bytes"] is None
    result = CheckpointMaintenance(store, scope).apply(
        OWNER, action="prune", project=None, generation=plan["generation"],
        candidates=[], operation_key=_key("orphan-child"), authority_check=lambda: True)
    assert result["status"] == "refused"
    assert payloads.load(snap.ref) is not None
    with sqlite3.connect(store.directory / "history.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM group_files").fetchone()[0] == 1


def test_orphan_child_inserted_with_row_commit_blocks_later_owned_gc(tmp_path, monkeypatch):
    roots, store, scope, history, payloads = _setup(tmp_path)
    snap = _add(history, payloads, roots[0], 1)
    plan = CheckpointInventory(store, scope).maintenance_preview(OWNER, "clear")
    original_delete = CheckpointMaintenance._delete_rows

    def insert_orphan(db, candidates):
        removed, counts = original_delete(db, candidates)
        db.execute("""INSERT INTO group_files
            (group_id,path,pre_ref,pre_existed,post_existed) VALUES (?,?,?,1,0)""",
                   ("late-missing-group", "late.txt", snap.ref))
        return removed, counts

    monkeypatch.setattr(CheckpointMaintenance, "_delete_rows", staticmethod(insert_orphan))
    result = CheckpointMaintenance(store, scope).apply(
        OWNER, action="clear", project=None, generation=plan["generation"],
        candidates=["file:1"], operation_key=_key("late-orphan"), authority_check=lambda: True)
    assert result["status"] == "partial" and result["journal_state"] == "uncertain"
    assert payloads.load(snap.ref) is not None
    assert CheckpointInventory(store, scope).maintenance_preview(OWNER, "prune")["ok"] is False


def test_byte_budget_counts_protected_incomplete_rows_before_selecting_oldest(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path)
    for ident in (1, 2, 3):
        _add(history, payloads, roots[0], ident)
    with sqlite3.connect(store.directory / "history.sqlite3") as db:
        db.execute("UPDATE entries SET status='restore_incomplete' WHERE id=2")
    inventory = CheckpointInventory(store, scope)
    logical = inventory._accounting(inventory._inventory(None))[0]["row_logical"]
    cap = logical["file:2"] + logical["file:3"]
    plan = inventory.maintenance_preview(OWNER, "prune", max_bytes=cap)
    assert [row["id"] for row in plan["candidates"]] == ["file:1"]
    assert plan["retention"]["remaining_over_bytes"] == 0


def test_byte_budget_with_unmeasured_generic_ref_refuses_exact_selection(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path)
    _add(history, payloads, roots[0], 1)
    generic = store.take(roots[0] / "note-1.txt")
    with sqlite3.connect(store.directory / "history.sqlite3") as db:
        db.execute("UPDATE entries SET undo_ref=? WHERE id=1", (generic.ref,))
    plan = CheckpointInventory(store, scope).maintenance_preview(OWNER, "prune", max_bytes=1)
    assert plan["ok"] is False and plan["complete"] is False
    assert plan["reclaimable_bytes"] is None
    assert plan["retention"]["remaining_over_bytes"] is None


def test_clear_above_display_limit_executes_in_two_fresh_approved_batches(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path)
    snap = _add(history, payloads, roots[0], 1)
    info = roots[0].stat()
    with sqlite3.connect(store.directory / "history.sqlite3") as db:
        db.executemany("""INSERT INTO entries
            (id,path,root,root_dev,root_ino,op,pre_ref,status,post_existed,
             post_sha,post_size,post_mode,source_kind,created_at)
             VALUES (?,?,?,?,?,'write',?,'applied',1,?,4,384,'filetools',?)""",
             [(ident, str(roots[0] / "note-1.txt"), str(roots[0]), info.st_dev,
               info.st_ino, snap.ref, _key("post"), float(ident))
              for ident in range(2, 502)])
    inventory = CheckpointInventory(store, scope)
    first = inventory.maintenance_preview(OWNER, "clear", limit=500)
    assert first["complete"] is True and first["batch"]["remaining_eligible_rows"] == 1
    assert len(first["candidates"]) == 500
    result = CheckpointMaintenance(store, scope).apply(
        OWNER, action="clear", project=None, generation=first["generation"],
        candidates=[row["id"] for row in first["candidates"]],
        operation_key=_key("clear-batch-1"), authority_check=lambda: True)
    assert result["ok"] is True
    second = inventory.maintenance_preview(OWNER, "clear", limit=500)
    assert second["complete"] is True and len(second["candidates"]) == 1
    assert second["generation"] != first["generation"]
    result = CheckpointMaintenance(store, scope).apply(
        OWNER, action="clear", project=None, generation=second["generation"],
        candidates=[row["id"] for row in second["candidates"]],
        operation_key=_key("clear-batch-2"), authority_check=lambda: True)
    assert result["ok"] is True
    assert payloads.load(snap.ref) is None


def test_clear_owned_asset_batch_keeps_blob_until_last_record_is_removed(tmp_path, monkeypatch):
    roots, store, scope, history, payloads = _setup(tmp_path)
    snap = _add(history, payloads, roots[0], 1)
    monkeypatch.setattr("agents.core.checkpoint_inventory.MAX_GC_CANDIDATES", 1)
    inventory = CheckpointInventory(store, scope)
    first = inventory.maintenance_preview(OWNER, "clear", limit=500)
    assert first["complete"] is True
    assert first["owned_gc"]["records"] == [snap.ref]
    assert first["owned_gc"]["blobs"] == []
    assert first["batch"]["remaining_eligible_assets"] >= 1
    result = CheckpointMaintenance(store, scope).apply(
        OWNER, action="clear", project=None, generation=first["generation"],
        candidates=["file:1"], operation_key=_key("asset-batch-1"),
        authority_check=lambda: True)
    assert result["ok"] is True
    assert payloads.blob(snap.blob_sha, snap.size) == b"shared"
    for batch in (2, 3):
        current = inventory.maintenance_preview(OWNER, "clear", limit=500)
        assert current["complete"] is True and current["candidates"] == []
        assert len(current["owned_gc"]["blobs"]) == 1
        result = CheckpointMaintenance(store, scope).apply(
            OWNER, action="clear", project=None, generation=current["generation"],
            candidates=[], operation_key=_key(f"asset-batch-{batch}"),
            authority_check=lambda: True)
        assert result["ok"] is True
    assert payloads.blob(snap.blob_sha, snap.size) is None


def test_preview_categorizes_generic_shared_owned_direct_post_and_unreferenced(tmp_path):
    roots, store, scope, history, payloads = _setup(tmp_path, two_roots=True)
    snap = _add(history, payloads, roots[0], 1)
    generic = store.take(roots[0] / "note-1.txt")
    orphan_blob = payloads.put_blob(b"unreferenced")
    info = roots[1].stat()
    with sqlite3.connect(store.directory / "history.sqlite3") as db:
        db.execute("""INSERT INTO entries
            (id,path,root,root_dev,root_ino,op,pre_ref,undo_ref,status,post_existed,
             post_sha,post_size,post_mode,source_kind,created_at)
             VALUES (2,?,?,?,?,?,?,?,'applied',1,?,4,384,'filetools',2)""",
             (str(roots[1] / "shared.txt"), str(roots[1]), info.st_dev, info.st_ino,
              "write", snap.ref, generic.ref, _key("post")))
    plan = CheckpointInventory(store, scope).maintenance_preview(
        OWNER, "prune", project=str(roots[0]))
    refs = plan["reference_breakdown"]
    assert refs["generic_retained_records"] == 1
    assert refs["shared_owned_records"] == 1
    assert refs["shared_owned_blobs"] == 2
    assert refs["retained_direct_post_blobs"] == 1
    assert refs["unreferenced_owned_blobs"] >= 1
    assert orphan_blob in plan["owned_gc"]["blobs"]
