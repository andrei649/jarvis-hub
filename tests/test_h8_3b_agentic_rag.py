"""Tests for H8.3b — Agentic RAG Tool."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.memory.rag_tool import (
    TOOL_SPEC, MemorySearchTool, agentic_search,
)


# ── tool spec ────────────────────────────────────────────────────────────────

def test_tool_spec_shape():
    assert TOOL_SPEC["name"] == "search_memory"
    assert "query" in TOOL_SPEC["input_schema"]["properties"]
    assert TOOL_SPEC["input_schema"]["required"] == ["query"]


# ── single tool call ─────────────────────────────────────────────────────────

def _fake_recall(query, top_k):
    db = {
        "daughter": [{"text": "Cosmina", "score": 3}],
        "car": [{"text": "Tesla", "score": 2}],
    }
    for k, v in db.items():
        if k in query.lower():
            return v[:top_k]
    return []


def test_search_returns_hits_and_records_call():
    tool = MemorySearchTool(_fake_recall)
    res = tool.search("who is the daughter?")
    assert res["count"] == 1 and res["hits"][0]["text"] == "Cosmina"
    assert tool.calls[-1]["query"] == "who is the daughter?"


def test_search_empty_query():
    tool = MemorySearchTool(_fake_recall)
    assert tool.search("  ")["count"] == 0


def test_search_swallows_recall_errors():
    def boom(q, k):
        raise RuntimeError("recall down")
    assert MemorySearchTool(boom).search("x")["hits"] == []


# ── agentic loop ─────────────────────────────────────────────────────────────

def test_agentic_answers_immediately():
    tool = MemorySearchTool(_fake_recall)
    planner = lambda q, hist: {"action": "answer", "answer": "It's Cosmina."}
    out = agentic_search("daughter name?", tool, planner)
    assert out["stopped"] == "answered"
    assert out["iterations"] == 1
    assert out["answer"] == "It's Cosmina."


def test_agentic_retries_with_refined_query():
    tool = MemorySearchTool(_fake_recall)

    def planner(q, hist):
        # first query found nothing → refine to 'car'; then answer
        if hist[-1]["hits"]:
            return {"action": "answer", "answer": "Tesla."}
        return {"action": "search", "query": "what car"}

    out = agentic_search("vehicle?", tool, planner)
    assert out["queries"] == ["vehicle?", "what car"]   # retried with new query
    assert out["answer"] == "Tesla."
    assert out["iterations"] == 2


def test_agentic_caps_at_max_iters():
    tool = MemorySearchTool(_fake_recall)
    planner = lambda q, hist: {"action": "search", "query": "again"}   # never answers
    out = agentic_search("x", tool, planner, max_iters=3)
    assert out["stopped"] == "max_iters"
    assert out["iterations"] == 3


# ── endpoints ────────────────────────────────────────────────────────────────

def test_rag_endpoints():
    from agents import web
    with TestClient(web.app) as c:
        spec = c.get("/api/memory/tool-spec")
        assert spec.status_code == 200 and spec.json()["name"] == "search_memory"
        assert c.post("/api/memory/search-tool", json={}).status_code == 400
        r = c.post("/api/memory/search-tool", json={"query": "anything", "top_k": 3})
        assert r.status_code == 200
        assert "hits" in r.json() and "count" in r.json()
