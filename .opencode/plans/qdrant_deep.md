# SPECIFICATION: H3.x Detailed Qdrant Vector Store Service

## 1. Chunking Strategy for `memory_logs/` JSON Parsing
To parse variable JSON transaction payloads into deterministic memory vectors without blowing context windows:
- **Strategy**: Textual Flattening. Convert JSON fields into an explicit semantic string: `"Timestamp: {t} | Source: {s} | Content: {c}"`.
- **Chunk Size**: 512 tokens.
- **Overlap**: 64 tokens.
- **Execution Hook**: Background ticker built on `apscheduler` flushes the log queue every 5 minutes.

## 2. Dynamic Embedding Configuration
To support multi-model capability without code modification:
- **Router Property Mapping**: If `EMBEDDING_MODEL` in `.env` matches `bge-large-en-v1.5`, set vectors dimension to `1024`. If it matches `nomic-embed-text`, set dimension to `768`.
- **Endpoint Abstraction**: All requests point to `EMBEDDING_ENDPOINT`, managed by the `HybridRouter` system.

## 3. Exception Safety and Graceful Degradation (Fallback Protocol)
The system must never throw a 5xx error if the vector store crashes.
```python
try:
    embeddings = await self.hybrid_router.get_embeddings(text)
    context = await self.qdrant_client.search(collection, embeddings)
except (QdrantTimeoutError, ConnectionError, Exception) as e:
    self.logger.error(f"Qdrant unreachable: {e}. Executing fallback pathway.")
    context = ""
```

## 4. Operational Guardrails inside `orchestrator.py`
- **Resource Lock Integration**: Before scheduling a log indexing batch via `apscheduler`, the storage client must check `LockManager.is_component_locked("memory_logs/")`. If Claude Code or the user is actively rewriting log blocks, the processing engine backs off and delays the batch job to prevent collision.
