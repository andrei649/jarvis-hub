"""Runtime supervisor run-log: bounded JSONL cycles + cross-restart cycle state."""

from __future__ import annotations

import json

from agents.core.observability.runtime_log import RuntimeRunLog


def _paths(tmp_path):
    return tmp_path / "logs" / "runtime.jsonl", tmp_path / "logs" / "runtime_state.json"


def test_record_cycle_appends_one_bounded_json_line(tmp_path):
    log_path, state_path = _paths(tmp_path)
    ticks = iter([100.0, 100.25, 100.25, 100.25])
    run_log = RuntimeRunLog(log_path=log_path, state_path=state_path, clock=lambda: next(ticks))

    record = run_log.record_cycle(
        heartbeat={"scheduler_running": True, "heartbeats": []},
        coordinator={"mode": "auto", "max_tier": None},
        night_shift={"enabled": False, "active_window": False},
        ok=True,
    )

    assert record.cycle == 1
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload == {
        "cycle": 1,
        "started_at": 100.0,
        "duration_s": 0.25,
        "ok": True,
        "heartbeat": {"scheduler_running": True, "heartbeats": []},
        "coordinator": {"mode": "auto", "max_tier": None},
        "night_shift": {"enabled": False, "active_window": False},
        "error": "",
    }


def test_failed_cycle_records_ok_false_and_bounded_error(tmp_path):
    log_path, state_path = _paths(tmp_path)
    run_log = RuntimeRunLog(log_path=log_path, state_path=state_path, clock=lambda: 5.0)

    record = run_log.record_cycle(
        heartbeat={},
        coordinator={},
        night_shift={},
        ok=False,
        error="x" * 900,
    )

    assert record.ok is False
    assert len(record.error) == 500


def test_cycle_counter_persists_and_resumes_across_restart(tmp_path):
    log_path, state_path = _paths(tmp_path)
    first = RuntimeRunLog(log_path=log_path, state_path=state_path, clock=lambda: 1.0)
    first.record_cycle(heartbeat={}, coordinator={}, night_shift={}, ok=True)
    first.record_cycle(heartbeat={}, coordinator={}, night_shift={}, ok=True)
    assert first.cycle == 2

    # Simulate a crash + restart: a brand new instance reads the same paths.
    second = RuntimeRunLog(log_path=log_path, state_path=state_path, clock=lambda: 2.0)
    assert second.cycle == 2
    third_record = second.record_cycle(heartbeat={}, coordinator={}, night_shift={}, ok=True)
    assert third_record.cycle == 3

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["cycle"] == 3
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_corrupt_state_file_falls_back_to_zero_instead_of_raising(tmp_path):
    log_path, state_path = _paths(tmp_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("not json", encoding="utf-8")

    run_log = RuntimeRunLog(log_path=log_path, state_path=state_path, clock=lambda: 9.0)

    assert run_log.cycle == 0
    record = run_log.record_cycle(heartbeat={}, coordinator={}, night_shift={}, ok=True)
    assert record.cycle == 1


def test_corrupt_state_file_is_quarantined_not_discarded(tmp_path):
    log_path, state_path = _paths(tmp_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("not json", encoding="utf-8")

    RuntimeRunLog(log_path=log_path, state_path=state_path, clock=lambda: 42.0)

    quarantined = state_path.with_name(f"{state_path.name}.corrupt-42")
    assert quarantined.exists()
    assert quarantined.read_text(encoding="utf-8") == "not json"
    assert not state_path.exists()


def test_missing_state_file_starts_at_zero(tmp_path):
    log_path, state_path = _paths(tmp_path)

    run_log = RuntimeRunLog(log_path=log_path, state_path=state_path, clock=lambda: 9.0)

    assert run_log.cycle == 0
    assert not state_path.exists()


def test_bounded_dict_truncates_oversized_values_and_key_count(tmp_path):
    log_path, state_path = _paths(tmp_path)
    run_log = RuntimeRunLog(log_path=log_path, state_path=state_path, clock=lambda: 1.0)
    oversized = {f"key-{i}": "v" * 400 for i in range(30)}

    record = run_log.record_cycle(
        heartbeat=oversized, coordinator={}, night_shift={}, ok=True
    )

    assert len(record.heartbeat) <= 20
    for value in record.heartbeat.values():
        assert len(value) <= 300


def test_non_dict_status_is_wrapped_not_raised(tmp_path):
    log_path, state_path = _paths(tmp_path)
    run_log = RuntimeRunLog(log_path=log_path, state_path=state_path, clock=lambda: 1.0)

    record = run_log.record_cycle(
        heartbeat="scheduler down", coordinator={}, night_shift={}, ok=False
    )

    assert record.heartbeat == {"value": "scheduler down"}
