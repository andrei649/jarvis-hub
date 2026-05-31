"""Tests for Gemini context cache management."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.gemini_cache import ContextCache, GEMINI_API_BASE
from core.settings_db import get_conn


def _mock_response(data: dict, status: int = 200):
    """Build a minimal mock httpx Response."""
    class _Resp:
        def __init__(self):
            self._data = data
            self.status_code = status
        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception(f"HTTP {self.status_code}")
        def json(self):
            return self._data
    return _Resp()


@pytest.mark.asyncio
async def test_cache_key_generation():
    key1 = ContextCache.cache_key("be helpful", "gemini-2.5-flash")
    key2 = ContextCache.cache_key("be helpful", "gemini-2.5-flash")
    key3 = ContextCache.cache_key("be nice", "gemini-2.5-flash")
    assert key1 == key2
    assert key1 != key3


@pytest.mark.asyncio
async def test_cache_key_includes_model():
    key1 = ContextCache.cache_key("be helpful", "gemini-2.5-flash")
    key2 = ContextCache.cache_key("be helpful", "gemini-2.5-pro")
    assert key1 != key2


def test_cache_init_no_network():
    conn = get_conn()
    conn.execute("DELETE FROM settings WHERE category='cache'")
    conn.commit()
    conn.close()
    cache = ContextCache(api_key="test")
    assert cache.api_key == "test"
    assert cache._cache_map == {}


@pytest.mark.asyncio
async def test_close():
    cache = ContextCache(api_key="test")
    await cache.close()


@pytest.mark.asyncio
async def test_create_cache_network_error(monkeypatch):
    async def mock_post(*a, **kw):
        raise Exception("connection refused")
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
    cache = ContextCache(api_key="test")
    result = await cache.create_or_extend(
        session_id="s1",
        system_instruction="be helpful",
        history=[{"role": "user", "parts": [{"text": "hello"}]}],
        model="gemini-2.5-flash",
    )
    assert result is None


@pytest.mark.asyncio
async def test_delete_cache_no_name(monkeypatch):
    async def mock_delete(*a, **kw):
        raise Exception("not found")
    monkeypatch.setattr("httpx.AsyncClient.delete", mock_delete)
    cache = ContextCache(api_key="test")
    result = await cache.delete("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_create_cache_success(monkeypatch):
    async def mock_post(*a, **kw):
        return _mock_response({"name": "cachedContents/abc123"})
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
    cache = ContextCache(api_key="test")
    result = await cache.create_or_extend(
        session_id="s1",
        system_instruction="be helpful",
        history=[{"role": "user", "parts": [{"text": "hello"}]}],
        model="gemini-2.5-flash",
    )
    assert result == "cachedContents/abc123"
    assert cache.get_cache_info("s1") is not None
    assert cache.get_cache_info("s1")["cache_name"] == "cachedContents/abc123"


@pytest.mark.asyncio
async def test_extend_cache_success(monkeypatch):
    async def mock_patch(*a, **kw):
        return _mock_response({})
    monkeypatch.setattr("httpx.AsyncClient.patch", mock_patch)
    cache = ContextCache(api_key="test")
    cache._cache_map["s1"] = {"cache_name": "cachedContents/abc123", "model": "gemini-2.5-flash"}
    result = await cache.create_or_extend(
        session_id="s1",
        system_instruction="be helpful",
        history=[],
        model="gemini-2.5-flash",
    )
    assert result == "cachedContents/abc123"


@pytest.mark.asyncio
async def test_extend_failure_falls_back_to_create(monkeypatch):
    calls = []
    async def mock_patch(*a, **kw):
        calls.append("patch")
        raise Exception("stale entry")
    async def mock_post(*a, **kw):
        calls.append("post")
        return _mock_response({"name": "cachedContents/def456"})
    monkeypatch.setattr("httpx.AsyncClient.patch", mock_patch)
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
    cache = ContextCache(api_key="test")
    cache._cache_map["s1"] = {"cache_name": "cachedContents/stale", "model": "gemini-2.5-flash"}
    result = await cache.create_or_extend(
        session_id="s1",
        system_instruction="be helpful",
        history=[{"role": "user", "parts": [{"text": "hello"}]}],
        model="gemini-2.5-flash",
    )
    assert result == "cachedContents/def456"
    assert calls == ["patch", "post"]
    assert cache.get_cache_info("s1")["cache_name"] == "cachedContents/def456"


@pytest.mark.asyncio
async def test_delete_cache_success(monkeypatch):
    async def mock_delete(*a, **kw):
        return _mock_response({})
    monkeypatch.setattr("httpx.AsyncClient.delete", mock_delete)
    cache = ContextCache(api_key="test")
    cache._cache_map["s1"] = {"cache_name": "cachedContents/abc123", "model": "gemini-2.5-flash"}
    result = await cache.delete("cachedContents/abc123")
    assert result is True
    assert cache.get_cache_info("s1") is None


@pytest.mark.asyncio
async def test_count_entries():
    cache = ContextCache(api_key="test")
    assert cache.count_entries() == 0
    cache._cache_map["s1"] = {"cache_name": "x"}
    assert cache.count_entries() == 1


@pytest.mark.asyncio
async def test_persistence_round_trip(monkeypatch):
    async def mock_post(*a, **kw):
        return _mock_response({"name": "cachedContents/persist"})
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
    cache = ContextCache(api_key="test")
    await cache.create_or_extend(
        session_id="s1",
        system_instruction="be helpful",
        history=[{"role": "user", "parts": [{"text": "hello"}]}],
        model="gemini-2.5-flash",
    )
    # Create a new instance and verify it loads the persisted data
    cache2 = ContextCache(api_key="test")
    info = cache2.get_cache_info("s1")
    assert info is not None
    assert info["cache_name"] == "cachedContents/persist"
    # Clean up
    conn = get_conn()
    conn.execute("DELETE FROM settings WHERE category='cache'")
    conn.commit()
    conn.close()
