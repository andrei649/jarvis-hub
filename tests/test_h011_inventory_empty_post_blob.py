"""One created-then-deleted file never locks the whole checkpoint inventory (#1321 review).

Two terminal commands in one agent turn share a ``terminal_turn`` group: the first
creates a file and the second deletes it. finish_scope recorded the deletion with the
empty blob's hash but never stored that blob (main did the same), and the new inventory
check then marked the whole store incomplete, refusing every restore, diff and
maintenance call. The empty blob is now stored, and a store that already holds such a
row (its bytes are known) is still complete.
"""
from __future__ import annotations

import hashlib

import pytest

from agents.core.checkpoint_inventory import CheckpointInventory
from agents.core.commands import Principal
from agents.core.file_checkpoint_history import HISTORY_SUPPORTED, FileCheckpointHistory
from agents.core.file_tools import FileScope, SnapshotStore

pytestmark = pytest.mark.skipif(not HISTORY_SUPPORTED,
                                reason="file checkpoint history needs O_DIRECTORY (POSIX only)")

ADMIN = Principal(channel="web", admin=True)
EMPTY = hashlib.sha256(b"").hexdigest()


def _created_then_deleted_in_one_turn(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")
    store = tmp_path / "snapshots"
    history = FileCheckpointHistory(SnapshotStore(store), FileScope([root]))
    earlier = history.begin_scope(root, source_kind="terminal_invocation", source_key="earlier")
    (root / "a.txt").write_text("hello again", encoding="utf-8")
    assert history.finish_scope(earlier["id"], reaped=True)["status"] == "finished"
    first = history.begin_scope(root, source_kind="terminal_turn", source_key="turn-1")
    (root / "new.txt").write_text("scratch", encoding="utf-8")
    assert history.finish_scope(first["id"], reaped=True)["status"] == "finished"
    second = history.begin_scope(root, source_kind="terminal_turn", source_key="turn-1")
    assert second["id"] == first["id"]                      # the finished group is reused
    (root / "new.txt").unlink()
    assert history.finish_scope(second["id"], reaped=True)["status"] == "finished"
    inventory = CheckpointInventory(SnapshotStore(store), FileScope([root]))
    return history, inventory, store, first["id"]


def _assert_inventory_works(history, inventory, group_id):
    listed = inventory.list(ADMIN)
    assert listed["ok"] is True, listed
    assert inventory.maintenance_preview(ADMIN, "prune")["ok"] is True
    assert inventory.maintenance_preview(ADMIN, "clear")["ok"] is True
    assert history.plan_group_restore(group_id)["ok"] is True


def test_a_file_created_and_deleted_in_one_turn_keeps_the_inventory_complete(tmp_path):
    history, inventory, store, group_id = _created_then_deleted_in_one_turn(tmp_path)
    assert (store / "checkpoint_payloads-v1" / "blobs" / EMPTY).is_file()
    _assert_inventory_works(history, inventory, group_id)


def test_a_store_already_missing_the_empty_blob_is_still_complete(tmp_path):
    history, inventory, store, group_id = _created_then_deleted_in_one_turn(tmp_path)
    (store / "checkpoint_payloads-v1" / "blobs" / EMPTY).unlink()   # as main left it
    _assert_inventory_works(history, inventory, group_id)


def test_any_other_missing_post_blob_still_makes_the_inventory_incomplete(tmp_path):
    history, inventory, store, _group_id = _created_then_deleted_in_one_turn(tmp_path)
    referenced = hashlib.sha256(b"hello again").hexdigest()      # the earlier group's post
    (store / "checkpoint_payloads-v1" / "blobs" / referenced).unlink()
    assert inventory.list(ADMIN)["ok"] is False
