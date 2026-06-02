"""Tests for H5.14 — Retrieval Fusion Engine (Reciprocal Rank Fusion).

Pure fuser + HybridRetriever + MemoryManager.hybrid_search, all offline
(InMemoryVectorStore + InMemoryGraph, no Qdrant/Neo4j).
"""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.memory.fusion import reciprocal_rank_fusion, FusedHit, HybridRetriever
from agents.core.memory.store import InMemoryVectorStore
from agents.core.memory.graph import InMemoryGraph
from agents.core.memory.manager import MemoryManager


# ── Task 1: pure RRF fuser ────────────────────────────────────────────────────

def test_rrf_rewards_agreement_across_sources():
    # "b" is present in both lists; "a"/"c" each appear in only one.
    lists = {
        "vector": [("a", {"t": "av"}), ("b", {"t": "bv"})],
        "graph":  [("c", {"t": "cg"}), ("b", {"t": "bg"})],
    }
    out = reciprocal_rank_fusion(lists, k=60, top_k=10)
    ids = [h.id for h in out]
    assert ids[0] == "b"                       # appears in both → highest fused score
    assert set(ids) == {"a", "b", "c"}
    b = next(h for h in out if h.id == "b")
    assert b.sources == ["vector", "graph"]    # provenance tracked
    assert b.payload["t"] in ("bv", "bg")      # payload preserved


def test_rrf_weights_bias_source():
    lists = {"vector": [("a", {})], "graph": [("b", {})]}
    out = reciprocal_rank_fusion(lists, k=60, weights={"graph": 5.0}, top_k=10)
    assert out[0].id == "b"                    # graph up-weighted → wins


def test_rrf_respects_rank_order_and_top_k():
    lists = {"vector": [("a", {}), ("b", {}), ("c", {})]}
    out = reciprocal_rank_fusion(lists, k=60, top_k=2)
    assert [h.id for h in out] == ["a", "b"]   # rank 1 > rank 2, truncated to 2


def test_rrf_empty_input():
    assert reciprocal_rank_fusion({}, top_k=5) == []


# ── Task 2: HybridRetriever over the real in-memory stores ────────────────────

def test_hybrid_retriever_fuses_vector_and_graph():
    vs = InMemoryVectorStore(dimension=3)
    vs.add("conv:1", [1.0, 0.0, 0.0], {"text": "andrei works at raiffeisen"})
    vs.add("conv:2", [0.0, 1.0, 0.0], {"text": "cats kiwi and pepper"})
    g = InMemoryGraph()
    g.add_entity("Raiffeisen", "company", {"industry": "banking"})

    r = HybridRetriever(vs, g)
    hits = r.retrieve(embedding=[1.0, 0.0, 0.0], keyword="raiffeisen", top_k=5)
    ids = [h.id for h in hits]
    assert "conv:1" in ids and "Raiffeisen" in ids      # both sources represented
    assert all(h.score > 0 for h in hits)


def test_hybrid_retriever_single_source_ok():
    vs = InMemoryVectorStore(dimension=3)
    vs.add("x", [1.0, 0.0, 0.0], {})
    r = HybridRetriever(vs, None)
    assert [h.id for h in r.retrieve(embedding=[1.0, 0.0, 0.0])] == ["x"]


def test_hybrid_retriever_no_inputs_returns_empty():
    r = HybridRetriever(InMemoryVectorStore(dimension=3), InMemoryGraph())
    assert r.retrieve() == []


def test_hybrid_retriever_graph_dedup():
    g = InMemoryGraph()
    # a property match + name match could surface the same entity twice
    g.add_entity("Raiffeisen", "company", {"note": "raiffeisen hq"})
    r = HybridRetriever(None, g)
    hits = r.retrieve(keyword="raiffeisen", top_k=5)
    assert [h.id for h in hits] == ["Raiffeisen"]       # de-duplicated


# ── Task 3: MemoryManager.hybrid_search ───────────────────────────────────────

@pytest.mark.asyncio
async def test_memory_manager_hybrid_search():
    m = MemoryManager()                                  # in-memory defaults (768-dim)
    emb = [1.0] + [0.0] * 767
    await m.store_embedding("conv:1", emb, {"text": "raiffeisen"})
    await m.add_fact(name="Raiffeisen", entity_type="company")
    hits = await m.hybrid_search(embedding=emb, keyword="raiffeisen", top_k=5)
    ids = [h.id for h in hits]
    assert "conv:1" in ids
    assert "Raiffeisen" in ids
    assert all(isinstance(h, FusedHit) for h in hits)
