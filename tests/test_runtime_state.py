"""Tests for the Always-On runtime crash-safe state store."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.autonomy.runtime_state import RuntimeStateStore


def test_load_missing_file_returns_defaults(tmp_path):
    store = RuntimeStateStore(tmp_path / "state.json")
    state = store.load()
    assert state["cycle"] == 0
    assert state["boot_id"] == 0
    assert state["consecutive_clean"] == 0
    assert state["last_status"] is None


def test_save_then_load_roundtrip(tmp_path):
    store = RuntimeStateStore(tmp_path / "state.json")
    state = store.load()
    state["cycle"] = 42
    state["boot_id"] = 3
    state["last_status"] = "clean"
    state["consecutive_clean"] = 5
    store.save(state)

    reloaded = store.load()
    assert reloaded["cycle"] == 42
    assert reloaded["boot_id"] == 3
    assert reloaded["last_status"] == "clean"
    assert reloaded["consecutive_clean"] == 5


def test_save_is_atomic_no_partial_file_left(tmp_path):
    path = tmp_path / "state.json"
    store = RuntimeStateStore(path)
    store.save({"cycle": 1})
    assert path.exists()
    assert not path.with_name(path.name + ".tmp").exists()


def test_corrupt_state_is_quarantined_and_defaults_returned(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json at all", encoding="utf-8")
    store = RuntimeStateStore(path)
    state = store.load()
    assert state["cycle"] == 0
    # original corrupt file moved aside, not left in place
    quarantined = list(tmp_path.glob("state.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "not json at all"


def test_non_object_json_root_is_treated_as_corrupt(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    store = RuntimeStateStore(path)
    state = store.load()
    assert state["cycle"] == 0
    assert list(tmp_path.glob("state.json.corrupt-*"))


def test_negative_or_bad_counters_coerced_to_zero(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"cycle": -5, "boot_id": "nope", "consecutive_clean": 3.7}', encoding="utf-8")
    store = RuntimeStateStore(path)
    state = store.load()
    assert state["cycle"] == 0
    assert state["boot_id"] == 0
    assert state["consecutive_clean"] == 3


def test_default_path_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_RUNTIME_STATE", str(tmp_path / "custom" / "state.json"))
    from agents.core.autonomy.runtime_state import default_state_path
    assert default_state_path() == tmp_path / "custom" / "state.json"
