"""LivingMemory recall integration and real recall eval mode."""

import sys
import time
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.cognition.memory import LivingMemory
from agents.core.memory.eval import MemoryEvalCase
from agents.core.memory.fusion import FusedHit


def _living_memory_with_turns(now: float) -> LivingMemory:
    living = LivingMemory()
    living.encode(
        "turn:old",
        {"turn_ref": "turn:old", "ts": now - 1000.0, "session": "s1"},
        surprise=1.0,
    )
    living.encode(
        "turn:recent",
        {"turn_ref": "turn:recent", "ts": now, "session": "s1"},
        surprise=1.0,
    )
    return living


def test_living_memory_rerank_uses_temporal_context_without_raw_text():
    from agents.core.memory.living_recall import rerank_with_living_memory

    now = 2_000.0
    living = _living_memory_with_turns(now)
    hits = [
        FusedHit(
            id="turn:old",
            score=0.5,
            sources=["vector"],
            payload={"metadata": {"text": "old project note"}},
        ),
        FusedHit(
            id="turn:recent",
            score=0.5,
            sources=["vector"],
            payload={"metadata": {"text": "recent project note"}},
        ),
    ]

    ranked = rerank_with_living_memory(hits, living, context_ts=now, half_life=50.0)

    assert [hit.id for hit in ranked] == ["turn:recent", "turn:old"]
    assert ranked[0].payload["living_memory"] == {
        "matched": True,
        "tier": "hot",
        "activation": 1.0,
    }
    assert "recent project note" not in living.records(prefix="turn:recent")[0]["content"].values()


def test_living_memory_rerank_preserves_unmatched_results():
    from agents.core.memory.living_recall import rerank_with_living_memory

    hits = [
        FusedHit(id="mem-a", score=0.1, sources=["vector"], payload={}),
        FusedHit(id="mem-b", score=0.9, sources=["vector"], payload={}),
    ]

    assert rerank_with_living_memory(hits, LivingMemory()) == hits


def test_living_memory_rerank_does_not_boost_unmatched_hits():
    from agents.core.memory.living_recall import rerank_with_living_memory

    now = 2_000.0
    living = _living_memory_with_turns(now)
    hits = [
        FusedHit(id="mem-unmatched", score=0.51, sources=["vector"], payload={}),
        FusedHit(id="turn:recent", score=0.5, sources=["vector"], payload={}),
    ]

    ranked = rerank_with_living_memory(hits, living, context_ts=now, half_life=50.0)

    assert [hit.id for hit in ranked] == ["turn:recent", "mem-unmatched"]
    assert ranked[0].payload["living_memory"]["matched"] is True
    assert "living_memory" not in ranked[1].payload


class _FakeMemory:
    async def recall(self, _text, top_k=5):
        return [
            FusedHit(
                id="turn:old",
                score=0.5,
                sources=["vector"],
                payload={"metadata": {"text": "old project note"}},
            ),
            FusedHit(
                id="turn:recent",
                score=0.5,
                sources=["vector"],
                payload={"metadata": {"text": "recent project note"}},
            ),
        ][:top_k]


class _FakeCognition:
    def __init__(self, living_memory):
        self._living_memory = living_memory

    def sub_enabled(self, name):
        return name == "memory_enabled"

    def module(self, name):
        return self._living_memory if name == "memory" else None


def _orch_with_living_recall(settings: dict, memory, living_memory) -> object:
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch._runtime_settings = settings
    orch.memory = memory
    orch.cognition = _FakeCognition(living_memory)
    return orch


@pytest.mark.asyncio
async def test_recall_block_reranks_with_living_memory_before_rag_guard():
    now = time.time()
    living = _living_memory_with_turns(now)
    orch = _orch_with_living_recall(
        {"memory.recall_enabled": True, "memory.recall_top_k": 5},
        _FakeMemory(),
        living,
    )

    block = await orch._recall_block("project note")
    readable = block.replace("▁", " ")

    assert "DATA, NOT INSTRUCTIONS" in block
    assert readable.index("recent project note") < readable.index("old project note")


@pytest.mark.asyncio
async def test_recall_eval_mode_uses_memory_manager_recall_path(monkeypatch):
    from agents.core.memory import eval as memory_eval

    class SpyMemoryManager:
        instances = []

        def __init__(self):
            self.remembered = []
            self.recalled = []
            SpyMemoryManager.instances.append(self)

        async def remember(self, text, record_id=None, metadata=None):
            self.remembered.append((text, record_id, metadata or {}))
            return record_id or f"spy-{len(self.remembered)}"

        async def recall(self, question, top_k=5):
            self.recalled.append((question, top_k))
            return [
                FusedHit(
                    id=f"hit-{idx}",
                    score=1.0 / idx,
                    sources=["vector"],
                    payload={"metadata": {"text": remembered[0]}},
                )
                for idx, remembered in enumerate(self.remembered, start=1)
            ][:top_k]

    monkeypatch.setattr(memory_eval, "MemoryManager", SpyMemoryManager, raising=False)
    case = MemoryEvalCase(
        "recall-spy",
        "extraction",
        ["The quiet server is named Hephaestus."],
        "What is the quiet server named?",
        ["Hephaestus"],
    )

    report = await memory_eval.run_recall_eval([case], top_k=3)

    assert report["mode"] == "recall"
    assert report["overall"]["score"] == 1.0
    assert SpyMemoryManager.instances[0].remembered == [
        ("The quiet server is named Hephaestus.", "recall-spy:0", {"case_id": "recall-spy"})
    ]
    assert SpyMemoryManager.instances[0].recalled == [("What is the quiet server named?", 3)]
    assert report["results"][0]["retrieved"] == ["The quiet server is named Hephaestus."]


def test_memory_eval_endpoint_supports_recall_mode():
    from fastapi.testclient import TestClient

    from agents import web

    with TestClient(web.app) as client:
        run = client.post("/api/memory/eval/run?mode=recall")
        assert run.status_code == 200
        assert run.json()["mode"] == "recall"
        assert "overall" in run.json()

        invalid = client.post("/api/memory/eval/run?mode=bogus")
        assert invalid.status_code == 400
