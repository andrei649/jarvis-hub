"""Tests for the Always-On runtime run-log (append/read/summarize)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import time

from agents.core.autonomy.runtime_log import append_record, read_records, summarize_recent


def test_append_and_read_roundtrip(tmp_path):
    path = tmp_path / "runtime.jsonl"
    append_record(path, {"phase": "cycle", "cycle": 1})
    append_record(path, {"phase": "cycle", "cycle": 2})
    records = read_records(path)
    assert [r["cycle"] for r in records] == [1, 2]
    assert all("ts" in r for r in records)


def test_read_records_skips_corrupt_lines(tmp_path):
    path = tmp_path / "runtime.jsonl"
    path.write_text('{"phase": "cycle", "cycle": 1}\nnot json\n{"phase": "cycle", "cycle": 2}\n', encoding="utf-8")
    records = read_records(path)
    assert [r["cycle"] for r in records] == [1, 2]


def test_read_records_missing_file_is_empty(tmp_path):
    assert read_records(tmp_path / "nope.jsonl") == []


def test_read_records_limit_keeps_newest(tmp_path):
    path = tmp_path / "runtime.jsonl"
    for i in range(5):
        append_record(path, {"phase": "cycle", "cycle": i})
    records = read_records(path, limit=2)
    assert [r["cycle"] for r in records] == [3, 4]


def test_append_record_never_raises_on_bad_path():
    # A path under a file (not a directory) cannot be created — append_record must
    # swallow the OSError rather than propagate it into the cycle that produced it.
    bad_parent = "/dev/null/impossible/runtime.jsonl"
    append_record(bad_parent, {"phase": "cycle"})  # must not raise


def test_summarize_recent_counts_clean_and_degraded(tmp_path):
    path = tmp_path / "runtime.jsonl"
    now = time.time()
    append_record(path, {
        "phase": "cycle", "ts": _iso(now - 10), "status": "clean", "boot_id": 1,
        "worker": {"done_delta": 2, "failed_delta": 0},
        "night_shift": {"active": False},
    })
    append_record(path, {
        "phase": "cycle", "ts": _iso(now - 5), "status": "degraded", "boot_id": 1,
        "worker": {"done_delta": 0, "failed_delta": 1},
        "night_shift": {"active": False},
    })
    append_record(path, {
        "phase": "cycle", "ts": _iso(now - 1), "status": "clean", "boot_id": 1,
        "worker": {"done_delta": 1, "failed_delta": 0},
        "night_shift": {"active": True},
    })
    summary = summarize_recent(path, hours=24, now=now)
    assert summary["cycles"] == 3
    assert summary["clean"] == 2
    assert summary["degraded"] == 1
    assert summary["errors"] == 0
    # streak resets after the degraded cycle, so the trailing clean cycle is 1.
    assert summary["consecutive_clean"] == 1
    assert summary["tasks_done"] == 3
    assert summary["tasks_failed"] == 1
    assert summary["last_status"] == "clean"
    assert summary["night_shift_active"] is True


def test_summarize_recent_window_excludes_old_records(tmp_path):
    path = tmp_path / "runtime.jsonl"
    now = time.time()
    append_record(path, {"phase": "cycle", "ts": _iso(now - 100 * 3600), "status": "clean"})
    append_record(path, {"phase": "cycle", "ts": _iso(now - 1), "status": "clean"})
    summary = summarize_recent(path, hours=24, now=now)
    assert summary["cycles"] == 1


def test_summarize_recent_empty_log_is_zeroed(tmp_path):
    summary = summarize_recent(tmp_path / "nope.jsonl", hours=24)
    assert summary["cycles"] == 0
    assert summary["last_status"] is None


def test_summarize_recent_counts_supervisor_restarts(tmp_path):
    path = tmp_path / "runtime.jsonl"
    now = time.time()
    append_record(path, {"phase": "supervisor", "event": "child_exit", "ts": _iso(now - 1)})
    append_record(path, {"phase": "cycle", "ts": _iso(now), "status": "clean"})
    summary = summarize_recent(path, hours=24, now=now)
    assert summary["child_restarts"] == 1
    assert summary["cycles"] == 1


def _iso(epoch: float) -> str:
    from datetime import UTC, datetime
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="milliseconds")
