import logging
import math
from typing import Any

logger = logging.getLogger("jarvis.memory.store")

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    logger.warning("numpy not available — vector store disabled")


class VectorRecord:
    __slots__ = ("id", "vector", "metadata", "timestamp")

    def __init__(self, record_id: str, vector: list[float], metadata: dict = None):
        self.id = record_id
        self.vector = vector
        self.metadata = metadata or {}
        self.timestamp = __import__("time").time()


class VectorStore:
    def __init__(self, dimension: int = 768):
        self.dimension = dimension
        self.records: list[VectorRecord] = []
        self._id_index: dict[str, int] = {}
        logger.info(f"VectorStore initialized (dim={dimension}, numpy={HAS_NUMPY})")

    def add(self, record_id: str, vector: list[float], metadata: dict = None):
        if len(vector) != self.dimension:
            raise ValueError(f"Expected dim={self.dimension}, got {len(vector)}")
        record = VectorRecord(record_id, vector, metadata)
        self.records.append(record)
        self._id_index[record_id] = len(self.records) - 1

    def search(self, query: list[float], k: int = 5) -> list[dict[str, Any]]:
        if not self.records:
            return []
        if HAS_NUMPY:
            return self._search_numpy(query, k)
        return self._search_naive(query, k)

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
            sim = float(np.dot(q, v) / (q_norm * v_norm)) if v_norm > 0 else 0.0
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
        results = [rec for rec in self.records if rec.metadata.get("sender") == sender]
        results.sort(key=lambda r: r.timestamp, reverse=True)
        return [
            {"id": r.id, "metadata": r.metadata, "timestamp": r.timestamp}
            for r in results[:k]
        ]

    def search_by_text_subset(self, query: list[float], sender: str = None, k: int = 5) -> list[dict[str, Any]]:
        if not self.records:
            return []
        results = self._search_numpy(query, k * 3) if HAS_NUMPY else self._search_naive(query, k * 3)
        if sender:
            results = [r for r in results if r.get("metadata", {}).get("sender") == sender]
        return results[:k]

    def get(self, record_id: str) -> VectorRecord:
        idx = self._id_index.get(record_id)
        if idx is not None:
            return self.records[idx]
        return None

    def remove(self, record_id: str):
        idx = self._id_index.pop(record_id, None)
        if idx is not None:
            self.records.pop(idx)
            for rid, i in list(self._id_index.items()):
                if i > idx:
                    self._id_index[rid] = i - 1

    def __len__(self):
        return len(self.records)
