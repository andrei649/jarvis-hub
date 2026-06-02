"""Tests for H5.15 — Daily Reflection & Graph Consolidation.

All offline: InMemoryGraph + MemoryManager, no Neo4j/Qdrant.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy.reflection import DailyReflector
from agents.core.memory.manager import MemoryManager


# ── helpers ───────────────────────────────────────────────────────────────────

async def _mem_with_turns(*turns) -> MemoryManager:
    """Return a MemoryManager pre-seeded with conversation turns."""
    m = MemoryManager()
    sid = await m.new_session()
    for role, content in turns:
        await m.add_turn(sid, role, content)
    return m


def _llm_returning(payload: dict):
    async def _llm(prompt: str) -> str:
        return json.dumps(payload)
    return _llm


# ── Task 1: idempotency ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reflection_skips_when_disabled():
    m = await _mem_with_turns(("user", "Hello"), ("assistant", "Hi"))
    r = DailyReflector(m, _llm_returning({}))
    result = await r.run(enabled=False)
    assert result["skipped"] is True
    assert result["reason"] == "disabled"


@pytest.mark.asyncio
async def test_reflection_idempotent_same_day():
    m = await _mem_with_turns(("user", "Hello"))
    calls = []

    async def _llm(p):
        calls.append(p)
        return json.dumps({"entities": [], "relations": [], "lessons": []})

    r = DailyReflector(m, _llm)
    await r.run()
    await r.run()            # second call same day → skipped
    assert len(calls) == 1   # LLM called only once


@pytest.mark.asyncio
async def test_reflection_runs_again_next_day():
    m = await _mem_with_turns(("user", "Hello"))
    calls = []

    async def _llm(p):
        calls.append(p)
        return json.dumps({"entities": [], "relations": [], "lessons": []})

    r = DailyReflector(m, _llm)
    await r.run()
    r._last_run = date.today() - timedelta(days=1)   # simulate yesterday's run
    await r.run()
    assert len(calls) == 2


# ── Task 2: entity + relation consolidation ───────────────────────────────────

@pytest.mark.asyncio
async def test_entities_promoted_to_graph():
    m = await _mem_with_turns(("user", "Andrei works at Raiffeisen"))
    payload = {
        "entities": [
            {"name": "Andrei", "type": "person", "properties": {}},
            {"name": "Raiffeisen", "type": "place", "properties": {}},
        ],
        "relations": [],
        "lessons": ["Andrei works at Raiffeisen"],
    }
    r = DailyReflector(m, _llm_returning(payload))
    result = await r.run()
    assert result["promoted"]["entities"] == 2
    assert result["entities_extracted"] == 2
    # Verify graph contains entities
    andrei = m.graph.get_entity("Andrei")
    assert andrei is not None
    assert andrei["type"] == "person"


@pytest.mark.asyncio
async def test_relations_promoted_to_graph():
    m = await _mem_with_turns(("user", "Andrei uses Jarvis daily"))
    payload = {
        "entities": [],
        "relations": [{"source": "Andrei", "relation": "USES", "target": "Jarvis"}],
        "lessons": [],
    }
    r = DailyReflector(m, _llm_returning(payload))
    result = await r.run()
    assert result["promoted"]["relations"] == 1
    rels = m.graph.get_relations("Andrei")
    assert any(rel["relation"] == "USES" for rel in rels)


# ── Task 3: graceful degradation ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reflection_no_conversations():
    m = MemoryManager()
    # Reset in-memory state so no persisted session bleeds in from other tests.
    m.conversation.sessions = {}
    m.conversation.current_session_id = None
    r = DailyReflector(m, _llm_returning({}))
    result = await r.run()
    assert result["skipped"] is True
    assert result["reason"] == "no_conversations"


@pytest.mark.asyncio
async def test_reflection_handles_malformed_llm_json():
    m = await _mem_with_turns(("user", "test"))

    async def _bad_llm(p: str) -> str:
        return "not json at all"

    r = DailyReflector(m, _bad_llm)
    result = await r.run()
    assert result["promoted"]["entities"] == 0
    assert result["promoted"]["relations"] == 0


@pytest.mark.asyncio
async def test_reflection_skips_empty_entity_names():
    m = await _mem_with_turns(("user", "something"))
    payload = {
        "entities": [{"name": "", "type": "concept"}, {"name": "  ", "type": "person"}],
        "relations": [],
        "lessons": [],
    }
    r = DailyReflector(m, _llm_returning(payload))
    result = await r.run()
    assert result["promoted"]["entities"] == 0   # blank names ignored


# ── Task 4: status ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_before_run():
    m = MemoryManager()
    r = DailyReflector(m, _llm_returning({}))
    s = r.status()
    assert s["last_run"] is None
    assert s["enabled"] is True


@pytest.mark.asyncio
async def test_status_after_run():
    m = await _mem_with_turns(("user", "Hello Jarvis"))
    r = DailyReflector(m, _llm_returning({"entities": [], "relations": [], "lessons": []}))
    await r.run()
    s = r.status()
    assert s["last_run"] == date.today().isoformat()
    assert s["last_result"] is not None
