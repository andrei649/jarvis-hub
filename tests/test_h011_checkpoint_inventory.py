"""H011 owner inventory reads index metadata without conferring effect authority."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

from agents.core.checkpoint_inventory import CheckpointInventory
from agents.core.commands import Principal
from agents.core.file_checkpoint_history import FileCheckpointHistory
from agents.core.file_tools import FileScope, SnapshotStore

ADMIN = Principal(channel="web", admin=True)
GUEST = Principal(channel="web", admin=False)
REF = "a" * 64


def service(tmp_path, *, terminal_enabled=True):
    root = tmp_path / "project"
    root.mkdir()
    store = tmp_path / "snapshots"
    return CheckpointInventory(SnapshotStore(store), FileScope([root]),
                               terminal_enabled=terminal_enabled), root, store


def legacy_db(store):
    store.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(store / "history.sqlite3")
    db.execute("""CREATE TABLE entries (
        id INTEGER PRIMARY KEY, path TEXT NOT NULL, root TEXT NOT NULL,
        root_dev INTEGER NOT NULL, root_ino INTEGER NOT NULL,
        op TEXT NOT NULL, pre_ref TEXT NOT NULL, status TEXT NOT NULL,
        post_existed INTEGER, post_sha TEXT, post_size INTEGER, post_mode INTEGER,
        undo_ref TEXT, source_kind TEXT NOT NULL, tool_turn TEXT,
        created_at REAL NOT NULL)""")
    db.commit()
    return db


def add_file(db, root, *, ident=1, status="applied", pre_ref=REF):
    info = root.stat()
    db.execute("""INSERT INTO entries
        (id,path,root,root_dev,root_ino,op,pre_ref,status,post_existed,
         post_sha,post_size,post_mode,source_kind,created_at)
        VALUES (?,?,?,?,?,'write',?,?,1,?,3,420,'filetools',?)""",
        (ident, str(root / f"note-{ident}.txt"), str(root), info.st_dev, info.st_ino,
         pre_ref, status, hashlib.sha256(b"new").hexdigest(), float(ident)))
    db.commit()


def add_group(db, root, *, ident="b" * 32, status="finished"):
    info = root.stat()
    db.execute("""CREATE TABLE groups (
        id TEXT PRIMARY KEY, root TEXT NOT NULL, root_dev INTEGER NOT NULL,
        root_ino INTEGER NOT NULL, source_kind TEXT NOT NULL,
        source_key TEXT NOT NULL, status TEXT NOT NULL,
        created_at REAL NOT NULL, finished_at REAL,
        excluded INTEGER NOT NULL DEFAULT 0, note TEXT,
        policy_version INTEGER NOT NULL DEFAULT 1,
        undo_group_id TEXT)""")
    db.execute("""CREATE TABLE group_files (
        group_id TEXT NOT NULL, path TEXT NOT NULL,
        pre_ref TEXT, pre_existed INTEGER NOT NULL,
        post_existed INTEGER, post_sha TEXT, post_size INTEGER,
        post_mode INTEGER, change_kind TEXT,
        undo_ref TEXT, restore_status TEXT,
        PRIMARY KEY (group_id,path))""")
    db.execute("""INSERT INTO groups
        (id,root,root_dev,root_ino,source_kind,source_key,status,created_at)
        VALUES (?,?,?,?,?,?,?,?)""",
        (ident, str(root), info.st_dev, info.st_ino,
         "terminal", "task:1", status, 4.0))
    db.execute("""INSERT INTO group_files
        (group_id,path,pre_ref,pre_existed,post_existed,post_sha,post_size,
         post_mode,change_kind) VALUES (?,?,?,1,1,?,5,420,'modified')""",
        (ident, "group.txt", REF, hashlib.sha256(b"after").hexdigest()))
    db.commit()


def test_nonadmin_refuses_before_index_or_path_probe(tmp_path, monkeypatch):
    inventory, root, store = service(tmp_path)
    def unexpected_connect(*_a, **_kw):
        raise AssertionError("guest must not touch index or filesystem")
    original_stat = os.stat
    def guarded_stat(path, *args, **kwargs):
        if str(path).startswith(str(tmp_path)):
            raise AssertionError("guest must not probe checkpoint paths")
        return original_stat(path, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", unexpected_connect)
    monkeypatch.setattr(os, "stat", guarded_stat)
    for method, args in ((inventory.status, (GUEST,)),
                         (inventory.list, (GUEST,)),
                         (inventory.maintenance_preview, (GUEST, "clear"))):
        with pytest.raises(PermissionError, match="admin_required"):
            method(*args)


def test_absent_store_is_empty_and_not_created(tmp_path):
    inventory, root, store = service(tmp_path, terminal_enabled=False)
    status = inventory.status(ADMIN)
    assert status["ok"] is True and status["store"]["state"] == "absent"
    assert status["counts"] == {"files": 0, "groups": 0, "incomplete": 0}
    assert status["features"]["terminal_groups"]["enabled"] is False
    assert inventory.list(ADMIN)["items"] == []
    assert inventory.maintenance_preview(ADMIN, "clear")["candidates"] == []
    assert not store.exists()


def test_entries_only_legacy_index_still_lists_file_checkpoint(tmp_path):
    inventory, root, store = service(tmp_path)
    with legacy_db(store) as db:
        add_file(db, root)
    rows = inventory.list(ADMIN)["items"]
    assert len(rows) == 1
    assert rows[0]["id"] == "file:1" and rows[0]["type"] == "file"
    assert rows[0]["root"] == str(root) and rows[0]["root_state"] == "live"
    assert inventory.status(ADMIN)["counts"] == {"files": 1, "groups": 0, "incomplete": 0}


def test_enabled_terminal_feature_is_independent_of_an_empty_index(tmp_path):
    inventory, _root, store = service(tmp_path, terminal_enabled=True)
    feature = inventory.status(ADMIN)["features"]["terminal_groups"]
    assert feature["enabled"] is True and feature["supported"] is True
    assert feature["schema_present"] is False
    assert not store.exists()


def test_group_schema_coexists_with_file_entries_and_logical_bytes(tmp_path):
    inventory, root, store = service(tmp_path)
    with legacy_db(store) as db:
        add_file(db, root)
        add_group(db, root)
    status = inventory.status(ADMIN)
    assert status["counts"] == {"files": 1, "groups": 1, "incomplete": 0}
    assert status["projects"][0]["observed_post_bytes"] == 8
    rows = inventory.list(ADMIN)["items"]
    assert {row["id"] for row in rows} == {"file:1", "group:" + "b" * 32}
    assert {row["type"] for row in rows} == {"file", "group"}


def test_unreachable_and_replaced_roots_remain_visible(tmp_path):
    inventory, root, store = service(tmp_path)
    with legacy_db(store) as db:
        add_file(db, root)
    moved = tmp_path / "moved"
    root.rename(moved)
    assert inventory.list(ADMIN)["items"][0]["root_state"] == "unreachable"
    root.mkdir()
    assert inventory.list(ADMIN)["items"][0]["root_state"] == "changed"


def test_unconfigured_stored_root_is_not_probed(tmp_path, monkeypatch):
    inventory, root, store = service(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    with legacy_db(store) as db:
        add_file(db, other)
    old_stat = os.stat
    def guarded(path, *args, **kwargs):
        if str(path) == str(other):
            raise AssertionError("unconfigured root probed")
        return old_stat(path, *args, **kwargs)
    monkeypatch.setattr(os, "stat", guarded)
    row = inventory.list(ADMIN)["items"][0]
    assert row["root"] == str(other) and row["root_state"] == "unconfigured"


def test_project_filter_and_limit_report_omitted_without_hiding_records(tmp_path):
    inventory, root, store = service(tmp_path)
    with legacy_db(store) as db:
        add_file(db, root, ident=1)
        add_file(db, root, ident=2, status="restore_incomplete")
    page = inventory.list(ADMIN, project=str(root), limit=1)
    assert len(page["items"]) == 1 and page["omitted"] == 1
    assert page["items"][0]["id"] == "file:2"
    assert inventory.status(ADMIN)["counts"]["incomplete"] == 1


def test_preview_digest_changes_when_root_becomes_unreachable(tmp_path):
    inventory, root, store = service(tmp_path)
    with legacy_db(store) as db:
        add_file(db, root)
    before = inventory.maintenance_preview(ADMIN, "prune", keep_orphans=False)
    assert before["candidates"] == []
    root.rename(tmp_path / "disconnected")
    after = inventory.maintenance_preview(ADMIN, "prune", keep_orphans=False)
    assert after["generation"] != before["generation"]
    assert [item["id"] for item in after["candidates"]] == ["file:1"]
    assert after["candidates"][0]["root_state"] == "unreachable"


def test_new_store_orphan_changes_preview_generation_without_candidate(tmp_path):
    inventory, root, store = service(tmp_path)
    with legacy_db(store) as db:
        add_file(db, root)
    before = inventory.maintenance_preview(ADMIN, "clear")
    (store / "orphan.json").write_text("{}")
    after = inventory.maintenance_preview(ADMIN, "clear")
    assert before["generation"] != after["generation"]
    assert [row["id"] for row in after["candidates"]] == ["file:1"]


def test_index_reference_change_invalidates_preview_generation(tmp_path):
    inventory, root, store = service(tmp_path)
    with legacy_db(store) as db:
        add_file(db, root)
        before = inventory.maintenance_preview(ADMIN, "clear")
        db.execute("UPDATE entries SET pre_ref=? WHERE id=1", ("b" * 64,))
        db.commit()
    after = inventory.maintenance_preview(ADMIN, "clear")
    assert before["generation"] != after["generation"]
    assert before["candidates"] == after["candidates"]


@pytest.mark.parametrize("file_status", ["prepared", "restore_incomplete"])
def test_incomplete_orphan_is_not_prune_candidate(tmp_path, file_status):
    inventory, root, store = service(tmp_path)
    with legacy_db(store) as db:
        add_file(db, root, status=file_status)
    root.rename(tmp_path / "disconnected")
    preview = inventory.maintenance_preview(ADMIN, "prune", keep_orphans=False)
    assert preview["candidates"] == []
    assert inventory.status(ADMIN)["counts"]["incomplete"] == 1


@pytest.mark.parametrize("group_status", ["capturing", "ready", "running"])
def test_active_group_states_are_incomplete_and_not_orphan_prune_candidates(
    tmp_path, group_status,
):
    inventory, root, store = service(tmp_path)
    with legacy_db(store) as db:
        add_group(db, root, status=group_status)
    root.rename(tmp_path / "disconnected")
    assert inventory.status(ADMIN)["counts"]["incomplete"] == 1
    preview = inventory.maintenance_preview(ADMIN, "prune", keep_orphans=False)
    assert preview["candidates"] == []
    assert inventory.list(ADMIN)["items"][0]["status"] == group_status


def test_actual_group_begin_and_finish_inventory_lifecycle(tmp_path):
    inventory, root, store = service(tmp_path)
    note = root / "note.txt"
    note.write_text("before")
    history = FileCheckpointHistory(SnapshotStore(store), FileScope([root]))
    capture = history.begin_scope(
        root, source_kind="terminal_invocation", source_key="inventory-test",
    )
    assert capture["status"] == "ready"
    assert inventory.list(ADMIN)["items"][0]["id"] == "group:" + capture["id"]
    assert inventory.status(ADMIN)["counts"]["incomplete"] == 1

    note.write_text("after")
    finished = history.finish_scope(
        capture["id"], reaped=True, run_id=capture["run_id"],
    )
    assert finished["status"] == "finished"
    assert inventory.status(ADMIN)["counts"]["incomplete"] == 0
    assert inventory.list(ADMIN)["items"][0]["status"] == "finished"


def test_preview_protects_shared_refs_and_has_no_effect(tmp_path):
    inventory, root, store = service(tmp_path)
    with legacy_db(store) as db:
        add_file(db, root)
    (store / f"{REF}.json").write_text('{"blob_sha":"' + REF + '"}')
    blobs = store / "blobs"
    blobs.mkdir()
    (blobs / REF).write_bytes(b"private bytes")
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in store.rglob("*") if p.is_file()}
    preview = inventory.maintenance_preview(ADMIN, "clear")
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in store.rglob("*") if p.is_file()}
    assert preview["reclaimable_bytes"] is None
    assert preview["protected_shared_refs"] >= 1
    assert [item["id"] for item in preview["candidates"]] == ["file:1"]
    assert before == after


def test_clear_legacy_has_no_candidates_or_unrelated_traversal(tmp_path):
    inventory, root, store = service(tmp_path)
    (tmp_path / "legacy-2020").mkdir()
    result = inventory.maintenance_preview(ADMIN, "clear-legacy")
    assert result["candidates"] == [] and result["complete"] is True
    assert (tmp_path / "legacy-2020").exists() and not store.exists()


@pytest.mark.parametrize("method,args", [
    ("status", {"limit": 0}), ("list", {"limit": 501}),
    ("status", {"project": "bad\npath"}),
    ("status", {"project": "x" * 4097}),
    ("maintenance_preview", {"action": "restore"}),
])
def test_invalid_query_arguments_refuse_without_creating_store(tmp_path, method, args):
    inventory, root, store = service(tmp_path)
    with pytest.raises(ValueError):
        getattr(inventory, method)(ADMIN, **args)
    assert not store.exists()


def test_storage_scan_is_bounded_and_never_follows_symlink(tmp_path, monkeypatch):
    from agents.core import checkpoint_inventory as module
    inventory, root, store = service(tmp_path)
    store.mkdir()
    (store / "one.json").write_text("{}")
    (store / "two.json").write_text("{}")
    secret = tmp_path / "secret"
    secret.write_bytes(b"secret")
    (store / "three.json").symlink_to(secret)
    monkeypatch.setattr(module, "MAX_STORAGE_FILES", 1)
    status = inventory.status(ADMIN)
    assert status["store"]["bytes_exact"] is False
    assert status["store"]["bytes"] is None
    assert secret.read_bytes() == b"secret"


def test_inventory_never_reads_original_project_file_bytes(tmp_path, monkeypatch):
    inventory, root, store = service(tmp_path)
    secret = root / "note-1.txt"
    secret.write_bytes(b"private original")
    with legacy_db(store) as db:
        add_file(db, root)
    old_read = Path.read_bytes
    def guarded(self):
        if self == secret:
            raise AssertionError("project contents read")
        return old_read(self)
    monkeypatch.setattr(Path, "read_bytes", guarded)
    assert inventory.status(ADMIN)["counts"]["files"] == 1
    assert inventory.list(ADMIN)["items"][0]["id"] == "file:1"
