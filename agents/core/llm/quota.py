"""H373 — see how much provider quota is left, and never hammer a provider that said stop.

Nerva learned about a provider's rate limit only from a failed request: a 429 benched the key in
one process's memory, and nothing showed how close the next one was. Hermes reads the quota
headers off every response and shares a 429 across processes; so does Nerva:

- **Captured on every response.** A response hook on every cloud backend's HTTP client
  (:func:`response_hook`, hung by ``llm_async_client``) reads the provider's own quota headers
  — OpenAI-style ``x-ratelimit-{limit,remaining,reset}-{requests,tokens}``, Anthropic's
  ``anthropic-ratelimit-{requests,tokens,input-tokens,output-tokens}-{limit,remaining,reset}``
  and ``retry-after`` — and stores the latest numbers per backend and key.
- **Shared across processes.** The numbers and every 429 live in one SQLite file under the
  data folder, so the hub, the CLI, the scheduler and any worker see the same state. A 429
  blocks that backend and key until its ``retry-after`` (else :data:`DEFAULT_BLOCK_SECONDS`,
  never more than :data:`MAX_BLOCK_SECONDS`); every process's request hook
  (:func:`request_hook`) refuses a request to a blocked backend and key before it is sent
  (:class:`ProviderRateLimited`), so one 429 is not multiplied by retries elsewhere. Another
  key in the pool is not blocked.
- **Shown.** :func:`usage` gives each backend's requests/tokens left, their reset times and any
  block, for ``GET /api/llm/quota``, the HUD Provider Quota panel and ``/usage``.

Only cloud hosts are tracked (a local model has no quota), a key is identified by a short
fingerprint of its hash, never the key, and every failure here is swallowed: a quota reader
never breaks a request.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("jarvis.llm.quota")

DEFAULT_BLOCK_SECONDS = 30.0
MAX_BLOCK_SECONDS = 900.0
KEY_HEADERS = ("x-api-key", "authorization", "x-goog-api-key", "api-key")
KINDS = ("requests", "tokens", "input-tokens", "output-tokens")

_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")


class ProviderRateLimited(httpx.RequestError):
    """A request to a backend and key that a provider rate-limited was refused before sending."""


def key_fingerprint(request: httpx.Request) -> str:
    """A short fingerprint of the credential a request carries ("" when it carries none)."""
    for name in KEY_HEADERS:
        value = request.headers.get(name)
        if value:
            return hashlib.sha256(value.encode()).hexdigest()[:12]
    value = request.url.params.get("key")
    return hashlib.sha256(value.encode()).hexdigest()[:12] if value else ""


def parse_duration(text: str) -> float | None:
    """``"6m0s"``, ``"1.5s"``, ``"20ms"`` or a plain number of seconds, as seconds."""
    text = str(text or "").strip().lower()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    parts = _DURATION_RE.findall(text)
    if not parts or "".join(n + u for n, u in parts) != text:
        return None
    scale = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    return sum(float(n) * scale[u] for n, u in parts)


def _reset_at(value: str, now: float) -> float | None:
    """A reset given as a duration (OpenAI) or an RFC 3339 time (Anthropic), as an epoch."""
    seconds = parse_duration(value)
    if seconds is not None:
        return now + seconds
    try:
        return datetime.fromisoformat(str(value).strip()).timestamp()   # "Z" is read since 3.11
    except ValueError:
        return None


def retry_after(headers: Any, now: float | None = None) -> float | None:
    """Seconds from ``retry-after`` (a number or an HTTP date), ``None`` when absent or unreadable."""
    now = time.time() if now is None else now
    value = headers.get("retry-after") if headers is not None else None
    if not value:
        return None
    seconds = parse_duration(value)
    if seconds is not None:
        return seconds
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, when.timestamp() - now)


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_headers(headers: Any, now: float | None = None) -> dict:
    """The quota a response reports: ``{kind: {limit, remaining, reset_at}}``, plus
    ``retry_after``; empty when the response carries none."""
    now = time.time() if now is None else now
    out: dict = {}
    for kind in KINDS:
        entry = {}
        for field in ("limit", "remaining", "reset"):
            raw = headers.get(f"anthropic-ratelimit-{kind}-{field}") or headers.get(f"x-ratelimit-{field}-{kind}")
            if raw is None:
                continue
            if field == "reset":
                at = _reset_at(raw, now)
                if at is not None:
                    entry["reset_at"] = at
            else:
                number = _int(raw)
                if number is not None:
                    entry[field] = number
        if entry:
            out[kind] = entry
    wait = retry_after(headers, now)
    if wait is not None:
        out["retry_after"] = wait
    return out


class QuotaStore:
    """The shared quota state: the latest numbers per backend and key, and the 429 blocks."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            from agents.core.paths import data_path
            path = data_path("provider_quota.db")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS quota (backend TEXT NOT NULL, key_fp TEXT NOT NULL,"
                         " observed_at REAL NOT NULL, data TEXT NOT NULL, PRIMARY KEY (backend, key_fp))")
            conn.execute("CREATE TABLE IF NOT EXISTS blocks (backend TEXT NOT NULL, key_fp TEXT NOT NULL,"
                         " until REAL NOT NULL, status INTEGER NOT NULL, at REAL NOT NULL,"
                         " PRIMARY KEY (backend, key_fp))")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=2.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        return _Closing(conn)

    def record(self, backend: str, key_fp: str, data: dict, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock, self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO quota (backend, key_fp, observed_at, data) VALUES (?, ?, ?, ?)",
                         (backend, key_fp, now, json.dumps(data, sort_keys=True)))

    def block(self, backend: str, key_fp: str, seconds: float | None, status: int = 429,
              now: float | None = None) -> float:
        """Block ``backend``/``key_fp`` for ``seconds`` (the default when unknown); the end time."""
        now = time.time() if now is None else now
        wait = DEFAULT_BLOCK_SECONDS if seconds is None else seconds
        until = now + min(MAX_BLOCK_SECONDS, max(0.0, float(wait)))
        with self._lock, self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO blocks (backend, key_fp, until, status, at) VALUES (?, ?, ?, ?, ?)",
                         (backend, key_fp, until, int(status), now))
        return until

    def blocked_until(self, backend: str, key_fp: str, now: float | None = None) -> float | None:
        now = time.time() if now is None else now
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT until FROM blocks WHERE backend=? AND key_fp=?", (backend, key_fp)).fetchone()
        return row[0] if row and row[0] > now else None

    def snapshot(self, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT backend, key_fp, observed_at, data FROM quota ORDER BY backend, key_fp").fetchall()
            blocks = {(b, k): (u, s) for b, k, u, s in conn.execute(
                "SELECT backend, key_fp, until, status FROM blocks WHERE until > ?", (now,)).fetchall()}
        out = []
        seen = set()
        for backend, key_fp, observed_at, data in rows:
            seen.add((backend, key_fp))
            out.append(_entry(backend, key_fp, observed_at, _load(data), blocks.get((backend, key_fp)), now))
        for (backend, key_fp), block in sorted(blocks.items()):
            if (backend, key_fp) not in seen:
                out.append(_entry(backend, key_fp, None, {}, block, now))
        return out


class _Closing:
    """``with`` closes the connection (sqlite3's own context manager only commits)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, *exc) -> None:
        self._conn.close()


def _load(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _entry(backend, key_fp, observed_at, data, block, now) -> dict:
    kinds = {}
    for kind in KINDS:
        entry = data.get(kind)
        if not isinstance(entry, dict):
            continue
        limit, remaining = entry.get("limit"), entry.get("remaining")
        fraction = (remaining / limit) if isinstance(limit, int) and limit > 0 and isinstance(remaining, int) else None
        reset_at = entry.get("reset_at")
        kinds[kind] = {"limit": limit, "remaining": remaining,
                       "left": None if fraction is None else round(max(0.0, min(1.0, fraction)), 4),
                       "resets_in": None if not isinstance(reset_at, (int, float)) else round(max(0.0, reset_at - now), 1)}
    return {
        "backend": backend, "key": key_fp, "observed_at": observed_at, "quota": kinds,
        "blocked": block is not None,
        "blocked_for": None if block is None else round(max(0.0, block[0] - now), 1),
        "block_status": None if block is None else block[1],
    }


_store: QuotaStore | None = None
_store_lock = threading.Lock()


def get_store() -> QuotaStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = QuotaStore()
        return _store


def set_store(store: QuotaStore | None) -> None:
    global _store
    with _store_lock:
        _store = store


def _cloud(request: httpx.Request) -> bool:
    from agents.core.http_client import host_is_local

    return not host_is_local((request.url.host or "").lower().rstrip("."))


def request_hook(backend: str):
    """Refuse a request to a backend and key a provider rate-limited, before it is sent."""

    async def _hook(request: httpx.Request) -> None:
        try:
            if not _cloud(request):
                return
            until = get_store().blocked_until(backend, key_fingerprint(request))
        except Exception:
            logger.debug("quota guard unavailable", exc_info=True)
            return
        if until is not None:
            raise ProviderRateLimited(
                f"{backend} is rate-limited for {max(0.0, until - time.time()):.0f}s more (shared 429 guard)",
                request=request)

    return _hook


def response_hook(backend: str):
    """Record the quota a cloud response reports, and share a 429 with every process."""

    async def _hook(response: httpx.Response) -> None:
        try:
            request = response.request
            if not _cloud(request):
                return
            key_fp = key_fingerprint(request)
            data = parse_headers(response.headers)
            store = get_store()
            if data:
                store.record(backend, key_fp, data)
            if response.status_code == 429:
                until = store.block(backend, key_fp, data.get("retry_after"), 429)
                logger.warning("%s answered 429: every process holds requests on this key for %.0fs",
                               backend, until - time.time())
        except Exception:
            logger.debug("quota capture failed", exc_info=True)

    return _hook


def usage() -> list[dict]:
    """Every backend's quota and block, for the route, the panel and ``/usage``."""
    return get_store().snapshot()


def render(rows: list[dict]) -> str:
    """``/usage`` as text: one line per backend and key."""
    if not rows:
        return "No provider quota seen yet: it is read from each cloud provider's responses."
    lines = []
    for row in rows:
        parts = []
        for kind, q in row["quota"].items():
            if q["remaining"] is None:
                continue
            left = f"{q['remaining']}" + (f"/{q['limit']}" if q["limit"] is not None else "")
            reset = f", resets in {q['resets_in']:.0f}s" if q["resets_in"] is not None else ""
            parts.append(f"{kind} {left}{reset}")
        block = f" — BLOCKED for {row['blocked_for']:.0f}s after a {row['block_status']}" if row["blocked"] else ""
        key = f" (key {row['key'][:6]})" if row["key"] else ""
        lines.append(f"{row['backend']}{key}: {', '.join(parts) or 'no quota headers'}{block}")
    return "Provider quota:\n" + "\n".join(lines)


__all__ = [
    "DEFAULT_BLOCK_SECONDS", "MAX_BLOCK_SECONDS", "ProviderRateLimited", "QuotaStore", "get_store",
    "key_fingerprint", "parse_duration", "parse_headers", "render", "request_hook", "response_hook",
    "retry_after", "set_store", "usage",
]
