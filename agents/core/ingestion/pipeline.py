"""
pipeline.py — Orchestrates the full data ingestion for Howard.

Phases:
  1. Parse Facebook Messenger exports (JSON)
  2. Parse WhatsApp exports (TXT)
  3. Normalize into common format
  4. Run stylometric analysis (VoiceProfile)
  5. Run knowledge extraction (entities, relationships, decisions)
  6. Generate embeddings and store in VectorStore
  7. Save everything to disk (SQLite + JSON + VectorStore)
"""

import json
import logging
import math
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .embedder import Embedder, clear_process_cache
from .knowledge import KnowledgeExtractor
from .lifecycle import default_archive_root, default_import_root
from .normalizer import NormalizedMessage
from .parser_facebook import FacebookParser
from .parser_whatsapp import WhatsAppParser
from .provenance import ProvenanceLedger, content_fingerprint
from .stylometry import StylometryAnalyzer

logger = logging.getLogger("jarvis.ingestion.pipeline")

EMBEDDING_DIM = 768

# Process-wide read pipeline for Howard's per-turn RAG lookup. Constructing a
# fresh IngestionPipeline per turn forced a full archive.db reload + re-embed on
# the event loop every time; sharing one instance loads the archive once.
_SHARED_PIPELINE: Optional["IngestionPipeline"] = None


def get_shared_pipeline() -> "IngestionPipeline":
    """Return the process-wide read pipeline, creating it on first use."""
    global _SHARED_PIPELINE
    if _SHARED_PIPELINE is None:
        _SHARED_PIPELINE = IngestionPipeline()
    return _SHARED_PIPELINE


def reset_shared_pipeline() -> None:
    """Drop the shared pipeline so the next lookup reloads a rewritten archive."""
    global _SHARED_PIPELINE
    _SHARED_PIPELINE = None


def clear_live_ingestion(pipeline: Optional["IngestionPipeline"] = None) -> dict:
    """Forget Howard archive content retained by live process objects.

    ``pipeline`` is normally the watcher's long-lived writer; the process-wide
    RAG reader is cleared automatically. The operation is idempotent and does
    not write anything back to disk.
    """
    global _SHARED_PIPELINE
    targets = []
    for candidate in (_SHARED_PIPELINE, pipeline):
        if candidate is not None and all(candidate is not item for item in targets):
            targets.append(candidate)

    messages = 0
    for item in targets:
        messages += len(item.messages)
        item.messages.clear()
        item.my_messages.clear()
        item.stylometry.profile = type(item.stylometry.profile)()
        item.knowledge.entities.clear()
        item.knowledge.decisions.clear()
        item.knowledge.relationships.clear()
        item.knowledge.topic_clusters.clear()
    _SHARED_PIPELINE = None
    return {
        "pipelines": len(targets),
        "messages": messages,
        "embedding_entries": clear_process_cache(),
    }


class IngestionPipeline:
    def __init__(
        self,
        data_root: str | Path | None = None,
        output_root: str | Path | None = None,
        my_name: str = "Andrei Tarcomnicu",
        my_short_name: str = "Andrei",
        *,
        ledger: Optional[ProvenanceLedger] = None,
        clock: Optional[Callable[[], float]] = None,
    ):
        self.data_root = Path(data_root) if data_root is not None else default_import_root()
        self.output_root = Path(output_root) if output_root is not None else default_archive_root()
        self.output_root.mkdir(parents=True, exist_ok=True)

        self.fb_parser = FacebookParser(my_name=my_name)
        self.wa_parser = WhatsAppParser(my_name=my_short_name)
        self.stylometry = StylometryAnalyzer(profile_path=self.output_root / "voice_profile.json")
        self.knowledge = KnowledgeExtractor(output_dir=self.output_root)
        self.embedder = Embedder(cache_dir=self.output_root / "embedding_cache")

        self.messages: list[NormalizedMessage] = []
        self.my_messages: list[NormalizedMessage] = []

        # 0.37 wiring: when a provenance ledger is attached, each parsed message
        # gets an auditable origin record (opt-in; None → behaviour unchanged).
        self._ledger = ledger
        self._clock = clock or time.time
        # message content-fingerprint → its parse-phase provenance record id, so a
        # derived artifact can name the message it came from (see _record_derived_provenance).
        self._parse_record_ids: dict[str, str] = {}

    def _record_provenance(self, messages, *, source: str, phase: str,
                           run_id: str, now: float) -> int:
        """Best-effort: record one provenance entry per message into the attached
        ledger. A no-op when no ledger is wired; a ledger hiccup never breaks
        ingestion. Returns how many records were written.

        Also remembers each message's record id in ``self._parse_record_ids``
        (keyed by the message's content fingerprint) so a *derived* artifact —
        an embedding, an extracted entity — can name the message it came from
        via ``parent_id``. That link is what makes the ledger auditable rather
        than decorative: `lineage()` can then walk embedding → message → file.
        """
        if self._ledger is None:
            return 0
        recorded = 0
        for m in messages:
            try:
                text = getattr(m, "text", "") or ""
                rec = self._ledger.record(
                    source=getattr(m, "source", "") or source,
                    origin=str(getattr(m, "conversation_id", "") or ""),
                    phase=phase,
                    content=text,
                    run_id=run_id,
                    now=now,
                    meta={"sender": getattr(m, "sender", ""),
                          "is_me": bool(getattr(m, "is_me", False))},
                )
                if phase == "parse" and isinstance(rec, dict) and rec.get("id"):
                    self._parse_record_ids.setdefault(content_fingerprint(text), rec["id"])
                recorded += 1
            except Exception:
                logger.debug("provenance record failed", exc_info=True)
        return recorded

    def _record_derived_provenance(self, artifacts, *, source: str, phase: str,
                                   run_id: str, now: float,
                                   parent_id: str | None = None) -> int:
        """Record provenance for artifacts *derived* from messages (0.37).

        ``artifacts`` is an iterable of ``(content, meta)`` pairs — an extracted
        entity name, an embedded message's text, etc. Same best-effort contract
        as ``_record_provenance``: a no-op without a ledger, and a ledger hiccup
        is swallowed so ingestion never fails over an audit write.

        Blank content is skipped rather than stored as an empty record: a
        fingerprint of "" would collide across every empty artifact and prove
        nothing, which is worse than having no record.
        """
        if self._ledger is None:
            return 0
        recorded = 0
        for content, meta in artifacts:
            text = str(content or "").strip()
            if not text:
                continue
            try:
                self._ledger.record(
                    source=source, origin=str((meta or {}).get("origin", "")),
                    phase=phase, content=text, run_id=run_id, now=now,
                    parent_id=parent_id or self._parse_record_ids.get(
                        content_fingerprint(text)),
                    meta=dict(meta or {}),
                )
                recorded += 1
            except Exception:
                logger.debug("derived provenance record failed", exc_info=True)
        return recorded

    def run(self, fb_dir: Optional[str] = None, wa_dir: Optional[str] = None) -> dict:
        logger.info("=" * 50)
        logger.info("Ingestion pipeline started")
        logger.info("=" * 50)

        phases = []
        run_id = uuid.uuid4().hex[:12]
        now = self._clock()

        # Reset accumulation state so a re-run reflects exactly this run's inputs
        # rather than appending to a previously-loaded/parsed archive (which would
        # otherwise duplicate every message in memory, in SQLite, and in the JSONL).
        self.messages = []
        self.my_messages = []

        # Phase 1: Parse Facebook
        fb_path = Path(fb_dir) if fb_dir else self.data_root / "facebook" / "messages" / "inbox"
        fb_messages = list(self.fb_parser.parse_directory(fb_path))
        self.messages.extend(fb_messages)
        self._record_provenance(fb_messages, source="facebook", phase="parse", run_id=run_id, now=now)
        phases.append({"phase": "facebook", "messages": len(fb_messages)})
        logger.info(f"Phase 1 complete: {len(fb_messages)} Facebook messages")

        # Phase 2: Parse WhatsApp
        wa_path = Path(wa_dir) if wa_dir else self.data_root / "whatsapp"
        wa_messages = list(self.wa_parser.parse_directory(wa_path))
        self.messages.extend(wa_messages)
        self._record_provenance(wa_messages, source="whatsapp", phase="parse", run_id=run_id, now=now)
        phases.append({"phase": "whatsapp", "messages": len(wa_messages)})
        logger.info(f"Phase 2 complete: {len(wa_messages)} WhatsApp messages")

        # Phase 3: Filter my messages
        self.my_messages = [m for m in self.messages if m.is_me]
        logger.info(f"Phase 3: {len(self.my_messages)} messages from me out of {len(self.messages)} total")

        # Phase 4: Stylometry
        voice_profile = self.stylometry.analyze(self.messages)
        self.stylometry.save()
        if self.my_messages:
            voice_profile.avg_message_length = sum(len(m.text) for m in self.my_messages) / len(self.my_messages)
        phases.append({"phase": "stylometry", "top_words": voice_profile.top_words[:10]})

        # Phase 5: Knowledge extraction
        self.knowledge.extract(self.messages)
        self.knowledge.save()
        # 0.37: derived knowledge carries provenance too — an extracted entity or
        # decision is a claim about the owner's life, so it must be traceable to
        # the run that produced it, not just appear in memory unattributed.
        self._record_derived_provenance(
            [(name, {"kind": "entity"}) for name in self.knowledge.entities]
            + [(str(getattr(d, "text", "") or getattr(d, "pattern", "") or ""),
                {"kind": "decision"}) for d in self.knowledge.decisions]
            + [(name, {"kind": "relationship"}) for name in self.knowledge.relationships],
            source="ingestion", phase="knowledge", run_id=run_id, now=now,
        )
        phases.append({
            "phase": "knowledge",
            "entities": len(self.knowledge.entities),
            "decisions": len(self.knowledge.decisions),
            "relationships": len(self.knowledge.relationships),
        })

        # Phase 6: Generate embeddings
        logger.info("Phase 6: Generating embeddings...")
        self.embedder.embed_many(self.messages)
        # Each embedding links back to its source message via parent_id (resolved
        # from the parse-phase fingerprint map), so `lineage()` can walk
        # embedding → message → file — the chain provenance.py documents.
        self._record_derived_provenance(
            [((m.text or ""), {"kind": "embedding", "origin": m.conversation_id or ""})
             for m in self.messages],
            source="ingestion", phase="embed", run_id=run_id, now=now,
        )
        phases.append({
            "phase": "embeddings",
            "total": len(self.messages),
            "cache": self.embedder.cache_stats,
        })

        # Phase 7: Save to SQLite
        db_path = self.output_root / "archive.db"
        self._save_sqlite(db_path)
        phases.append({"phase": "sqlite", "path": str(db_path)})

        # Phase 8: Save raw messages JSON
        json_path = self.output_root / "messages.jsonl"
        self._save_jsonl(json_path)
        phases.append({"phase": "jsonl", "path": str(json_path)})

        summary = {
            "run_id": run_id,
            "total_messages": len(self.messages),
            "my_messages": len(self.my_messages),
            "facebook_messages": len(fb_messages),
            "whatsapp_messages": len(wa_messages),
            "phases": phases,
            "voice_profile": voice_profile.to_dict(),
            "output_dir": str(self.output_root),
        }

        summary_path = self.output_root / "ingestion_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Ingestion summary saved to {summary_path}")

        # A fresh ingestion rewrote archive.db — force the shared read pipeline to
        # reload it on the next lookup instead of serving the pre-run snapshot.
        reset_shared_pipeline()

        return summary

    def _save_sqlite(self, db_path: Path):
        # check_same_thread=False: pipeline may run from asyncio.to_thread (H7.4).
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                conversation_id TEXT,
                sender TEXT,
                is_me INTEGER,
                text TEXT,
                timestamp REAL,
                metadata TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sender ON messages(sender)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation ON messages(conversation_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_is_me ON messages(is_me)
        """)

        # Reflect exactly the current run — the table persists across runs (CREATE
        # IF NOT EXISTS), so without this a re-ingest appends a full duplicate set.
        conn.execute("DELETE FROM messages")

        conn.executemany(
            "INSERT INTO messages (source, conversation_id, sender, is_me, text, timestamp, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    m.source,
                    m.conversation_id,
                    m.sender,
                    1 if m.is_me else 0,
                    m.text,
                    m.timestamp,
                    json.dumps(m.metadata, ensure_ascii=False),
                )
                for m in self.messages
            ],
        )
        conn.commit()
        row_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn.close()
        logger.info(f"SQLite: {row_count} messages saved to {db_path}")

    def _save_jsonl(self, jsonl_path: Path):
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for m in self.messages:
                f.write(json.dumps(asdict(m), ensure_ascii=False) + "\n")
        logger.info(f"JSONL: {len(self.messages)} messages saved to {jsonl_path}")

    def load_from_sqlite(self, db_path: Path):
        """Load messages from SQLite to memory for querying."""
        if not db_path.exists():
            logger.warning(f"SQLite database {db_path} does not exist. Cannot load messages.")
            return
        try:
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.execute("SELECT source, conversation_id, sender, is_me, text, timestamp, metadata FROM messages")
            self.messages = []
            for row in cursor:
                metadata = json.loads(row[6]) if row[6] else {}
                m = NormalizedMessage(
                    source=row[0],
                    conversation_id=row[1],
                    sender=row[2],
                    is_me=row[3] == 1,
                    text=row[4],
                    timestamp=row[5],
                    metadata=metadata
                )
                # Retrieve cached embedding from disk
                if self.embedder.cache is not None:
                    m.embedding = self.embedder.cache.get(m.text)
                # If cache miss, dynamically compute embedding
                if not m.embedding:
                    m.embedding = self.embedder.embed(m.text)
                self.messages.append(m)
            self.my_messages = [m for m in self.messages if m.is_me]
            conn.close()
            logger.info(f"Loaded {len(self.messages)} messages from SQLite for search")
        except Exception as e:
            logger.error(f"Error loading messages from SQLite: {e}")

    def search_similar(self, query: str, k: int = 5, only_me: bool = False) -> list[NormalizedMessage]:
        if not self.messages:
            db_path = self.output_root / "archive.db"
            self.load_from_sqlite(db_path)

        query_vec = self.embedder.embed(query)
        # Loop-invariant: the query norm is the same for every archived message,
        # so compute it once instead of re-deriving a 768-dim sqrt per message.
        norm_q = math.sqrt(sum(v * v for v in query_vec))
        scored = []
        for m in self.messages:
            if only_me and not m.is_me:
                continue
            if not m.embedding:
                continue
            sim = sum(a * b for a, b in zip(query_vec, m.embedding))
            norm_m = math.sqrt(sum(v * v for v in m.embedding))
            if norm_q * norm_m > 0:
                sim /= (norm_q * norm_m)
            scored.append((sim, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:k]]

    def get_stats(self) -> dict:
        """Return current ingestion stats without re-running."""
        return {
            "total_messages": len(self.messages),
            "my_messages": len(self.my_messages),
            "conversations": len(set(m.conversation_id for m in self.messages)),
            "senders": len(set(m.sender for m in self.messages)),
            "source_breakdown": {
                "facebook": sum(1 for m in self.messages if m.source == "facebook"),
                "whatsapp": sum(1 for m in self.messages if m.source == "whatsapp"),
            },
        }
