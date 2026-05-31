"""Tests for Gemini context cache management."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.llm.gemini_cache import ContextCache


@pytest.mark.asyncio
async def test_cache_key_generation():
    cache = ContextCache(api_key="test")
    key1 = cache.cache_key("be helpful", "gemini-2.5-flash")
    key2 = cache.cache_key("be helpful", "gemini-2.5-flash")
    key3 = cache.cache_key("be nice", "gemini-2.5-flash")
    assert key1 == key2
    assert key1 != key3


@pytest.mark.asyncio
async def test_cache_key_includes_model():
    cache = ContextCache(api_key="test")
    key1 = cache.cache_key("be helpful", "gemini-2.5-flash")
    key2 = cache.cache_key("be helpful", "gemini-2.5-pro")
    assert key1 != key2


def test_cache_init_no_network():
    cache = ContextCache(api_key="test")
    assert cache.api_key == "test"
    assert cache._cache_map == {}


@pytest.mark.asyncio
async def test_close():
    cache = ContextCache(api_key="test")
    await cache.close()  # should not raise


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
async def test_delete_cache_no_name():
    cache = ContextCache(api_key="test")
    result = await cache.delete("nonexistent")
    assert result is False
