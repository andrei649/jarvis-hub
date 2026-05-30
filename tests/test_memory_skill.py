from ports.vector_store import VectorRecord
from adapters.in_memory_vector_store import InMemoryVectorStoreAdapter


def test_skill_can_store_and_search_memories():
    # 1. Setup: Injectăm adaptorul in-memory în loc de Qdrant real
    vector_db = InMemoryVectorStoreAdapter()

    record1 = VectorRecord(
        id="msg_001", embedding=[0.1, 0.9, 0.0], payload={"text": "Andrei vrea analiză imobiliară"}
    )
    record2 = VectorRecord(
        id="msg_002", embedding=[0.9, 0.1, 0.0], payload={"text": "Cumpără lapte"}
    )

    vector_db.upsert([record1, record2])

    # 2. Execution: Căutăm cu un vector apropiat ca structură de record1
    query_vector = [0.15, 0.85, 0.0]
    results = vector_db.search(query_vector, limit=1)

    # 3. Assertions
    assert len(results) == 1
    assert results[0].id == "msg_001"
    assert "imobiliară" in results[0].payload["text"]
    assert results[0].score > 0.95


def test_delete_and_clear():
    vector_db = InMemoryVectorStoreAdapter()
    vector_db.upsert(
        [
            VectorRecord(id="a", embedding=[1.0, 0.0], payload={}),
            VectorRecord(id="b", embedding=[0.0, 1.0], payload={}),
        ]
    )
    vector_db.delete(["a"])
    assert [r.id for r in vector_db.search([1.0, 0.0])] == ["b"]
    vector_db.clear()
    assert vector_db.search([1.0, 0.0]) == []


def test_upsert_is_idempotent_and_copies_input():
    vector_db = InMemoryVectorStoreAdapter()
    emb = [0.2, 0.3]
    rec = VectorRecord(id="x", embedding=emb, payload={"k": "v"})
    vector_db.upsert([rec])
    vector_db.upsert([VectorRecord(id="x", embedding=[0.4, 0.5], payload={"k": "v2"})])

    # Mutating the original input must not leak into the store (defensive copy).
    emb.append(99.0)
    results = vector_db.search([0.4, 0.5], limit=5)
    assert len(results) == 1
    assert results[0].payload["k"] == "v2"


def test_empty_store_returns_empty():
    assert InMemoryVectorStoreAdapter().search([0.1, 0.2]) == []
