"""
checkpoint.py — Agent execution checkpointing with SQLite.
Saves agent execution state for crash recovery and resume.
Also tracks agent stats for promotion/demotion and structured sessions.
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis.checkpoint")

CHECKPOINT_DIR = Path("memory_logs/checkpoints")


class CheckpointManager:
    def __init__(self, db_path: str = None):
        if db_path is None:
            CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
            db_path = str(CHECKPOINT_DIR / "checkpoints.db")
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        # Guard concurrent access when called via asyncio.to_thread (H7.2)
        self._lock = threading.Lock()

    def initialize(self):
        # check_same_thread=False: save/load run via asyncio.to_thread (H7.2),
        # so the connection is touched from pool worker threads; a threading.Lock
        # serializes access. WAL + synchronous=NORMAL keeps the per-turn commit
        # cheap (~36x faster in-bench) without losing durability.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                state TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(agent_id, session_id)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_stats (
                agent_id TEXT PRIMARY KEY,
                total_calls INTEGER DEFAULT 0,
                success_calls INTEGER DEFAULT 0,
                failure_calls INTEGER DEFAULT 0,
                avg_latency REAL DEFAULT 0.0,
                last_status TEXT DEFAULT 'unknown',
                last_error TEXT,
                demoted INTEGER DEFAULT 0,
                promoted_from TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                agent_id TEXT,
                started_at TEXT,
                ended_at TEXT,
                turn_count INTEGER DEFAULT 0,
                summary TEXT,
                metadata TEXT DEFAULT '{}'
            )
        """)
        # list_sessions() orders by started_at and the table grows one row per
        # session; index started_at so the ordered scan stays cheap as history
        # accumulates.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at)"
        )
        self._conn.commit()
        logger.info(f"Checkpoint DB initialized: {self.db_path}")

    def save(self, orchestrator) -> bool:
        if not self._conn:
            return False
        try:
            state = {
                "session_id": orchestrator.session_id,
                "agent_ids": list(orchestrator.agents.keys()),
                "channel_ids": list(orchestrator.channels.keys()),
                "llm_backend": orchestrator.llm_router.name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO checkpoints (agent_id, session_id, state, data, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("orchestrator", orchestrator.session_id, "running",
                     json.dumps(state, ensure_ascii=False), state["timestamp"]),
                )
                self._conn.commit()
            return True
        except Exception as e:
            logger.warning(f"Checkpoint save failed: {e}")
            return False

    def load(self, agent_id: str, session_id: str) -> Optional[dict]:
        if not self._conn:
            return None
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT state, data FROM checkpoints WHERE agent_id=? AND session_id=?",
                    (agent_id, session_id),
                )
                row = cursor.fetchone()
            if row:
                return {"state": row[0], **json.loads(row[1])}
        except Exception as e:
            logger.warning(f"Checkpoint load failed: {e}")
        return None

    def restore(self, orchestrator) -> bool:
        if not self._conn:
            return False
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT data FROM checkpoints WHERE agent_id='orchestrator' ORDER BY rowid DESC LIMIT 1"
                )
                row = cursor.fetchone()
            if row:
                state = json.loads(row[0])
                orchestrator.session_id = state.get("session_id", orchestrator.session_id)
                logger.info(f"Restored from checkpoint: session={orchestrator.session_id}")
                return True
        except Exception as e:
            logger.warning(f"Checkpoint restore failed: {e}")
        return False

    def save_agent_execution(self, agent_id: str, session_id: str, prompt: str):
        if not self._conn:
            return
        try:
            data = json.dumps({"prompt": prompt, "timestamp": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO checkpoints (agent_id, session_id, state, data, created_at) VALUES (?, ?, ?, ?, ?)",
                    (agent_id, session_id, "executing", data, datetime.now(timezone.utc).isoformat()),
                )
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Agent checkpoint save failed: {e}")

    def clear_agent_checkpoint(self, agent_id: str, session_id: str):
        if not self._conn:
            return
        try:
            with self._lock:
                self._conn.execute(
                    "DELETE FROM checkpoints WHERE agent_id=? AND session_id=?",
                    (agent_id, session_id),
                )
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Checkpoint clear failed: {e}")

    def record_call(self, agent_id: str, success: bool, latency: float = 0.0, error: str = None):
        if not self._conn:
            return
        try:
            now = datetime.now(timezone.utc).isoformat()
            succ = 1 if success else 0
            fail = 0 if success else 1
            status = "success" if success else "failure"
            with self._lock:
                self._conn.execute("""
                    INSERT INTO agent_stats (agent_id, total_calls, success_calls, failure_calls,
                        avg_latency, last_status, last_error, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        total_calls = total_calls + 1,
                        success_calls = success_calls + ?,
                        failure_calls = failure_calls + ?,
                        avg_latency = (avg_latency * (total_calls - 1) + ?) / MAX(total_calls, 1),
                        last_status = ?,
                        last_error = ?,
                        updated_at = ?
                """, (agent_id, 1, succ, fail, latency, status, error, now, now,
                      succ, fail, latency, status, error, now))
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Failed to record call for {agent_id}: {e}")

    def get_agent_stats(self, agent_id: str) -> dict:
        if not self._conn:
            return {}
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT * FROM agent_stats WHERE agent_id=?", (agent_id,)
                )
                columns = [d[0] for d in cursor.description]
                row = cursor.fetchone()
            if row:
                return dict(zip(columns, row))
        except Exception as e:
            logger.warning(f"Failed to get stats for {agent_id}: {e}")
        return {}

    def get_all_agent_stats(self) -> dict[str, dict]:
        if not self._conn:
            return {}
        try:
            with self._lock:
                cursor = self._conn.execute("SELECT * FROM agent_stats")
                columns = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
            return {row[0]: dict(zip(columns, row)) for row in rows}
        except Exception as e:
            logger.warning(f"Failed to get all agent stats: {e}")
        return {}

    def create_session_record(self, session_id: str, agent_id: str = None, metadata: dict = None):
        if not self._conn:
            return
        try:
            with self._lock:
                self._conn.execute("""
                    INSERT OR IGNORE INTO sessions (id, agent_id, started_at, turn_count, metadata)
                    VALUES (?, ?, ?, 0, ?)
                """, (session_id, agent_id, datetime.now(timezone.utc).isoformat(),
                      json.dumps(metadata or {}, ensure_ascii=False)))
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Failed to create session record: {e}")

    def update_session(self, session_id: str, turn_count: int = None, summary: str = None):
        if not self._conn:
            return
        try:
            updates = ["ended_at=?"]
            params = [datetime.now(timezone.utc).isoformat()]
            if turn_count is not None:
                updates.append("turn_count=?")
                params.append(turn_count)
            if summary is not None:
                updates.append("summary=?")
                params.append(summary)
            params.append(session_id)
            with self._lock:
                self._conn.execute(f"UPDATE sessions SET {', '.join(updates)} WHERE id=?", params)
                self._conn.commit()
        except Exception as e:
            logger.warning(f"Failed to update session: {e}")

    def get_sessions(self, limit: int = 20) -> list[dict]:
        if not self._conn:
            return []
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
                )
                columns = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.warning(f"Failed to get sessions: {e}")
        return []

    def info(self) -> dict:
        if not self._conn:
            return {"status": "unavailable"}
        try:
            with self._lock:
                cp_count = self._conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
                agent_count = self._conn.execute("SELECT COUNT(*) FROM agent_stats").fetchone()[0]
                session_count = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            return {
                "status": "active",
                "checkpoints": cp_count,
                "agents_tracked": agent_count,
                "sessions_recorded": session_count,
            }
        except Exception:
            return {"status": "error"}

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
