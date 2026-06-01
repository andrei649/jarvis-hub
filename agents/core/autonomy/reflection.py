"""Daily Reflection & Graph Consolidation (H5.15).

Nightly loop: review today's conversations, extract highlights + lessons via
LLM, and promote them as entities/relations into Neo4j.

Design:
- Idempotent per calendar day (skips if already ran today).
- LLM prompt returns clean JSON; falls back gracefully on parse failure.
- Injectible memory + llm_call → fully offline-testable.
"""
import json
import logging
from datetime import date
from typing import Optional

logger = logging.getLogger("jarvis.reflection")

_REFLECTION_PROMPT = """\
You are Jarvis's memory consolidator. Review today's conversation turns and \
extract structured knowledge.

Conversations:
{context}

Respond with ONLY valid JSON (no markdown fences, no explanation):
{{
  "entities": [
    {{"name": "...", "type": "person|project|place|concept|event", \
"properties": {{"key": "value"}}}}
  ],
  "relations": [
    {{"source": "EntityA", "relation": "WORKS_ON|KNOWS|USES|LOCATED_AT|MANAGES", \
"target": "EntityB"}}
  ],
  "lessons": ["one-sentence lesson or key decision made today"]
}}
Extract only clearly mentioned facts. Omit speculation."""


class DailyReflector:
    """Nightly consolidator: extract knowledge from conversations → Neo4j graph."""

    def __init__(self, memory, llm_call):
        self._memory = memory      # MemoryManager
        self._llm_call = llm_call  # async (prompt: str) -> str
        self._last_run: Optional[date] = None
        self._last_result: Optional[dict] = None

    @property
    def last_run(self) -> Optional[date]:
        return self._last_run

    async def run(self, enabled: bool = True) -> dict:
        """Full nightly reflection cycle.  Idempotent per calendar day."""
        if not enabled:
            return {"skipped": True, "reason": "disabled"}
        today = date.today()
        if self._last_run == today:
            return {"skipped": True, "reason": "already_ran_today"}

        context = await self._gather_context()
        if not context:
            self._last_run = today
            return {"skipped": True, "reason": "no_conversations"}

        extracted = await self._reflect(context)
        promoted = await self._consolidate(extracted, today)

        self._last_run = today
        self._last_result = {
            "date": today.isoformat(),
            "context_chars": len(context),
            "entities_extracted": len(extracted.get("entities", [])),
            "relations_extracted": len(extracted.get("relations", [])),
            "lessons": extracted.get("lessons", []),
            "promoted": promoted,
        }
        logger.info(
            "Reflection done: %(e)s entities, %(r)s relations promoted",
            {"e": promoted["entities"], "r": promoted["relations"]},
        )
        return self._last_result

    async def _gather_context(self) -> str:
        session_id = self._memory.conversation.current_session_id
        if not session_id:
            return ""
        turns = await self._memory.get_history(session_id, last_n=60)
        if not turns:
            return ""
        lines = [
            f"{t.get('role', '?')}: {t.get('content', '')[:300]}"
            for t in turns
        ]
        return "\n".join(lines)

    async def _reflect(self, context: str) -> dict:
        prompt = _REFLECTION_PROMPT.format(context=context[:4000])
        try:
            raw = await self._llm_call(prompt)
            start, end = raw.find("{"), raw.rfind("}") + 1
            if 0 <= start < end:
                return json.loads(raw[start:end])
        except Exception as e:
            logger.warning("Reflection LLM error: %s", e)
        return {"entities": [], "relations": [], "lessons": []}

    async def _consolidate(self, extracted: dict, today: date) -> dict:
        meta = {"source": "daily_reflection", "date": today.isoformat()}
        entity_ok = relation_ok = 0

        for ent in extracted.get("entities", []):
            name = str(ent.get("name", "")).strip()
            if not name:
                continue
            try:
                props = {**ent.get("properties", {}), **meta}
                if await self._memory.add_fact(
                    name=name,
                    entity_type=ent.get("type", "concept"),
                    properties=props,
                ):
                    entity_ok += 1
            except Exception as e:
                logger.warning("Entity promote error (%s): %s", name, e)

        for rel in extracted.get("relations", []):
            src = str(rel.get("source", "")).strip()
            tgt = str(rel.get("target", "")).strip()
            relation = str(rel.get("relation", "RELATED_TO")).strip()
            if not (src and tgt and relation):
                continue
            try:
                if await self._memory.add_fact(
                    name=src,
                    source=src,
                    relation=relation,
                    target=tgt,
                    properties=meta,
                ):
                    relation_ok += 1
            except Exception as e:
                logger.warning("Relation promote error (%s→%s): %s", src, tgt, e)

        return {"entities": entity_ok, "relations": relation_ok}

    def status(self) -> dict:
        return {
            "enabled": True,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "last_result": self._last_result,
        }
