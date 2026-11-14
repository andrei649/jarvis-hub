"""Bounded, read-only projection of durable hub update progress."""

from __future__ import annotations

import json
import os
from dataclasses import FrozenInstanceError

import pytest

from agents.core import hub_update_apply
from agents.core import update_progress as progress
from agents.core.update_progress import (
    ProgressRecord,
    ProgressSnapshot,
    UpdateProgressUnavailable,
    read_progress_snapshot,
)


@pytest.fixture
def state(tmp_path, monkeypatch):
    previous = os.umask(0o077)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    directory = private / "update"
    monkeypatch.setattr(hub_update_apply, "state_dir", lambda: directory)
    try:
        yield directory
    finally:
        os.umask(previous)


def _record(*, kind="update", task_id=7, phase="restarting", result=None, **extra):
    return {"kind": kind, "task_id": task_id, "phase": phase, "result": result,
            "id": "private-receipt", "log": ["raw private detail"], **extra}


def _current(directory, record):
    directory.mkdir(mode=0o700, exist_ok=True)
    (directory / "current.json").write_text(json.dumps(record), encoding="utf-8")


def _receipts(directory, *records):
    directory.mkdir(mode=0o700, exist_ok=True)
    (directory / "receipts.jsonl").write_bytes(
        b"".join(json.dumps(item).encode() + b"\n" for item in records))


def test_missing_state_is_distinct_from_unavailable_and_projection_is_frozen(state):
    assert read_progress_snapshot() == ProgressSnapshot(current=None, last=None)
    _current(state, _record(phase="verifying"))
    _receipts(state, _record(phase="verified", result="verified", task_id=None))
    snapshot = read_progress_snapshot()
    assert snapshot == ProgressSnapshot(
        current=ProgressRecord("update", 7, "verifying", None),
        last=ProgressRecord("update", None, "verified", "verified"),
    )
    assert not hasattr(snapshot.current, "log")
    assert not hasattr(snapshot.last, "id")
    with pytest.raises(FrozenInstanceError):
        snapshot.current.phase = "done"


def test_newest_complete_receipt_in_bounded_tail_and_nonterminal_marker(state):
    state.mkdir(mode=0o700)
    path = state / "receipts.jsonl"
    with path.open("wb") as stream:
        stream.write((json.dumps(_record(result="failed", phase="failed")) + "\n").encode() * 700)
        stream.write((json.dumps(_record(kind="rollback", task_id=None,
                                          phase="rolled_back_restarting")) + "\n").encode())
    assert path.stat().st_size > 64 * 1024
    assert read_progress_snapshot().last == ProgressRecord(
        "rollback", None, "rolled_back_restarting", None)


@pytest.mark.parametrize("field,value", [
    ("kind", "plugin"), ("phase", "complete"), ("result", "success"),
    ("task_id", 0), ("task_id", True), ("task_id", "7"),
])
def test_unknown_or_malformed_projection_field_is_unavailable(state, field, value):
    _current(state, _record(**{field: value}))
    with pytest.raises(UpdateProgressUnavailable):
        read_progress_snapshot()


@pytest.mark.parametrize("content", [
    b"{}", b"[]", b"{broken", b"\xff", b"" , b"x" * (128 * 1024 + 1),
])
def test_malformed_or_oversized_current_is_unavailable(state, content):
    state.mkdir(mode=0o700)
    (state / "current.json").write_bytes(content)
    with pytest.raises(UpdateProgressUnavailable):
        read_progress_snapshot()


@pytest.mark.parametrize("suffix", [
    b"{broken}\n", b"{}\n", b"\n", b"partial", b"\xff\n",
    b"{" + b"x" * (64 * 1024) + b"}\n",
])
def test_malformed_or_incomplete_newest_receipt_never_falls_back(state, suffix):
    _receipts(state, _record(phase="verified", result="verified"))
    with (state / "receipts.jsonl").open("ab") as stream:
        stream.write(suffix)
    with pytest.raises(UpdateProgressUnavailable):
        read_progress_snapshot()


@pytest.mark.parametrize("name", ["current.json", "receipts.jsonl"])
def test_symlink_or_nonregular_state_refuses(state, tmp_path, name):
    state.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.write_text("{}", encoding="utf-8")
    (state / name).symlink_to(outside)
    with pytest.raises(UpdateProgressUnavailable):
        read_progress_snapshot()
    (state / name).unlink()
    (state / name).mkdir()
    with pytest.raises(UpdateProgressUnavailable):
        read_progress_snapshot()


def test_symlinked_update_directory_refuses(state, tmp_path):
    outside = tmp_path / "other"
    outside.mkdir()
    state.symlink_to(outside, target_is_directory=True)
    with pytest.raises(UpdateProgressUnavailable):
        read_progress_snapshot()


@pytest.mark.parametrize("content", [
    b'{"kind":"update","kind":"rollback","phase":"verified","result":"verified"}',
    b'{"kind":"update","phase":"rolling_back","result":"verified"}',
    b'{"kind":"update","phase":"verified"}',
    b'{"kind":"rollback","phase":"verified","result":"verified"}',
    b'{"kind":"update","phase":"verified","result":NaN}',
])
def test_duplicate_or_inconsistent_success_never_projects(state, content):
    state.mkdir(mode=0o700)
    (state / "current.json").write_bytes(content)
    with pytest.raises(UpdateProgressUnavailable):
        read_progress_snapshot()


def test_read_error_is_unavailable_not_absent(state, monkeypatch):
    _current(state, _record())
    opened = progress.os.open

    def refused(path, flags, *args, **kwargs):
        if str(path).endswith("current.json"):
            raise PermissionError("denied")
        return opened(path, flags, *args, **kwargs)

    monkeypatch.setattr(progress.os, "open", refused)
    with pytest.raises(UpdateProgressUnavailable):
        read_progress_snapshot()


def test_parent_replaced_during_read_is_unavailable(state, monkeypatch):
    _current(state, _record())
    reader = progress._read_regular
    moved = state.with_name("moved-update")

    def replace_parent(path, *, tail, cap):
        read = reader(path, tail=tail, cap=cap)
        if path.name == "current.json":
            state.rename(moved)
            state.mkdir(mode=0o700)
        return read

    monkeypatch.setattr(progress, "_read_regular", replace_parent)
    with pytest.raises(UpdateProgressUnavailable):
        read_progress_snapshot()


def test_parent_removed_during_read_is_unavailable(state, monkeypatch):
    _current(state, _record())
    reader = progress._read_regular

    def remove_parent(path, *, tail, cap):
        read = reader(path, tail=tail, cap=cap)
        if path.name == "current.json":
            (state / "current.json").unlink()
            state.rmdir()
        return read

    monkeypatch.setattr(progress, "_read_regular", remove_parent)
    with pytest.raises(UpdateProgressUnavailable):
        read_progress_snapshot()
