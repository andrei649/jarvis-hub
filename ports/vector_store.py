from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any, Optional


@dataclass
class VectorRecord:
    id: str
    embedding: List[float]
    payload: Dict[str, Any]
    score: Optional[float] = None  # Populat doar la căutare


class VectorStorePort(ABC):
    """
    Port (Interfață) pentru operațiuni vectoriale.
    Decuplează skill-urile de infrastructura reală (Qdrant/Milvus/etc.).
    """

    @abstractmethod
    def upsert(self, records: List[VectorRecord]) -> None:
        """Adaugă sau actualizează vectori în baza de date."""
        pass

    @abstractmethod
    def search(self, query_embedding: List[float], limit: int = 5) -> List[VectorRecord]:
        """Caută cei mai similari vectori pe baza distanței/similitudinii."""
        pass

    @abstractmethod
    def delete(self, ids: List[str]) -> None:
        """Șterge vectori după ID."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Golire completă (utilă în special pentru setup/teardown în teste)."""
        pass
