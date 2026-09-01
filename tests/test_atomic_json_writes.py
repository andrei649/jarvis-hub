"""Atomic JSON writes for the non-store writers (DRA-51 / audit Q6).

`JsonStore` has always written via tmp+replace, but three writers outside the
base rewrite their file in place: the per-turn memory snapshot, the ingestion
watcher state and the Oracle bridge session file. A crash (or any raising
serializer) mid-write left a truncated file that the loader then treats as
"empty", silently losing the previous good state. These tests pin the recovery.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.core.persistence import atomic_write_json  # noqa: E402


class _Unserializable:
    """json.dumps raises on this — stands in for a write that dies mid-flight."""


def test_atomic_write_json_leaves_no_tmp(tmp_path):
    target = tmp_path / "nested" / "state.json"
    atomic_write_json(target, {"x": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"x": 1}
    assert not list(target.parent.glob("*.tmp"))

    # A failing serialize must leave the previous good file byte-identical and
    # no tmp behind.
    before = target.read_bytes()
    with pytest.raises(TypeError):
        atomic_write_json(target, {"bad": _Unserializable()})
    assert target.read_bytes() == before
    assert not list(target.parent.glob("*.tmp"))


def test_save_memory_survives_failed_write(tmp_path, monkeypatch):
    from agents.core.memory import persistence

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    persistence.save_memory("sid1", [{"role": "user", "content": "hello"}])
    assert persistence.load_memory("sid1") == [{"role": "user", "content": "hello"}]

    # Second save cannot be serialized; save_memory swallows the error. The
    # previously saved conversation must survive intact.
    persistence.save_memory("sid1", [{"role": "user", "content": _Unserializable()}])
    assert persistence.load_memory("sid1") == [{"role": "user", "content": "hello"}]
    assert not list(tmp_path.glob("*.tmp"))


def test_watcher_state_survives_interrupted_write(tmp_path):
    from agents.core.ingestion.watcher import IngestionWatcher

    state_path = tmp_path / "state" / "watcher_state.json"
    watcher = IngestionWatcher(data_root=tmp_path / "data", state_path=state_path)
    watcher._save_state({"a.json": 1.0})
    assert watcher._load_state() == {"a.json": 1.0}

    real_write_text = Path.write_text

    def half_write(self, data, *args, **kwargs):
        real_write_text(self, data[: len(data) // 2], *args, **kwargs)
        raise OSError("disk full")

    with pytest.MonkeyPatch.context() as m:
        m.setattr(Path, "write_text", half_write)
        watcher._save_state({"b.json": 2.0})

    assert watcher._load_state() == {"a.json": 1.0}


def test_oracle_state_survives_interrupted_write(tmp_path, monkeypatch):
    from agents.core.plugins import oracle_bridge

    session_file = tmp_path / "sessions.json"
    monkeypatch.setattr(oracle_bridge, "SESSION_FILE", session_file)
    bridge = oracle_bridge.OracleBridgePlugin.__new__(oracle_bridge.OracleBridgePlugin)
    bridge.last_checked_sha = "abc123"
    bridge.sessions = []
    bridge.conflicts = []
    bridge.file_hashes = {"f.py": "deadbeef"}
    bridge.current_session = None
    bridge._save_state()
    assert json.loads(session_file.read_text(encoding="utf-8"))["last_checked_sha"] == "abc123"

    real_write_text = Path.write_text

    def half_write(self, data, *args, **kwargs):
        real_write_text(self, data[: len(data) // 2], *args, **kwargs)
        raise OSError("disk full")

    bridge.last_checked_sha = "zzz999"
    # Nested context so undoing the write_text patch does not also undo the
    # SESSION_FILE redirection this test depends on.
    with pytest.MonkeyPatch.context() as m:
        m.setattr(Path, "write_text", half_write)
        bridge._save_state()

    bridge.last_checked_sha = ""
    bridge._load_state()
    assert bridge.last_checked_sha == "abc123"
