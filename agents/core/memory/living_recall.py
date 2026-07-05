"""Post-fusion LivingMemory recall helpers.

LivingMemory stores turn metadata, not transcript text. This module therefore
never creates new recall snippets. It only re-orders already-retrieved hits when
their ids match LivingMemory turn references, then the usual RAG guard still
wraps the text before it enters a prompt.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agents.core.cognition.memory import tcm_rerank


def _payload_for_hit(hit: Any) -> dict | None:
    payload = getattr(hit, "payload", None)
    if payload is None and isinstance(hit, dict):
        payload = hit.get("payload")
    return payload if isinstance(payload, dict) else None


def _hit_id(hit: Any) -> str:
    value = getattr(hit, "id", None)
    if value is None and isinstance(hit, dict):
        value = hit.get("id")
    return str(value or "")


def _hit_score(hit: Any) -> float:
    value = getattr(hit, "score", None)
    if value is None and isinstance(hit, dict):
        value = hit.get("score")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _living_records_by_turn_ref(living_memory: Any, *, limit: int = 1000) -> dict[str, dict]:
    if living_memory is None or not hasattr(living_memory, "records"):
        return {}
    try:
        records = living_memory.records(prefix="", limit=limit) or []
    except Exception:
        return {}

    indexed: dict[str, dict] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        content = record.get("content")
        content = content if isinstance(content, dict) else {}
        turn_ref = content.get("turn_ref") or record.get("id")
        if turn_ref:
            indexed[str(turn_ref)] = record
    return indexed


def _annotate_hit(hit: Any, record: dict) -> None:
    payload = _payload_for_hit(hit)
    if payload is None:
        return
    payload["living_memory"] = {
        "matched": True,
        "tier": record.get("tier"),
        "activation": record.get("activation"),
    }


def rerank_with_living_memory(
    hits: Iterable[Any],
    living_memory: Any,
    *,
    context_ts: float | None = None,
    half_life: float = 86_400.0,
    weight: float = 0.3,
) -> list[Any]:
    """Re-rank already-fused hits using LivingMemory temporal context.

    Only matched hits are eligible. If no hit id matches a LivingMemory
    ``turn_ref``, the original order is returned unchanged.
    """
    original = list(hits or [])
    records_by_turn = _living_records_by_turn_ref(living_memory)
    if not original or not records_by_turn:
        return original

    rows: list[dict] = []
    matched = False
    for index, hit in enumerate(original):
        hit_id = _hit_id(hit)
        record = records_by_turn.get(hit_id)
        if record is not None:
            matched = True
            _annotate_hit(hit, record)
        content = record.get("content") if isinstance(record, dict) else {}
        content = content if isinstance(content, dict) else {}
        rows.append({
            "id": hit_id,
            "score": _hit_score(hit),
            "ts": content.get("ts") if record is not None else None,
            "_matched": record is not None,
            "_index": index,
            "_hit": hit,
        })

    if not matched:
        return original

    tcm_scores = {
        row["_index"]: row["tcm_score"]
        for row in tcm_rerank(
            [row for row in rows if row["_matched"]],
            context_ts=context_ts,
            half_life=half_life,
            weight=weight,
        )
    }
    ranked = [
        {**row, "tcm_score": tcm_scores.get(row["_index"], row["score"])}
        for row in rows
    ]
    ranked.sort(key=lambda row: (row["tcm_score"], -row["_index"]), reverse=True)
    return [row["_hit"] for row in ranked]
