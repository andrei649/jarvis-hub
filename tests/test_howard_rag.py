"""Tests for H5.1 Howard RAG dynamic search, prompt injection, and continuous watcher.

Covers:
  1. IngestionPipeline loading from mock SQLite database
  2. IngestionPipeline semantic search with RAG and lazy-loading
  3. IngestionWatcher directory scanning, state saving, and change-detection
  4. Agent process injecting custom RAG few-shots for Howard
"""

import json
import sqlite3
import sys
from pathlib import Path
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.ingestion.pipeline import IngestionPipeline
from agents.core.ingestion.watcher import IngestionWatcher
from agents.core.ingestion.normalizer import NormalizedMessage
from agents.core.agent import Agent
from agents.core.llm.hybrid_router import HybridRouter
from agents.core.llm.base import LLMBackend


# ── Ingestion & SQLite Loading Tests ──────────────────────────────────────────

def test_pipeline_load_from_sqlite(tmp_path):
    db_path = tmp_path / "archive.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE messages (
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
    conn.execute(
        "INSERT INTO messages (source, conversation_id, sender, is_me, text, timestamp, metadata) "
        "VALUES ('wa', 'c1', 'Andrei', 1, 'salut, ce mai faci?', 1700000000.0, '{}')"
    )
    conn.execute(
        "INSERT INTO messages (source, conversation_id, sender, is_me, text, timestamp, metadata) "
        "VALUES ('wa', 'c1', 'Sorina', 0, 'bine, tu?', 1700000005.0, '{}')"
    )
    conn.commit()
    conn.close()

    pipeline = IngestionPipeline(data_root=str(tmp_path / "data"), output_root=str(tmp_path))
    pipeline.load_from_sqlite(db_path)

    assert len(pipeline.messages) == 2
    assert len(pipeline.my_messages) == 1
    assert pipeline.my_messages[0].text == "salut, ce mai faci?"
    assert pipeline.my_messages[0].is_me is True


def test_pipeline_search_similar_lazy_loads(tmp_path):
    db_path = tmp_path / "archive.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE messages (
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
    conn.execute(
        "INSERT INTO messages (source, conversation_id, sender, is_me, text, timestamp, metadata) "
        "VALUES ('wa', 'c1', 'Andrei', 1, 'perfect', 1700000000.0, '{}')"
    )
    conn.commit()
    conn.close()

    # IngestionPipeline has no messages populated, but search_similar should lazy-load from output_root/archive.db
    pipeline = IngestionPipeline(data_root=str(tmp_path / "data"), output_root=str(tmp_path))
    pipeline.embedder.backend = "hash"  # Use deterministic hash embedding offline

    results = pipeline.search_similar("perfect", k=1, only_me=True)
    assert len(results) == 1
    assert results[0].text == "perfect"


# ── Ingestion Watcher Tests ───────────────────────────────────────────────────

def test_ingestion_watcher_creates_folders_and_detects_changes(tmp_path):
    data_root = tmp_path / "data"
    state_path = tmp_path / "watcher_state.json"
    pipeline = IngestionPipeline(data_root=str(data_root), output_root=str(tmp_path))
    pipeline.embedder.backend = "hash"

    watcher = IngestionWatcher(data_root=str(data_root), state_path=str(state_path), pipeline=pipeline)

    # First check: empty folder, should create subfolders
    assert watcher.check_and_run() is False
    assert (data_root / "whatsapp").exists()
    assert (data_root / "facebook" / "messages" / "inbox").exists()

    # Add a Whatsapp file
    wa_file = data_root / "whatsapp" / "chat.txt"
    wa_file.write_text("[01.06.2026, 09:00:00] Andrei: perfect\n", encoding="utf-8")

    # Second check: new file detected, should run pipeline (returns True)
    assert watcher.check_and_run() is True

    # Third check: no changes, should return False
    assert watcher.check_and_run() is False


# ── Agent Prompt RAG Injection Tests ──────────────────────────────────────────

class MockBackend(LLMBackend):
    def __init__(self):
        self.last_prompt = ""

    async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
        self.last_prompt = prompt
        return "I remember that."


def test_howard_agent_prompt_injection(tmp_path, monkeypatch):
    db_path = tmp_path / "archive.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE messages (
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
    conn.execute(
        "INSERT INTO messages (source, conversation_id, sender, is_me, text, timestamp, metadata) "
        "VALUES ('wa', 'c1', 'Andrei', 1, 'am ales varianta simpla', 1700000000.0, '{}')"
    )
    conn.commit()
    conn.close()

    # Monkeypatch IngestionPipeline default output_root to point to tmp_path so it resolves archive.db
    from agents.core.ingestion.pipeline import IngestionPipeline as IP
    original_init = IP.__init__
    def mock_init(self, *args, **kwargs):
        original_init(self, data_root=str(tmp_path / "data"), output_root=str(tmp_path))
        self.embedder.backend = "hash"
    monkeypatch.setattr(IP, "__init__", mock_init)

    # Setup agent
    router = HybridRouter()
    backend = MockBackend()
    router._local_available = True
    router._backend = backend

    config = {
        "name": "Howard",
        "model": "howard-lora-qwen-14b",
        "heartbeat": "no",
        "channel": "telegram",
        "plugins": [],
        "tier": "foundation"
    }

    agent = Agent("howard", config, llm_router=router)

    # Process prompt
    import asyncio
    asyncio.run(agent.process("ce ai ales?", {}))

    # Verify that mock message was searched and injected into prompt
    assert "am ales varianta simpla" in backend.last_prompt   # still injected (readable; datamark off for style)
    # CDX-7: the archive few-shots are now fenced as untrusted DATA before the prompt.
    assert "RETRIEVED MEMORY" in backend.last_prompt and "DATA, NOT INSTRUCTIONS" in backend.last_prompt
