"""Owned payloads past the inventory read budget never lock the checkpoint store (#1321).

Every owned blob was read and hashed to inventory the store, and once records and blobs
passed MAX_INVENTORY_READ_BYTES (512 MiB) the inventory answered limit_exceeded: restore,
diff and the prune/clear that would shrink the store were all refused, for good. Past the
budget a blob is now accounted by its identity; it is still hash-checked when read.
"""
from __future__ import annotations

import pytest

from agents.core import checkpoint_payloads
from agents.core.checkpoint_inventory import CheckpointInventory
from agents.core.commands import Principal
from agents.core.file_checkpoint_history import HISTORY_SUPPORTED, FileCheckpointHistory
from agents.core.file_tools import FileScope, SnapshotStore

pytestmark = pytest.mark.skipif(not HISTORY_SUPPORTED,
                                reason="file checkpoint history needs O_DIRECTORY (POSIX only)")

ADMIN = Principal(channel="web", admin=True)


def _three_runs(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("v0 " * 200, encoding="utf-8")
    store = tmp_path / "snapshots"
    history = FileCheckpointHistory(SnapshotStore(store), FileScope([root]))
    groups = []
    for run in range(3):
        scope = history.begin_scope(root, source_kind="terminal_invocation", source_key=f"r{run}")
        note.write_text(f"v{run + 1} " * 200, encoding="utf-8")
        assert history.finish_scope(scope["id"], reaped=True)["status"] == "finished"
        groups.append(scope["id"])
    return history, CheckpointInventory(SnapshotStore(store), FileScope([root])), store, groups


def test_a_store_past_the_read_budget_still_lists_diffs_restores_and_maintains(
        tmp_path, monkeypatch):
    history, inventory, store, groups = _three_runs(tmp_path)
    full = checkpoint_payloads.CheckpointPayloadStore(SnapshotStore(store)).inventory()
    assert full["unverified_blobs"] == 0
    monkeypatch.setattr(checkpoint_payloads, "MAX_INVENTORY_READ_BYTES",
                        full["record_bytes"] + 1)                 # records fit, blobs do not
    owned = checkpoint_payloads.CheckpointPayloadStore(SnapshotStore(store)).inventory()
    assert owned["state"] == "ready" and owned["complete"] is True
    assert owned["unverified_blobs"] == len(owned["blobs"]) > 0
    assert owned["blob_bytes"] == full["blob_bytes"]
    assert inventory.list(ADMIN)["ok"] is True
    assert inventory.maintenance_preview(ADMIN, "prune")["ok"] is True
    assert inventory.maintenance_preview(ADMIN, "clear")["ok"] is True
    assert history.plan_group_restore(groups[-1])["ok"] is True


def test_a_corrupted_blob_past_the_budget_is_still_refused_when_read(tmp_path, monkeypatch):
    _history, _inventory, store, _groups = _three_runs(tmp_path)
    payloads = checkpoint_payloads.CheckpointPayloadStore(SnapshotStore(store))
    full = payloads.inventory()
    monkeypatch.setattr(checkpoint_payloads, "MAX_INVENTORY_READ_BYTES", full["record_bytes"] + 1)
    sha = next(iter(full["blobs"]))
    size = full["blobs"][sha]["physical_size"]
    path = store / "checkpoint_payloads-v1" / "blobs" / sha
    path.write_bytes(b"x" * size)                                  # same size, other bytes
    with pytest.raises(checkpoint_payloads.PayloadRefusal):
        payloads.blob(sha, size)
