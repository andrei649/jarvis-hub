"""Tests for Gemini context cache management."""
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core import settings_db
from core.llm import gemini_cache as gemini_cache_module
from core.llm.gemini_cache import ContextCache, GEMINI_API_BASE


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


def _clear_persisted_cache() -> None:
    settings_db.ensure_initialized()
    conn = settings_db.get_conn()
    try:
        conn.execute("DELETE FROM settings WHERE category='cache'")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def isolate_persisted_cache(monkeypatch):
    _clear_persisted_cache()
    yield
    _clear_persisted_cache()


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


@pytest.mark.parametrize("method_name", ["_load_persisted", "_save_persisted"])
def test_cache_db_connection_closes_when_access_fails(monkeypatch, method_name):
    class FailingConnection:
        def __init__(self):
            self.closed = False

        def execute(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

        def close(self):
            self.closed = True

    conn = FailingConnection()
    cache = ContextCache.__new__(ContextCache)
    cache._cache_map = {}
    monkeypatch.setattr(gemini_cache_module, "ensure_initialized", lambda: None)
    monkeypatch.setattr(gemini_cache_module, "get_conn", lambda: conn)

    getattr(cache, method_name)()

    assert conn.closed is True


def test_cache_init_no_network(tmp_path, monkeypatch):
    original_path = settings_db.DB_PATH
    original_initialized = settings_db._initialized
    original_wal_set = settings_db._wal_set

    with monkeypatch.context() as patch:
        patch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
        patch.setattr(settings_db, "_initialized", False)
        patch.setattr(settings_db, "_wal_set", False)

        cache = ContextCache(api_key="test")

        conn = settings_db.get_conn()
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
        ).fetchone()
        conn.close()
        assert cache.api_key == "test"
        assert cache._cache_map == {}
        assert table is not None

    assert original_path == settings_db.DB_PATH
    assert settings_db._initialized is original_initialized
    assert settings_db._wal_set is original_wal_set


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
