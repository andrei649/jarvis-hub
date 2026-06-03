"""Tests for the shared JsonStore base (audit A3/Q1)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.core.persistence import JsonStore


class _DictStore(JsonStore):
    def _serialize(self):
        return self._d

    def _deserialize(self, raw):
        self._d = raw if isinstance(raw, dict) else {}


def test_roundtrip_and_atomic(tmp_path):
    p = tmp_path / "s.json"
    s = _DictStore(p)
    assert s._d == {}                       # missing file → empty
    s._d = {"x": 1}
    s._save()
    assert p.exists() and not p.with_suffix(".tmp").exists()   # tmp cleaned up
    assert _DictStore(p)._d == {"x": 1}     # reload from disk


def test_corrupt_file_recovers(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert _DictStore(p)._d == {}           # corrupt → empty, no crash


def test_has_lock(tmp_path):
    s = _DictStore(tmp_path / "s.json")
    assert hasattr(s, "_lock")


def test_real_stores_inherit_base():
    from agents.core.widget import WidgetStore
    from agents.core.rooms import RoomStore
    from agents.core.notes import NotesStore
    from agents.core.webhooks import WebhookStore
    from agents.core.arena import Arena
    from agents.core.observability.review_queue import ReviewQueue
    for cls in (WidgetStore, RoomStore, NotesStore, WebhookStore, Arena, ReviewQueue):
        assert issubclass(cls, JsonStore), cls.__name__


def test_arena_two_dict_serialize(tmp_path):
    from agents.core.arena import Arena
    p = tmp_path / "a.json"
    a = Arena(p)
    a.create_match("q", {"m1": "r1", "m2": "r2"})
    # reload preserves the dual matches/ratings shape through the base
    a2 = Arena(p)
    assert len(a2._matches) == 1 and isinstance(a2._ratings, dict)
