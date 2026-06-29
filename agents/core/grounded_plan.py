"""grounded_plan.py — 0.51: reference-grounded planning (honest, no fabrication).

The Reference-Driven Creation flow fetches sources, then asks the model to draft a
plan whose steps cite those sources. The risk is the model *claiming* grounding it
doesn't have — citing a reference id that wasn't provided, or proposing a step with
no citation at all. This module is the **honest-grounding enforcement layer**: a
pure validator/structurer that, given the reference set and a draft plan, reports
exactly which steps are grounded, which cite an **unknown** reference, and which are
**ungrounded** — never silently accepting an unsupported step.

It does not *generate* anything (the model proposes ``steps`` upstream); it makes the
grounding **auditable and honest**, mirroring the project's "facts / inference /
recommendation stay separate, nothing is fabricated" invariant.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _reference_index(references: Iterable[Mapping[str, Any]]) -> dict[str, dict]:
    """Map reference id → reference. Raises if a reference has no usable id."""
    index: dict[str, dict] = {}
    for ref in references:
        rid = str(ref.get("id") or "").strip()
        if not rid:
            raise ValueError("every reference needs a non-empty 'id'")
        index[rid] = dict(ref)
    return index


def ground_plan(
    goal: str,
    references: Iterable[Mapping[str, Any]],
    steps: Iterable[Mapping[str, Any]],
) -> dict:
    """Validate a draft plan against its reference set.

    ``references``: items with an ``id`` (and usually ``title``/``url``).
    ``steps``: items with ``text`` and optional ``cites`` (a list of reference ids).

    Returns a structured, honest grounded plan::

        {goal, reference_count, steps:[{index, text, cites, unknown_cites,
         cited_titles, grounded}], grounded_steps, ungrounded_steps,
         unknown_citations, unused_references, coverage, fully_grounded}

    A step is **grounded** iff it cites at least one *known* reference. ``cites`` on
    each output step is the deduped list of *valid* ids; ids not in the reference
    set are surfaced in ``unknown_cites`` (and the plan-level ``unknown_citations``)
    rather than dropped. ``fully_grounded`` is true only when every step is grounded
    **and** no unknown citation was made anywhere.
    """
    index = _reference_index(references)
    used: set[str] = set()
    unknown_all: list[str] = []
    out_steps: list[dict] = []
    ungrounded: list[int] = []

    for i, step in enumerate(steps):
        raw_cites = step.get("cites") or []
        valid: list[str] = []
        unknown: list[str] = []
        seen: set[str] = set()
        for c in raw_cites:
            cid = str(c).strip()
            if not cid or cid in seen:
                continue
            seen.add(cid)
            if cid in index:
                valid.append(cid)
                used.add(cid)
            else:
                unknown.append(cid)
                unknown_all.append(cid)
        grounded = bool(valid)
        if not grounded:
            ungrounded.append(i)
        out_steps.append({
            "index": i,
            "text": str(step.get("text") or ""),
            "cites": valid,
            "unknown_cites": unknown,
            "cited_titles": [str(index[c].get("title") or c) for c in valid],
            "grounded": grounded,
        })

    total = len(index)
    return {
        "goal": str(goal),
        "reference_count": total,
        "steps": out_steps,
        "grounded_steps": sum(1 for s in out_steps if s["grounded"]),
        "ungrounded_steps": ungrounded,
        # de-duplicated, order-stable
        "unknown_citations": list(dict.fromkeys(unknown_all)),
        "unused_references": [rid for rid in index if rid not in used],
        "coverage": (len(used) / total) if total else 0.0,
        "fully_grounded": not ungrounded and not unknown_all,
    }
