"""
memory/manager.py — Memory manager integrating conversation memory,
vector store, agent contexts, structured session persistence, and
knowledge graph.
"""

import asyncio
import logging
import os
from typing import Optional

from .conversation import ConversationMemory
from .graph import KnowledgeGraph, create_graph
from .seed_graph import seed_graph
from .store import InMemoryVectorStore, VectorStore

logger = logging.getLogger("jarvis.memory")


class MemoryManager:
    def __init__(self, graph_backend: str = None, vector_backend: str = None):
        if vector_backend is None:
            vector_backend = os.getenv("VECTOR_BACKEND", "memory")
        self.conversation = ConversationMemory(max_turns=100, persist=True)
        if vector_backend == "qdrant":
            self.vectors = self._init_qdrant()
        else:
            self.vectors = InMemoryVectorStore(dimension=768)
        self.agent_contexts: dict[str, dict] = {}
        self.graph: KnowledgeGraph = create_graph(graph_backend)
        self._lock = asyncio.Lock()
        seed_graph(self.graph)

    def _init_qdrant(self) -> VectorStore:
        from .qdrant_store import QdrantVectorStore

        url = os.getenv("QDRANT_URL", "http://localhost:6333")
        dimension = int(os.getenv("VECTOR_DIMENSION", "768"))
        return QdrantVectorStore(url=url, dimension=dimension)

    def set_checkpoint_manager(self, mgr):
        self._checkpoint_mgr = mgr

    async def new_session(self, session_id: str = None) -> str:
        async with self._lock:
            sid = await self.conversation.new_session(session_id)
            if hasattr(self, '_checkpoint_mgr') and self._checkpoint_mgr:
                self._checkpoint_mgr.create_session_record(sid)
            return sid

    async def resume_session(self, session_id: str) -> bool:
        async with self._lock:
            return await self.conversation.resume_session(session_id)

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

    async def hybrid_search(self, embedding: list[float] = None, keyword: str = None,
                            top_k: int = 10) -> list:
        """Fuse vector similarity + knowledge-graph hits via Reciprocal Rank
        Fusion (H5.14). Returns a ranked list of `fusion.FusedHit`."""
        from .fusion import HybridRetriever
        async with self._lock:
            retriever = HybridRetriever(
                self.vectors, self.graph,
                k=getattr(self, "fusion_k", 60),
                vector_weight=getattr(self, "fusion_vector_weight", 1.0),
                graph_weight=getattr(self, "fusion_graph_weight", 1.0),
            )
            return retriever.retrieve(embedding=embedding, keyword=keyword, top_k=top_k)

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

    async def add_fact(self, name: str, entity_type: str = None, properties: dict = None, source: str = None, relation: str = None, target: str = None) -> bool:
        """Add a fact to the knowledge graph. Supports entity or relation creation."""
        async with self._lock:
            if source and relation and target:
                ok = self.graph.add_relation(source, relation, target, properties)
            elif name and entity_type:
                ok = self.graph.add_entity(name, entity_type, properties)
            else:
                return False
            return ok

    async def query_facts(self, cypher: str, params: dict = None) -> list[dict]:
        """Run a Cypher query against the knowledge graph."""
        async with self._lock:
            return self.graph.query(cypher, params)

    async def get_entity_info(self, name: str) -> Optional[dict]:
        """Get entity info from the knowledge graph."""
        async with self._lock:
            entity = self.graph.get_entity(name)
            if entity:
                entity["relations"] = self.graph.get_relations(name)
            return entity
