"""Owner-only, stable read-only checkpoint selection over actual storage."""

from __future__ import annotations

import os
import sqlite3

import pytest

from agents.core.checkpoint_inventory import CheckpointInventory
from agents.core.checkpoint_selection import CheckpointSelection
from agents.core.commands import Principal
from agents.core.file_checkpoint_history import FileCheckpointHistory
from agents.core.file_tools import FileScope, FileTools, SnapshotStore

ADMIN = Principal(channel="web", admin=True)
GUEST = Principal(channel="web", admin=False)


def selector(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    store = SnapshotStore(tmp_path / "snapshots")
    scope = FileScope([root])
    return root, store, scope, CheckpointSelection(store, scope)


@pytest.mark.asyncio
async def test_actual_file_and_group_plan_stable_ids_and_instruction_labels(tmp_path):
    root, store, scope, selection = selector(tmp_path)
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    tools = FileTools(scope, snapshots=store)
    assert (await tools.write_file({"path": str(note), "content": "agent"}, approved=True))["ok"]
    entry_id = tools.history.list_entries()[0]["id"]
    instructions = root / "SOUL.md"
    instructions.write_text("old instructions", encoding="utf-8")
    history = FileCheckpointHistory(store, scope)
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    instructions.write_text("new instructions", encoding="utf-8")
    assert history.finish_scope(capture["id"], reaped=True)["status"] == "finished"

    file_plan = selection.plan(ADMIN, f"file:{entry_id}")
    assert file_plan["ok"] is True and file_plan["checkpoint_id"] == f"file:{entry_id}"
    assert file_plan["root"] == str(root)
    assert (file_plan["root_dev"], file_plan["root_ino"]) == (
        root.stat().st_dev, root.stat().st_ino)
    assert len(file_plan["indexed_signature"]) == 64
    assert file_plan["storage_plan"]["ok"] is True
    assert file_plan["instruction_sensitive_paths"] == []

    group_plan = selection.plan(ADMIN, "group:" + capture["id"], paths=["SOUL.md"])
    assert group_plan["ok"] is True and group_plan["storage_plan"]["eligible"] == 1
    assert group_plan["instruction_sensitive_paths"] == ["SOUL.md"]
    assert group_plan["instruction_labels"]["class"] == "agent_instructions"
    instructions.write_text("later owner instruction", encoding="utf-8")
    force_plan = selection.plan(ADMIN, "group:" + capture["id"],
                                paths=["SOUL.md"], force=True)
    assert force_plan["storage_plan"]["current"]["SOUL.md"][2] == len(
        b"later owner instruction")
    assert selection.plan(ADMIN, f"file:{entry_id}", paths=["note.txt"])["reason"] == "unsupported_paths"

    listed = CheckpointInventory(store, scope).list(ADMIN, limit=500)
    ordinal = 1 + [row["id"] for row in listed["items"]].index(f"file:{entry_id}")
    by_ordinal = selection.plan(ADMIN, ordinal)
    assert by_ordinal["checkpoint_id"] == file_plan["checkpoint_id"]
    assert by_ordinal["indexed_signature"] == file_plan["indexed_signature"]


@pytest.mark.asyncio
async def test_safe_vs_force_plan_current_fingerprint_and_real_bounded_diff(tmp_path):
    root, store, scope, selection = selector(tmp_path)
    note = root / "note.txt"
    note.write_text("old", encoding="utf-8")
    tools = FileTools(scope, snapshots=store)
    assert (await tools.write_file({"path": str(note), "content": "new password=abcdefghijk"},
                                   approved=True))["ok"]
    entry_id = tools.history.list_entries()[0]["id"]
    diff = selection.diff(ADMIN, f"file:{entry_id}", max_bytes=128)
    assert diff["ok"] is True and diff["checkpoint_id"] == f"file:{entry_id}"
    assert "abcdefghijk" not in diff["storage_diff"].get("diff", "")
    assert len(diff["storage_diff"].get("diff", "").encode()) <= 128
    note.write_text("owner later", encoding="utf-8")
    assert selection.plan(ADMIN, f"file:{entry_id}")["storage_plan"]["reason"] == "changed_since_checkpoint"
    forced = selection.plan(ADMIN, f"file:{entry_id}", force=True)
    assert forced["ok"] is True and forced["storage_plan"]["current"][2] == len(b"owner later")
    assert "owner later" not in str(forced)
    assert selection.diff(ADMIN, f"file:{entry_id}", path="note.txt")["reason"] == "unsupported_path_filter"


def test_guest_refused_before_any_index_or_scope_probe(tmp_path, monkeypatch):
    root, _store, _scope, selection = selector(tmp_path)
    original_stat = os.stat

    def guarded_stat(path, *args, **kwargs):
        if str(path).startswith(str(tmp_path)):
            raise AssertionError("guest probed checkpoint path")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", guarded_stat)
    monkeypatch.setattr(sqlite3, "connect", lambda *_a, **_kw: pytest.fail("guest opened index"))
    with pytest.raises(PermissionError, match="admin_required"):
        selection.plan(GUEST, "file:1", project=str(root), force=True)
    with pytest.raises(PermissionError, match="admin_required"):
        selection.diff(GUEST, "group:" + "a" * 32, project=str(root))


def test_absent_store_queries_do_not_create_it(tmp_path):
    root, store, _scope, selection = selector(tmp_path)
    assert selection.plan(ADMIN, "file:1")["ok"] is False
    assert selection.diff(ADMIN, "file:1")["ok"] is False
    assert not store.directory.exists()


def test_entries_only_index_is_read_only_and_refused_as_incomplete(tmp_path):
    from tests.test_h011_checkpoint_inventory import add_file, legacy_db

    root, store, _scope, selection = selector(tmp_path)
    with legacy_db(store.directory) as db:
        add_file(db, root)
    with sqlite3.connect(store.directory / "history.sqlite3") as db:
        before = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert selection.plan(ADMIN, "file:1")["reason"] == "index_incomplete"
    with sqlite3.connect(store.directory / "history.sqlite3") as db:
        after = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert after == before == {"entries"}


@pytest.mark.parametrize("identifier", [
    "file:0", "file:01", "file:-1", "file:1x", "group:" + "A" * 32,
    "group:abc", 0, -1, 501, True, "01", "../../file:1", "file:" + "9" * 100,
])
def test_malformed_identifiers_refuse(tmp_path, identifier):
    _root, _store, _scope, selection = selector(tmp_path)
    assert selection.plan(ADMIN, identifier)["reason"] == "invalid_identifier"


@pytest.mark.asyncio
async def test_project_and_root_identity_mismatch_refuse_before_storage_plan(tmp_path):
    root, store, scope, selection = selector(tmp_path)
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    tools = FileTools(scope, snapshots=store)
    assert (await tools.write_file({"path": str(note), "content": "agent"}, approved=True))["ok"]
    entry_id = tools.history.list_entries()[0]["id"]
    other = tmp_path / "other"
    other.mkdir()
    assert selection.plan(ADMIN, f"file:{entry_id}", project=str(other))["reason"] == "project_mismatch"
    unconfigured = CheckpointSelection(store, FileScope([other]))
    assert unconfigured.plan(ADMIN, f"file:{entry_id}")["reason"] == "root_untrusted"
    moved = tmp_path / "moved"
    root.rename(moved)
    root.mkdir()
    note.write_text("agent", encoding="utf-8")
    assert selection.plan(ADMIN, f"file:{entry_id}")["reason"] == "root_untrusted"


@pytest.mark.asyncio
async def test_group_invalid_selection_and_honest_diff_path_refusal(tmp_path):
    root, store, scope, selection = selector(tmp_path)
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    history = FileCheckpointHistory(store, scope)
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("after", encoding="utf-8")
    history.finish_scope(capture["id"], reaped=True)
    invalid = selection.plan(ADMIN, "group:" + capture["id"], paths=["../note.txt"])
    assert invalid["ok"] is False
    diff = selection.diff(ADMIN, "group:" + capture["id"], max_bytes=64)
    assert diff["ok"] is True and len(diff["storage_diff"].get("diff", "").encode()) <= 64
    assert selection.diff(ADMIN, "group:" + capture["id"], path="note.txt")["reason"] == "unsupported_path_filter"


@pytest.mark.asyncio
async def test_index_member_change_during_plan_refuses_stale_signature(tmp_path, monkeypatch):
    root, store, scope, selection = selector(tmp_path)
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    history = FileCheckpointHistory(store, scope)
    capture = history.begin_scope(root, source_kind="terminal_invocation", source_key="test")
    note.write_text("after", encoding="utf-8")
    history.finish_scope(capture["id"], reaped=True)
    original = FileCheckpointHistory.plan_group_restore

    def drift(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        with self._connection() as db:
            db.execute("""UPDATE group_files SET restore_status='skipped'
                WHERE group_id=? AND path='note.txt'""", (capture["id"],))
            db.commit()
        return result

    monkeypatch.setattr(FileCheckpointHistory, "plan_group_restore", drift)
    assert selection.plan(ADMIN, "group:" + capture["id"])["reason"] == "index_changed"


@pytest.mark.asyncio
async def test_project_filtered_ordinal_resolves_only_its_complete_view(tmp_path):
    root, store, scope, _selection = selector(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    both = FileScope([root, other])
    first = root / "one.txt"
    second = other / "two.txt"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    tools = FileTools(both, snapshots=store)
    assert (await tools.write_file({"path": str(first), "content": "changed"}, approved=True))["ok"]
    assert (await tools.write_file({"path": str(second), "content": "changed"}, approved=True))["ok"]
    selection = CheckpointSelection(store, both)
    listed = CheckpointInventory(store, both).list(ADMIN, limit=500)
    target = next(row for row in listed["items"] if row["root"] == str(root))
    chosen = selection.plan(ADMIN, 1, project=str(root))
    assert chosen["ok"] is True and chosen["checkpoint_id"] == target["id"]


@pytest.mark.asyncio
async def test_truncated_inventory_refuses_even_typed_id(tmp_path, monkeypatch):
    root, store, scope, selection = selector(tmp_path)
    note = root / "note.txt"
    note.write_text("before", encoding="utf-8")
    tools = FileTools(scope, snapshots=store)
    assert (await tools.write_file({"path": str(note), "content": "agent"}, approved=True))["ok"]
    monkeypatch.setattr(CheckpointInventory, "list", lambda *_a, **_kw: {
        "ok": True, "items": [], "truncated": True, "omitted": 1, "index_state": "ready",
    })
    assert selection.plan(ADMIN, "file:1")["reason"] == "inventory_incomplete"
