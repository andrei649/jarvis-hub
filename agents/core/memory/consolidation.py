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

DRA-27 (memory-hygiene leg 6) adds the pieces the HTTP apply surface needed and
the engine alone could not offer:

* ``existing_from_hits`` — adapts fused recall hits (``memory.fusion.FusedHit``
  or raw dicts) into the ``{id, key, text}`` shape the planner consumes, so a
  plan is computed against what the store *really* holds instead of ``[]``
  (a plan against nothing is degenerate: every candidate reads as "novel").
* ``validate_plan`` — the admissibility check an HTTP caller's plan must pass
  before it is applied (known ops, targets that exist, ADD/UPDATE carry text).
* ``ListStore`` — a pure in-memory store over ``{id, key, text}`` rows so a plan
  can be applied (or dry-run) to a caller-supplied snapshot and the merged
  result returned for inspection.
* ``apply_report`` — ``apply`` with a ``dry_run`` switch and an honest report
  (successes, errors, and what a dry run *would* have done), for the route.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

ADD, UPDATE, DELETE, NOOP = "ADD", "UPDATE", "DELETE", "NOOP"
OPS = frozenset({ADD, UPDATE, DELETE, NOOP})

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

    def apply(self, plan: list[dict], store, *, dry_run: bool = False) -> dict:
        """Apply a plan to a store exposing add(text, key=)/update(id, text)/delete(id).

        Returns the per-op success counts (the shape callers have always read).
        ``dry_run=True`` touches nothing and counts what *would* be applied; use
        :meth:`apply_report` when the errors and the dry-run flag matter too.
        """
        return self.apply_report(plan, store, dry_run=dry_run)["counts"]

    def apply_report(self, plan: list[dict], store, *, dry_run: bool = False) -> dict:
        """Apply (or dry-run) a plan and report honestly.

        ``counts`` are the ops that *succeeded* (or, in a dry run, would run);
        ``errors`` lists the ops whose store call raised — they were previously
        swallowed, so a caller could read a partial apply as a full one.
        """
        counts = {ADD: 0, UPDATE: 0, DELETE: 0, NOOP: 0}
        errors: list[dict] = []
        for idx, op in enumerate(plan or []):
            kind = op.get("op") if isinstance(op, dict) else None
            if kind not in OPS:
                errors.append({"index": idx, "op": kind, "reason": "unknown_op"})
                continue
            if dry_run:
                counts[kind] += 1
                continue
            try:
                if kind == ADD:
                    store.add(op.get("text", ""), key=op.get("key"))
                elif kind == UPDATE:
                    store.update(op.get("target_id"), op.get("text", ""))
                elif kind == DELETE:
                    store.delete(op.get("target_id"))
                counts[kind] += 1
            except Exception as exc:  # the store's failure is the caller's business
                errors.append({"index": idx, "op": kind, "reason": type(exc).__name__})
        return {"counts": counts, "dry_run": bool(dry_run), "errors": errors,
                "applied": sum(counts.values()) if not dry_run else 0}


# ── DRA-27: the pieces the HTTP apply surface needs ──────────────────────────

def _hit_field(hit, name: str, default=None):
    if isinstance(hit, dict):
        return hit.get(name, default)
    return getattr(hit, name, default)


def existing_from_hits(hits) -> list[dict]:
    """Adapt fused recall hits into the ``{id, key, text}`` rows the planner consumes.

    Accepts ``memory.fusion.FusedHit`` objects or raw dicts. Vector hits carry
    text under ``payload.metadata``, graph hits under ``payload.properties``
    (or just a ``name``). ``persistable`` says whether an apply can write the row
    back to the vector store (graph-only rows can be planned against but not
    rewritten by ``/consolidate/apply``). A hit with no id or text is dropped —
    it cannot be targeted, so it must not appear as an ``existing`` memory.
    """
    rows: list[dict] = []
    for hit in hits or []:
        try:
            hid = _hit_field(hit, "id")
            payload = _hit_field(hit, "payload") or {}
            if not isinstance(payload, dict):
                payload = {}
            md = payload.get("metadata") or payload.get("properties") or {}
            if not isinstance(md, dict):
                md = {}
            text = payload.get("text") or md.get("text") or payload.get("name") or ""
            if not hid or not str(text).strip():
                continue
            sources = list(_hit_field(hit, "sources") or [])
            key = md.get("key") or payload.get("key")
            rows.append({
                "id": str(hid),
                "key": str(key) if key else None,
                "text": str(text),
                "source": sources[0] if sources else "memory",
                "persistable": "vector" in sources,
            })
        except Exception:
            continue
    return rows


def validate_plan(plan, existing) -> list[str]:
    """Return the reasons a caller-supplied plan is NOT admissible (empty = fine).

    Stable, machine-readable reasons: ``plan_required``, ``existing_required``,
    ``bad_op:<index>``, ``unknown_target:<index>``, ``text_required:<index>``.
    """
    reasons: list[str] = []
    if not isinstance(existing, list) or not existing:
        reasons.append("existing_required")
    if not isinstance(plan, list) or not plan:
        reasons.append("plan_required")
        return reasons
    ids = {str(e.get("id")) for e in existing if isinstance(e, dict) and e.get("id")} \
        if isinstance(existing, list) else set()
    for idx, op in enumerate(plan):
        kind = op.get("op") if isinstance(op, dict) else None
        if kind not in OPS:
            reasons.append(f"bad_op:{idx}")
            continue
        if kind in (UPDATE, DELETE) and str(op.get("target_id") or "") not in ids:
            reasons.append(f"unknown_target:{idx}")
        if kind in (ADD, UPDATE) and not str(op.get("text") or "").strip():
            reasons.append(f"text_required:{idx}")
    return reasons


class ListStore:
    """A pure in-memory ``{id, key, text}`` store — the apply target for a
    caller-supplied snapshot. Ids for ADDs are ``new-<n>``; ``memories`` is the
    merged result. ``update``/``delete`` of an unknown id raise ``KeyError`` so
    ``apply_report`` records the miss instead of counting it as done."""

    def __init__(self, existing: list[dict] | None = None) -> None:
        self.memories: list[dict] = [dict(e) for e in (existing or []) if isinstance(e, dict)]
        self._n = 0

    def _find(self, item_id) -> dict:
        for m in self.memories:
            if str(m.get("id")) == str(item_id):
                return m
        raise KeyError(str(item_id))

    def add(self, text: str, key: str | None = None) -> str:
        self._n += 1
        rid = f"new-{self._n}"
        self.memories.append({"id": rid, "key": key, "text": text, "source": "consolidation"})
        return rid

    def update(self, item_id, text: str) -> None:
        self._find(item_id)["text"] = text

    def delete(self, item_id) -> None:
        self._find(item_id)  # raises for an unknown id
        self.memories = [m for m in self.memories if str(m.get("id")) != str(item_id)]
