"""
eval.py — H14.2 Memory Evaluation Harness (LongMemEval / LoCoMo-style).

The *measurement layer* for memory: a small, owned corpus of cases across five
abilities — extraction, multi-session, temporal, update, and abstention — with a
scorer and a per-ability report. The corpus is hand-authored (public LoCoMo
scores are disputed), and the harness is answer-function-agnostic: pass any
``answer_fn(question, facts) -> str`` (a real recall+LLM pipeline in prod, a fake
in tests) and get scores back.

Abstention cases have **no** supporting fact: the right behavior is to say "I
don't know" rather than hallucinate, so abstention is scored as *did it abstain*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from .manager import MemoryManager

ABILITIES = ["extraction", "multi_session", "temporal", "update", "abstention"]

# Markers that count as a (correct) abstention.
_ABSTAIN = ("i don't know", "i do not know", "not sure", "no information",
            "don't have", "do not have", "can't find", "cannot find", "unknown")


@dataclass
class MemoryEvalCase:
    id: str
    ability: str
    facts: list[str]                 # the "memory" to ingest for this case
    question: str
    expected: list[str] = field(default_factory=list)  # any-of substrings
    abstain: bool = False            # True → correct answer is to abstain

    def to_dict(self) -> dict:
        return {
            "id": self.id, "ability": self.ability, "facts": self.facts,
            "question": self.question, "expected": self.expected, "abstain": self.abstain,
        }


# ── owned corpus ─────────────────────────────────────────────────────────────

DEFAULT_CORPUS: list[MemoryEvalCase] = [
    # extraction — single fact stated, recall it
    MemoryEvalCase("ext-1", "extraction",
                   ["Andrei's daughter is named Cosmina."],
                   "What is the name of Andrei's daughter?", ["Cosmina"]),
    MemoryEvalCase("ext-2", "extraction",
                   ["The home server runs on a machine called Hephaestus."],
                   "What is the home server called?", ["Hephaestus"]),
    # multi_session — fact split across sessions must be combined
    MemoryEvalCase("multi-1", "multi_session",
                   ["Session 1: Andrei started learning the guitar.",
                    "Session 5: He now practices guitar every morning."],
                   "What instrument does Andrei practice every morning?", ["guitar"]),
    # temporal — reason about ordering / recency
    MemoryEvalCase("temp-1", "temporal",
                   ["In January Andrei lived in Bucharest.",
                    "In June Andrei moved to Cluj."],
                   "Where does Andrei live most recently?", ["Cluj"]),
    # update — a later fact overrides an earlier one
    MemoryEvalCase("upd-1", "update",
                   ["Andrei's car is a BMW.",
                    "Andrei sold the BMW and now drives a Tesla."],
                   "What car does Andrei drive now?", ["Tesla"]),
    # abstention — nothing in memory supports an answer
    MemoryEvalCase("abs-1", "abstention",
                   ["Andrei's daughter is named Cosmina."],
                   "What is the name of Andrei's cat?", abstain=True),
    MemoryEvalCase("abs-2", "abstention",
                   ["The home server is called Hephaestus."],
                   "What is Andrei's blood type?", abstain=True),
]


# ── scoring ──────────────────────────────────────────────────────────────────

def _is_abstention(answer: str) -> bool:
    low = (answer or "").lower()
    return any(marker in low for marker in _ABSTAIN)


def score_answer(case: MemoryEvalCase, answer: str) -> bool:
    """True if *answer* is correct for *case*."""
    if case.abstain:
        return _is_abstention(answer)
    low = (answer or "").lower()
    # Wrong if it abstained when an answer existed.
    if _is_abstention(low):
        return False
    return any(exp.lower() in low for exp in case.expected)


# ── baseline answerer (no LLM) ───────────────────────────────────────────────

def keyword_answer(question: str, facts: list[str]) -> str:
    """A deterministic baseline: return the most word-overlapping fact, else abstain.

    Recency-biased (later facts win ties) so simple update/temporal cases can pass.
    """
    q_words = set(re.findall(r"\w+", (question or "").lower()))
    best, best_score = "", 0.0
    for fact in facts:
        f_words = set(re.findall(r"\w+", fact.lower()))
        overlap = len(q_words & f_words)
        if overlap >= best_score:          # >= → later facts win ties (recency)
            best, best_score = fact, overlap
    if best_score < 2:
        return "I don't know."
    return best


# ── harness ──────────────────────────────────────────────────────────────────

AnswerFn = Callable[[str, list], str]


def run_eval(answer_fn: AnswerFn, corpus: Optional[list[MemoryEvalCase]] = None) -> dict:
    """Run *answer_fn* over the corpus; return per-ability + overall scores."""
    corpus = corpus if corpus is not None else DEFAULT_CORPUS
    per_ability: dict[str, dict] = {a: {"n": 0, "passed": 0} for a in ABILITIES}
    results = []
    for case in corpus:
        answer = answer_fn(case.question, case.facts)
        ok = score_answer(case, answer)
        bucket = per_ability.setdefault(case.ability, {"n": 0, "passed": 0})
        bucket["n"] += 1
        bucket["passed"] += int(ok)
        results.append({"id": case.id, "ability": case.ability, "passed": ok,
                        "answer": answer})

    for a, b in per_ability.items():
        b["score"] = round(b["passed"] / b["n"], 3) if b["n"] else None
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    return {
        "overall": {"n": total, "passed": passed,
                    "score": round(passed / total, 3) if total else None},
        "by_ability": per_ability,
        "results": results,
    }


def _hit_text(hit) -> str:
    payload = getattr(hit, "payload", None)
    if payload is None and isinstance(hit, dict):
        payload = hit.get("payload", hit)
    payload = payload if isinstance(payload, dict) else {}
    metadata = payload.get("metadata") or payload.get("properties") or {}
    metadata = metadata if isinstance(metadata, dict) else {}
    return str(payload.get("text") or metadata.get("text") or payload.get("name") or "")


async def _recall_answer(question: str, facts: list[str], *, case_id: str, top_k: int) -> tuple[str, list[str]]:
    manager = MemoryManager()
    from agents.core.ingestion.embedder import Embedder
    manager._embedder = Embedder(backend="hash")

    for idx, fact in enumerate(facts or []):
        await manager.remember(
            fact,
            record_id=f"{case_id}:{idx}",
            metadata={"case_id": case_id},
        )

    hits = await manager.recall(question, top_k=top_k)
    retrieved = [text for text in (_hit_text(hit) for hit in hits or []) if text]
    return keyword_answer(question, retrieved), retrieved


async def run_recall_eval(
    corpus: Optional[list[MemoryEvalCase]] = None,
    *,
    top_k: int = 5,
) -> dict:
    """Run the eval through real MemoryManager remember/recall.

    This deterministic mode is a recall-path gate, not an LLM-quality claim: it
    stores each case's facts, recalls against the question, then uses the
    keyword answerer only over retrieved snippets.
    """
    corpus = corpus if corpus is not None else DEFAULT_CORPUS
    per_ability: dict[str, dict] = {a: {"n": 0, "passed": 0} for a in ABILITIES}
    results = []
    for case in corpus:
        answer, retrieved = await _recall_answer(case.question, case.facts, case_id=case.id, top_k=top_k)
        ok = score_answer(case, answer)
        bucket = per_ability.setdefault(case.ability, {"n": 0, "passed": 0})
        bucket["n"] += 1
        bucket["passed"] += int(ok)
        results.append({
            "id": case.id,
            "ability": case.ability,
            "passed": ok,
            "answer": answer,
            "retrieved": retrieved,
        })

    for ability, bucket in per_ability.items():
        bucket["score"] = round(bucket["passed"] / bucket["n"], 3) if bucket["n"] else None
    total = len(results)
    passed = sum(1 for result in results if result["passed"])
    return {
        "mode": "recall",
        "top_k": top_k,
        "overall": {
            "n": total,
            "passed": passed,
            "score": round(passed / total, 3) if total else None,
        },
        "by_ability": per_ability,
        "results": results,
    }
