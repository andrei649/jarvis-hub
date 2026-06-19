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


class MemorySearchTool:
    """Wraps a recall function as the callable `search_memory` tool."""

    def __init__(self, recall_fn: RecallFn) -> None:
        self._recall = recall_fn
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
