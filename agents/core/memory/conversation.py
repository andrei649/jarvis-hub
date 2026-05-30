import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .persistence import save_memory, load_memory, list_sessions

logger = logging.getLogger("jarvis.memory.conversation")

MEMORY_DIR = Path("memory_logs")


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
                self._append_log(session_id, turn)
                self._save_snapshot(session_id)

    def _save_snapshot(self, session_id: str):
        """Full JSON save of the session."""
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
        try:
            MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            log_path = MEMORY_DIR / f"{session_id}.jsonl"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(turn.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to persist turn: {e}")
