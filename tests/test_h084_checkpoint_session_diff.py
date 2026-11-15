"""A project session diff compares an owned full-scope preimage with today's tree."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from agents.core import checkpoint_session_diff
from agents.core.file_checkpoint_history import (
    HISTORY_SUPPORTED,
    MAX_CAPTURE_BYTES,
    FileCheckpointHistory,
)
from agents.core.file_tools import FileScope, SnapshotStore

pytestmark = pytest.mark.skipif(not HISTORY_SUPPORTED, reason="full-scope history needs POSIX dirfds")


def _history(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    store = SnapshotStore(tmp_path / "private" / "snapshots")
    return root, store, FileCheckpointHistory(store, FileScope([root]))


def _finished(history, root, key="turn"):
    scope = history.begin_scope(root, source_kind="terminal_turn", source_key=key)
    history.finish_scope(scope["id"], reaped=True, run_id=scope["run_id"])
    return scope["id"]


def test_no_baseline_is_explicit_and_creates_no_store(tmp_path):
    root, store, history = _history(tmp_path)
    result = history.session_diff(root)
    assert result == {"ok": False, "reason": "no_baseline"}
    assert not store.directory.exists()


def test_earliest_retained_scope_covers_dirty_preexisting_and_later_tree(tmp_path):
    root, _store, history = _history(tmp_path)
    (root / "dirty.txt").write_text("owner start\n")
    (root / "delete.txt").write_text("old\n")
    oldest = _finished(history, root, "one")
    (root / "dirty.txt").write_text("first edit\n")
    _finished(history, root, "two")
    (root / "dirty.txt").write_text("later edit\n")
    (root / "delete.txt").unlink()
    (root / "new.txt").write_text("new\n")

    result = history.session_diff(root)
    assert result["ok"] is True and result["baseline"] == oldest
    assert result["approximate"] is True
    assert "-owner start" in result["diff"] and "+later edit" in result["diff"]
    assert "delete.txt" in result["diff"] and "new.txt" in result["diff"]
    assert "modified 1" in result["stat"]
    assert "added 1" in result["stat"] and "deleted 1" in result["stat"]


def test_oldest_retained_after_pruning_is_used(tmp_path):
    root, store, history = _history(tmp_path)
    target = root / "a.txt"
    target.write_text("one\n")
    old = _finished(history, root, "one")
    target.write_text("two\n")
    newer = _finished(history, root, "two")
    target.write_text("three\n")
    assert history.session_diff(root)["baseline"] == old
    with sqlite3.connect(store.directory / "history.sqlite3") as db:
        db.execute("DELETE FROM group_files WHERE group_id=?", (old,))
        db.execute("DELETE FROM group_exclusions WHERE group_id=?", (old,))
        db.execute("DELETE FROM groups WHERE id=?", (old,))
    result = history.session_diff(root)
    assert result["ok"] is True and result["baseline"] == newer
    assert "-two" in result["diff"] and "+three" in result["diff"]


def test_corrupt_earliest_preimage_refuses_instead_of_falling_forward(tmp_path):
    root, store, history = _history(tmp_path)
    (root / "a.txt").write_text("before\n")
    old = _finished(history, root, "one")
    _finished(history, root, "two")
    with sqlite3.connect(store.directory / "history.sqlite3") as db:
        db.execute("UPDATE group_files SET pre_ref=? WHERE group_id=? AND pre_existed=1",
                   ("0" * 64, old))
    result = history.session_diff(root)
    assert result == {"ok": False, "reason": "baseline_corrupt"}


def test_aggregate_preimage_cap_refuses_before_loading_over_limit_blob(tmp_path, monkeypatch):
    root, _store, history = _history(tmp_path)
    (root / "a.txt").write_bytes(b"a" * 6)
    (root / "b.txt").write_bytes(b"b" * 6)
    _finished(history, root)
    monkeypatch.setattr(checkpoint_session_diff, "MAX_SCOPE_BYTES", 10)
    loaded = []
    original = history.snapshot_blob

    def observed(snap):
        loaded.append(snap.path)
        return original(snap)

    monkeypatch.setattr(history, "snapshot_blob", observed)
    assert history.session_diff(root) == {"ok": False, "reason": "baseline_corrupt"}
    assert len(loaded) == 1


def test_root_inode_change_refuses(tmp_path):
    root, _store, history = _history(tmp_path)
    (root / "a.txt").write_text("before\n")
    _finished(history, root)
    os.rename(root, tmp_path / "old-project")
    root.mkdir()
    assert history.session_diff(root) == {"ok": False, "reason": "root_changed"}


def test_excluded_private_secret_and_oversize_are_not_diffed(tmp_path):
    root, _store, history = _history(tmp_path)
    (root / "api_key.txt").write_text("private before")
    (root / "visible.txt").write_text("safe before\n")
    _finished(history, root)
    (root / "api_key.txt").write_text("private after")
    (root / "visible.txt").write_text("safe after\n")
    result = history.session_diff(root)
    assert result["ok"] is True and result["excluded"] >= 1
    assert "api_key" not in result["diff"] and "private" not in result["diff"]
    assert "visible.txt" in result["diff"]


def test_baseline_oversize_now_readable_and_captured_now_excluded_are_not_changes(tmp_path):
    root, _store, history = _history(tmp_path)
    oversized = root / "large.txt"
    oversized.write_bytes(b"x" * (MAX_CAPTURE_BYTES + 1))
    captured = root / "captured.txt"
    captured.write_text("original\n")
    _finished(history, root)
    oversized.write_text("now small\n")
    captured.unlink()
    captured.symlink_to(tmp_path / "outside")
    result = history.session_diff(root)
    assert result["ok"] is True
    assert "large.txt" not in result["diff"] and "captured.txt" not in result["diff"]
    assert "added 0" in result["stat"] and "deleted 0" in result["stat"]
    assert result["excluded"] >= 2


def test_read_only_comparison_does_not_create_history_files(tmp_path):
    root, store, history = _history(tmp_path)
    (root / "a.txt").write_text("one\n")
    _finished(history, root)
    prior = sorted(str(path.relative_to(store.directory)) for path in store.directory.rglob("*"))
    history.session_diff(root)
    later = sorted(str(path.relative_to(store.directory)) for path in store.directory.rglob("*"))
    assert later == prior


def test_binary_and_mode_only_changes_are_reported_without_binary_content(tmp_path):
    root, _store, history = _history(tmp_path)
    mode = root / "mode.txt"
    mode.write_text("same\n")
    mode.chmod(0o644)
    data = root / "data.txt"
    data.write_text("initial\n")
    _finished(history, root)
    mode.chmod(0o600)
    # The scope scanner excludes NULs in its first 4096 bytes; place one
    # beyond that prefix to exercise the comparator's binary display guard.
    data.write_bytes(b"new" * 1500 + b"\x00binary")
    result = history.session_diff(root)
    assert result["ok"] is True
    assert "Mode changed: mode.txt" in result["diff"]
    assert "\x00binary" not in result["diff"]
    assert "binary content omitted 1" in result["stat"]


def test_diff_overflow_refuses_but_stat_remains_bounded(tmp_path):
    root, _store, history = _history(tmp_path)
    (root / "a.txt").write_text("one\n")
    _finished(history, root)
    (root / "a.txt").write_text("two\n")
    assert history.session_diff(root, max_bytes=10) == {"ok": False, "reason": "diff_too_large"}
    stat = history.session_diff(root, stat_only=True, max_bytes=10)
    assert stat["ok"] is True and stat["diff"] == ""
    assert "modified 1" in stat["stat"]
