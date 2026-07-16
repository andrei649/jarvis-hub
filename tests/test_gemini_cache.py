"""Tests for Gemini context cache management."""
import asyncio
import hashlib
import json
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import httpx
import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core import settings_db
from core.llm.auth_rotation import AuthProfilePool
from core.llm import gemini_cache as gemini_cache_module
from core.llm.gemini_cache import ContextCache, GEMINI_API_BASE


class RecordingPool(AuthProfilePool):
    def __init__(self, keys):
        super().__init__(keys, provider="gemini")
        self.successes = []
        self.failures_reported = []

    def report_success(self, key=None):
        self.successes.append(key)
        super().report_success(key)

    def report_failure(self, key=None):
        self.failures_reported.append(key)
        return super().report_failure(key)


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


def _httpx_response(method: str, url: str, status: int, data=None):
    return httpx.Response(
        status,
        request=httpx.Request(method, url),
        json=data or {},
    )


def _digest_parts(parts) -> str:
    encoded = json.dumps(
        list(parts),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _persisted_entry(
    *,
    lease,
    cache_name="cachedContents/abc123",
    model="gemini-2.5-flash",
    system_instruction="be helpful",
    prefix=("turn one",),
    policy_fingerprint="policy-v1",
):
    return {
        "cache_name": cache_name,
        "model": model,
        "system_digest": _digest_parts((system_instruction,)),
        "prefix_count": len(prefix),
        "prefix_digest": _digest_parts(prefix),
        "policy_fingerprint": policy_fingerprint,
        "profile_fingerprint": hashlib.sha256(lease.api_key.encode("utf-8")).hexdigest(),
    }


@pytest.fixture(autouse=True)
def isolated_settings_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    settings_db.ensure_initialized()


@pytest.mark.asyncio
async def test_acquire_binding_hit_returns_recorded_boundary():
    pool = AuthProfilePool(["cache-secret"], provider="gemini")
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    cache._cache_map["s1"] = _persisted_entry(lease=lease)

    try:
        binding = await cache.acquire_binding(
            session_id="s1",
            model="gemini-2.5-flash",
            system_instruction="be helpful",
            history=("turn one", "turn two"),
            policy_fingerprint="policy-v1",
            lease=lease,
        )

        assert binding is not None
        assert binding.lease == lease
        assert binding.session_id == "s1"
        assert binding.cache_name == "cachedContents/abc123"
        assert binding.cached_prefix_count == 1
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_acquire_binding_miss_on_identity_change():
    pool = AuthProfilePool(["cache-secret"], provider="gemini")
    other_pool = AuthProfilePool(["other-secret"], provider="gemini")
    lease = pool.lease()
    other_lease = other_pool.lease()
    assert lease is not None
    assert other_lease is not None
    cache = ContextCache(lambda: pool)
    cache._cache_map["s1"] = _persisted_entry(lease=lease)
    variants = (
        {"model": "gemini-2.5-pro"},
        {"system_instruction": "be concise"},
        {"history": ("changed turn", "turn two")},
        {"history": ()},
        {"lease": other_lease},
    )

    try:
        for changes in variants:
            request = {
                "session_id": "s1",
                "model": "gemini-2.5-flash",
                "system_instruction": "be helpful",
                "history": ("turn one", "turn two"),
                "policy_fingerprint": "policy-v1",
                "lease": lease,
            }
            request.update(changes)
            assert await cache.acquire_binding(**request) is None
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_legacy_entry_is_miss():
    pool = AuthProfilePool(["cache-secret"], provider="gemini")
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    cache._cache_map["s1"] = {
        "cache_name": "cachedContents/legacy",
        "model": "gemini-2.5-flash",
        "contents_count": 1,
    }

    try:
        binding = await cache.acquire_binding(
            session_id="s1",
            model="gemini-2.5-flash",
            system_instruction="be helpful",
            history=("turn one",),
            policy_fingerprint="policy-v1",
            lease=lease,
        )
        assert binding is None
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_malformed_entry_is_miss():
    pool = AuthProfilePool(["cache-secret"], provider="gemini")
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    cache._cache_map["s1"] = {
        **_persisted_entry(lease=lease),
        "prefix_count": "1",
    }

    try:
        binding = await cache.acquire_binding(
            session_id="s1",
            model="gemini-2.5-flash",
            system_instruction="be helpful",
            history=("turn one",),
            policy_fingerprint="policy-v1",
            lease=lease,
        )
        assert binding is None
    finally:
        await cache.close()


@pytest.mark.parametrize(
    "current_policy",
    ("mode=enforce;scanner=v1", "mode=warn;scanner=v2"),
)
@pytest.mark.asyncio
async def test_policy_or_scanner_change_invalidates_mapping(current_policy):
    pool = AuthProfilePool(["cache-secret"], provider="gemini")
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    cache._cache_map["s1"] = _persisted_entry(
        lease=lease,
        policy_fingerprint="mode=warn;scanner=v1",
    )

    try:
        binding = await cache.acquire_binding(
            session_id="s1",
            model="gemini-2.5-flash",
            system_instruction="be helpful",
            history=("turn one",),
            policy_fingerprint=current_policy,
            lease=lease,
        )
        assert binding is None
    finally:
        await cache.close()


def test_cache_entry_is_frozen_and_slotted():
    entry = gemini_cache_module.CacheEntry(
        cache_name="cachedContents/abc123",
        model="gemini-2.5-flash",
        system_digest="system-digest",
        prefix_count=1,
        prefix_digest="prefix-digest",
        policy_fingerprint="policy-v1",
        profile_fingerprint="profile-digest",
    )

    assert not hasattr(entry, "__dict__")
    with pytest.raises(FrozenInstanceError):
        entry.model = "gemini-2.5-pro"


@pytest.mark.asyncio
async def test_persistence_omits_raw_history_and_api_key():
    pool = AuthProfilePool(["cache-secret"], provider="gemini")
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    expected = _persisted_entry(lease=lease)
    cache._cache_map["s1"] = {
        **expected,
        "raw_history": ["private turn"],
        "api_key": lease.api_key,
        "profile_id": lease.profile_id,
    }

    try:
        cache._save_map()
        conn = settings_db.get_conn()
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE category='cache' AND key='entries'"
            ).fetchone()
        finally:
            conn.close()

        assert row is not None
        raw_value = row["value"]
        assert json.loads(raw_value) == {"s1": expected}
        assert "private turn" not in raw_value
        assert lease.api_key not in raw_value
        assert lease.profile_id not in raw_value
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_compare_and_delete_preserves_newer_mapping():
    pool = AuthProfilePool(["cache-secret"], provider="gemini")
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    cache._cache_map["s1"] = _persisted_entry(
        lease=lease,
        cache_name="cachedContents/old",
    )

    try:
        binding = await cache.acquire_binding(
            session_id="s1",
            model="gemini-2.5-flash",
            system_instruction="be helpful",
            history=("turn one",),
            policy_fingerprint="policy-v1",
            lease=lease,
        )
        assert binding is not None
        assert binding.invalidate_cache is not None
        cache._cache_map["s1"] = _persisted_entry(
            lease=lease,
            cache_name="cachedContents/new",
        )

        removed = await binding.invalidate_cache()

        assert removed is False
        assert cache._entry_for("s1") is not None
        assert cache._entry_for("s1").cache_name == "cachedContents/new"
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_invalidate_removes_only_expected_mapping():
    pool = AuthProfilePool(["cache-secret"], provider="gemini")
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    cache._cache_map["s1"] = _persisted_entry(
        lease=lease,
        cache_name="cachedContents/expected",
    )
    cache._save_map()

    try:
        removed = await cache.invalidate(
            session_id="s1",
            expected_cache_name="cachedContents/expected",
        )

        assert removed is True
        assert cache._entry_for("s1") is None
        reloaded = ContextCache(lambda: pool)
        try:
            assert reloaded._entry_for("s1") is None
        finally:
            await reloaded.close()
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_same_session_create_is_serialized(monkeypatch):
    pool = AuthProfilePool(["cache-secret"], provider="gemini")
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    calls = []
    active = 0
    max_active = 0

    async def enter_network(method):
        nonlocal active, max_active
        calls.append(method)
        active += 1
        max_active = max(max_active, active)
        if method == "post":
            first_entered.set()
            await release_first.wait()
        active -= 1

    async def mock_post(*args, **kwargs):
        await enter_network("post")
        return _mock_response({"name": "cachedContents/serialized"})

    async def mock_patch(*args, **kwargs):
        await enter_network("patch")
        return _mock_response({})

    monkeypatch.setattr(cache._client, "post", mock_post)
    monkeypatch.setattr(cache._client, "patch", mock_patch)
    request = {
        "session_id": "s1",
        "system_instruction": "be helpful",
        "history": ("turn one",),
        "model": "gemini-2.5-flash",
        "policy_fingerprint": "policy-v1",
        "lease": lease,
    }

    try:
        first = asyncio.create_task(cache.create_or_extend(**request))
        await first_entered.wait()
        second = asyncio.create_task(cache.create_or_extend(**request))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert calls == ["post"]

        release_first.set()
        assert await asyncio.gather(first, second) == [
            "cachedContents/serialized",
            "cachedContents/serialized",
        ]
        assert calls == ["post", "patch"]
        assert max_active == 1
    finally:
        release_first.set()
        await cache.close()


@pytest.mark.asyncio
async def test_different_sessions_can_create_concurrently(monkeypatch):
    pool = AuthProfilePool(["cache-secret"], provider="gemini")
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    both_entered = asyncio.Event()
    release = asyncio.Event()
    entered = 0
    max_active = 0

    async def mock_post(url, *, headers, json):
        nonlocal entered, max_active
        entered += 1
        max_active = max(max_active, entered)
        if entered == 2:
            both_entered.set()
        await release.wait()
        entered -= 1
        cache_suffix = json["contents"][0]["parts"][0]["text"]
        return _mock_response({"name": f"cachedContents/{cache_suffix}"})

    monkeypatch.setattr(cache._client, "post", mock_post)

    async def create(session_id, turn):
        return await cache.create_or_extend(
            session_id=session_id,
            system_instruction="be helpful",
            history=(turn,),
            model="gemini-2.5-flash",
            policy_fingerprint="policy-v1",
            lease=lease,
        )

    try:
        first = asyncio.create_task(create("s1", "one"))
        second = asyncio.create_task(create("s2", "two"))
        await asyncio.wait_for(both_entered.wait(), timeout=1.0)
        assert max_active == 2
        release.set()
        assert set(await asyncio.gather(first, second)) == {
            "cachedContents/one",
            "cachedContents/two",
        }
    finally:
        release.set()
        await cache.close()


@pytest.mark.parametrize("method_name", ["_load_map", "_save_map"])
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


@pytest.mark.asyncio
async def test_cache_init_and_close_without_network():
    cache = ContextCache(lambda: None)
    assert cache._cache_map == {}
    await cache.close()


@pytest.mark.asyncio
async def test_create_uses_header_auth_and_persists_exact_identity(monkeypatch):
    pool = RecordingPool(["cache-secret"])
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    request = {}

    async def mock_post(url, *, headers, json):
        request.update(url=url, headers=headers, payload=json)
        return _mock_response({"name": "cachedContents/persist"})

    monkeypatch.setattr(cache._client, "post", mock_post)
    try:
        result = await cache.create_or_extend(
            session_id="s1",
            system_instruction="be helpful",
            history=("private one", "private two"),
            model="gemini-2.5-flash",
            policy_fingerprint="policy-v1",
            lease=lease,
        )

        assert result == "cachedContents/persist"
        assert request["url"] == f"{GEMINI_API_BASE}/cachedContents"
        assert "cache-secret" not in request["url"]
        assert request["headers"] == {"x-goog-api-key": "cache-secret"}
        assert request["payload"]["contents"] == [
            {"role": "user", "parts": [{"text": "private one"}]},
            {"role": "user", "parts": [{"text": "private two"}]},
        ]
        assert pool.successes == [lease.profile_id]
        assert set(cache._cache_map["s1"]) == {
            "cache_name",
            "model",
            "system_digest",
            "prefix_count",
            "prefix_digest",
            "policy_fingerprint",
            "profile_fingerprint",
        }

        reloaded = ContextCache(lambda: pool)
        try:
            binding = await reloaded.acquire_binding(
                session_id="s1",
                model="gemini-2.5-flash",
                system_instruction="be helpful",
                history=("private one", "private two", "uncached tail"),
                policy_fingerprint="policy-v1",
                lease=lease,
            )
            assert binding is not None
            assert binding.cached_prefix_count == 2
        finally:
            await reloaded.close()
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_rotatable_create_attempts_each_healthy_lease_once(monkeypatch):
    pool = RecordingPool(["key-one", "key-two", "key-three"])
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    attempts = []

    async def mock_post(url, *, headers, json):
        attempts.append((url, headers["x-goog-api-key"]))
        if len(attempts) < 3:
            return _httpx_response("POST", url, 429)
        return _mock_response({"name": "cachedContents/third"})

    monkeypatch.setattr(cache._client, "post", mock_post)
    try:
        result = await cache.create_or_extend(
            session_id="s1",
            system_instruction="be helpful",
            history=("turn one",),
            model="gemini-2.5-flash",
            policy_fingerprint="policy-v1",
            lease=lease,
        )

        assert result == "cachedContents/third"
        assert [key for _, key in attempts] == ["key-one", "key-two", "key-three"]
        assert all("key=" not in url and key not in url for url, key in attempts)
        assert pool.failures_reported == ["gemini-1", "gemini-2"]
        assert pool.successes == ["gemini-3"]
        assert cache._entry_for("s1").profile_fingerprint == hashlib.sha256(
            b"key-three"
        ).hexdigest()
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_rotated_lease_never_carries_cache_name(monkeypatch):
    pool = RecordingPool(["key-one", "key-two"])
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    cache._cache_map["s1"] = _persisted_entry(
        lease=lease,
        cache_name="cachedContents/old",
    )
    calls = []

    async def mock_patch(url, *, headers, json):
        calls.append(("patch", url, headers["x-goog-api-key"]))
        return _httpx_response("PATCH", url, 429)

    async def mock_post(url, *, headers, json):
        calls.append(("post", url, headers["x-goog-api-key"]))
        return _mock_response({"name": "cachedContents/new"})

    monkeypatch.setattr(cache._client, "patch", mock_patch)
    monkeypatch.setattr(cache._client, "post", mock_post)
    try:
        result = await cache.create_or_extend(
            session_id="s1",
            system_instruction="be helpful",
            history=("turn one",),
            model="gemini-2.5-flash",
            policy_fingerprint="policy-v1",
            lease=lease,
        )

        assert result == "cachedContents/new"
        assert calls == [
            (
                "patch",
                f"{GEMINI_API_BASE}/cachedContents/old",
                "key-one",
            ),
            ("post", f"{GEMINI_API_BASE}/cachedContents", "key-two"),
        ]
        assert pool.failures_reported == ["gemini-1"]
        assert pool.successes == ["gemini-2"]
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_non_rotatable_extend_failure_recreates_on_same_lease(monkeypatch):
    pool = RecordingPool(["cache-secret"])
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    cache._cache_map["s1"] = _persisted_entry(
        lease=lease,
        cache_name="cachedContents/stale",
    )
    calls = []

    async def mock_patch(url, *, headers, json):
        calls.append(("patch", headers["x-goog-api-key"]))
        return _httpx_response("PATCH", url, 404)

    async def mock_post(url, *, headers, json):
        calls.append(("post", headers["x-goog-api-key"]))
        return _mock_response({"name": "cachedContents/recreated"})

    monkeypatch.setattr(cache._client, "patch", mock_patch)
    monkeypatch.setattr(cache._client, "post", mock_post)
    try:
        result = await cache.create_or_extend(
            session_id="s1",
            system_instruction="be helpful",
            history=("turn one",),
            model="gemini-2.5-flash",
            policy_fingerprint="policy-v1",
            lease=lease,
        )
        assert result == "cachedContents/recreated"
        assert calls == [("patch", "cache-secret"), ("post", "cache-secret")]
        assert pool.failures_reported == []
        assert pool.successes == [lease.profile_id]
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_create_failure_is_secret_safe_and_does_not_persist(
    monkeypatch,
    caplog,
):
    pool = RecordingPool(["cache-secret"])
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)

    async def mock_post(url, *, headers, json):
        return _httpx_response("POST", url, 500, {"error": "private turn"})

    monkeypatch.setattr(cache._client, "post", mock_post)
    try:
        with caplog.at_level("WARNING", logger="jarvis.gemini.cache"):
            result = await cache.create_or_extend(
                session_id="s1",
                system_instruction="be helpful",
                history=("private turn",),
                model="gemini-2.5-flash",
                policy_fingerprint="policy-v1",
                lease=lease,
            )
        assert result is None
        assert cache._entry_for("s1") is None
        assert "cache-secret" not in caplog.text
        assert "private turn" not in caplog.text
        assert pool.successes == []
        assert pool.failures_reported == []
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_delete_uses_header_auth_and_compare_deletes_mapping(monkeypatch):
    pool = RecordingPool(["cache-secret"])
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    cache._cache_map["s1"] = _persisted_entry(
        lease=lease,
        cache_name="cachedContents/delete-me",
    )
    request = {}

    async def mock_delete(url, *, headers):
        request.update(url=url, headers=headers)
        return _mock_response({})

    monkeypatch.setattr(cache._client, "delete", mock_delete)
    try:
        deleted = await cache.delete("cachedContents/delete-me", lease=lease)
        assert deleted is True
        assert request == {
            "url": f"{GEMINI_API_BASE}/cachedContents/delete-me",
            "headers": {"x-goog-api-key": "cache-secret"},
        }
        assert cache._entry_for("s1") is None
        assert pool.successes == [lease.profile_id]
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_delete_failure_reports_exact_profile_without_secret_log(
    monkeypatch,
    caplog,
):
    pool = RecordingPool(["cache-secret", "other-secret"])
    lease = pool.lease()
    assert lease is not None
    cache = ContextCache(lambda: pool)
    cache._cache_map["s1"] = _persisted_entry(
        lease=lease,
        cache_name="cachedContents/keep-me",
    )

    async def mock_delete(url, *, headers):
        return _httpx_response("DELETE", url, 429)

    monkeypatch.setattr(cache._client, "delete", mock_delete)
    try:
        with caplog.at_level("WARNING", logger="jarvis.gemini.cache"):
            deleted = await cache.delete("cachedContents/keep-me", lease=lease)
        assert deleted is False
        assert cache._entry_for("s1") is not None
        assert pool.failures_reported == [lease.profile_id]
        assert "cache-secret" not in caplog.text
        assert "cachedContents/keep-me" not in caplog.text
    finally:
        await cache.close()
