"""
gemini_cache.py — Gemini Context Caching via REST cachedContents API.
Manages creation, extension, and deletion of cached content for session history.
Cache mappings are persisted in the SQLite settings DB (category "cache")
via direct INSERT OR REPLACE to bypass put_category's update-only constraint.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, fields

import httpx

from ..settings_db import ensure_initialized, get_conn

from .auth_rotation import AuthLease, AuthProfilePool, is_rotatable_status
from .gemini_context import GeminiRequestBinding
from .provider_errors import log_provider_failure, provider_http_status

logger = logging.getLogger("jarvis.gemini.cache")

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_TTL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class CacheEntry:
    cache_name: str
    model: str
    system_digest: str
    prefix_count: int
    prefix_digest: str
    policy_fingerprint: str
    profile_id: str


def _digest_parts(parts: Sequence[str]) -> str:
    encoded = json.dumps(
        list(parts),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ContextCache:
    def __init__(
        self,
        auth_pool_provider: Callable[[], AuthProfilePool | None],
    ) -> None:
        self._auth_pool_provider = auth_pool_provider
        self._cache_map = self._load_map()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._client = httpx.AsyncClient(timeout=30.0)

    async def acquire_binding(
        self,
        *,
        session_id: str,
        model: str,
        system_instruction: str,
        history: Sequence[str],
        policy_fingerprint: str,
        lease: AuthLease,
    ) -> GeminiRequestBinding | None:
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            entry = self._entry_for(session_id)
            if entry is None or not self._entry_matches(
                entry,
                model=model,
                system_instruction=system_instruction,
                history=history,
                policy_fingerprint=policy_fingerprint,
                lease=lease,
            ):
                return None
            expected_name = entry.cache_name

            async def invalidate_cache() -> bool:
                return await self.invalidate(
                    session_id=session_id,
                    expected_cache_name=expected_name,
                )

            return GeminiRequestBinding(
                lease=lease,
                session_id=session_id,
                cache_name=entry.cache_name,
                cached_prefix_count=entry.prefix_count,
                invalidate_cache=invalidate_cache,
            )

    async def invalidate(
        self,
        *,
        session_id: str,
        expected_cache_name: str,
    ) -> bool:
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            entry = self._entry_for(session_id)
            if entry is None or entry.cache_name != expected_cache_name:
                return False
            del self._cache_map[session_id]
            self._save_map()
            return True

    def _entry_for(self, session_id: str) -> CacheEntry | None:
        raw = self._cache_map.get(session_id)
        if not isinstance(raw, dict):
            return None
        try:
            values = {field.name: raw[field.name] for field in fields(CacheEntry)}
        except (KeyError, TypeError, ValueError):
            return None
        if type(values["prefix_count"]) is not int:
            return None
        if any(
            not isinstance(value, str) for name, value in values.items() if name != "prefix_count"
        ):
            return None
        return CacheEntry(**values)

    def _entry_matches(
        self,
        entry: CacheEntry,
        *,
        model: str,
        system_instruction: str,
        history: Sequence[str],
        policy_fingerprint: str,
        lease: AuthLease,
    ) -> bool:
        if entry.prefix_count < 0 or entry.prefix_count > len(history):
            return False
        return (
            entry.model == model
            and entry.system_digest == _digest_parts((system_instruction,))
            and entry.prefix_digest == _digest_parts(history[: entry.prefix_count])
            and entry.policy_fingerprint == policy_fingerprint
            and entry.profile_id == lease.profile_id
        )

    def _load_map(self) -> dict[str, dict]:
        conn = None
        try:
            ensure_initialized()
            conn = get_conn()
            row = conn.execute(
                "SELECT value FROM settings WHERE category='cache' AND key='entries'"
            ).fetchone()
            if row:
                loaded = json.loads(row["value"])
                if isinstance(loaded, dict):
                    logger.info("Loaded %d cache entries from DB", len(loaded))
                    return loaded
        except Exception as exc:
            logger.warning(
                "Failed to load persisted Gemini cache entries (%s)",
                type(exc).__name__,
            )
        finally:
            if conn is not None:
                conn.close()
        return {}

    def _save_map(self) -> None:
        serialized = {
            session_id: asdict(entry)
            for session_id in tuple(self._cache_map)
            if isinstance(session_id, str) and (entry := self._entry_for(session_id)) is not None
        }
        conn = None
        try:
            ensure_initialized()
            conn = get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO settings "
                "(category, key, value, label, kind, opts) VALUES (?,?,?,?,?,?)",
                (
                    "cache",
                    "entries",
                    json.dumps(serialized, ensure_ascii=False, separators=(",", ":")),
                    "Cache entries",
                    "json",
                    "[]",
                ),
            )
            conn.commit()
        except Exception as exc:
            logger.warning(
                "Failed to persist cache map (%s)",
                type(exc).__name__,
            )
        finally:
            if conn is not None:
                conn.close()

    async def create_or_extend(
        self,
        *,
        session_id: str,
        system_instruction: str,
        history: Sequence[str],
        model: str,
        policy_fingerprint: str,
        lease: AuthLease,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> str | None:
        history_parts = tuple(history)
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            pool = self._auth_pool_provider()
            max_attempts = 1
            if pool is not None:
                max_attempts = max(1, min(pool.size, pool.healthy_count()))

            current_lease = lease
            attempted_profiles: set[str] = set()
            entry = self._entry_for(session_id)
            cache_name = (
                entry.cache_name
                if entry is not None
                and self._entry_matches(
                    entry,
                    model=model,
                    system_instruction=system_instruction,
                    history=history_parts,
                    policy_fingerprint=policy_fingerprint,
                    lease=current_lease,
                )
                else None
            )

            while len(attempted_profiles) < max_attempts:
                if current_lease.profile_id in attempted_profiles:
                    return None
                attempted_profiles.add(current_lease.profile_id)

                if cache_name is not None:
                    try:
                        await self._extend(
                            cache_name=cache_name,
                            ttl_seconds=ttl_seconds,
                            lease=current_lease,
                        )
                    except Exception as exc:
                        log_provider_failure(
                            logger,
                            provider="Gemini",
                            operation="cache extension",
                            exc=exc,
                        )
                        if self._is_rotatable_failure(exc):
                            next_lease = self._rotate_lease(
                                pool=pool,
                                failed_lease=current_lease,
                                attempted_profiles=attempted_profiles,
                            )
                            if next_lease is None:
                                return None
                            current_lease = next_lease
                            cache_name = None
                            continue
                        cache_name = None
                    else:
                        self._report_success(pool, current_lease)
                        return cache_name

                try:
                    created_name = await self._create(
                        system_instruction=system_instruction,
                        history=history_parts,
                        model=model,
                        ttl_seconds=ttl_seconds,
                        lease=current_lease,
                    )
                except Exception as exc:
                    log_provider_failure(
                        logger,
                        provider="Gemini",
                        operation="cache creation",
                        exc=exc,
                    )
                    if not self._is_rotatable_failure(exc):
                        return None
                    next_lease = self._rotate_lease(
                        pool=pool,
                        failed_lease=current_lease,
                        attempted_profiles=attempted_profiles,
                    )
                    if next_lease is None:
                        return None
                    current_lease = next_lease
                    cache_name = None
                    continue

                entry = CacheEntry(
                    cache_name=created_name,
                    model=model,
                    system_digest=_digest_parts((system_instruction,)),
                    prefix_count=len(history_parts),
                    prefix_digest=_digest_parts(history_parts),
                    policy_fingerprint=policy_fingerprint,
                    profile_id=current_lease.profile_id,
                )
                self._cache_map[session_id] = asdict(entry)
                self._save_map()
                self._report_success(pool, current_lease)
                logger.info("Gemini cache created")
                return created_name
            return None

    async def _create(
        self,
        *,
        system_instruction: str,
        history: Sequence[str],
        model: str,
        ttl_seconds: int,
        lease: AuthLease,
    ) -> str:
        url = f"{GEMINI_API_BASE}/cachedContents"
        payload = {
            "model": f"models/{model}",
            "contents": [{"role": "user", "parts": [{"text": part}]} for part in history],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "ttl": f"{ttl_seconds}s",
        }
        response = await self._client.post(
            url,
            headers={"x-goog-api-key": lease.api_key},
            json=payload,
        )
        response.raise_for_status()
        cache_name = response.json().get("name")
        if not isinstance(cache_name, str) or not cache_name:
            raise ValueError("Gemini cache response omitted its name")
        return cache_name

    async def _extend(
        self,
        *,
        cache_name: str,
        ttl_seconds: int,
        lease: AuthLease,
    ) -> None:
        response = await self._client.patch(
            f"{GEMINI_API_BASE}/{cache_name.lstrip('/')}",
            headers={"x-goog-api-key": lease.api_key},
            json={"ttl": f"{ttl_seconds}s"},
        )
        response.raise_for_status()

    async def delete(self, cache_name: str, *, lease: AuthLease) -> bool:
        url = f"{GEMINI_API_BASE}/{cache_name.lstrip('/')}"
        pool = self._auth_pool_provider()
        try:
            response = await self._client.delete(
                url,
                headers={"x-goog-api-key": lease.api_key},
            )
            response.raise_for_status()
        except Exception as exc:
            log_provider_failure(
                logger,
                provider="Gemini",
                operation="cache deletion",
                exc=exc,
            )
            if self._is_rotatable_failure(exc) and pool is not None:
                pool.report_failure(lease.profile_id)
            return False
        self._report_success(pool, lease)
        sessions = [
            session_id
            for session_id in tuple(self._cache_map)
            if (entry := self._entry_for(session_id)) is not None and entry.cache_name == cache_name
        ]
        for session_id in sessions:
            await self.invalidate(
                session_id=session_id,
                expected_cache_name=cache_name,
            )
        return True

    @staticmethod
    def _is_rotatable_failure(exc: BaseException) -> bool:
        status = provider_http_status(exc)
        return status is not None and is_rotatable_status(status)

    @staticmethod
    def _report_success(
        pool: AuthProfilePool | None,
        lease: AuthLease,
    ) -> None:
        if pool is not None:
            pool.report_success(lease.profile_id)

    @staticmethod
    def _rotate_lease(
        *,
        pool: AuthProfilePool | None,
        failed_lease: AuthLease,
        attempted_profiles: set[str],
    ) -> AuthLease | None:
        if pool is None:
            return None
        pool.report_failure(failed_lease.profile_id)
        for _ in range(pool.size):
            lease = pool.lease()
            if lease is not None and lease.profile_id not in attempted_profiles:
                return lease
            pool.rotate()
        return None

    async def close(self) -> None:
        await self._client.aclose()
