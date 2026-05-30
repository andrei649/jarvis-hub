import logging
import uuid
from typing import Any

import httpx

from .store import VectorRecord, VectorStore

logger = logging.getLogger("jarvis.memory.qdrant")


def _record_id_to_uuid(record_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, record_id))


class QdrantVectorStore(VectorStore):
    def __init__(self, url: str = "http://localhost:6333", collection: str = "jarvis_memory", dimension: int = 768):
        self.url = url.rstrip("/")
        self.collection = collection
        self.dimension = dimension
        self._client = httpx.Client(timeout=10.0)
        self._collection_ready = False
        logger.info(f"QdrantVectorStore initialized (url={url}, collection={collection}, dim={dimension})")

    def _ensure_collection(self):
        if self._collection_ready:
            return
        try:
            resp = self._client.get(f"{self.url}/collections/{self.collection}")
            if resp.status_code == 200:
                self._collection_ready = True
                return
        except Exception:
            pass
        try:
            payload = {
                "vectors": {
                    "size": self.dimension,
                    "distance": "Cosine",
                }
            }
            resp = self._client.put(f"{self.url}/collections/{self.collection}", json=payload)
            if resp.status_code == 200:
                self._collection_ready = True
                logger.info(f"Created Qdrant collection '{self.collection}' (dim={self.dimension})")
            else:
                logger.warning(f"Failed to create Qdrant collection: {resp.status_code} {resp.text}")
        except Exception as exc:
            logger.warning(f"Qdrant unreachable — cannot create collection: {exc}")

    def add(self, record_id: str, vector: list[float], metadata: dict = None):
        if len(vector) != self.dimension:
            raise ValueError(f"Expected dim={self.dimension}, got {len(vector)}")
        try:
            self._ensure_collection()
            point_id = _record_id_to_uuid(record_id)
            payload = {"_record_id": record_id, **(metadata or {})}
            body = {
                "points": [
                    {
                        "id": point_id,
                        "vector": vector,
                        "payload": payload,
                    }
                ]
            }
            resp = self._client.put(
                f"{self.url}/collections/{self.collection}/points",
                json=body,
            )
            if resp.status_code != 200:
                logger.warning(f"Qdrant upsert failed: {resp.status_code} {resp.text}")
        except Exception as exc:
            logger.warning(f"Qdrant add error (degraded): {exc}")

    def search(self, query: list[float], k: int = 5) -> list[dict[str, Any]]:
        try:
            self._ensure_collection()
            body = {
                "vector": query,
                "limit": k,
                "with_payload": True,
            }
            resp = self._client.post(
                f"{self.url}/collections/{self.collection}/points/search",
                json=body,
            )
            if resp.status_code != 200:
                logger.warning(f"Qdrant search failed: {resp.status_code} {resp.text}")
                return []
            results = resp.json().get("result", [])
            return [
                {
                    "id": r["payload"].get("_record_id", str(r["id"])),
                    "score": r["score"],
                    "metadata": {k: v for k, v in r.get("payload", {}).items() if k != "_record_id"},
                }
                for r in results
            ]
        except Exception as exc:
            logger.warning(f"Qdrant search error (degraded): {exc}")
            return []

    def get(self, record_id: str) -> VectorRecord | None:
        try:
            self._ensure_collection()
            point_id = _record_id_to_uuid(record_id)
            resp = self._client.get(
                f"{self.url}/collections/{self.collection}/points/{point_id}"
            )
            if resp.status_code == 404:
                return None
            if resp.status_code != 200:
                logger.warning(f"Qdrant get failed: {resp.status_code} {resp.text}")
                return None
            result = resp.json().get("result", {})
            if not result:
                return None
            payload = result.get("payload", {})
            metadata = {k: v for k, v in payload.items() if k != "_record_id"}
            return VectorRecord(record_id, result.get("vector", []), metadata)
        except Exception as exc:
            logger.warning(f"Qdrant get error (degraded): {exc}")
            return None

    def remove(self, record_id: str):
        try:
            self._ensure_collection()
            point_id = _record_id_to_uuid(record_id)
            body = {"points": [point_id]}
            resp = self._client.post(
                f"{self.url}/collections/{self.collection}/points/delete",
                json=body,
            )
            if resp.status_code != 200:
                logger.warning(f"Qdrant delete failed: {resp.status_code} {resp.text}")
        except Exception as exc:
            logger.warning(f"Qdrant remove error (degraded): {exc}")

    def search_by_sender(self, sender: str, k: int = 10) -> list[dict]:
        try:
            self._ensure_collection()
            body = {
                "filter": {
                    "must": [
                        {"key": "sender", "match": {"value": sender}}
                    ]
                },
                "limit": k * 3,
                "with_payload": True,
                "with_vector": False,
            }
            resp = self._client.post(
                f"{self.url}/collections/{self.collection}/points/scroll",
                json=body,
            )
            if resp.status_code != 200:
                logger.warning(f"Qdrant scroll failed: {resp.status_code} {resp.text}")
                return []
            points = resp.json().get("result", {}).get("points", [])
            results = []
            for p in points:
                payload = p.get("payload", {})
                metadata = {key: val for key, val in payload.items() if key not in ("_record_id", "timestamp")}
                results.append({
                    "id": payload.get("_record_id", str(p["id"])),
                    "metadata": metadata,
                    "timestamp": payload.get("timestamp", 0),
                })
            results.sort(key=lambda r: r["timestamp"], reverse=True)
            return results[:k]
        except Exception as exc:
            logger.warning(f"Qdrant search_by_sender error (degraded): {exc}")
            return []

    def search_by_text_subset(self, query: list[float], sender: str = None, k: int = 5) -> list[dict[str, Any]]:
        try:
            self._ensure_collection()
            body: dict[str, Any] = {
                "vector": query,
                "limit": k * 3,
                "with_payload": True,
            }
            if sender:
                body["filter"] = {
                    "must": [
                        {"key": "sender", "match": {"value": sender}}
                    ]
                }
            resp = self._client.post(
                f"{self.url}/collections/{self.collection}/points/search",
                json=body,
            )
            if resp.status_code != 200:
                logger.warning(f"Qdrant search failed: {resp.status_code} {resp.text}")
                return []
            results = resp.json().get("result", [])
            return [
                {
                    "id": r["payload"].get("_record_id", str(r["id"])),
                    "score": r["score"],
                    "metadata": {key: val for key, val in r.get("payload", {}).items() if key != "_record_id"},
                }
                for r in results[:k]
            ]
        except Exception as exc:
            logger.warning(f"Qdrant search_by_text_subset error (degraded): {exc}")
            return []

    def __len__(self):
        try:
            self._ensure_collection()
            resp = self._client.post(
                f"{self.url}/collections/{self.collection}/points/count",
                json={},
            )
            if resp.status_code == 200:
                return resp.json().get("result", {}).get("count", 0)
        except Exception as exc:
            logger.warning(f"Qdrant count error (degraded): {exc}")
        return 0
