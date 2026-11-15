"""Literal project paths select only verified session comparison rows."""

from __future__ import annotations

import os
import sqlite3

import pytest

from agents.core import checkpoint_session_diff
from agents.core.diff_paths import validate_paths
from agents.core.file_checkpoint_history import HISTORY_SUPPORTED, FileCheckpointHistory
from agents.core.file_tools import FileScope, SnapshotStore


@pytest.fixture
def history(tmp_path):
    old_umask = os.umask(0o077)
    project = tmp_path / "project"
    private = tmp_path / "private"
    project.mkdir(mode=0o700)
    private.mkdir(mode=0o700)
    try:
        yield project, FileCheckpointHistory(
            SnapshotStore(private / "snapshots"), FileScope([project]))
    finally:
        os.umask(old_umask)


def _baseline(history, project):
    scope = history.begin_scope(project, source_kind="terminal_turn", source_key="first")
    history.finish_scope(scope["id"], reaped=True, run_id=scope["run_id"])
    return scope["id"]


@pytest.mark.parametrize("paths,expected", [
    ((), ()), ([], ()), (("src/a.py",), ("src/a.py",)),
    (["A File.txt", "src/ünicode.py"], ("A File.txt", "src/ünicode.py")),
])
def test_bounded_literal_path_validator_accepts_exact_bytes(paths, expected):
    assert validate_paths(paths) == expected


@pytest.mark.parametrize("paths", [
    None, "src/a.py", {"src/a.py"}, ("",), ("/etc/passwd",), ("../x",),
    ("a/../b",), ("./a",), ("a/./b",), ("a//b",), ("a/",),
    ("C:/windows",), ("\\\\host\\share",), ("a\\b",),
    ("a\x00b",), ("a\nb",), ("a\u2028b",), ("a\u200bb",),
    ("a\u202eb",), ("a\ud800b",),
    ("*.py",), ("a?.py",), ("a[1].py",), (":(glob)foo",), ("a:b",),
    ("x" * 257,), ("ü" * 129,), tuple(str(n) for n in range(9)),
    ("x" * 200,) * 6, ("same", "same"), (42,),
])
def test_bounded_literal_path_validator_refuses_unsafe_or_ambiguous(paths):
    assert validate_paths(paths) is None


@pytest.mark.skipif(not HISTORY_SUPPORTED, reason="full-scope history needs POSIX dirfds")
def test_selected_changed_added_deleted_and_prefix_boundary(history):
    project, ledger = history
    (project / "src").mkdir()
    (project / "src2").mkdir()
    (project / "src" / "change.txt").write_text("before\n")
    (project / "src" / "delete.txt").write_text("old\n")
    (project / "src2" / "other.txt").write_text("other before\n")
    oldest = _baseline(ledger, project)
    (project / "src" / "change.txt").write_text("after\n")
    (project / "src" / "delete.txt").unlink()
    (project / "src" / "new.txt").write_text("new\n")
    (project / "src2" / "other.txt").write_text("other after\n")

    selected = ledger.session_diff(project, paths=("src",))
    assert selected["ok"] is True and selected["baseline"] == oldest
    assert selected["approximate"] is True
    assert "src/change.txt" in selected["diff"]
    assert "src/delete.txt" in selected["diff"] and "src/new.txt" in selected["diff"]
    assert "src2/other.txt" not in selected["diff"]
    assert "modified 1" in selected["stat"]
    assert "added 1" in selected["stat"] and "deleted 1" in selected["stat"]
    assert "src2/other.txt" in ledger.session_diff(project)["diff"]
    empty = ledger.session_diff(project, paths=())
    assert empty["ok"] is True and empty["diff"] == ""
    assert "modified 0" in empty["stat"]

    one = ledger.session_diff(project, paths=("src/change.txt",))
    assert "src/change.txt" in one["diff"]
    assert "src/delete.txt" not in one["diff"] and "src/new.txt" not in one["diff"]
    missing = ledger.session_diff(project, paths=("not-here",))
    assert missing["ok"] is True and missing["baseline"] == oldest
    assert missing["diff"] == "" and "modified 0" in missing["stat"]


@pytest.mark.skipif(not HISTORY_SUPPORTED, reason="full-scope history needs POSIX dirfds")
def test_invalid_direct_filter_refuses_before_baseline_or_scan(history, monkeypatch):
    project, ledger = history
    monkeypatch.setattr(checkpoint_session_diff, "_read_baseline",
                        lambda *_: pytest.fail("invalid filter read baseline"))
    monkeypatch.setattr(ledger, "_scan_group",
                        lambda *_: pytest.fail("invalid filter scanned tree"))
    for paths in (("../escape",), "src", ("src",) * 9):
        assert ledger.session_diff(project, paths=paths) == {
            "ok": False, "reason": "invalid_paths"}


@pytest.mark.skipif(not HISTORY_SUPPORTED, reason="full-scope history needs POSIX dirfds")
def test_selected_overflow_and_protected_path_still_use_existing_floors(history):
    project, ledger = history
    (project / "visible.txt").write_text("before\n")
    (project / "api_key.txt").write_text("private before\n")
    _baseline(ledger, project)
    (project / "visible.txt").write_text("after\n")
    (project / "api_key.txt").write_text("private after\n")
    assert ledger.session_diff(project, paths=("visible.txt",), max_bytes=10) == {
        "ok": False, "reason": "diff_too_large"}
    stat = ledger.session_diff(project, paths=("visible.txt",), stat_only=True,
                               max_bytes=10)
    assert stat["ok"] is True and "modified 1" in stat["stat"]
    secret = ledger.session_diff(project, paths=("api_key.txt",))
    assert secret["ok"] is True and "private" not in secret["diff"]


@pytest.mark.skipif(not HISTORY_SUPPORTED, reason="full-scope history needs POSIX dirfds")
def test_selected_path_cannot_hide_unrelated_corrupt_baseline(history):
    project, ledger = history
    (project / "selected.txt").write_text("before\n")
    (project / "unrelated.txt").write_text("before\n")
    oldest = _baseline(ledger, project)
    (project / "selected.txt").write_text("after\n")
    with sqlite3.connect(ledger.snapshots.directory / "history.sqlite3") as db:
        db.execute("UPDATE group_files SET pre_ref=? WHERE group_id=? AND path=?",
                   ("0" * 64, oldest, "unrelated.txt"))
    assert ledger.session_diff(project, paths=("selected.txt",)) == {
        "ok": False, "reason": "baseline_corrupt"}
    assert ledger.session_diff(project, paths=()) == {
        "ok": False, "reason": "baseline_corrupt"}
