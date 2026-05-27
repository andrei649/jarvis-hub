"""
memory/manager.py — Memory manager integrating conversation memory,
vector store, agent contexts, and structured session persistence.
"""

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

    def set_checkpoint_manager(self, mgr):
        self._checkpoint_mgr = mgr

    def new_session(self, session_id: str = None) -> str:
        sid = self.conversation.new_session(session_id)
        if hasattr(self, '_checkpoint_mgr') and self._checkpoint_mgr:
            self._checkpoint_mgr.create_session_record(sid)
        return sid

    def add_turn(self, session_id: str, role: str, content: str, agent_id: str = None):
        self.conversation.add_turn(session_id, role, content, agent_id)

        if hasattr(self, '_checkpoint_mgr') and self._checkpoint_mgr:
            turn_count = len(self.conversation.sessions.get(session_id, []))
            self._checkpoint_mgr.update_session(session_id, turn_count=turn_count)

    def get_context(self, session_id: str, last_n: int = 10) -> str:
        return self.conversation.get_context(session_id, last_n)

    def get_history(self, session_id: str, last_n: int = None) -> list[dict]:
        return self.conversation.get_history(session_id, last_n)

    def update_agent_context(self, agent_id: str, key: str, value):
        if agent_id not in self.agent_contexts:
            self.agent_contexts[agent_id] = {}
        self.agent_contexts[agent_id][key] = value

    def get_agent_context(self, agent_id: str) -> dict:
        return self.agent_contexts.get(agent_id, {})

    def store_embedding(self, record_id: str, vector: list[float], metadata: dict = None):
        self.vectors.add(record_id, vector, metadata)

    def search_similar(self, query: list[float], k: int = 5) -> list[dict]:
        return self.vectors.search(query, k)

    def clear(self, session_id: str = None):
        if session_id:
            self.conversation.clear(session_id)
        else:
            self.conversation.clear()

    def get_session_stats(self) -> dict:
        return {
            "sessions": len(self.conversation.sessions),
            "current_session": self.conversation.current_session_id,
            "total_turns": sum(len(t) for t in self.conversation.sessions.values()),
            "vectors": len(self.vectors),
            "agent_contexts": list(self.agent_contexts.keys()),
        }
