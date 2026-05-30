import math
from typing import List, Dict
from ports.vector_store import VectorStorePort, VectorRecord


class InMemoryVectorStoreAdapter(VectorStorePort):
    """
    Adaptor de test/mock care rulează integral în memorie.
    Implementează similitudinea cosinus nativă, fără dependențe externe.
    """

    def __init__(self):
        self._storage: Dict[str, VectorRecord] = {}

    def upsert(self, records: List[VectorRecord]) -> None:
        for record in records:
            # Stocăm o copie pentru a evita mutațiile accidentale în memorie
            self._storage[record.id] = VectorRecord(
                id=record.id,
                embedding=list(record.embedding),
                payload=dict(record.payload),
            )

    def delete(self, ids: List[str]) -> None:
        for record_id in ids:
            self._storage.pop(record_id, None)

    def clear(self) -> None:
        self._storage.clear()

    def search(self, query_embedding: List[float], limit: int = 5) -> List[VectorRecord]:
        if not self._storage:
            return []

        scored_results = []
        for record in self._storage.values():
            score = self._calculate_cosine_similarity(query_embedding, record.embedding)

            # Creăm un nou record care include și scorul de similaritate
            result_record = VectorRecord(
                id=record.id,
                embedding=record.embedding,
                payload=record.payload,
                score=score,
            )
            scored_results.append(result_record)

        # Sortăm descrescător după scor (cel mai similar primul)
        scored_results.sort(key=lambda x: x.score if x.score is not None else -1.0, reverse=True)

        return scored_results[:limit]

    def _calculate_cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Calcul de similitudine cosinus în Python pur."""
        if len(v1) != len(v2) or not v1:
            return 0.0

        dot_product = sum(a * b for a, b in zip(v1, v2))
        norm_v1 = math.sqrt(sum(a * a for a in v1))
        norm_v2 = math.sqrt(sum(b * b for b in v2))

        if norm_v1 == 0.0 or norm_v2 == 0.0:
            return 0.0

        return dot_product / (norm_v1 * norm_v2)
