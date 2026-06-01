"""Tests for real-embeddings recall wiring.

Covers:
  * Embedder LM Studio backend (OpenAI-compatible /v1/embeddings) with an
    injected client — no network.
  * Embedder degrading to the deterministic hash embedding when the backend
    raises (reliability guarantee).
  * MemoryManager.remember + recall round trip and embed() guards.
  * MemoryManager.add_turn auto-embedding when MEMORY_EMBED_TURNS is on.

All offline (hash backend / injected client, InMemoryVectorStore + InMemoryGraph).
"""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.ingestion.embedder import Embedder, EMBEDDING_DIM
from agents.core.memory.manager import MemoryManager


# ── Injected LM Studio client doubles ─────────────────────────────────────────

class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeLMStudioClient:
    """Mimics httpx.Client.post for /v1/embeddings."""

    def __init__(self, vector):
        self._vector = vector
        self.calls = []

    def post(self, url, json=None):
        self.calls.append((url, json))
        return _Resp({"data": [{"embedding": list(self._vector)}]})


class BoomClient:
    def post(self, url, json=None):
        raise RuntimeError("connection refused")


# ── Embedder: LM Studio backend ───────────────────────────────────────────────

def test_lmstudio_backend_uses_injected_client():
    vec = [0.1] * EMBEDDING_DIM
    client = FakeLMStudioClient(vec)
    emb = Embedder(backend="lmstudio", model="m", http_client=client)
    out = emb.embed("hello world")
    assert out == vec
    assert client.calls[0][0] == "/v1/embeddings"
    assert client.calls[0][1]["input"] == "hello world"
    assert client.calls[0][1]["model"] == "m"


def test_lmstudio_backend_degrades_to_hash_on_failure():
    emb = Embedder(backend="lmstudio", model="m", http_client=BoomClient(),
                   max_retries=0)
    out = emb.embed("resilient please")
    # Falls back to the deterministic hash embedding rather than raising.
    assert len(out) == EMBEDDING_DIM
    assert out == emb._embed_hash("resilient please")


def test_lmstudio_empty_embedding_falls_back():
    class EmptyClient:
        def post(self, url, json=None):
            return _Resp({"data": [{"embedding": []}]})

    emb = Embedder(backend="lmstudio", model="m", http_client=EmptyClient(),
                   max_retries=0)
    out = emb.embed("text")
    assert len(out) == EMBEDDING_DIM  # hash fallback


def test_from_env_defaults_to_lmstudio(monkeypatch):
    monkeypatch.delenv("EMBED_BACKEND", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    emb = Embedder.from_env()
    assert emb.backend == "lmstudio"
    assert emb.base_url == "http://localhost:1234"
    assert emb.max_retries == 1  # short retries on the interactive path


# ── MemoryManager: remember / recall round trip ───────────────────────────────

def _hash_manager() -> MemoryManager:
    mm = MemoryManager()
    mm._embedder = Embedder(backend="hash")  # deterministic, offline
    return mm


@pytest.mark.asyncio
async def test_remember_then_recall_round_trip():
    mm = _hash_manager()
    rid = await mm.remember("deadline for project X is June 15",
                            metadata={"kind": "fact"})
    assert rid is not None
    assert len(mm.vectors) == 1

    # Recall the same text → the stored vector should come back top-ranked.
    hits = await mm.recall("deadline for project X is June 15", top_k=5)
    assert hits, "expected at least one fused hit"
    assert hits[0].id == rid
    assert "vector" in hits[0].sources


@pytest.mark.asyncio
async def test_embed_returns_none_for_empty():
    mm = _hash_manager()
    assert await mm.embed("") is None
    assert await mm.embed("   ") is None


@pytest.mark.asyncio
async def test_remember_skips_on_dim_mismatch():
    mm = _hash_manager()

    class WrongDimEmbedder:
        def embed(self, text):
            return [0.0] * 16  # != store dimension (768)

    mm._embedder = WrongDimEmbedder()
    rid = await mm.remember("oops")
    assert rid is None
    assert len(mm.vectors) == 0


@pytest.mark.asyncio
async def test_add_turn_embeds_when_enabled():
    mm = _hash_manager()
    mm.embed_turns = True
    sid = await mm.new_session()
    await mm.add_turn(sid, "user", "remember that I like espresso")
    assert len(mm.vectors) == 1


@pytest.mark.asyncio
async def test_add_turn_no_embed_by_default():
    mm = _hash_manager()
    assert mm.embed_turns is False
    sid = await mm.new_session()
    await mm.add_turn(sid, "user", "this should not be embedded")
    assert len(mm.vectors) == 0
