"""
embedder.py — Text embedding for Howard's ingestion pipeline.

Generates embeddings for chat messages using a local embedding model.
Supports multiple backends: Ollama (nomic-embed-text), or a simple
character-level fallback when no embedding model is available.
"""

import logging
import math
from pathlib import Path
from typing import Optional

from .normalizer import NormalizedMessage

logger = logging.getLogger("jarvis.ingestion.embedder")

EMBEDDING_DIM = 768


class Embedder:
    def __init__(self, backend: str = "ollama", model: str = "nomic-embed-text"):
        self.backend = backend
        self.model = model
        self._client = None
        self._setup()

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

    def embed(self, text: str) -> list[float]:
        if not text or not text.strip():
            return [0.0] * EMBEDDING_DIM

        if self.backend == "ollama" and self._client:
            return self._embed_ollama(text)

        return self._embed_hash(text)

    def embed_many(self, messages: list[NormalizedMessage]) -> list[NormalizedMessage]:
        for msg in messages:
            msg.embedding = self.embed(msg.text)
        return messages

    def _embed_ollama(self, text: str) -> list[float]:
        try:
            response = self._client.embeddings(model=self.model, prompt=text[:2048])
            return response.get("embedding", self._embed_hash(text))
        except Exception as e:
            logger.warning(f"Ollama embedding failed: {e}")
            return self._embed_hash(text)

    def _embed_hash(self, text: str) -> list[float]:
        import hashlib

        text_bytes = text.encode("utf-8")
        vec = [0.0] * EMBEDDING_DIM
        chunk_size = max(1, len(text_bytes) // EMBEDDING_DIM)

        for i in range(EMBEDDING_DIM):
            start = (i * chunk_size) % len(text_bytes)
            end = min(start + chunk_size, len(text_bytes))
            chunk = text_bytes[start:end] if end > start else text_bytes[start:start+1]
            hash_bytes = hashlib.md5(chunk).digest()
            vec[i] = (int.from_bytes(hash_bytes[:4], "big") / 2**32) * 2 - 1

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec
