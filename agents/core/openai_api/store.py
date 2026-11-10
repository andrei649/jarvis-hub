"""G12 (H560 / H614) — durable state of the OpenAI-compatible API.

One SQLite file (``<data root>/openai_api.db``) holds three small tables:

- ``keys``: the bearer keys the owner issued. Only a SHA-256 of each key is kept; the key
  itself is shown once, when it is issued. A key is either the owner's (``owner = 1``: its
  turns are the owner's own words, like the HUD) or a guest's (``owner = 0``: every turn it
  starts is an inbound, untrusted turn, so the kernel queues each mutating action for the
  owner's approval). Revoking a key refuses it at once.
- ``conversations``: which Nerva sessions a key has already spoken in, so the API knows
  whether the client's history is news to Nerva (a first turn) or already in the session.
- ``responses``: what a ``/v1/responses`` call (or a non-streamed chat completion) answered,
  scoped to the key that asked, so ``previous_response_id`` can continue the same session and
  ``GET``/``DELETE /v1/responses/{id}`` work. Rows expire after :data:`RESPONSE_TTL_SECONDS`
  and the table is capped at :data:`MAX_RESPONSES`.

Nothing in this file is a credential Nerva could use elsewhere: a key hash only opens this API.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KEY_PREFIX = "nrv-"
RESPONSE_TTL_SECONDS = 30 * 24 * 3600
MAX_RESPONSES = 5_000
MAX_KEYS = 200
MAX_NAME_CHARS = 64
BUSY_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ApiKey:
    """An issued key, as the API sees it (never the key itself)."""

    key_id: str
    name: str
    owner: bool
    created_at: float
    revoked_at: float | None = None
    last_used_at: float | None = None

    def public(self) -> dict[str, Any]:
        return {"id": self.key_id, "name": self.name, "owner": self.owner,
                "created_at": int(self.created_at),
                "revoked": self.revoked_at is not None,
                "last_used_at": int(self.last_used_at) if self.last_used_at else None}


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class OpenAIApiStore:
    """Keys, known conversations and stored responses (thread-safe, one file)."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            from agents.core.paths import data_path
            path = data_path("openai_api.db")
        self.path = str(path)
        self._lock = threading.Lock()
        self._memory: sqlite3.Connection | None = None
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS keys ("
                " key_id TEXT PRIMARY KEY, name TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,"
                " owner INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,"
                " revoked_at REAL, last_used_at REAL)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS conversations ("
                " session_id TEXT PRIMARY KEY, key_id TEXT NOT NULL, created_at REAL NOT NULL,"
                " last_used_at REAL NOT NULL, turns INTEGER NOT NULL DEFAULT 0)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS responses ("
                " response_id TEXT PRIMARY KEY, key_id TEXT NOT NULL, session_id TEXT NOT NULL,"
                " created_at REAL NOT NULL, body TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS responses_created ON responses (created_at)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.path == ":memory:":
            if self._memory is None:
                self._memory = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
            yield self._memory
            return
        conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
        finally:
            conn.close()

    # ── keys ────────────────────────────────────────────────────────────────

    def issue(self, name: str, *, owner: bool = False) -> tuple[str, ApiKey]:
        """Mint a key. Returns ``(key, record)``; the key is not stored and cannot be shown again."""
        name = " ".join(str(name or "").split())[:MAX_NAME_CHARS]
        if not name:
            raise ValueError("a key needs a name")
        key = KEY_PREFIX + secrets.token_urlsafe(32)
        key_id = "key_" + secrets.token_hex(6)
        now = time.time()
        with self._lock, self._connect() as conn:
            live = conn.execute("SELECT COUNT(*) FROM keys WHERE revoked_at IS NULL").fetchone()[0]
            if live >= MAX_KEYS:
                raise ValueError(f"at most {MAX_KEYS} live keys; revoke one first")
            conn.execute("INSERT INTO keys (key_id, name, digest, owner, created_at) VALUES (?, ?, ?, ?, ?)",
                         (key_id, name, _digest(key), 1 if owner else 0, now))
        return key, ApiKey(key_id, name, bool(owner), now)

    def verify(self, supplied: str) -> ApiKey | None:
        """The live key ``supplied`` names, or ``None`` (unknown, malformed or revoked)."""
        if not isinstance(supplied, str) or not supplied.startswith(KEY_PREFIX) or len(supplied) > 256:
            return None
        digest = _digest(supplied)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT key_id, name, digest, owner, created_at, revoked_at, last_used_at FROM keys"
                " WHERE digest=?", (digest,)).fetchone()
            if row is None or not secrets.compare_digest(row[2], digest) or row[5] is not None:
                return None
            now = time.time()
            conn.execute("UPDATE keys SET last_used_at=? WHERE key_id=?", (now, row[0]))
        return ApiKey(row[0], row[1], bool(row[3]), row[4], row[5], now)

    def list_keys(self) -> list[ApiKey]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT key_id, name, owner, created_at, revoked_at, last_used_at FROM keys"
                " ORDER BY created_at").fetchall()
        return [ApiKey(r[0], r[1], bool(r[2]), r[3], r[4], r[5]) for r in rows]

    def revoke(self, key_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("UPDATE keys SET revoked_at=? WHERE key_id=? AND revoked_at IS NULL",
                               (time.time(), str(key_id)))
            return cur.rowcount == 1

    # ── conversations ───────────────────────────────────────────────────────

    def conversation_turns(self, session_id: str, key_id: str) -> int:
        """How many turns this key already ran in the session (0: new to Nerva)."""
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT turns FROM conversations WHERE session_id=? AND key_id=?",
                               (session_id, key_id)).fetchone()
        return int(row[0]) if row else 0

    def record_turn(self, session_id: str, key_id: str) -> None:
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (session_id, key_id, created_at, last_used_at, turns)"
                " VALUES (?, ?, ?, ?, 1) ON CONFLICT(session_id) DO UPDATE SET"
                " last_used_at=excluded.last_used_at, turns=turns+1", (session_id, key_id, now, now))

    # ── stored responses ────────────────────────────────────────────────────

    def save_response(self, response_id: str, key_id: str, session_id: str, body: dict) -> None:
        now = time.time()
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM responses WHERE created_at < ?", (now - RESPONSE_TTL_SECONDS,))
            conn.execute("INSERT OR REPLACE INTO responses (response_id, key_id, session_id, created_at, body)"
                         " VALUES (?, ?, ?, ?, ?)", (response_id, key_id, session_id, now, text))
            excess = conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0] - MAX_RESPONSES
            if excess > 0:
                conn.execute("DELETE FROM responses WHERE response_id IN (SELECT response_id FROM responses"
                             " ORDER BY created_at LIMIT ?)", (excess,))

    def get_response(self, response_id: str, key_id: str) -> tuple[str, dict] | None:
        """``(session_id, body)`` of a response this key stored, else ``None`` (never another key's)."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT session_id, body, created_at FROM responses WHERE response_id=? AND key_id=?",
                (str(response_id), key_id)).fetchone()
        if row is None or row[2] < time.time() - RESPONSE_TTL_SECONDS:
            return None
        try:
            body = json.loads(row[1])
        except ValueError:
            return None
        return row[0], body if isinstance(body, dict) else {}

    def delete_response(self, response_id: str, key_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM responses WHERE response_id=? AND key_id=?",
                               (str(response_id), key_id))
            return cur.rowcount == 1


_store: OpenAIApiStore | None = None
_store_lock = threading.Lock()


def get_store() -> OpenAIApiStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = OpenAIApiStore()
        return _store


def set_store(store: OpenAIApiStore | None) -> None:
    """Swap the process store (tests; ``None`` opens the default file on next use)."""
    global _store
    with _store_lock:
        _store = store
