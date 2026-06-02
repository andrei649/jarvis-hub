"""Tests for H7.4 — Query-embedding cache + fast-fail for recall.

Covers:
  1. Same text embedded twice calls the backend only ONCE (in-process LRU hit).
  2. Fresh Embedder instance with the same tmp cache_dir reads from disk and
     does NOT call the backend (disk cache hit, process-equivalent isolation).
  3. Embedder.from_env(cache_dir=None) with EMBED_CACHE_DIR set yields an
     embedder whose cache is non-None and rooted at the given dir.
  4. Different backend/model namespaces do not collide in the in-process cache
     (hash vs lmstudio produce different vectors for the same text).

All offline — uses injected fake LM Studio client (no network).
"""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.ingestion.embedder import (
    Embedder,
    EMBEDDING_DIM,
    _PROC_CACHE,
)


# ── Fake LM Studio client (mirrors FakeLMStudioClient in test_memory_embeddings) ──

class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeLMStudioClient:
    """Mimics httpx.Client.post for /v1/embeddings; counts calls."""

    def __init__(self, vector):
        self._vector = vector
        self.calls = 0

    def post(self, url, json=None):
        self.calls += 1
        return _Resp({"data": [{"embedding": list(self._vector)}]})


# ── helpers ───────────────────────────────────────────────────────────────────

def _lmstudio_embedder(client, tmp_path=None, model="test-model"):
    """Build an lmstudio Embedder with an injected client and no retries."""
    return Embedder(
        backend="lmstudio",
        model=model,
        cache_dir=str(tmp_path) if tmp_path is not None else None,
        http_client=client,
        max_retries=0,
        backoff_base=0.0,
    )


def _clear_proc_cache():
    """Clear the module-level in-process LRU between tests."""
    _PROC_CACHE.clear()


# ── Test 1: in-process LRU — same text, same embedder, backend called once ────

def test_same_text_twice_hits_proc_cache(tmp_path):
    """Embedding the same text twice on a single Embedder instance calls the
    backend only once; the second call is served from the in-process LRU."""
    _clear_proc_cache()
    vec = [0.5] * EMBEDDING_DIM
    client = FakeLMStudioClient(vec)
    emb = _lmstudio_embedder(client, tmp_path)

    v1 = emb.embed("the quick brown fox")
    v2 = emb.embed("the quick brown fox")

    assert v1 == v2 == vec
    assert client.calls == 1, (
        f"Expected 1 backend call but got {client.calls}; "
        "second call should have been served from in-process cache"
    )


# ── Test 2: disk cache — fresh instance reads from disk, no backend call ──────

def test_disk_cache_hit_on_fresh_instance(tmp_path):
    """A fresh Embedder pointed at the same cache_dir should serve the
    embedding from disk without touching the backend."""
    _clear_proc_cache()
    vec = [0.3] * EMBEDDING_DIM
    text = "persistent embedding test"

    # First instance: computes and caches to disk.
    client1 = FakeLMStudioClient(vec)
    emb1 = _lmstudio_embedder(client1, tmp_path)
    emb1.embed(text)
    assert client1.calls == 1

    # Clear the in-process cache to simulate a fresh process.
    _clear_proc_cache()

    # Second instance (same cache dir): should hit the disk cache.
    client2 = FakeLMStudioClient(vec)
    emb2 = _lmstudio_embedder(client2, tmp_path)
    v2 = emb2.embed(text)

    assert v2 == vec
    assert client2.calls == 0, (
        f"Expected 0 backend calls (disk hit) but got {client2.calls}"
    )
    assert emb2.cache_stats["hits"] == 1


# ── Test 3: from_env respects EMBED_CACHE_DIR env var ─────────────────────────

def test_from_env_uses_embed_cache_dir_env(tmp_path, monkeypatch):
    """Embedder.from_env(cache_dir=None) with EMBED_CACHE_DIR set must produce
    an embedder whose cache is non-None and rooted at that directory."""
    custom_dir = str(tmp_path / "my_embed_cache")
    monkeypatch.setenv("EMBED_CACHE_DIR", custom_dir)
    monkeypatch.setenv("EMBED_BACKEND", "hash")  # avoid real network

    emb = Embedder.from_env(cache_dir=None)

    assert emb.cache is not None, "cache must be non-None when EMBED_CACHE_DIR is set"
    assert str(emb.cache.dir).startswith(custom_dir), (
        f"cache dir {emb.cache.dir!r} not rooted at {custom_dir!r}"
    )


def test_from_env_default_cache_dir_is_non_none(monkeypatch):
    """Embedder.from_env() without EMBED_CACHE_DIR must still produce a
    non-None cache (defaults to memory_logs/embedding_cache/recall)."""
    monkeypatch.delenv("EMBED_CACHE_DIR", raising=False)
    monkeypatch.setenv("EMBED_BACKEND", "hash")  # avoid real network

    emb = Embedder.from_env(cache_dir=None)

    assert emb.cache is not None, (
        "from_env must provide a default cache_dir so recall is always cached"
    )
    # Sanity: the default path contains 'recall'
    assert "recall" in str(emb.cache.dir).lower()


# ── Test 4: backend/model namespace isolation in in-process cache ─────────────

def test_different_backends_do_not_collide_in_proc_cache():
    """hash and lmstudio backends keyed by the same text must return different
    vectors and must not collide in the in-process LRU."""
    _clear_proc_cache()
    text = "namespace collision test"

    # Hash embedder (deterministic, no network).
    hash_emb = Embedder(backend="hash", model="hash", max_retries=0)
    hash_vec = hash_emb.embed(text)

    # LM Studio embedder with a distinct fake vector.
    lm_vec = [0.99] * EMBEDDING_DIM
    client = FakeLMStudioClient(lm_vec)
    lm_emb = _lmstudio_embedder(client, model="test-model")
    lm_out = lm_emb.embed(text)

    assert hash_vec != lm_vec, "hash and lmstudio must produce different vectors"
    assert lm_out == lm_vec, "lmstudio embedder returned wrong vector"

    # Re-embed with hash: must still get hash vector, not the lmstudio one.
    _clear_proc_cache()  # force a fresh proc-cache lookup
    hash_vec2 = Embedder(backend="hash", model="hash", max_retries=0).embed(text)
    assert hash_vec2 == hash_vec, "hash embedding must be deterministic and namespace-isolated"


def test_different_models_do_not_collide_in_proc_cache():
    """Two lmstudio embedders with different model names and different fake
    vectors must not return each other's vectors from the in-process cache."""
    _clear_proc_cache()
    text = "model namespace test"

    vec_a = [0.1] * EMBEDDING_DIM
    vec_b = [0.9] * EMBEDDING_DIM

    client_a = FakeLMStudioClient(vec_a)
    emb_a = Embedder(backend="lmstudio", model="model-A",
                     http_client=client_a, max_retries=0)

    client_b = FakeLMStudioClient(vec_b)
    emb_b = Embedder(backend="lmstudio", model="model-B",
                     http_client=client_b, max_retries=0)

    out_a = emb_a.embed(text)
    out_b = emb_b.embed(text)

    assert out_a == vec_a
    assert out_b == vec_b
    assert out_a != out_b, "different model keys must not share a proc-cache entry"
