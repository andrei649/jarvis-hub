"""The consumer side of the H23.29 run-log: `read_runtime_health` + the morning
brief section it feeds.

The run-log's whole point is that the supervisor loop becomes *observable*. A
producer nobody reads proves nothing, so these cover the reduction from raw
JSONL to the brief's one-liner — including the case that actually matters
operationally: a loop that stopped ticking without ever writing a failure line.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import pytest  # noqa: E402

from agents.core.autonomy.digest import _runtime_health, build_morning_brief  # noqa: E402
from agents.core.autonomy.queue import TaskQueue  # noqa: E402
from agents.core.observability.runtime_log import (  # noqa: E402
    DEFAULT_LOG_PATH,
    RuntimeRunLog,
    default_log_path,
    read_runtime_health,
)


@pytest.fixture
def q(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    yield queue
    queue.close()


def _cycle(log: Path, cycle: int, *, started_at: float, ok: bool = True, error: str = "") -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "cycle": cycle, "started_at": started_at, "duration_s": 0.1, "ok": ok,
            "heartbeat": {}, "coordinator": {}, "night_shift": {}, "error": error,
        }) + "\n")


def _event(log: Path, event: str, *, at: float, **fields) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"supervisor_event": event, "at": at, **fields}) + "\n")


# ── read_runtime_health ───────────────────────────────────────────

def test_missing_log_is_absent_not_a_failure(tmp_path):
    """No run-log means the single-process deployment, not a broken runtime."""
    health = read_runtime_health(tmp_path / "nope.jsonl")
    assert health == {"present": False}


def test_healthy_tail_reports_the_latest_cycle(tmp_path):
    log = tmp_path / "runtime.jsonl"
    now = 1_000_000.0
    for i in (1, 2, 3):
        _cycle(log, i, started_at=now - (3 - i) * 20)

    health = read_runtime_health(log, now=now)

    assert health["present"] is True
    assert health["cycle"] == 3
    assert health["last_ok"] is True
    assert health["stale"] is False
    assert health["age_s"] == 0.0
    assert health["cycles_seen"] == 3
    assert health["failures"] == 0


def test_a_loop_that_stopped_ticking_reads_as_stale(tmp_path):
    """The load-bearing case: the last line says ok, but it is an hour old.
    A supervisor can die without ever writing a failure, so only age reveals it."""
    log = tmp_path / "runtime.jsonl"
    now = 1_000_000.0
    _cycle(log, 7, started_at=now - 3600, ok=True)

    health = read_runtime_health(log, now=now, stale_after_s=900)

    assert health["last_ok"] is True
    assert health["stale"] is True
    assert health["age_s"] == 3600.0


def test_failed_cycles_and_respawns_are_counted_in_window(tmp_path):
    log = tmp_path / "runtime.jsonl"
    now = 1_000_000.0
    _cycle(log, 1, started_at=now - 100, ok=False, error="boom")
    _event(log, "child_exited", at=now - 90, pid=1, exit_code=-9)
    _event(log, "respawned", at=now - 89, pid=2)
    _cycle(log, 2, started_at=now - 10, ok=True)

    health = read_runtime_health(log, now=now)

    assert health["cycle"] == 2
    assert health["last_ok"] is True
    assert health["failures"] == 1
    assert health["respawns"] == 1


def test_events_outside_the_window_are_not_counted(tmp_path):
    log = tmp_path / "runtime.jsonl"
    now = 1_000_000.0
    _cycle(log, 1, started_at=now - 90_000, ok=False)   # >24h ago
    _event(log, "respawned", at=now - 90_000, pid=2)
    _cycle(log, 2, started_at=now - 5, ok=True)

    health = read_runtime_health(log, now=now, window_s=24 * 3600)

    assert health["cycles_seen"] == 1
    assert health["failures"] == 0
    assert health["respawns"] == 0


def test_a_torn_line_does_not_lose_the_rest_of_the_tail(tmp_path):
    log = tmp_path / "runtime.jsonl"
    now = 1_000_000.0
    _cycle(log, 1, started_at=now - 40)
    with log.open("a", encoding="utf-8") as fh:
        fh.write('{"cycle": 2, "started_at": tr\n')  # a crash mid-write
    _cycle(log, 3, started_at=now - 5)

    health = read_runtime_health(log, now=now)

    assert health["cycle"] == 3
    assert health["cycles_seen"] == 2  # 1 and 3; the torn line is skipped


def test_supervisor_started_but_no_cycle_yet(tmp_path):
    log = tmp_path / "runtime.jsonl"
    now = 1_000_000.0
    _event(log, "spawned", at=now - 2, pid=1)

    health = read_runtime_health(log, now=now)

    assert health == {"present": True, "cycles_seen": 0, "respawns": 0}


def test_tail_is_bounded_for_a_long_running_log(tmp_path):
    """One line per cycle forever — the reader must stay O(tail), not O(file)."""
    log = tmp_path / "runtime.jsonl"
    now = 1_000_000.0
    for i in range(1, 4001):
        _cycle(log, i, started_at=now - (4000 - i))
    assert log.stat().st_size > 256 * 1024

    health = read_runtime_health(log, now=now)

    assert health["cycle"] == 4000          # newest line still read
    assert health["cycles_seen"] < 4000     # older ones fell outside the tail


def test_real_run_log_round_trips_through_the_reader(tmp_path):
    """Guard the producer/consumer contract against drift on either side."""
    log, state = tmp_path / "runtime.jsonl", tmp_path / "runtime_state.json"
    run_log = RuntimeRunLog(log_path=log, state_path=state)
    run_log.record_cycle(
        heartbeat={"scheduler_running": True}, coordinator={"mode": "auto", "max_tier": None},
        night_shift={"enabled": False, "active_window": False}, ok=True,
    )

    health = read_runtime_health(log, now=time.time())

    assert health["present"] is True
    assert health["cycle"] == 1
    assert health["last_ok"] is True
    assert health["stale"] is False


def test_default_log_path_honours_the_env_override(monkeypatch):
    monkeypatch.delenv("JARVIS_RUNTIME_LOG", raising=False)
    assert default_log_path() == Path(DEFAULT_LOG_PATH)
    monkeypatch.setenv("JARVIS_RUNTIME_LOG", "/tmp/elsewhere.jsonl")
    assert default_log_path() == Path("/tmp/elsewhere.jsonl")


# ── the brief section ─────────────────────────────────────────────

def test_brief_is_byte_identical_without_a_runtime_summary(q):
    """Default-off discipline: no run-log wired changes nothing about the brief."""
    q.enqueue("jarvis", "research", "Some task")
    assert build_morning_brief(q, runtime_health=None) == build_morning_brief(q)


def test_brief_omits_the_section_when_no_run_log_exists(q, tmp_path):
    text = build_morning_brief(q, runtime_health=read_runtime_health(tmp_path / "nope.jsonl"))
    assert "Runtime" not in text


def test_brief_shows_a_healthy_loop(q):
    text = build_morning_brief(q, runtime_health={
        "present": True, "cycle": 12, "last_ok": True, "age_s": 20.0,
        "stale": False, "failures": 0, "respawns": 0,
    })
    assert "🫀 *Runtime*" in text
    assert "#12" in text and "✅" in text


def test_brief_shouts_when_the_loop_is_stale(q):
    text = build_morning_brief(q, runtime_health={
        "present": True, "cycle": 12, "last_ok": True, "age_s": 3600.0,
        "stale": True, "failures": 0, "respawns": 2,
    })
    assert "oprită" in text
    assert "2 reporniri/24h" in text


def test_brief_surfaces_the_last_error_bounded(q):
    text = build_morning_brief(q, runtime_health={
        "present": True, "cycle": 3, "last_ok": False, "last_error": "E" * 400,
        "age_s": 5.0, "stale": False, "failures": 1, "respawns": 0,
    })
    assert "❌" in text
    assert "E" * 120 in text
    assert "E" * 200 not in text  # truncated, never a wall of text in a Telegram brief


def test_malformed_health_payload_is_ignored_not_rendered(q):
    for junk in (None, "nope", 42, [], {"present": True, "cycle": None}):
        text = build_morning_brief(q, runtime_health=junk)
        if junk == {"present": True, "cycle": None}:
            assert "niciun ciclu" in text
        else:
            assert "🫀" not in text


def test_runtime_health_renderer_never_raises_on_partial_dicts():
    """Field-by-field defensiveness: the brief must ship even on a half-written summary."""
    for partial in ({"present": True}, {"present": True, "cycle": 1},
                    {"present": True, "cycle": 1, "age_s": None, "stale": True}):
        assert isinstance(_runtime_health(partial), str)
