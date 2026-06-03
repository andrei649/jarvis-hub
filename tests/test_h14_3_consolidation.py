"""Tests for H14.3 — Sleep-time memory consolidation (Mem0-style)."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.memory.consolidation import (
    ConsolidationEngine, similarity, ADD, UPDATE, DELETE, NOOP,
)

EXISTING = [
    {"id": "m1", "key": "home_city", "text": "User lives in Bucharest"},
    {"id": "m2", "key": "pet", "text": "User has a dog named Rex"},
]


# ── similarity ───────────────────────────────────────────────────────────────

def test_similarity_bounds():
    assert similarity("the cat sat", "the cat sat") == 1.0
    assert similarity("abc", "xyz") == 0.0
    assert 0 < similarity("user lives in Bucharest", "user lives in Cluj") < 1


# ── per-candidate decisions ──────────────────────────────────────────────────

def test_add_novel():
    eng = ConsolidationEngine()
    op = eng.decide({"key": "job", "text": "User works as an architect"}, EXISTING)
    assert op["op"] == ADD


def test_noop_duplicate():
    eng = ConsolidationEngine()
    op = eng.decide({"key": "pet", "text": "user has a dog named rex"}, EXISTING)
    assert op["op"] == NOOP and op["target_id"] == "m2"


def test_update_same_key_new_value():
    eng = ConsolidationEngine()
    op = eng.decide({"key": "home_city", "text": "User lives in Cluj now"}, EXISTING)
    assert op["op"] == UPDATE and op["target_id"] == "m1"


def test_delete_on_negation():
    eng = ConsolidationEngine()
    op = eng.decide({"text": "User no longer has a dog named Rex"}, EXISTING)
    assert op["op"] == DELETE and op["target_id"] == "m2"


def test_negation_without_match_is_noop():
    eng = ConsolidationEngine()
    op = eng.decide({"text": "User no longer plays the trombone"}, EXISTING)
    assert op["op"] == NOOP


def test_injected_decider_overrides():
    eng = ConsolidationEngine(decider=lambda c, e: {"op": NOOP, "reason": "llm says skip"})
    assert eng.decide({"text": "anything"}, EXISTING)["op"] == NOOP


# ── batch plan + summary + apply ─────────────────────────────────────────────

def test_plan_summary():
    eng = ConsolidationEngine()
    plan = eng.plan([
        {"key": "home_city", "text": "User lives in Cluj"},      # UPDATE
        {"key": "job", "text": "User is a teacher"},             # ADD
        {"key": "pet", "text": "user has a dog named rex"},      # NOOP
        {"text": "User no longer lives in Cluj"},                # DELETE (matches the just-updated m1)
    ], EXISTING)
    summary = eng.summarize(plan)
    assert summary[UPDATE] == 1 and summary[ADD] == 1 and summary[NOOP] == 1 and summary[DELETE] == 1


def test_apply_to_store():
    eng = ConsolidationEngine()

    class _Store:
        def __init__(self): self.added = []; self.updated = []; self.deleted = []
        def add(self, text, key=None): self.added.append((key, text))
        def update(self, id, text): self.updated.append((id, text))
        def delete(self, id): self.deleted.append(id)

    store = _Store()
    plan = [
        {"op": ADD, "text": "new", "key": "k"},
        {"op": UPDATE, "target_id": "m1", "text": "changed"},
        {"op": DELETE, "target_id": "m2"},
        {"op": NOOP},
    ]
    counts = eng.apply(plan, store)
    assert counts == {ADD: 1, UPDATE: 1, DELETE: 1, NOOP: 1}
    assert store.added == [("k", "new")] and store.deleted == ["m2"]


# ── endpoint ─────────────────────────────────────────────────────────────────

def test_consolidate_endpoint():
    from agents import web
    with TestClient(web.app) as c:
        if getattr(web.orch, "consolidation", None) is None:
            return
        assert c.post("/api/memory/consolidate", json={}).status_code == 400
        r = c.post("/api/memory/consolidate", json={
            "existing": EXISTING,
            "candidates": [{"key": "home_city", "text": "User lives in Iasi"}],
        })
        assert r.status_code == 200
        assert r.json()["plan"][0]["op"] == UPDATE
        assert r.json()["summary"]["UPDATE"] == 1
