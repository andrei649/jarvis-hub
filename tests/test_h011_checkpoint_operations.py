"""Durable intent/task identity without granting checkpoint effect authority."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from agents.core.checkpoint_operations import (
    CheckpointOperationError,
    CheckpointOperationStore,
)
from agents.core.file_tools import SnapshotStore


def store(tmp_path):
    return CheckpointOperationStore(SnapshotStore(tmp_path / "snapshots"))


def digest(intent):
    return hashlib.sha256(json.dumps(
        intent, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode()).hexdigest()


def test_prepare_binds_immutable_detached_intent_and_completed_replay(tmp_path):
    journal = store(tmp_path)
    intent = {"action": "clear", "project": "/test", "options": {"paths": ["one"]}}
    prepared = journal.prepare(intent)
    assert prepared["ok"] is True and prepared["state"] == "prepared"
    request_id = prepared["request_id"]
    assert len(request_id) == 32 and all(c in "0123456789abcdef" for c in request_id)
    assert prepared["intent_sha"] == digest(intent)
    intent["options"]["paths"].append("later")
    prepared["intent"]["options"]["paths"].append("tamper")
    assert journal.get(request_id)["intent"]["options"]["paths"] == ["one"]

    bound = journal.bind_task(request_id, 17, prepared["intent_sha"])
    assert bound["ok"] is True and bound["state"] == "bound" and bound["task_id"] == 17
    claimed = journal.claim(request_id, task_id=17, intent_sha=prepared["intent_sha"])
    assert claimed["ok"] is True and claimed["state"] == "running"
    assert claimed["replay"] is False and claimed["intent"]["options"]["paths"] == ["one"]
    result = {"status": "ok", "removed": ["file:1"]}
    finished = journal.finish(request_id, task_id=17, intent_sha=prepared["intent_sha"],
                              result=result)
    assert finished["ok"] is True and finished["state"] == "completed"
    result["removed"].append("injected")
    finished["result"]["removed"].append("returned-mutated")
    replay = CheckpointOperationStore(journal.snapshots).claim(
        request_id, task_id=17, intent_sha=prepared["intent_sha"])
    assert replay["ok"] is True and replay["state"] == "completed"
    assert replay["replay"] is True and replay["result"] == {"status": "ok", "removed": ["file:1"]}


def test_get_unknown_or_absent_store_creates_nothing(tmp_path):
    journal = store(tmp_path)
    assert journal.get("a" * 32) is None
    assert not journal.snapshots.directory.exists()
    prepared = journal.prepare({"action": "list"})
    assert journal.get("b" * 32) is None
    assert journal.get(prepared["request_id"])["state"] == "prepared"


def test_two_instances_concurrent_claim_has_one_running_transition(tmp_path):
    first = store(tmp_path)
    prepared = first.prepare({"action": "prune", "generation": "x"})
    assert first.bind_task(prepared["request_id"], 19, prepared["intent_sha"])["ok"]
    second = CheckpointOperationStore(first.snapshots)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(item.claim, prepared["request_id"], task_id=19,
                               intent_sha=prepared["intent_sha"])
                   for item in (first, second)]
        results = [future.result() for future in futures]
    assert sum(result.get("ok") is True for result in results) == 1
    assert {result.get("reason") for result in results if not result.get("ok")} == {
        "operation_in_flight"}
    assert first.get(prepared["request_id"])["state"] == "running"


def test_two_instances_concurrent_first_prepare_create_distinct_records(tmp_path):
    first = store(tmp_path)
    second = CheckpointOperationStore(first.snapshots)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(item.prepare, {"ordinal": ordinal})
                   for ordinal, item in enumerate((first, second))]
        prepared = [future.result() for future in futures]
    assert all(row["ok"] is True for row in prepared)
    assert len({row["request_id"] for row in prepared}) == 2
    assert all(first.get(row["request_id"])["state"] == "prepared" for row in prepared)


def test_running_and_uncertain_restart_never_replay_effect(tmp_path):
    journal = store(tmp_path)
    prepared = journal.prepare({"action": "clear"})
    request_id, sha = prepared["request_id"], prepared["intent_sha"]
    assert journal.bind_task(request_id, 23, sha)["ok"]
    assert journal.claim(request_id, task_id=23, intent_sha=sha)["ok"]
    restarted = CheckpointOperationStore(journal.snapshots)
    running = restarted.claim(request_id, task_id=23, intent_sha=sha)
    assert running["ok"] is False and running["reason"] == "operation_in_flight"
    uncertain = restarted.mark_uncertain(request_id, task_id=23, intent_sha=sha)
    assert uncertain["ok"] is True and uncertain["state"] == "uncertain"
    assert CheckpointOperationStore(journal.snapshots).claim(
        request_id, task_id=23, intent_sha=sha)["reason"] == "operation_uncertain"
    assert journal.finish(request_id, task_id=23, intent_sha=sha,
                          result={"status": "ok"})["ok"] is False


def test_unique_task_binding_and_identity_mismatches_do_not_mutate(tmp_path):
    journal = store(tmp_path)
    first = journal.prepare({"a": 1})
    second = journal.prepare({"a": 2})
    assert journal.bind_task(first["request_id"], 31, first["intent_sha"])["ok"]
    assert journal.bind_task(second["request_id"], 31, second["intent_sha"])["ok"] is False
    assert journal.bind_task(first["request_id"], 32, first["intent_sha"])["ok"] is False
    assert journal.bind_task(first["request_id"], 31, "f" * 64)["ok"] is False
    assert journal.claim(first["request_id"], task_id=32,
                         intent_sha=first["intent_sha"])["ok"] is False
    assert journal.claim(first["request_id"], task_id=31,
                         intent_sha="f" * 64)["ok"] is False
    assert journal.get(first["request_id"])["state"] == "bound"
    assert journal.get(second["request_id"])["state"] == "prepared"


def test_finish_requires_current_matching_running_claim(tmp_path):
    journal = store(tmp_path)
    prepared = journal.prepare({"action": "clear"})
    request_id, sha = prepared["request_id"], prepared["intent_sha"]
    assert journal.bind_task(request_id, 37, sha)["ok"]
    assert journal.finish(request_id, task_id=37, intent_sha=sha,
                          result={"status": "ok"})["ok"] is False
    assert journal.claim(request_id, task_id=37, intent_sha=sha)["ok"]
    assert journal.finish(request_id, task_id=38, intent_sha=sha,
                          result={"status": "ok"})["ok"] is False
    assert journal.finish(request_id, task_id=37, intent_sha="e" * 64,
                          result={"status": "ok"})["ok"] is False
    assert journal.get(request_id)["state"] == "running"
    assert journal.finish(request_id, task_id=37, intent_sha=sha,
                          result={"status": "ok"})["ok"] is True
    assert journal.finish(request_id, task_id=37, intent_sha=sha,
                          result={"status": "again"})["ok"] is False


@pytest.mark.parametrize("intent", [
    {1: "number key"},
    {"nested": [{"ok": 1, 2: "wrong"}]},
    {"float": float("nan")},
    {"custom": object()},
    {"large": "x" * (128 * 1024)},
])
def test_bad_json_intent_refuses_before_store_io(tmp_path, monkeypatch, intent):
    journal = store(tmp_path)
    old_stat = os.stat
    def guarded(path, *args, **kwargs):
        if str(path).startswith(str(journal.snapshots.directory)):
            raise AssertionError("invalid intent probed store")
        return old_stat(path, *args, **kwargs)
    monkeypatch.setattr(os, "stat", guarded)
    with pytest.raises(ValueError):
        journal.prepare(intent)
    monkeypatch.undo()
    assert not journal.snapshots.directory.exists()


def test_bad_identity_and_bool_task_refuse_before_io(tmp_path, monkeypatch):
    journal = store(tmp_path)
    def unexpected(*_a, **_kw):
        raise AssertionError("invalid identity opened SQLite")
    monkeypatch.setattr(sqlite3, "connect", unexpected)
    with pytest.raises(ValueError):
        journal.bind_task("x", 1, "a" * 64)
    with pytest.raises(ValueError):
        journal.bind_task("a" * 32, True, "a" * 64)
    with pytest.raises(ValueError):
        journal.claim("a" * 32, task_id=0, intent_sha="a" * 64)
    with pytest.raises(ValueError):
        journal.finish("a" * 32, task_id=1, intent_sha="UPPER", result={})


def test_symlinked_store_or_database_refuses_without_following(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "snapshots"
    linked.symlink_to(outside, target_is_directory=True)
    journal = CheckpointOperationStore(SnapshotStore(linked))
    with pytest.raises(CheckpointOperationError, match="store_invalid"):
        journal.prepare({"action": "clear"})
    assert list(outside.iterdir()) == []
    linked.unlink()

    journal = store(tmp_path)
    prepared = journal.prepare({"action": "clear"})
    db = journal.snapshots.directory / "checkpoint_operations.sqlite3"
    db.unlink()
    outside_db = tmp_path / "outside.sqlite3"
    outside_db.write_text("private")
    db.symlink_to(outside_db)
    with pytest.raises(CheckpointOperationError, match="store_invalid"):
        journal.get(prepared["request_id"])
    with pytest.raises(CheckpointOperationError, match="store_invalid"):
        journal.prepare({"action": "prune"})
    assert outside_db.read_text() == "private"


def test_private_permissions_and_no_history_or_blob_mutation(tmp_path):
    journal = store(tmp_path)
    prepared = journal.prepare({"action": "clear"})
    directory = journal.snapshots.directory
    db = directory / "checkpoint_operations.sqlite3"
    assert directory.is_dir() and db.is_file()
    assert directory.stat().st_mode & 0o077 == 0
    assert db.stat().st_mode & 0o077 == 0
    assert db.exists() and not (directory / "history.sqlite3").exists()
    assert not (directory / "blobs").exists()
    assert journal.get(prepared["request_id"])["state"] == "prepared"


def test_corrupt_stored_intent_and_loose_directory_permissions_refuse(tmp_path):
    journal = store(tmp_path)
    prepared = journal.prepare({"action": "clear"})
    db_path = journal.snapshots.directory / "checkpoint_operations.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE checkpoint_operations SET intent_json=? WHERE request_id=?",
                   ('{"action":"prune"}', prepared["request_id"]))
    with pytest.raises(CheckpointOperationError, match="store_invalid"):
        journal.get(prepared["request_id"])
    journal.snapshots.directory.chmod(0o755)
    with pytest.raises(CheckpointOperationError, match="store_invalid"):
        journal.prepare({"action": "other"})
