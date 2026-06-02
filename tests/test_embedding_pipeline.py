"""Tests for H5.17 — Batch & Cache Embeddings Pipeline.

Offline: uses the deterministic `hash` backend (no Ollama / network) and a
temp cache dir. Covers disk caching, persistence, batch alignment + de-dup,
rate-limit retry/backoff, and graceful degradation.
"""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.ingestion.embedder import Embedder, EmbeddingCache, EMBEDDING_DIM
from agents.core.ingestion.normalizer import NormalizedMessage


def _embedder(tmp_path, **kw):
    return Embedder(backend="hash", cache_dir=tmp_path, backoff_base=0.0, **kw)


# ── EmbeddingCache ────────────────────────────────────────────────────────────

def test_cache_hit_after_first_put(tmp_path):
    c = EmbeddingCache(tmp_path, namespace="hash:test")
    assert c.get("hello") is None        # miss
    c.put("hello", [0.1, 0.2, 0.3])
    assert c.get("hello") == [0.1, 0.2, 0.3]  # hit
    assert c.stats["hits"] == 1 and c.stats["misses"] == 1


def test_cache_namespacing_isolates_models(tmp_path):
    a = EmbeddingCache(tmp_path, namespace="ollama:nomic")
    b = EmbeddingCache(tmp_path, namespace="hash:hash")
    a.put("x", [1.0])
    assert b.get("x") is None            # different namespace → no collision


# ── Embedder caching + persistence ────────────────────────────────────────────

def test_embed_is_cached_and_stable(tmp_path):
    e = _embedder(tmp_path)
    v1 = e.embed("andrei works at raiffeisen")
    assert len(v1) == EMBEDDING_DIM
    v2 = e.embed("andrei works at raiffeisen")
    assert v1 == v2
    assert e.cache_stats["hits"] >= 1    # second call hit the cache


def test_cache_persists_across_embedder_instances(tmp_path):
    _embedder(tmp_path).embed("persist me")
    e2 = _embedder(tmp_path)             # fresh instance, same cache dir
    e2.embed("persist me")
    assert e2.cache_stats["hits"] == 1   # served from disk written by e1


# ── Batch: alignment + de-duplication ─────────────────────────────────────────

def test_embed_batch_aligned_and_dedup(tmp_path):
    e = _embedder(tmp_path)
    texts = ["a", "b", "a", "", "c"]
    out = e.embed_batch(texts)
    assert len(out) == len(texts)
    assert out[0] == out[2]                       # same text → same vector
    assert out[3] == [0.0] * EMBEDDING_DIM        # empty → zero vector
    assert all(len(v) == EMBEDDING_DIM for v in out)
    # "a","b","c" are 3 unique non-empty misses → 3 cache writes only
    assert e.cache_stats["writes"] == 3


def test_embed_many_sets_embeddings(tmp_path):
    e = _embedder(tmp_path)
    def _msg(text, ts):
        return NormalizedMessage(source="wa", conversation_id="c1", sender="andrei",
                                 is_me=True, text=text, timestamp=ts)
    msgs = [_msg("hi", 0.0), _msg("hi", 1.0)]
    e.embed_many(msgs)
    assert msgs[0].embedding == msgs[1].embedding         # identical text reused
    assert len(msgs[0].embedding) == EMBEDDING_DIM


def test_batch_parallel_matches_serial(tmp_path):
    texts = [f"msg-{i}" for i in range(10)]
    serial = _embedder(tmp_path / "s").embed_batch(texts)
    parallel = _embedder(tmp_path / "p", max_workers=4).embed_batch(texts)
    assert serial == parallel             # order preserved regardless of workers


# ── Rate-limit resilience ─────────────────────────────────────────────────────

def test_retry_succeeds_after_transient_failures(tmp_path):
    e = _embedder(tmp_path, max_retries=3)
    calls = {"n": 0}
    real_hash = e._embed_hash

    def flaky(text):
        calls["n"] += 1
        if calls["n"] < 3:               # fail twice, then succeed
            raise RuntimeError("429 rate limit")
        return real_hash(text)

    e._embed_primary = flaky
    vec = e.embed("retry me")
    assert len(vec) == EMBEDDING_DIM
    assert calls["n"] == 3               # 2 failures + 1 success


def test_exhausted_retries_degrade_to_hash(tmp_path):
    e = _embedder(tmp_path, max_retries=2)
    e._embed_primary = lambda text: (_ for _ in ()).throw(RuntimeError("always 429"))
    vec = e.embed("never works")
    # degrades to the deterministic hash embedding instead of crashing the ingest
    assert vec == e._embed_hash("never works")
