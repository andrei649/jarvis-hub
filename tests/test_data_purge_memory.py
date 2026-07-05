"""AUD-2 — 'forget me' also erases the memory subsystem at rest.

Builds a data root with the memory stores (graph/entities/decay), an embedding
cache, conversation transcripts, AND non-memory files that must survive, then
exercises purge_data(memory=True). Asserts the memory PII is gone while config
JSON and the non-session journals are preserved, and that the live in-memory
stores are cleared first (so a running orchestrator can't re-persist them).
"""
import json
from pathlib import Path

from agents.core import data_purge as dp


def _seed_memory_root(tmp_path) -> Path:
    root = tmp_path / "data"
    root.mkdir(parents=True, exist_ok=True)
    # Memory at rest (PII) — must be erased.
    (root / "bitemporal_kg.json").write_text('{"facts": [{"subject": "Alice"}]}', encoding="utf-8")
    (root / "entities.json").write_text('{"Alice": {"type": "person"}}', encoding="utf-8")
    (root / "decay.json").write_text('{"items": {"x": 1}}', encoding="utf-8")
    (root / "cognition").mkdir(parents=True, exist_ok=True)
    (root / "cognition" / "core_memory.json").write_text(
        '{"facts": ["Alice lives in Bucharest"]}',
        encoding="utf-8",
    )
    (root / "cognition" / "living_tiers.json").write_text(
        '{"items": {"turn:1": {"content": "Alice secret", "activation": 1.0}}}',
        encoding="utf-8",
    )
    (root / "embedding_cache" / "recall").mkdir(parents=True, exist_ok=True)
    (root / "embedding_cache" / "recall" / "v.json").write_text("[1,2,3]", encoding="utf-8")
    # Conversation transcripts (session-keyed) — must be erased.
    (root / "convo-1.jsonl").write_text('{"role": "user", "content": "secret"}\n', encoding="utf-8")
    (root / "convo-1.json").write_text('{"session_id": "convo-1", "turns": []}', encoding="utf-8")
    (root / "live-sess.jsonl").write_text('{"role": "user", "content": "hi"}\n', encoding="utf-8")
    (root / "live-sess.json").write_text('{"session_id": "live-sess", "turns": []}', encoding="utf-8")
    # Non-memory files — must SURVIVE the memory purge.
    (root / "canvas.json").write_text('{"elements": ["keep me"]}', encoding="utf-8")
    (root / "autonomy_journal.jsonl").write_text('{"event": "keep"}\n', encoding="utf-8")
    (root / "problems.jsonl").write_text('{"problem": "keep"}\n', encoding="utf-8")
    return root


def test_memory_at_rest_is_erased(tmp_path):
    root = _seed_memory_root(tmp_path)
    report = dp.purge_data(source_root=str(root), backup_first=False, memory=True,
                           session_ids=["live-sess"])
    mem = report["purged"]["memory"]
    # fixed memory stores + embedding cache gone
    assert not (root / "bitemporal_kg.json").exists()
    assert not (root / "entities.json").exists()
    assert not (root / "decay.json").exists()
    assert not (root / "cognition" / "core_memory.json").exists()
    assert not (root / "cognition" / "living_tiers.json").exists()
    assert not (root / "embedding_cache").exists()
    assert set(mem["files"]) == {
        "bitemporal_kg.json",
        "entities.json",
        "decay.json",
        "cognition/core_memory.json",
        "cognition/living_tiers.json",
    }
    assert mem["dirs"] == ["embedding_cache"]
    # conversation transcripts gone (both the glob-discovered and the live one)
    assert not (root / "convo-1.jsonl").exists()
    assert not (root / "convo-1.json").exists()
    assert not (root / "live-sess.jsonl").exists()
    assert not (root / "live-sess.json").exists()
    assert set(mem["sessions"]) == {"convo-1", "live-sess"}


def test_non_memory_files_survive(tmp_path):
    root = _seed_memory_root(tmp_path)
    dp.purge_data(source_root=str(root), backup_first=False, memory=True)
    # config JSON and the non-session journals are NOT memory → untouched
    assert json.loads((root / "canvas.json").read_text()) == {"elements": ["keep me"]}
    assert (root / "autonomy_journal.jsonl").exists()
    assert (root / "problems.jsonl").exists()


def test_memory_flag_off_leaves_memory_intact(tmp_path):
    root = _seed_memory_root(tmp_path)
    report = dp.purge_data(source_root=str(root), backup_first=False)  # memory=False default
    assert "memory" not in report["purged"]
    assert (root / "entities.json").exists()
    assert (root / "convo-1.jsonl").exists()


# ── clear_live_memory orchestration ────────────────────────────────
class _Spy:
    def __init__(self):
        self.cleared = False

    def clear(self):
        self.cleared = True


class _FakeConv:
    def __init__(self):
        self.sessions = {"s1": [], "s2": []}


class _FakeMem:
    def __init__(self):
        self.conversation = _FakeConv()
        self.graph = _Spy()
        self.vectors = _Spy()
        self.cleared = False

    async def clear(self, session_id=None):
        self.cleared = True


class _FakeOrch:
    def __init__(self, cognition=None):
        self.memory = _FakeMem()
        self.entities = _Spy()
        self.decay = _Spy()
        self.cognition = cognition


class _FakeCognition:
    def __init__(self, living_memory):
        self._living_memory = living_memory

    def module(self, name):
        return self._living_memory if name == "memory" else None


async def test_clear_live_memory_clears_all_stores():
    from agents.core.cognition.memory import LivingMemory

    living = LivingMemory()
    living.core.put("Alice lives in Bucharest")
    living.encode("turn:1", {"summary": "Alice secret"}, surprise=1.0)
    orch = _FakeOrch(cognition=_FakeCognition(living))
    cleared = await dp.clear_live_memory(orch)
    assert orch.memory.cleared is True
    assert orch.memory.graph.cleared is True
    assert orch.memory.vectors.cleared is True
    assert orch.entities.cleared is True
    assert orch.decay.cleared is True
    assert living.core.list() == []
    assert living.records() == []
    assert set(cleared) == {
        "conversation",
        "graph",
        "vectors",
        "entities",
        "decay",
        "cognition_memory",
    }


async def test_clear_live_memory_is_defensive_on_missing_stores():
    class _Bare:
        pass
    # No memory/entities/decay attributes at all → no crash, empty result.
    assert await dp.clear_live_memory(_Bare()) == []
