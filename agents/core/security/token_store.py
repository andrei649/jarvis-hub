"""token_store.py — issued API tokens with TTL, rotation, and hash-at-rest (AUD-6 / F19).

The static ``JARVIS_ADMIN_TOKEN`` / ``JARVIS_USER_TOKEN`` env tokens remain the
bootstrap credential. This adds *issued* tokens on top: minted on demand, returned
in clear **exactly once**, and stored only as a SHA-256 hash — so the store never
holds a usable token — with an optional expiry. The auth guards accept a valid
issued token in addition to the env token; ``rotate`` revokes the prior issued
tokens of a scope, so an old or expired token is rejected.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

SCOPES = ("admin", "user")
_DAY = 86400


class TokenStore:
    def __init__(self, db_path: Optional[str] = None):
        self._path = Path(db_path) if db_path else data_path("security", "tokens.db")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS issued_tokens (
                token_hash TEXT PRIMARY KEY,
                scope      TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL,
                label      TEXT DEFAULT ''
            )
        """)
        self._conn.commit()

    @staticmethod
    def _hash(token: str) -> str:
        # Tokens carry 256 bits of entropy, so a hash lookup is a safe verification
        # primitive: an attacker can't produce a raw token whose SHA-256 collides.
        return hashlib.sha256(token.encode()).hexdigest()

    def issue(self, scope: str, ttl_days: Optional[float] = None, label: str = "") -> str:
        """Mint a token of *scope*; store only its hash; return the raw token ONCE."""
        if scope not in SCOPES:
            raise ValueError(f"unknown scope: {scope}")
        raw = secrets.token_urlsafe(32)
        now = time.time()
        expires = now + ttl_days * _DAY if ttl_days and ttl_days > 0 else None
        with self._lock:
            self._conn.execute(
                "INSERT INTO issued_tokens (token_hash, scope, created_at, expires_at, label) "
                "VALUES (?, ?, ?, ?, ?)",
                (self._hash(raw), scope, now, expires, label),
            )
            self._conn.commit()
        return raw

    def verify(self, token: str, now: Optional[float] = None) -> Optional[str]:
        """Return the scope of a valid, unexpired token, else None."""
        if not token:
            return None
        now = now if now is not None else time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT scope, expires_at FROM issued_tokens WHERE token_hash=?",
                (self._hash(token),),
            ).fetchone()
        if not row:
            return None
        scope, expires_at = row
        if expires_at is not None and now >= expires_at:
            return None
        return scope

    def has_scope(self, scope: str, now: Optional[float] = None) -> bool:
        """True if at least one unexpired token of *scope* exists."""
        now = now if now is not None else time.time()
        with self._lock:
            rows = self._conn.execute(
                "SELECT expires_at FROM issued_tokens WHERE scope=?", (scope,)
            ).fetchall()
        return any(e is None or now < e for (e,) in rows)

    def rotate(self, scope: str, ttl_days: Optional[float] = None, label: str = "") -> str:
        """Revoke all existing issued tokens of *scope*, then issue a fresh one."""
        if scope not in SCOPES:
            raise ValueError(f"unknown scope: {scope}")
        with self._lock:
            self._conn.execute("DELETE FROM issued_tokens WHERE scope=?", (scope,))
            self._conn.commit()
        return self.issue(scope, ttl_days=ttl_days, label=label)

    def revoke_all(self, scope: Optional[str] = None) -> int:
        with self._lock:
            if scope:
                cur = self._conn.execute("DELETE FROM issued_tokens WHERE scope=?", (scope,))
            else:
                cur = self._conn.execute("DELETE FROM issued_tokens")
            self._conn.commit()
            return cur.rowcount or 0

    def purge_expired(self, now: Optional[float] = None) -> int:
        now = now if now is not None else time.time()
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM issued_tokens WHERE expires_at IS NOT NULL AND expires_at < ?", (now,)
            )
            self._conn.commit()
            return cur.rowcount or 0

    def close(self):
        self._conn.close()


_store: Optional[TokenStore] = None
_store_lock = threading.Lock()


def get_token_store() -> TokenStore:
    """Process-wide issued-token store (lazy singleton)."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = TokenStore()
    return _store
