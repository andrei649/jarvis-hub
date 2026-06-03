"""
incremental.py — H12.6 Incremental KG updates (per-turn, not just nightly).

Lightweight, offline triple extraction so facts stated in a conversation land in
the knowledge graph *within the same session*, instead of waiting for the nightly
consolidation pass (H5.15). Extracted (subject, predicate, object) triples are
written to the live KnowledgeGraph (entities + relations) and, when available,
to the bi-temporal store (H14.1) so contradictions invalidate cleanly.

Extraction is deliberately conservative (a handful of high-precision patterns) —
the nightly LLM pass remains the high-recall path.
"""

from __future__ import annotations

import re
from typing import Optional

_PN = r"[A-Z][\w-]+(?:\s+[A-Z][\w-]+)?"   # a proper noun (1–2 capitalized words)
_ART = r"(?:a |an |the )?"

# (compiled pattern, predicate or None→use group2 as predicate, object group index)
_PATTERNS: list[tuple[re.Pattern, Optional[str]]] = [
    # "Andrei's daughter is Cosmina" → (Andrei, daughter, Cosmina)
    (re.compile(rf"({_PN})'s (\w+) (?:is|are|was|were) {_ART}({_PN})"), None),
    # "Andrei lives in Cluj" / "moved to Cluj"
    (re.compile(rf"({_PN}) (?:lives? in|moved to) {_ART}({_PN})"), "lives_in"),
    (re.compile(rf"({_PN}) works? (?:at|for) {_ART}({_PN})"), "works_at"),
    (re.compile(rf"({_PN}) (?:drives?|owns?|uses?|likes?|knows?) {_ART}({_PN})"), "related_to"),
    # copula: "Hephaestus is a server" → (Hephaestus, is_a, server)
    (re.compile(rf"({_PN}) is {_ART}(\w+)"), "is_a"),
]

# Words that should never be treated as a subject/object on their own.
_STOP = {"I", "He", "She", "It", "We", "They", "The", "This", "That", "There",
         "But", "And", "If", "When", "What", "Who"}


def _clean(tok: str) -> str:
    return tok.strip().strip(".,;:!?'\"")


def extract_triples(text: str) -> list[tuple[str, str, str]]:
    """Extract conservative (subject, predicate, object) triples from *text*."""
    if not text:
        return []
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for pattern, fixed_pred in _PATTERNS:
        for m in pattern.finditer(text):
            subj = _clean(m.group(1))
            if fixed_pred is None:
                pred = _clean(m.group(2)).lower()
                obj = _clean(m.group(3))
            else:
                pred = fixed_pred
                obj = _clean(m.group(2))
            if not subj or not obj or subj in _STOP or obj in _STOP:
                continue
            if subj.lower() == obj.lower():
                continue
            triple = (subj, pred, obj)
            if triple not in seen:
                seen.add(triple)
                out.append(triple)
    return out


class IncrementalKGUpdater:
    """Write per-turn triples into the live graph (+ optional bi-temporal store)."""

    def __init__(self, graph, bitemporal=None) -> None:
        self._graph = graph
        self._bt = bitemporal
        self.last_added: list[dict] = []

    def ingest(self, text: str, ts: Optional[float] = None, source: str = "conversation") -> int:
        """Extract + write triples. Returns the count written."""
        triples = extract_triples(text)
        added = []
        for subj, pred, obj in triples:
            try:
                if self._graph is not None:
                    self._graph.add_entity(subj, "unknown")
                    self._graph.add_entity(obj, "unknown")
                    self._graph.add_relation(subj, pred, obj, {"source": source})
                if self._bt is not None:
                    # is_a is multi-valued; other predicates are single-valued.
                    self._bt.add_fact(subj, pred, obj, valid_from=ts,
                                      multi=(pred == "is_a"))
                added.append({"subject": subj, "predicate": pred, "object": obj})
            except Exception:
                continue
        self.last_added = added
        return len(added)
