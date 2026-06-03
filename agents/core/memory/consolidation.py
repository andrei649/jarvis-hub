"""
consolidation.py — H14.3 Sleep-time memory consolidation (Mem0-style).

Reframes nightly reflection as **incremental consolidation**: given new candidate
memories and the related existing memories, decide an explicit operation per
candidate — ADD (novel), UPDATE (supersede a same-key/near-duplicate fact),
DELETE (retract a contradicted/obsolete fact), or NOOP (already known). The
result is a reversible *plan* the caller can apply, so the store stays
self-cleaning instead of monotonically growing.

Deterministic + offline by default (token-overlap similarity + simple negation
detection); an LLM decider can be injected for richer judgement.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

ADD, UPDATE, DELETE, NOOP = "ADD", "UPDATE", "DELETE", "NOOP"

# phrases in a candidate that signal a retraction of a prior memory
_NEGATION = re.compile(
    r"\b(no longer|not any ?more|stopped|cancel(?:l?ed|s)?|quit|"
    r"isn'?t|doesn'?t|won'?t|never mind|forget|retract|obsolete)\b", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def similarity(a: str, b: str) -> float:
    """Jaccard token overlap in [0,1]."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class ConsolidationEngine:
    def __init__(self, similarity_threshold: float = 0.5,
                 decider: Optional[Callable[[dict, list[dict]], dict]] = None) -> None:
        self.threshold = similarity_threshold
        self._decider = decider

    def _best_match(self, cand: dict, existing: list[dict]) -> Optional[dict]:
        key = cand.get("key")
        # exact key match wins
        if key:
            keyed = [e for e in existing if e.get("key") == key]
            if keyed:
                return max(keyed, key=lambda e: similarity(cand.get("text", ""), e.get("text", "")))
        # else best text-similarity match above threshold
        scored = [(similarity(cand.get("text", ""), e.get("text", "")), e) for e in existing]
        scored = [(s, e) for s, e in scored if s >= self.threshold]
        if not scored:
            return None
        return max(scored, key=lambda se: se[0])[1]

    def decide(self, cand: dict, existing: list[dict]) -> dict:
        """Decide a single operation for *cand* against *existing* memories."""
        if self._decider is not None:
            try:
                return self._decider(cand, existing)
            except Exception:
                pass  # fall back to heuristic
        match = self._best_match(cand, existing)
        text = cand.get("text", "")

        if cand.get("delete") or _NEGATION.search(text):
            if match is not None:
                return {"op": DELETE, "target_id": match.get("id"), "key": match.get("key"),
                        "reason": "retraction/obsolete"}
            return {"op": NOOP, "reason": "retraction with no matching memory"}

        if match is None:
            return {"op": ADD, "text": text, "key": cand.get("key"), "reason": "novel"}
        if _norm(match.get("text", "")) == _norm(text):
            return {"op": NOOP, "target_id": match.get("id"), "reason": "duplicate"}
        return {"op": UPDATE, "target_id": match.get("id"), "text": text,
                "key": cand.get("key") or match.get("key"), "reason": "supersedes prior value"}

    def plan(self, candidates: list[dict], existing: list[dict]) -> list[dict]:
        """Produce an operation plan. Each ADD/UPDATE is reflected into a working
        copy so later candidates in the same batch see prior decisions."""
        working = [dict(e) for e in (existing or [])]
        ops: list[dict] = []
        synth = 0
        for cand in candidates or []:
            op = self.decide(cand, working)
            ops.append(op)
            if op["op"] == ADD:
                synth += 1
                working.append({"id": f"_new{synth}", "key": op.get("key"), "text": op.get("text", "")})
            elif op["op"] == UPDATE:
                for w in working:
                    if w.get("id") == op.get("target_id"):
                        w["text"] = op.get("text", w["text"])
            elif op["op"] == DELETE:
                working[:] = [w for w in working if w.get("id") != op.get("target_id")]
        return ops

    @staticmethod
    def summarize(plan: list[dict]) -> dict:
        out = {ADD: 0, UPDATE: 0, DELETE: 0, NOOP: 0}
        for op in plan:
            out[op["op"]] = out.get(op["op"], 0) + 1
        return out

    def apply(self, plan: list[dict], store) -> dict:
        """Apply a plan to a store exposing add(text, key=)/update(id, text)/delete(id)."""
        counts = {ADD: 0, UPDATE: 0, DELETE: 0, NOOP: 0}
        for op in plan:
            kind = op["op"]
            try:
                if kind == ADD:
                    store.add(op.get("text", ""), key=op.get("key"))
                elif kind == UPDATE:
                    store.update(op.get("target_id"), op.get("text", ""))
                elif kind == DELETE:
                    store.delete(op.get("target_id"))
                counts[kind] += 1
            except Exception:
                pass
        return counts
