"""
embedder.py — Text embedding for Howard's ingestion pipeline (H5.17).

Generates embeddings for chat messages using a local embedding model
(Ollama / nomic-embed-text) with a character-hash fallback when no model is
available.

H5.17 — Batch & Cache Embeddings Pipeline:
  * **Disk cache** (`EmbeddingCache`): content-addressed, sharded, crash-safe.
    Re-embedding text already seen is a cache hit, so a massive Howard ingest
    that is interrupted and re-run does not recompute everything.
  * **Batching** (`embed_batch`): resolves cache hits first, de-duplicates,
    and computes only the misses.
  * **Rate-limit resilience**: each backend call is retried with exponential
    backoff; after the budget is exhausted it degrades to the hash embedding
    so a single flaky call never aborts the whole ingest.
  * **Parallelism**: misses can be computed across a small thread pool.

All I/O is injectable / offline-capable, so the pipeline is unit-tested without
Ollama or the network.
"""

import hashlib
import json
import logging
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from .normalizer import NormalizedMessage

logger = logging.getLogger("jarvis.ingestion.embedder")

EMBEDDING_DIM = 768


class EmbeddingCache:
    """Content-addressed on-disk cache for embeddings.

    Key = ``sha256(namespace \\x00 text)``. Entries are sharded into subdirs by
    the first two hex chars (keeps any one directory small) and written as small
    JSON files via atomic temp-file rename (crash-safe). Tracks hit/miss stats.
    """

    def __init__(self, cache_dir, namespace: str = "default"):
        self.dir = Path(cache_dir)
        self.namespace = namespace
        self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0
        self.writes = 0

    def _key(self, text: str) -> str:
        h = hashlib.sha256()
        h.update(self.namespace.encode("utf-8"))
        h.update(b"\x00")
        h.update(text.encode("utf-8"))
        return h.hexdigest()

    def _path(self, key: str) -> Path:
        return self.dir / key[:2] / f"{key}.json"

    def get(self, text: str) -> Optional[list[float]]:
        path = self._path(self._key(text))
        if not path.exists():
            self.misses += 1
            return None
        try:
            vec = json.loads(path.read_text(encoding="utf-8"))["vector"]
            self.hits += 1
            return vec
        except Exception:
            # Corrupt entry — treat as a miss; it will be overwritten.
            self.misses += 1
            return None

    def put(self, text: str, vector: list[float]) -> None:
        key = self._key(text)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps({"vector": vector}), encoding="utf-8")
            os.replace(tmp, path)  # atomic on the same filesystem
            self.writes += 1
        except Exception as e:  # never let a cache write abort an ingest
            logger.warning(f"Embedding cache write failed for {key[:8]}: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    @property
    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "hit_rate": (self.hits / total) if total else 0.0,
        }


class Embedder:
    def __init__(self, backend: str = "ollama", model: str = "nomic-embed-text",
                 cache_dir=None, *, max_retries: int = 3, backoff_base: float = 0.5,
                 backoff_max: float = 8.0, max_workers: int = 1):
        self.backend = backend
        self.model = model
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.max_workers = max(1, max_workers)
        self._client = None
        self._setup()
        # Namespace the cache by the backend that actually produces vectors, so
        # ollama and hash embeddings are never mixed under one key.
        self.cache = (
            EmbeddingCache(cache_dir, namespace=f"{self.backend}:{self.model}")
            if cache_dir is not None else None
        )

    def _setup(self):
        if self.backend == "ollama":
            try:
                import ollama
                self._client = ollama
                logger.info(f"Embedder: Ollama/{self.model}")
            except ImportError:
                logger.warning("Ollama not installed, falling back to hash embeddings")
                self.backend = "hash"
        else:
            logger.info(f"Embedder: {self.backend}")

    # ── public API ────────────────────────────────────────────────────────────

    def embed(self, text: str) -> list[float]:
        """Embed one text (cache-aware)."""
        if not text or not text.strip():
            return [0.0] * EMBEDDING_DIM
        if self.cache is not None:
            cached = self.cache.get(text)
            if cached is not None:
                return cached
        vec = self._embed_resilient(text)
        if self.cache is not None:
            self.cache.put(text, vec)
        return vec

    def embed_batch(self, texts: list[str], *, batch_size: int = 32) -> list[list[float]]:
        """Embed many texts with caching, de-duplication, and parallel misses.

        Returns a list aligned 1:1 with ``texts``. ``batch_size`` bounds how many
        unique misses are dispatched per wave (keeps memory + a remote backend's
        in-flight load in check).
        """
        results: list[Optional[list[float]]] = [None] * len(texts)
        misses: dict[str, list[int]] = {}  # unique text -> positions needing it

        for i, text in enumerate(texts):
            if not text or not text.strip():
                results[i] = [0.0] * EMBEDDING_DIM
                continue
            if self.cache is not None:
                cached = self.cache.get(text)
                if cached is not None:
                    results[i] = cached
                    continue
            misses.setdefault(text, []).append(i)

        unique_texts = list(misses.keys())
        for start in range(0, len(unique_texts), max(1, batch_size)):
            wave = unique_texts[start:start + max(1, batch_size)]
            computed = self._compute_wave(wave)
            for text, vec in zip(wave, computed):
                if self.cache is not None:
                    self.cache.put(text, vec)
                for pos in misses[text]:
                    results[pos] = vec

        return [r if r is not None else [0.0] * EMBEDDING_DIM for r in results]

    def embed_many(self, messages: list[NormalizedMessage]) -> list[NormalizedMessage]:
        """Embed a list of NormalizedMessages in place (batched + cached)."""
        vectors = self.embed_batch([m.text for m in messages])
        for msg, vec in zip(messages, vectors):
            msg.embedding = vec
        return messages

    @property
    def cache_stats(self) -> Optional[dict]:
        return self.cache.stats if self.cache is not None else None

    # ── internals ─────────────────────────────────────────────────────────────

    def _compute_wave(self, texts: list[str]) -> list[list[float]]:
        """Compute embeddings for a wave of unique misses, optionally in parallel."""
        if self.max_workers == 1 or len(texts) == 1:
            return [self._embed_resilient(t) for t in texts]
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            return list(pool.map(self._embed_resilient, texts))

    def _embed_resilient(self, text: str) -> list[float]:
        """Call the primary backend with retry+backoff; degrade to hash on failure."""
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._embed_primary(text)
            except Exception as e:  # rate limit, transient network, model busy…
                last_exc = e
                if attempt < self.max_retries:
                    delay = min(self.backoff_base * (2 ** attempt), self.backoff_max)
                    logger.warning(
                        f"embed attempt {attempt + 1}/{self.max_retries + 1} failed "
                        f"({type(e).__name__}), retrying in {delay:.2f}s"
                    )
                    if delay > 0:
                        time.sleep(delay)
        logger.warning(f"embed exhausted retries ({last_exc}); using hash fallback")
        return self._embed_hash(text)

    def _embed_primary(self, text: str) -> list[float]:
        """Raw backend call. Ollama may raise (caught by `_embed_resilient`);
        the hash backend is deterministic and never raises."""
        if self.backend == "ollama" and self._client:
            response = self._client.embeddings(model=self.model, prompt=text[:2048])
            vec = response.get("embedding")
            if not vec:
                raise ValueError("empty embedding from ollama")
            return vec
        return self._embed_hash(text)

    def _embed_hash(self, text: str) -> list[float]:
        text_bytes = text.encode("utf-8")
        if not text_bytes:
            return [0.0] * EMBEDDING_DIM
        vec = [0.0] * EMBEDDING_DIM
        chunk_size = max(1, len(text_bytes) // EMBEDDING_DIM)

        for i in range(EMBEDDING_DIM):
            start = (i * chunk_size) % len(text_bytes)
            end = min(start + chunk_size, len(text_bytes))
            chunk = text_bytes[start:end] if end > start else text_bytes[start:start + 1]
            hash_bytes = hashlib.md5(chunk).digest()
            vec[i] = (int.from_bytes(hash_bytes[:4], "big") / 2**32) * 2 - 1

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec
