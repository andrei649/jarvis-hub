"""
rag_tool.py — H8.3b Agentic RAG Tool (extends H8.3).

Recall stops being a fixed top-k injection and becomes an LLM-callable tool:
``search_memory(query, top_k)``. The model decides *when* and *how* to search and
may **retry with a different query** if the first results are weak. This module
provides the tool wrapper, its function-calling spec, and an agentic loop driven
by an injected planner (the LLM in production, a scripted fake in tests).
"""

from __future__ import annotations

from typing import Callable

from ..security import quarantine, taint
from ..security.rag_guard import REDACTION, provenance_from_hit
from ..security.recall_taint import mark_turn_recall_tainted

# Function-calling schema exposed to the model (Anthropic/OpenAI-style).
TOOL_SPEC = {
    "name": "search_memory",
    "description": (
        "Search the user's long-term memory (facts, entities, knowledge graph). "
        "Call this when you need information you weren't given. You may call it "
        "multiple times with refined queries if the first results are insufficient."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look up."},
            "top_k": {"type": "integer", "description": "Max results (default 5)."},
        },
        "required": ["query"],
    },
}

# recall_fn(query, top_k) -> list[dict] (each hit: {"text"/"name", "score", ...})
RecallFn = Callable[[str, int], list]
# planner(query, history) -> {"action": "search"|"answer", "query"?: str, "answer"?: str}
PlannerFn = Callable[[str, list], dict]


def _sanitize_hit(hit: dict) -> dict:
    """CDX-7 follow-up: scan a retrieved hit and **redact** it if the injection
    scanner flags it. Retrieved memory is untrusted data — a stored string (or one
    synced from an untrusted feed into the graph) could carry "ignore previous
    instructions…" that the model would otherwise read straight out of the
    ``search_memory`` tool result. The prompt-string recall sites are fenced by
    ``rag_guard.wrap_memory``; this is the dict-shaped tool path it deferred.

    Clean hits pass through unchanged (same object). A flagged hit keeps its score
    and metadata but its text is replaced by the redaction marker and tagged
    ``injection_flagged`` so the model/UI sees *that* something matched without
    reading the injected instructions.
    """
    if not isinstance(hit, dict):
        return hit
    field = "text" if "text" in hit else ("name" if "name" in hit else None)
    text = (hit.get(field) if field else "") or ""
    flags = quarantine.detect_injection(text) if text else []
    if not flags:
        return hit
    out = dict(hit)
    out[field or "text"] = REDACTION
    out["injection_flagged"] = True
    out["flags"] = flags
    return out


def _hit_tainted(hit) -> bool:
    """SEC-B5: does this hit carry recall taint — an upstream taint mark, an untrusted
    source label, or the injection flag ``_sanitize_hit`` just set?

    This path renders no fenced block, so it cannot read ``WrappedMemory.tainted``; this
    is the same verdict computed on one un-fenced hit. The flat hits this tool receives
    key their provenance as ``source``, while the fused-hit shape ``provenance_from_hit``
    adapts uses ``sources`` — so both are consulted rather than one guessed.
    """
    if not isinstance(hit, dict):
        return False
    if hit.get("injection_flagged") or taint.is_tainted(hit):
        return True
    md = hit.get("metadata") or hit.get("properties") or {}
    if taint.is_tainted(md):
        return True
    return taint.is_untrusted_source(hit.get("source") or provenance_from_hit(hit).source)


class MemorySearchTool:
    """Wraps a recall function as the callable `search_memory` tool."""

    def __init__(self, recall_fn: RecallFn, *, scan: bool = True) -> None:
        self._recall = recall_fn
        # CDX-7 follow-up: scan retrieved hits for injection and redact flagged
        # ones before they reach the model. On by default; off only for callers
        # that have already sanitized upstream.
        self._scan = scan
        self.calls: list[dict] = []

    @property
    def spec(self) -> dict:
        return dict(TOOL_SPEC)

    def search(self, query: str, top_k: int = 5) -> dict:
        query = (query or "").strip()
        top_k = max(1, min(int(top_k or 5), 50))
        if not query:
            return {"query": "", "hits": [], "count": 0}
        try:
            hits = list(self._recall(query, top_k) or [])
        except Exception:
            hits = []
        hits = hits[:top_k]
        if self._scan:
            hits = [_sanitize_hit(h) for h in hits]
        if any(_hit_tainted(h) for h in hits):
            # SEC-B5: the model is about to read untrusted recalled memory — same
            # turn-scoped escalation the prompt-string recall path raises.
            mark_turn_recall_tainted()
        self.calls.append({"query": query, "count": len(hits)})
        return {"query": query, "hits": hits, "count": len(hits)}


def agentic_search(
    query: str,
    tool: MemorySearchTool,
    planner: PlannerFn,
    max_iters: int = 3,
) -> dict:
    """Agentic recall loop: search → let the planner refine or answer.

    The planner sees the running history of (query, hits) and returns either
    {"action": "answer", "answer": ...} to stop, or {"action": "search",
    "query": <refined>} to retry. Capped at *max_iters* searches.
    """
    history: list[dict] = []
    queries: list[str] = []
    all_hits: list = []
    current = query

    for i in range(max(1, max_iters)):
        result = tool.search(current)
        queries.append(result["query"])
        all_hits.extend(result["hits"])
        history.append({"query": result["query"], "hits": result["hits"]})

        decision = planner(current, history) or {}
        if decision.get("action") == "answer":
            return {
                "answer": decision.get("answer", ""),
                "iterations": i + 1,
                "queries": queries,
                "hits": all_hits,
                "stopped": "answered",
            }
        # refine query for the next iteration (fall back to same query)
        current = decision.get("query") or current

    return {
        "answer": "",
        "iterations": max(1, max_iters),
        "queries": queries,
        "hits": all_hits,
        "stopped": "max_iters",
    }
