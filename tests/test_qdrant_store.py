import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.memory.store import InMemoryVectorStore, VectorRecord, VectorStore


class TestInMemoryVectorStore:
    def test_add_and_get(self):
        store = InMemoryVectorStore(dimension=4)
        store.add("rec_1", [0.1, 0.2, 0.3, 0.4], {"sender": "alice"})
        rec = store.get("rec_1")
        assert rec is not None
        assert rec.id == "rec_1"
        assert rec.vector == [0.1, 0.2, 0.3, 0.4]
        assert rec.metadata["sender"] == "alice"

    def test_add_dimension_mismatch(self):
        store = InMemoryVectorStore(dimension=3)
        with pytest.raises(ValueError, match="Expected dim=3"):
            store.add("rec_1", [0.1, 0.2], {})

    def test_search(self):
        store = InMemoryVectorStore(dimension=3)
        store.add("a", [1.0, 0.0, 0.0], {"tag": "x"})
        store.add("b", [0.0, 1.0, 0.0], {"tag": "y"})
        store.add("c", [0.9, 0.1, 0.0], {"tag": "x"})
        results = store.search([1.0, 0.0, 0.0], k=2)
        assert len(results) == 2
        assert results[0]["id"] == "a"

    def test_search_empty(self):
        store = InMemoryVectorStore(dimension=3)
        assert store.search([1.0, 0.0, 0.0]) == []

    def test_search_by_sender(self):
        store = InMemoryVectorStore(dimension=3)
        store.add("a", [1.0, 0.0, 0.0], {"sender": "alice"})
        store.add("b", [0.0, 1.0, 0.0], {"sender": "bob"})
        store.add("c", [0.9, 0.1, 0.0], {"sender": "alice"})
        results = store.search_by_sender("alice", k=10)
        assert len(results) == 2
        assert all(r["metadata"]["sender"] == "alice" for r in results)

    def test_search_by_text_subset(self):
        store = InMemoryVectorStore(dimension=3)
        store.add("a", [1.0, 0.0, 0.0], {"sender": "alice"})
        store.add("b", [0.0, 1.0, 0.0], {"sender": "bob"})
        store.add("c", [0.9, 0.1, 0.0], {"sender": "alice"})
        results = store.search_by_text_subset([1.0, 0.0, 0.0], sender="alice", k=5)
        assert len(results) == 2
        assert all(r["metadata"]["sender"] == "alice" for r in results)

    def test_remove(self):
        store = InMemoryVectorStore(dimension=3)
        store.add("a", [1.0, 0.0, 0.0], {})
        store.add("b", [0.0, 1.0, 0.0], {})
        store.remove("a")
        assert store.get("a") is None
        assert store.get("b") is not None
        assert store.get("b").id == "b"

    def test_len(self):
        store = InMemoryVectorStore(dimension=3)
        assert len(store) == 0
        store.add("a", [1.0, 0.0, 0.0], {})
        assert len(store) == 1
        store.add("b", [0.0, 1.0, 0.0], {})
        assert len(store) == 2

    def test_vector_store_is_abstract(self):
        with pytest.raises(TypeError):
            VectorStore()


class TestQdrantVectorStore:
    @pytest.fixture
    def mock_client(self):
        with patch("agents.core.memory.qdrant_store.httpx.Client") as mock:
            yield mock

    @pytest.fixture
    def store(self, mock_client):
        from agents.core.memory.qdrant_store import QdrantVectorStore

        client_instance = mock_client.return_value
        client_instance.get.return_value.status_code = 200
        client_instance.get.return_value.json.return_value = {
            "result": {"status": "green", "points_count": 0}
        }
        client_instance.put.return_value.status_code = 200
        client_instance.put.return_value.json.return_value = {"result": {"status": "ok"}}
        client_instance.post.return_value.status_code = 200
        client_instance.post.return_value.json.return_value = {"result": []}
        return QdrantVectorStore(url="http://localhost:6333", dimension=768)

    def test_creates_collection_on_first_add(self, mock_client):
        from agents.core.memory.qdrant_store import QdrantVectorStore

        client_instance = mock_client.return_value
        client_instance.get.return_value.status_code = 404
        client_instance.put.return_value.status_code = 200
        client_instance.put.return_value.json.return_value = {"result": True}
        client_instance.post.return_value.status_code = 200
        client_instance.post.return_value.json.return_value = {"result": []}

        store = QdrantVectorStore(url="http://localhost:6333", dimension=768)
        store.add("rec_1", [0.1] * 768, {"sender": "alice"})

        client_instance.put.assert_any_call(
            "http://localhost:6333/collections/jarvis_memory",
            json={"vectors": {"size": 768, "distance": "Cosine"}},
        )

    def test_search_returns_results(self, store, mock_client):
        client_instance = mock_client.return_value
        client_instance.post.return_value.json.return_value = {
            "result": [
                {
                    "id": "550e8400-e29b-41d4-a716-446655440000",
                    "score": 0.95,
                    "payload": {"_record_id": "rec_1", "sender": "alice"},
                },
                {
                    "id": "550e8400-e29b-41d4-a716-446655440001",
                    "score": 0.80,
                    "payload": {"_record_id": "rec_2", "sender": "bob"},
                },
            ]
        }

        results = store.search([0.1] * 768, k=5)
        assert len(results) == 2
        assert results[0]["id"] == "rec_1"
        assert results[0]["score"] == 0.95
        assert results[0]["metadata"] == {"sender": "alice"}
        assert results[1]["id"] == "rec_2"

    def test_get_returns_record(self, store, mock_client):
        from agents.core.memory.qdrant_store import _record_id_to_uuid

        point_id = _record_id_to_uuid("rec_1")
        client_instance = mock_client.return_value
        client_instance.get.return_value.status_code = 200
        client_instance.get.return_value.json.return_value = {
            "result": {
                "id": point_id,
                "vector": [0.1] * 768,
                "payload": {"_record_id": "rec_1", "sender": "alice"},
            }
        }

        rec = store.get("rec_1")
        assert rec is not None
        assert rec.id == "rec_1"
        assert rec.metadata == {"sender": "alice"}

    def test_get_returns_none_for_404(self, store, mock_client):
        client_instance = mock_client.return_value
        client_instance.get.return_value.status_code = 404

        rec = store.get("missing")
        assert rec is None

    def test_remove(self, store, mock_client):
        client_instance = mock_client.return_value
        client_instance.post.return_value.status_code = 200

        store.remove("rec_1")
        client_instance.post.assert_called_once()
        call_args = client_instance.post.call_args
        assert "delete" in call_args[0][0]

    def test_len(self, store, mock_client):
        client_instance = mock_client.return_value
        client_instance.post.return_value.json.return_value = {"result": {"count": 42}}

        assert len(store) == 42

    def test_graceful_degradation_on_connection_refused(self, mock_client):
        from agents.core.memory.qdrant_store import QdrantVectorStore

        client_instance = mock_client.return_value
        client_instance.get.side_effect = ConnectionRefusedError("Connection refused")
        client_instance.put.side_effect = ConnectionRefusedError("Connection refused")
        client_instance.post.side_effect = ConnectionRefusedError("Connection refused")

        store = QdrantVectorStore(url="http://localhost:6333", dimension=768)

        store.add("rec_1", [0.1] * 768, {"sender": "alice"})

        results = store.search([0.1] * 768, k=5)
        assert results == []

        rec = store.get("rec_1")
        assert rec is None

        store.remove("rec_1")

        assert len(store) == 0

    def test_search_by_sender(self, store, mock_client):
        client_instance = mock_client.return_value
        client_instance.post.return_value.json.return_value = {
            "result": {
                "points": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "payload": {"_record_id": "rec_1", "sender": "alice", "timestamp": 1000},
                    },
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440001",
                        "payload": {"_record_id": "rec_2", "sender": "alice", "timestamp": 2000},
                    },
                ]
            }
        }

        results = store.search_by_sender("alice", k=10)
        assert len(results) == 2
        assert results[0]["id"] == "rec_2"
        assert results[0]["timestamp"] == 2000

    def test_search_by_text_subset(self, store, mock_client):
        client_instance = mock_client.return_value
        client_instance.post.return_value.json.return_value = {
            "result": [
                {
                    "id": "550e8400-e29b-41d4-a716-446655440000",
                    "score": 0.90,
                    "payload": {"_record_id": "rec_1", "sender": "alice"},
                },
            ]
        }

        results = store.search_by_text_subset([0.1] * 768, sender="alice", k=5)
        assert len(results) == 1
        assert results[0]["id"] == "rec_1"
        assert results[0]["score"] == 0.90

    def test_add_dimension_mismatch(self, store):
        with pytest.raises(ValueError, match="Expected dim=768"):
            store.add("rec_1", [0.1, 0.2], {})
