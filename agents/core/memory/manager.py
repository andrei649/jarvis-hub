"""
memory/manager.py — Memory manager integrating conversation memory,
vector store, agent contexts, and structured session persistence.
"""

import asyncio
import logging
from typing import Optional

from .conversation import ConversationMemory
from .store import VectorStore

logger = logging.getLogger("jarvis.memory")


class MemoryManager:
    def __init__(self):
        self.conversation = ConversationMemory(max_turns=100, persist=True)
        self.vectors = VectorStore(dimension=768)
        self.agent_contexts: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    def set_checkpoint_manager(self, mgr):
        self._checkpoint_mgr = mgr

    async def new_session(self, session_id: str = None) -> str:
        async with self._lock:
            sid = await self.conversation.new_session(session_id)
            if hasattr(self, '_checkpoint_mgr') and self._checkpoint_mgr:
                self._checkpoint_mgr.create_session_record(sid)
            return sid

    async def add_turn(self, session_id: str, role: str, content: str, agent_id: str = None):
        async with self._lock:
            await self.conversation.add_turn(session_id, role, content, agent_id)

            if hasattr(self, '_checkpoint_mgr') and self._checkpoint_mgr:
                turn_count = len(self.conversation.sessions.get(session_id, []))
                self._checkpoint_mgr.update_session(session_id, turn_count=turn_count)

    async def get_context(self, session_id: str, last_n: int = 10) -> str:
        async with self._lock:
            return await self.conversation.get_context(session_id, last_n)

    async def get_history(self, session_id: str, last_n: int = None) -> list[dict]:
        async with self._lock:
            return await self.conversation.get_history(session_id, last_n)

    async def update_agent_context(self, agent_id: str, key: str, value):
        async with self._lock:
            if agent_id not in self.agent_contexts:
                self.agent_contexts[agent_id] = {}
            self.agent_contexts[agent_id][key] = value

    async def get_agent_context(self, agent_id: str) -> dict:
        async with self._lock:
            return self.agent_contexts.get(agent_id, {})

    async def store_embedding(self, record_id: str, vector: list[float], metadata: dict = None):
        async with self._lock:
            self.vectors.add(record_id, vector, metadata)

    async def search_similar(self, query: list[float], k: int = 5) -> list[dict]:
        async with self._lock:
            return self.vectors.search(query, k)

    async def clear(self, session_id: str = None):
        async with self._lock:
            if session_id:
                await self.conversation.clear(session_id)
            else:
                await self.conversation.clear()

    async def get_session_stats(self) -> dict:
        async with self._lock:
            return {
                "sessions": len(self.conversation.sessions),
                "current_session": self.conversation.current_session_id,
                "total_turns": sum(len(t) for t in self.conversation.sessions.values()),
                "vectors": len(self.vectors),
                "agent_contexts": list(self.agent_contexts.keys()),
            }
