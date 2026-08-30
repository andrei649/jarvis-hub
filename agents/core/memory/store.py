"""
store.py — Memory stores for Jarvis.

Contains:
  - VectorStore / InMemoryVectorStore: vector similarity search (legacy / embeddings)
  - MemoryStore: structured, persistent key/value memory for user facts and preferences.
    Backed by SQLite with WAL mode. Semantic search is stubbed (H8.3 wires Qdrant).
"""
import asyncio
import json
import logging
import math
import sqlite3
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("jarvis.memory.store")

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    logger.warning("numpy not available — vector store disabled")

# H11.2 (DRA-40): the compiled Rust hot-path crate, when it is actually built.
# `load_native()` existed but nothing called it, so `rust/jarvis_native` was
# unreachable even after `maturin build` — the ✅ row promised "preferă extensia
# compilată, altfel Python". Resolved once and cached: a missing extension is a
# failed import, and Python does not memoize those, so retrying per search would
# put an exception on the hot path. Tests substitute this module attribute.
_NATIVE_BACKEND = None


def _native():
    """Return the H11.2 hot-path module (Rust extension when built, else the fallback)."""
    global _NATIVE_BACKEND
    if _NATIVE_BACKEND is None:
        from agents.core.native_fallback import load_native

        _NATIVE_BACKEND = load_native()
    return _NATIVE_BACKEND


class VectorRecord:
    __slots__ = ("id", "vector", "metadata", "timestamp")

    def __init__(self, record_id: str, vector: list[float], metadata: dict = None):
        self.id = record_id
        self.vector = vector
        self.metadata = metadata or {}
        self.timestamp = __import__("time").time()


class VectorStore(ABC):
    @abstractmethod
    def add(self, record_id: str, vector: list[float], metadata: dict = None):
        ...

    @abstractmethod
    def search(self, query: list[float], k: int = 5) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def get(self, record_id: str):
        ...

    @abstractmethod
    def remove(self, record_id: str):
        ...

    @abstractmethod
    def search_by_sender(self, sender: str, k: int = 10) -> list[dict]:
        ...

    @abstractmethod
    def search_by_text_subset(self, query: list[float], sender: str = None, k: int = 5) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def clear(self) -> None:
        """Remove every record. Backs ``POST /api/admin/forget`` (AUDIT-2).

        Abstract on purpose. ``data_purge.clear_live_memory`` used to call this behind
        ``if hasattr(store, "clear")``, and no implementation defined it — so the wipe was
        unreachable, failed silently, and the purge still reported ``ok``. Under the
        documented qdrant/neo4j backends that meant every embedding survived a forget
        permanently, with no code path that could remove it. Declaring it here makes a
        missing implementation an import error instead of a silent no-op.
        """
        ...

    @abstractmethod
    def __len__(self):
        ...


class InMemoryVectorStore(VectorStore):
    def __init__(self, dimension: int = 768):
        self.dimension = dimension
        self.records: list[VectorRecord] = []
        self._id_index: dict[str, int] = {}
        # BUG-12 residual: MemoryManager wraps every call in an asyncio.Lock, but a
        # caller reaching this store directly (bypassing the manager) would race
        # unguarded list/dict mutation from a concurrent asyncio.to_thread. Mirror
        # the _PROC_CACHE_LOCK pattern in ingestion/embedder.py.
        self._lock = threading.Lock()
        logger.info(f"InMemoryVectorStore initialized (dim={dimension}, numpy={HAS_NUMPY})")

    def add(self, record_id: str, vector: list[float], metadata: dict = None):
        if len(vector) != self.dimension:
            raise ValueError(f"Expected dim={self.dimension}, got {len(vector)}")
        record = VectorRecord(record_id, vector, metadata)
        with self._lock:
            self.records.append(record)
            self._id_index[record_id] = len(self.records) - 1

    def search(self, query: list[float], k: int = 5) -> list[dict[str, Any]]:
        with self._lock:
            if not self.records:
                return []
            return self._rank(query, k)

    def _rank(self, query: list[float], k: int) -> list[dict]:
        """The single ranking dispatch shared by every search entry point.

        Order is the H11.2 contract: the compiled crate when it is present, then
        numpy, then the naive loop. Keeping one dispatch is deliberate — the
        previous two call sites were why wiring the native path anywhere would
        still have left `search_by_text_subset` on the old route.
        """
        if getattr(_native(), "BACKEND", "python") == "rust":
            return self._search_native(query, k)
        if HAS_NUMPY:
            return self._search_numpy(query, k)
        return self._search_naive(query, k)

    def _search_native(self, query: list[float], k: int) -> list[dict]:
        """Rank through the Rust crate, matching ``_search_numpy``'s contract.

        Both guards below exist to match ``_search_numpy``, the route this
        replaces on a normal install, rather than the naive loop:

        * a zero-norm query returns ``[]`` (numpy's ``q_norm == 0``), not the
          naive path's "score everything 0.0";
        * a wrong-length query raises, because ``np.dot`` does. The crate's
          ``top_k_similar`` instead ranks over ``min(len(a), len(b))``, so
          without this a dimension bug would stop being a loud ValueError and
          start returning quietly truncated — and wrong — retrieval results.

        Scores are f64 here and float32 there, so they agree to well within
        retrieval tolerance, not bit-for-bit.
        """
        if len(query) != self.dimension:
            raise ValueError(f"Expected dim={self.dimension}, got {len(query)}")
        if not any(query):
            return []
        ranked = _native().top_k_similar(list(query), [r.vector for r in self.records], k)
        return [
            {
                "id": self.records[i].id,
                "score": float(score),
                "metadata": self.records[i].metadata,
            }
            for i, score in ranked
        ]

    def _search_numpy(self, query: list[float], k: int) -> list[dict]:
        q = np.array(query, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []
        q = q / q_norm

        scores = []
        for rec in self.records:
            v = np.array(rec.vector, dtype=np.float32)
            v_norm = np.linalg.norm(v)
            # q is already unit-length (normalized above); dividing by q_norm again
            # would scale every score by 1/q_norm and mis-report cosine as
            # cosine/q_norm — the naive path already divides by v_norm only.
            sim = float(np.dot(q, v) / v_norm) if v_norm > 0 else 0.0
            scores.append(sim)

        top_indices = np.argsort(scores)[-k:][::-1]
        return [
            {
                "id": self.records[i].id,
                "score": float(scores[i]),
                "metadata": self.records[i].metadata,
            }
            for i in top_indices
        ]

    def _search_naive(self, query: list[float], k: int) -> list[dict]:
        def cosine_sim(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            return dot / (na * nb) if na * nb > 0 else 0.0

        scored = [(cosine_sim(query, rec.vector), rec) for rec in self.records]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"id": rec.id, "score": score, "metadata": rec.metadata}
            for score, rec in scored[:k]
        ]

    def search_by_sender(self, sender: str, k: int = 10) -> list[dict]:
        with self._lock:
            results = [rec for rec in self.records if rec.metadata.get("sender") == sender]
            results.sort(key=lambda r: r.timestamp, reverse=True)
            return [
                {"id": r.id, "metadata": r.metadata, "timestamp": r.timestamp}
                for r in results[:k]
            ]

    def search_by_text_subset(self, query: list[float], sender: str = None, k: int = 5) -> list[dict[str, Any]]:
        with self._lock:
            if not self.records:
                return []
            results = self._rank(query, k * 3)
            if sender:
                results = [r for r in results if r.get("metadata", {}).get("sender") == sender]
            return results[:k]

    def get(self, record_id: str) -> VectorRecord:
        with self._lock:
            idx = self._id_index.get(record_id)
            if idx is not None:
                return self.records[idx]
            return None

    def clear(self) -> None:
        with self._lock:
            self.records.clear()
            self._id_index.clear()

    def remove(self, record_id: str):
        with self._lock:
            idx = self._id_index.pop(record_id, None)
            if idx is not None:
                self.records.pop(idx)
                for rid, i in list(self._id_index.items()):
                    if i > idx:
                        self._id_index[rid] = i - 1

    def __len__(self):
        with self._lock:
            return len(self.records)


# ---------------------------------------------------------------------------
# H8.2 — Structured memory store (SQLite-backed key/value)
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "memory.db"


class MemoryStore:
    """Structured, persistent memory for user facts and preferences.

    Backed by SQLite with WAL mode.  Semantic search is stubbed
    (H8.3 wires Qdrant).
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._path = Path(db_path or DEFAULT_DB_PATH)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._lock:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS memory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category TEXT NOT NULL,
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        metadata TEXT DEFAULT '{}',
                        created_at TEXT DEFAULT (datetime('now')),
                        updated_at TEXT DEFAULT (datetime('now')),
                        UNIQUE(category, key)
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memory_category ON memory(category)"
                )

    async def upsert(self, category: str, key: str, value: str, metadata: dict = None):
        meta_json = json.dumps(metadata or {})
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._upsert_sync, category, key, value, meta_json)

    def _upsert_sync(self, category: str, key: str, value: str, meta_json: str):
        with self._lock:
            with self._conn() as conn:
                conn.execute("""
                    INSERT INTO memory (category, key, value, metadata)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(category, key) DO UPDATE SET
                        value=excluded.value,
                        metadata=excluded.metadata,
                        updated_at=datetime('now')
                """, (category, key, value, meta_json))

    async def get(self, category: str, key: str) -> Optional[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_sync, category, key)

    def _get_sync(self, category: str, key: str) -> Optional[dict]:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM memory WHERE category=? AND key=?", (category, key)
                ).fetchone()
                return dict(row) if row else None

    async def get_category(self, category: str) -> list[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_category_sync, category)

    def _get_category_sync(self, category: str) -> list[dict]:
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM memory WHERE category=? ORDER BY updated_at DESC",
                    (category,),
                ).fetchall()
                return [dict(r) for r in rows]

    async def get_all(self) -> dict[str, list[dict]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_all_sync)

    def _get_all_sync(self) -> dict[str, list[dict]]:
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM memory ORDER BY category, updated_at DESC"
                ).fetchall()
                result: dict[str, list] = {}
                for r in rows:
                    d = dict(r)
                    result.setdefault(d["category"], []).append(d)
                return result

    async def delete(self, category: str, key: str) -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._delete_sync, category, key)

    def _delete_sync(self, category: str, key: str) -> bool:
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute(
                    "DELETE FROM memory WHERE category=? AND key=?", (category, key)
                )
                return cur.rowcount > 0

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        """Basic text search — semantic search stubbed for H8.3."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._search_sync, query, limit)

    def _search_sync(self, query: str, limit: int) -> list[dict]:
        with self._lock:
            with self._conn() as conn:
                pattern = f"%{query}%"
                rows = conn.execute(
                    "SELECT * FROM memory WHERE value LIKE ? OR key LIKE ?"
                    " ORDER BY updated_at DESC LIMIT ?",
                    (pattern, pattern, limit),
                ).fetchall()
                return [dict(r) for r in rows]
