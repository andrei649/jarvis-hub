import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from pathlib import Path

from agents.core.paths import data_root

from .persistence import list_sessions, load_memory, save_memory

logger = logging.getLogger("jarvis.memory.conversation")

# Resolved LAZILY, not at import. `MEMORY_DIR = data_root()` bound the repo's
# memory_logs/ before a caller could redirect JARVIS_HOME, so scripts/install_smoke.py
# — which DOES set JARVIS_HOME to a temp dir — still wrote its fixture session into the
# live store, and every later boot restored "install_smoke" as the owner's session
# (2026-07-27 QA finding). Same class, and same fix, as the autonomy.db leak in #723.
# `MEMORY_DIR = None` means "ask data_root() each time". It stays a module attribute
# because tests pin it directly (monkeypatch.setattr(persistence, "MEMORY_DIR", tmp)),
# and that seam is worth keeping — it is how the traversal tests get a sandbox.
MEMORY_DIR: Path | None = None


def memory_dir() -> Path:
    """Where session state lives, resolved NOW — honors an explicit MEMORY_DIR override
    first, then the current JARVIS_HOME. Public because callers legitimately need the
    path (tests, the KG writing beside a snapshot); read it through this, never through
    a value captured at import."""
    return MEMORY_DIR if MEMORY_DIR is not None else data_root()


_memory_dir = memory_dir   # internal alias, kept so use sites read tersely


class Turn:
    __slots__ = ("role", "content", "agent_id", "timestamp", "token_count")

    def __init__(self, role: str, content: str, agent_id: str = None, token_count: int = 0):
        self.role = role
        self.content = content
        self.agent_id = agent_id
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.token_count = token_count

    def to_dict(self):
        return {
            "role": self.role,
            "content": self.content,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "token_count": self.token_count,
        }


class ConversationMemory:
    def __init__(self, max_turns: int = 100, persist: bool = True):
        self.sessions: dict[str, list[Turn]] = {}
        self.max_turns = max_turns
        self.persist = persist
        self.current_session_id: Optional[str] = None
        self._dirty = set()
        self._lock = asyncio.Lock()

        if persist:
            self._load_latest_session()

    def _load_latest_session(self):
        sessions = list_sessions()
        if sessions:
            sid = sessions[0]
            turns_data = load_memory(sid)
            if turns_data:
                self.sessions[sid] = []
                for t in turns_data:
                    turn = Turn(t["role"], t["content"], t.get("agent_id"), t.get("token_count", 0))
                    self.sessions[sid].append(turn)
                self.current_session_id = sid
                logger.info(f"Restored session {sid} ({len(turns_data)} turns)")

    async def new_session(self, session_id: str = None) -> str:
        async with self._lock:
            sid = session_id or datetime.now(timezone.utc).strftime("session_%Y%m%d_%H%M%S")
            if sid not in self.sessions:
                self.sessions[sid] = []
                logger.info(f"New session: {sid}")
            self.current_session_id = sid
            return sid

    async def resume_session(self, session_id: str) -> bool:
        """Make a specific past session current, loading it from disk if needed.

        Unlike `_load_latest_session` (init-only, newest), this resumes any
        chosen session by id. Returns False if it has no in-memory or on-disk turns.
        """
        async with self._lock:
            if session_id not in self.sessions:
                turns_data = load_memory(session_id)
                if not turns_data:
                    return False
                self.sessions[session_id] = [
                    Turn(t["role"], t["content"], t.get("agent_id"), t.get("token_count", 0))
                    for t in turns_data
                ]
                logger.info(f"Resumed session {session_id} ({len(turns_data)} turns)")
            self.current_session_id = session_id
            return True

    async def add_turn(self, session_id: str, role: str, content: str, agent_id: str = None):
        async with self._lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = []
            turn = Turn(role, content, agent_id, token_count=len(content) // 4)
            self.sessions[session_id].append(turn)
            if len(self.sessions[session_id]) > self.max_turns:
                self.sessions[session_id].pop(0)
            self._dirty.add(session_id)
            if self.persist:
                # AUD-7 / F9: both the append-log and the full-snapshot write are
                # blocking disk I/O. On the SSE hot path that would stall the event
                # loop (the snapshot rewrites the whole session every turn). Build the
                # JSON-able data here (cheap, under the lock so it can't tear) and do
                # the actual writes in a worker thread so streaming is never blocked.
                turn_dict = turn.to_dict()
                turns_data = [t.to_dict() for t in self.sessions[session_id]]
                await asyncio.to_thread(self._persist_turn, session_id, turn_dict, turns_data)

    def _persist_turn(self, session_id: str, turn_dict: dict, turns_data: list[dict]):
        """Blocking persistence, run off the event loop (see add_turn). Per-turn
        durability is unchanged: the snapshot is still written every turn — only the
        thread it runs on differs."""
        self._append_log_dict(session_id, turn_dict)
        try:
            save_memory(session_id, turns_data)
        except Exception as e:
            logger.warning(f"Snapshot save failed: {e}")

    def _save_snapshot(self, session_id: str):
        """Full JSON save of the session (kept for direct/synchronous callers)."""
        try:
            turns_data = [t.to_dict() for t in self.sessions.get(session_id, [])]
            save_memory(session_id, turns_data)
        except Exception as e:
            logger.warning(f"Snapshot save failed: {e}")

    async def get_history(self, session_id: str, last_n: int = None) -> list[dict]:
        async with self._lock:
            turns = self.sessions.get(session_id, [])
            if last_n is not None:
                turns = turns[-last_n:] if last_n > 0 else []
            return [t.to_dict() for t in turns]

    async def get_context(self, session_id: str, last_n: int = 10) -> str:
        turns = await self.get_history(session_id, last_n)
        if not turns:
            return ""
        lines = []
        for t in turns:
            speaker = t["agent_id"] or t["role"]
            lines.append(f"[{speaker}]: {t['content']}")
        return "\n".join(lines)

    async def clear(self, session_id: str = None):
        async with self._lock:
            if session_id:
                self.sessions.pop(session_id, None)
            else:
                self.sessions.clear()

    def _append_log(self, session_id: str, turn: Turn):
        self._append_log_dict(session_id, turn.to_dict())

    def _append_log_dict(self, session_id: str, turn_dict: dict):
        try:
            _memory_dir().mkdir(parents=True, exist_ok=True)
            log_path = _memory_dir() / f"{session_id}.jsonl"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(turn_dict, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to persist turn: {e}")
