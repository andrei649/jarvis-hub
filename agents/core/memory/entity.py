"""
entity.py — H8.1b Entity Memory Store (extends H8.1 profile memory).

A dedicated, searchable index of the *named entities* that show up in
conversations — people, projects, places, organizations, concepts — kept
separately from the user-profile facts (H8.1) and the relation graph. Each
entity accumulates a mention count, the sources/contexts it appeared in, and
first/last-seen timestamps, so the HUD Memory tab can list and search them.

Extraction is pluggable: a lightweight, offline proper-noun heuristic is built
in (``extract_entities``), and an LLM extractor can be injected for richer
typing. Storage is a small JSON file (atomic writes), fully offline-testable.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from ..persistence import JsonStore
from typing import Optional

DEFAULT_PATH = Path("memory_logs/entities.json")

# Type hints by keyword — cheap classification for the heuristic extractor.
_TYPE_HINTS = {
    "person": {"mr", "ms", "dr", "prof"},
    "organization": {"inc", "ltd", "gmbh", "srl", "corp", "bank", "llc"},
}

# Common capitalized words that are not entities (sentence starts, etc.).
_STOPWORDS = {
    "the", "a", "an", "i", "you", "he", "she", "it", "we", "they", "this",
    "that", "these", "those", "and", "or", "but", "if", "then", "when", "what",
    "who", "why", "how", "is", "are", "was", "were", "do", "does", "did",
    "can", "could", "should", "would", "will", "my", "your", "his", "her",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
}

# Runs of Capitalized words (allowing internal & / . ') → candidate proper nouns.
_PROPER_NOUN = re.compile(r"\b([A-Z][\w.&'-]*(?:\s+[A-Z][\w.&'-]*)*)")


def _classify(name: str) -> str:
    low = {w.strip(".").lower() for w in name.split()}
    for etype, hints in _TYPE_HINTS.items():
        if low & hints:
            return etype
    return "unknown"


def extract_entities(text: str) -> list[tuple[str, str]]:
    """Heuristic proper-noun extraction → list of (name, type). Offline."""
    if not text:
        return []
    seen: dict[str, str] = {}
    for m in _PROPER_NOUN.finditer(text):
        # Trim edge punctuation (e.g. trailing sentence period) but keep internal
        # marks like AT&T / O'Brien / U.S.
        phrase = m.group(1).strip().strip(".,;:!?\"'")
        if not phrase:
            continue
        # Drop single tokens that are just a capitalized stopword / sentence start.
        words = phrase.split()
        if len(words) == 1 and words[0].lower() in _STOPWORDS:
            continue
        if len(phrase) < 2:
            continue
        key = phrase
        if key not in seen:
            seen[key] = _classify(phrase)
    return list(seen.items())


class EntityStore(JsonStore):
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return self._entities

    def _deserialize(self, raw) -> None:
        self._entities = raw if isinstance(raw, dict) else {}


    # ── write ──────────────────────────────────────────────────────────────

    def record(
        self,
        name: str,
        entity_type: str = "unknown",
        source: str = "",
        context: str = "",
        ts: Optional[float] = None,
    ) -> dict:
        """Upsert an entity, incrementing its mention count + recency."""
        name = (name or "").strip()
        if not name:
            return {}
        ts = ts or time.time()
        key = name.lower()
        with self._lock:
            ent = self._entities.get(key)
            if ent is None:
                ent = {
                    "name": name,
                    "type": entity_type,
                    "mentions": 0,
                    "sources": [],
                    "contexts": [],
                    "first_seen": ts,
                    "last_seen": ts,
                }
                self._entities[key] = ent
            ent["mentions"] += 1
            ent["last_seen"] = ts
            # Upgrade type if we learn something more specific than "unknown".
            if ent["type"] == "unknown" and entity_type != "unknown":
                ent["type"] = entity_type
            if source and source not in ent["sources"]:
                ent["sources"].append(source)
            if context:
                ent["contexts"].append(context[:200])
                ent["contexts"] = ent["contexts"][-5:]  # keep last 5 samples
            self._save()
            return dict(ent)

    def ingest_text(self, text: str, source: str = "") -> int:
        """Extract + record all entities in *text*; return count recorded."""
        pairs = extract_entities(text)
        for name, etype in pairs:
            self.record(name, etype, source=source, context=text)
        return len(pairs)

    # ── read ───────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[dict]:
        with self._lock:
            ent = self._entities.get((name or "").strip().lower())
            return dict(ent) if ent else None

    def search(self, query: str = "", entity_type: str = "", limit: int = 50) -> list[dict]:
        """Search by substring over name/type; most-mentioned first."""
        q = (query or "").strip().lower()
        with self._lock:
            items = list(self._entities.values())
        out = []
        for e in items:
            if entity_type and e["type"] != entity_type:
                continue
            if q and q not in e["name"].lower() and q not in e["type"].lower():
                continue
            out.append(e)
        out.sort(key=lambda e: (e["mentions"], e["last_seen"]), reverse=True)
        return [dict(e) for e in out[:max(1, limit)]]

    def stats(self) -> dict:
        with self._lock:
            items = list(self._entities.values())
        by_type: dict[str, int] = {}
        for e in items:
            by_type[e["type"]] = by_type.get(e["type"], 0) + 1
        return {
            "entities": len(items),
            "mentions_total": sum(e["mentions"] for e in items),
            "by_type": by_type,
        }

    def delete(self, name: str) -> bool:
        with self._lock:
            key = (name or "").strip().lower()
            if key in self._entities:
                del self._entities[key]
                self._save()
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._entities.clear()
            self._save()
