"""
fusion.py — Retrieval Fusion Engine (H5.14).

Blends ranked results from the vector store (semantic similarity: Qdrant /
InMemoryVectorStore) and the knowledge graph (factual relations: Neo4j /
InMemoryGraph) into one ranked list via **Reciprocal Rank Fusion (RRF)**.

RRF is *rank*-based, not *score*-based, so it merges result lists whose scores
live on different scales (cosine similarity vs. graph relevance) **without
normalization**:

    rrf_score(d) = Σ_i  weight_i / (k + rank_i(d))

`rank_i(d)` is d's 1-based rank in list i (the term is omitted when d is absent
from list i); `k` is a damping constant (default 60, per Cormack et al. 2009);
`weight_i` biases one source over another.

The fuser is **pure and source-agnostic** (operates on `{source: [(id, payload)]}`)
so it is unit-tested offline; `HybridRetriever` adapts the two stores' concrete
hit shapes and is tested with the in-memory backends — no Qdrant/Neo4j needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FusedHit:
    """One fused result: its id, accumulated RRF score, contributing sources, and
    a merged payload (first non-empty value wins per key)."""
    id: str
    score: float = 0.0
    sources: list[str] = field(default_factory=list)
    payload: dict = field(default_factory=dict)


def reciprocal_rank_fusion(
    ranked_lists: dict[str, list[tuple[str, dict]]],
    *,
    k: int = 60,
    weights: Optional[dict[str, float]] = None,
    top_k: int = 10,
) -> list[FusedHit]:
    """Weighted Reciprocal Rank Fusion over already-ranked result lists.

    Args:
        ranked_lists: ``{source_name: [(doc_id, payload), ...]}`` — list order is
            the rank order (index 0 = rank 1).
        k: RRF damping constant (larger = flatter contribution by rank).
        weights: per-source multiplier (default 1.0 each).
        top_k: number of fused hits to return.

    Returns:
        Fused hits sorted by descending RRF score.
    """
    weights = weights or {}
    acc: dict[str, FusedHit] = {}
    for source, hits in ranked_lists.items():
        w = weights.get(source, 1.0)
        for rank, (doc_id, payload) in enumerate(hits, start=1):
            hit = acc.get(doc_id)
            if hit is None:
                hit = FusedHit(id=doc_id)
                acc[doc_id] = hit
            hit.score += w / (k + rank)
            if source not in hit.sources:
                hit.sources.append(source)
            for key, val in (payload or {}).items():
                hit.payload.setdefault(key, val)  # first non-empty wins
    return sorted(acc.values(), key=lambda h: h.score, reverse=True)[:top_k]


class HybridRetriever:
    """Fuses vector-store + knowledge-graph retrieval into one ranked list.

    Stores are injected and duck-typed (each exposes ``.search(...)``), so this
    runs offline in tests with ``InMemoryVectorStore`` + ``InMemoryGraph`` and
    unchanged in production against Qdrant + Neo4j.

    Hit shapes adapted (verified against ``store.py`` / ``graph.py``):
      * vector ``search(embedding, k)`` -> ``[{"id", "score", "metadata"}, ...]``
      * graph  ``search(keyword)``      -> ``[{"name", "type", "properties"}, ...]``
    """

    def __init__(self, vector_store=None, graph=None, *, k: int = 60,
                 vector_weight: float = 1.0, graph_weight: float = 1.0):
        self.vectors = vector_store
        self.graph = graph
        self.k = k
        self.weights = {"vector": vector_weight, "graph": graph_weight}

    def retrieve(self, *, embedding: Optional[list[float]] = None,
                 keyword: Optional[str] = None, top_k: int = 10) -> list[FusedHit]:
        """Retrieve from each available source and fuse. Either input may be
        omitted (single-source retrieval still works)."""
        ranked: dict[str, list[tuple[str, dict]]] = {}

        if embedding is not None and self.vectors is not None:
            vhits = self.vectors.search(embedding, k=top_k) or []
            ranked["vector"] = [(str(h.get("id")), h) for h in vhits if h.get("id")]

        if keyword and self.graph is not None:
            ghits = self.graph.search(keyword) or []
            # de-dup graph entities (search may yield a name twice: name + prop match)
            seen: set[str] = set()
            glist: list[tuple[str, dict]] = []
            for g in ghits:
                name = g.get("name")
                if name and name not in seen:
                    seen.add(name)
                    glist.append((str(name), g))
            ranked["graph"] = glist

        return reciprocal_rank_fusion(ranked, k=self.k, weights=self.weights, top_k=top_k)
