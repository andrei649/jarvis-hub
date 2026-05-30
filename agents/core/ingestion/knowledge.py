"""
knowledge.py — Knowledge extraction for Howard.

Extracts entities, relationships, topics, and decision patterns
from normalized chat messages. Feeds into the knowledge graph (Neo4j when available)
and builds a lightweight relationship index in SQLite.
"""

import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from .normalizer import NormalizedMessage

logger = logging.getLogger("jarvis.ingestion.knowledge")

SHARED_INTEREST_KEYWORDS = {
    "bmw", "mașină", "car", "n54", "e93", "335i", "cosmina",
    "casă", "house", "construcție", "build", "renovare",
    "digitaholic", "marketing", "crm", "mar-tech", "martech",
    "fitness", "snowboard", "motocross", "mx",
    "tech", "ai", "llm", "agent", "python", "coding",
    "music", "muzică", "retro", "ipod", "psp", "polaroid", "casio",
}

DECISION_TRIGGERS = [
    "am ales", "am decis", "am luat", "am cumpărat", "am vândut",
    "am schimbat", "am făcut", "am început", "am renunțat",
    "i chose", "i decided", "i bought", "i sold", "i switched",
    "i started", "i quit", "i picked",
    "cred că", "parcă", "mai bine", "better to",
    "not a fan", "nu-mi place", "prefer",
]

RELATIONSHIP_PATTERNS = [
    (re.compile(r"\b(my wife|soția mea|logodnica mea|iubita mea|partenera mea)\b", re.IGNORECASE), "partner"),
    (re.compile(r"\b(my son|fiul meu|băiatul meu)\b", re.IGNORECASE), "son"),
    (re.compile(r"\b(bro|frate|my guy|boss|băi|măi)\b", re.IGNORECASE), "close_friend"),
    (re.compile(r"\b(colega|coleg|colleague|teammate)\b", re.IGNORECASE), "colleague"),
    (re.compile(r"\b(client|clientă)\b", re.IGNORECASE), "client"),
    (re.compile(r"\b(șef|boss|manager|lead)\b", re.IGNORECASE), "superior"),
    (re.compile(r"\b(mamă|mama|mother)\b", re.IGNORECASE), "mother"),
    (re.compile(r"\b(tată|tata|father)\b", re.IGNORECASE), "father"),
    (re.compile(r"\b(soră|sora|sister)\b", re.IGNORECASE), "sister"),
    (re.compile(r"\b(frate|brother)\b", re.IGNORECASE), "brother"),
]


@dataclass
class ExtractedEntity:
    name: str
    type: str  # "person", "place", "topic", "product", "brand"
    mentions: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    context: list[str] = field(default_factory=list)
    related_to: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DecisionPattern:
    trigger_text: str
    context: str
    timestamp: float
    outcome: str = ""
    topic: str = ""
    conversation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RelationshipEntry:
    person: str
    relation_type: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    last_updated: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class KnowledgeExtractor:
    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir
        self.entities: dict[str, ExtractedEntity] = {}
        self.decisions: list[DecisionPattern] = []
        self.relationships: dict[str, RelationshipEntry] = {}
        self.topic_clusters: dict[str, list[NormalizedMessage]] = defaultdict(list)

    def extract(self, messages: list[NormalizedMessage]):
        for msg in messages:
            if not msg.text.strip():
                continue
            self._extract_entities(msg)
            self._extract_decisions(msg)
            self._extract_topics(msg)

        self._resolve_relationships()

        logger.info(
            f"Knowledge extraction: {len(self.entities)} entities, "
            f"{len(self.decisions)} decisions, "
            f"{len(self.relationships)} relationships"
        )
        return self

    def _extract_entities(self, msg: NormalizedMessage):
        text_lower = msg.text.lower()

        shared_interests = [kw for kw in SHARED_INTEREST_KEYWORDS if kw in text_lower]
        for interest in shared_interests:
            if interest not in self.entities:
                self.entities[interest] = ExtractedEntity(
                    name=interest, type="topic",
                    first_seen=msg.timestamp
                )
            self.entities[interest].mentions += 1
            self.entities[interest].last_seen = msg.timestamp
            if len(self.entities[interest].context) < 5:
                self.entities[interest].context.append(msg.text[:200])

        for pattern, rel_type in RELATIONSHIP_PATTERNS:
            if pattern.search(text_lower):
                if msg.sender not in self.relationships:
                    self.relationships[msg.sender] = RelationshipEntry(
                        person=msg.sender,
                        relation_type=rel_type,
                        confidence=0.5,
                        last_updated=msg.timestamp,
                    )
                else:
                    self.relationships[msg.sender].confidence = min(
                        1.0, self.relationships[msg.sender].confidence + 0.1
                    )
                    self.relationships[msg.sender].last_updated = msg.timestamp
                    # Upgrade relation type if more specific found
                    if rel_type != self.relationships[msg.sender].relation_type:
                        self.relationships[msg.sender].relation_type = rel_type

                if len(self.relationships[msg.sender].evidence) < 10:
                    self.relationships[msg.sender].evidence.append(msg.text[:200])

    def _extract_decisions(self, msg: NormalizedMessage):
        text_lower = msg.text.lower()
        for trigger in DECISION_TRIGGERS:
            if trigger in text_lower:
                self.decisions.append(DecisionPattern(
                    trigger_text=trigger,
                    context=msg.text[:300],
                    timestamp=msg.timestamp,
                    conversation=msg.conversation_id,
                ))
                break

    def _extract_topics(self, msg: NormalizedMessage):
        text_lower = msg.text.lower()
        for keyword in SHARED_INTEREST_KEYWORDS:
            if keyword in text_lower:
                self.topic_clusters[keyword].append(msg)

    def _resolve_relationships(self):
        for person, entry in self.relationships.items():
            freq = sum(1 for m in self.topic_clusters.get("bmw", []) if m.sender == person)
            freq += sum(1 for m in self.topic_clusters.get("cosmina", []) if m.sender == person)
            if freq > 5:
                entry.confidence = min(1.0, entry.confidence + 0.2)

    def to_json(self) -> dict:
        return {
            "entities": {k: v.to_dict() for k, v in self.entities.items()},
            "decisions": [d.to_dict() for d in self.decisions[-500:]],
            "relationships": {k: v.to_dict() for k, v in self.relationships.items()},
            "topic_coverage": {k: len(v) for k, v in self.topic_clusters.items()},
        }

    def save(self, path: Optional[Path] = None):
        save_path = path or (self.output_dir / "knowledge.json" if self.output_dir else None)
        if not save_path:
            return
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(
            json.dumps(self.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"Knowledge saved to {save_path}")
