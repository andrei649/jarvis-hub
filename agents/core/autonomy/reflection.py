"""Daily Reflection & Graph Consolidation (H5.15).

Nightly loop: review today's conversations, extract highlights + lessons via
LLM, and promote them as entities/relations into Neo4j.

Design:
- Idempotent per calendar day (skips if already ran today).
- LLM prompt returns clean JSON; falls back gracefully on parse failure.
- Injectible memory + llm_call → fully offline-testable.
"""
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Optional

from agents.core.persistence import JsonStore

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


class ReflectionRunStore(JsonStore):
    """Durable daily-reflection run ledger.

    The store records the public result for each calendar day so restart cycles
    do not accidentally re-run the same nightly reflection.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(path)

    def _serialize(self):
        return {"runs": self._runs}

    def _deserialize(self, raw) -> None:
        runs = raw.get("runs", {}) if isinstance(raw, dict) else {}
        self._runs = runs if isinstance(runs, dict) else {}

    def get(self, day: date | str) -> Optional[dict]:
        key = day.isoformat() if isinstance(day, date) else str(day)
        with self._lock:
            result = self._runs.get(key)
            return dict(result) if isinstance(result, dict) else None

    def record(self, day: date | str, result: dict) -> dict:
        key = day.isoformat() if isinstance(day, date) else str(day)
        item = dict(result or {})
        item.setdefault("date", key)
        with self._lock:
            self._runs[key] = item
            self._save()
        return dict(item)

    def latest(self) -> Optional[dict]:
        with self._lock:
            if not self._runs:
                return None
            key = sorted(self._runs)[-1]
            result = self._runs.get(key)
            return dict(result) if isinstance(result, dict) else None


class DailyReflector:
    """Nightly consolidator: extract knowledge from conversations → Neo4j graph."""

    def __init__(
        self,
        memory,
        llm_call,
        *,
        run_store: ReflectionRunStore | None = None,
        living_memory: Any | Callable[[], Any] | None = None,
    ):
        self._memory = memory      # MemoryManager
        self._llm_call = llm_call  # async (prompt: str) -> str
        self._run_store = run_store
        self._living_memory = living_memory
        self._last_run: Optional[date] = None
        self._last_result: Optional[dict] = None
        self._restore_latest_run()

    @property
    def last_run(self) -> Optional[date]:
        return self._last_run

    async def run(self, enabled: bool = True, *, force: bool = False) -> dict:
        """Full nightly reflection cycle.  Idempotent per calendar day."""
        if not enabled:
            return {"skipped": True, "reason": "disabled"}
        today = date.today()
        if not force and self._last_run == today:
            return {"skipped": True, "reason": "already_ran_today"}
        if not force:
            stored = self._stored_result(today)
            if stored is not None:
                self._last_run = today
                self._last_result = stored
                return {"skipped": True, "reason": "already_ran_today"}

        context = await self._gather_context()
        if not context:
            self._last_run = today
            result = {"skipped": True, "reason": "no_conversations"}
            self._last_result = self._record_run(today, result)
            return result

        extracted = await self._reflect(context)
        promoted = await self._consolidate(extracted, today)
        living_promoted = self._consolidate_living_memory(extracted, today)

        self._last_run = today
        self._last_result = {
            "date": today.isoformat(),
            "context_chars": len(context),
            "entities_extracted": len(extracted.get("entities", [])),
            "relations_extracted": len(extracted.get("relations", [])),
            "lessons": extracted.get("lessons", []),
            "promoted": promoted,
            "living_memory": living_promoted,
        }
        self._last_result = self._record_run(today, self._last_result)
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

    def _consolidate_living_memory(self, extracted: dict, today: date) -> dict:
        living = self._resolve_living_memory()
        if living is None:
            return {"available": False, "encoded": 0, "core": 0}
        encoded = core = 0
        day = today.isoformat()
        lessons = extracted.get("lessons", [])
        if not isinstance(lessons, list):
            lessons = []

        try:
            from ..cognition.memory import neuromodulators
            nm = neuromodulators(reward=0.8, surprise=1.0, novelty=0.6)
            for idx, item in enumerate(lessons):
                lesson = str(item or "").strip()
                if not lesson:
                    continue
                digest = hashlib.sha256(lesson.encode("utf-8", errors="ignore")).hexdigest()
                mem_id = f"reflection:{day}:lesson:{idx}:{digest[:12]}"
                result = living.encode(
                    mem_id,
                    {
                        "kind": "daily_reflection_lesson",
                        "date": day,
                        "source": "daily_reflection",
                        "lesson_sha256": digest,
                        "chars": len(lesson),
                    },
                    surprise=1.0,
                    nm=nm,
                )
                if result.get("encoded"):
                    encoded += 1
                core_memory = getattr(living, "core", None)
                if core_memory is not None and hasattr(core_memory, "put"):
                    core_memory.put(f"{day}: {lesson[:300]}")
                    core += 1
        except Exception:
            logger.debug("LivingMemory reflection handoff skipped", exc_info=True)
        return {"available": True, "encoded": encoded, "core": core}

    def _resolve_living_memory(self):
        source = self._living_memory
        if callable(source):
            try:
                return source()
            except Exception:
                logger.debug("LivingMemory provider failed during reflection", exc_info=True)
                return None
        return source

    def _stored_result(self, today: date) -> Optional[dict]:
        if self._run_store is None:
            return None
        try:
            return self._run_store.get(today)
        except Exception:
            logger.debug("Reflection run store read skipped", exc_info=True)
            return None

    def _record_run(self, today: date, result: dict) -> dict:
        if self._run_store is None:
            return result
        try:
            return self._run_store.record(today, result)
        except Exception:
            logger.debug("Reflection run store write skipped", exc_info=True)
            return result

    def _restore_latest_run(self) -> None:
        if self._run_store is None:
            return
        try:
            latest = self._run_store.latest()
        except Exception:
            logger.debug("Reflection run store restore skipped", exc_info=True)
            return
        if not latest:
            return
        raw_date = str(latest.get("date", "") or "")
        try:
            self._last_run = date.fromisoformat(raw_date)
        except ValueError:
            self._last_run = None
        self._last_result = latest

    def status(self) -> dict:
        return {
            "enabled": True,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "last_result": self._last_result,
        }
