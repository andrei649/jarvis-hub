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

H7.4 — Query-embedding cache + fast-fail for recall:
  * **In-process LRU** (`_PROC_CACHE`): bounded dict keyed by
    ``(backend, model, text)``; skips even the disk read for hot queries
    within a single process.
  * **from_env default cache_dir**: when no ``cache_dir`` is supplied,
    defaults to ``memory_logs/embedding_cache/recall`` (overridable via
    ``EMBED_CACHE_DIR``) so recall always benefits from the disk cache.

All I/O is injectable / offline-capable, so the pipeline is unit-tested without
Ollama or the network.
"""

import hashlib
import json
import logging
import math
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from .normalizer import NormalizedMessage

logger = logging.getLogger("jarvis.ingestion.embedder")

EMBEDDING_DIM = 768

# ── In-process LRU cache (H7.4) ──────────────────────────────────────────────
# Keyed by (backend, model, text) so vectors from different backends/models
# never collide even when the text is identical.
_PROC_CACHE_MAX = 256
_PROC_CACHE: "OrderedDict[tuple, list[float]]" = OrderedDict()
# BUG-12: embedding runs via asyncio.to_thread, so the module-global OrderedDict
# is touched concurrently from multiple threads. Guard every get/put/move/popitem
# under this lock — OrderedDict mutation is not thread-safe and a concurrent
# move_to_end/popitem can corrupt its internal linked list.
_PROC_CACHE_LOCK = threading.Lock()


def _proc_cache_get(key: tuple) -> Optional[list[float]]:
    with _PROC_CACHE_LOCK:
        if key in _PROC_CACHE:
            _PROC_CACHE.move_to_end(key)  # LRU: mark as recently used
            return _PROC_CACHE[key]
    return None


def _proc_cache_put(key: tuple, vec: list[float]) -> None:
    with _PROC_CACHE_LOCK:
        _PROC_CACHE[key] = vec
        _PROC_CACHE.move_to_end(key)
        while len(_PROC_CACHE) > _PROC_CACHE_MAX:
            _PROC_CACHE.popitem(last=False)  # evict LRU entry


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
                 cache_dir=None, *, base_url: str = None, http_client=None,
                 max_retries: int = 3, backoff_base: float = 0.5,
                 backoff_max: float = 8.0, max_workers: int = 1):
        self.backend = backend
        self.model = model
        self.base_url = base_url
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.max_workers = max(1, max_workers)
        self._client = None          # ollama module
        self._http_client = http_client  # injectable httpx-like client (lmstudio)
        self._setup()
        # Namespace the cache by the backend that actually produces vectors, so
        # ollama and hash embeddings are never mixed under one key.
        self.cache = (
            EmbeddingCache(cache_dir, namespace=f"{self.backend}:{self.model}")
            if cache_dir is not None else None
        )
        # Per-instance hit counter that includes both proc-cache and disk-cache
        # hits so that cache_stats["hits"] remains meaningful even when the
        # in-process LRU absorbs calls before they reach the disk layer.
        self._proc_hits = 0

    def _setup(self):
        if self.backend == "ollama":
            try:
                import ollama
                self._client = ollama
                logger.info(f"Embedder: Ollama/{self.model}")
            except ImportError:
                logger.warning("Ollama not installed, falling back to hash embeddings")
                self.backend = "hash"
        elif self.backend == "lmstudio":
            self.base_url = self.base_url or "http://localhost:1234"
            if self._http_client is None:
                try:
                    import httpx
                    self._http_client = httpx.Client(base_url=self.base_url, timeout=30.0)
                except ImportError:
                    logger.warning("httpx not installed, falling back to hash embeddings")
                    self.backend = "hash"
            logger.info(f"Embedder: LM Studio/{self.model} @ {self.base_url}")
        else:
            logger.info(f"Embedder: {self.backend}")

    @classmethod
    def from_env(cls, cache_dir=None):
        """Build an Embedder from EMBED_* env vars.

        Defaults to LM Studio's OpenAI-compatible ``/v1/embeddings`` endpoint
        (on-theme with the local-first stack); set EMBED_BACKEND=ollama to use a
        dedicated Ollama embedding model instead. Either degrades to the
        deterministic hash embedding if the backend is unreachable, so recall
        never hard-fails. Retries are kept short here because this runs on the
        interactive query path (unlike the bulk ingestion embedder).

        H7.4: when ``cache_dir`` is None, defaults to
        ``memory_logs/embedding_cache/recall`` (relative to the repo root).
        Override with the ``EMBED_CACHE_DIR`` env var."""
        backend = os.getenv("EMBED_BACKEND", "lmstudio")
        model = os.getenv(
            "EMBED_MODEL",
            "text-embedding-nomic-embed-text-v1.5" if backend == "lmstudio" else "nomic-embed-text",
        )
        base_url = os.getenv("EMBED_BASE_URL", "http://localhost:1234")
        if cache_dir is None:
            _repo_root = Path(__file__).resolve().parent.parent.parent.parent
            _default_cache = _repo_root / "memory_logs" / "embedding_cache" / "recall"
            cache_dir = os.getenv("EMBED_CACHE_DIR") or str(_default_cache)
        return cls(backend=backend, model=model, cache_dir=cache_dir,
                   base_url=base_url, max_retries=1, backoff_base=0.2, backoff_max=1.0)

    # ── public API ────────────────────────────────────────────────────────────

    def embed(self, text: str) -> list[float]:
        """Embed one text (in-process cache → disk cache → backend).

        H7.4: checks the bounded in-process LRU first (keyed by backend+model+text)
        before touching disk or the network backend.
        """
        if not text or not text.strip():
            return [0.0] * EMBEDDING_DIM
        proc_key = (self.backend, self.model, text)
        cached_proc = _proc_cache_get(proc_key)
        if cached_proc is not None:
            self._proc_hits += 1
            return cached_proc
        if self.cache is not None:
            cached_disk = self.cache.get(text)
            if cached_disk is not None:
                _proc_cache_put(proc_key, cached_disk)
                return cached_disk
        vec = self._embed_resilient(text)
        _proc_cache_put(proc_key, vec)
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
        """Return cache statistics.

        ``hits`` combines both proc-cache hits (in-process LRU) and disk-cache
        hits so that callers see the full picture regardless of which layer
        served the request.
        """
        if self.cache is None:
            return None
        stats = dict(self.cache.stats)
        total_hits = stats["hits"] + self._proc_hits
        total = total_hits + stats["misses"]
        stats["hits"] = total_hits
        stats["proc_hits"] = self._proc_hits
        stats["disk_hits"] = stats["hits"] - self._proc_hits
        stats["hit_rate"] = (total_hits / total) if total else 0.0
        return stats

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
        if self.backend == "lmstudio" and self._http_client:
            resp = self._http_client.post(
                "/v1/embeddings",
                json={"model": self.model, "input": text[:2048]},
            )
            resp.raise_for_status()
            data = resp.json()
            vec = (data.get("data") or [{}])[0].get("embedding")
            if not vec:
                raise ValueError("empty embedding from lm studio")
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
            # Deterministic hash→float for the fallback embedding (not security).
            hash_bytes = hashlib.md5(chunk, usedforsecurity=False).digest()
            vec[i] = (int.from_bytes(hash_bytes[:4], "big") / 2**32) * 2 - 1

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec
