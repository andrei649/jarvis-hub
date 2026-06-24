"""token_store.py — managed API tokens with TTL, rotation, and hash-at-rest (AUD-6 / F19).

The managed store is the authoritative credential system: tokens are minted on
demand, returned in clear **exactly once**, stored only as a SHA-256 hash — so the
store never holds a usable token — with an optional expiry. ``rotate`` revokes the
prior tokens of a scope, so an old or expired token is rejected.

**Full-replace posture (AUD-6).** The static ``JARVIS_ADMIN_TOKEN`` /
``JARVIS_USER_TOKEN`` env vars are the *bootstrap* credential — the guards still
accept them (constant-time) so existing deployments keep working — but they are no
longer permanent: once a scope is rotated through this store, the static env token
of that scope is **revoked for good** (a persistent ``revoked:<scope>`` flag in
``_meta`` that survives restarts). Adopting a managed token therefore supersedes
the static one, which is the whole point of "replace the env token". The guards
read :meth:`env_revoked` to honour this.

**Recovery (no permanent lockout).** Two hatches keep the owner from being locked
out of their own box: (1) when the store holds no token of a tier *and* the env
token is unset/revoked, a direct localhost origin is trusted (dev posture, see
``web._admin_guard``); (2) this module is runnable as a CLI —
``python -m agents.core.security.token_store rotate admin`` mints a fresh token
from the machine itself (filesystem access is the owner's root of trust), no HTTP.
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
        # _meta carries persistent flags, notably "revoked:<scope>" — set when a
        # scope is rotated, so the static env token of that scope stays revoked
        # across restarts (the env var alone can't resurrect it).
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS _meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
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

    def env_revoked(self, scope: str) -> bool:
        """True once the static env token of *scope* has been superseded by a
        rotation through this store (a persistent ``revoked:<scope>`` flag). The
        guards consult this so the static token stops working after rotation."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM _meta WHERE key=?", (f"revoked:{scope}",)
            ).fetchone()
        return row is not None

    def _mark_env_revoked(self, scope: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES (?, ?)",
            (f"revoked:{scope}", "1"),
        )

    def rotate(self, scope: str, ttl_days: Optional[float] = None, label: str = "") -> str:
        """Revoke all existing tokens of *scope* AND the static env token of that
        scope (persistent flag), then issue a fresh managed one. This is what makes
        adopting a managed token a true replacement of the static env token."""
        if scope not in SCOPES:
            raise ValueError(f"unknown scope: {scope}")
        with self._lock:
            self._conn.execute("DELETE FROM issued_tokens WHERE scope=?", (scope,))
            self._mark_env_revoked(scope)
            self._conn.commit()
        return self.issue(scope, ttl_days=ttl_days, label=label)

    def revoke_all(self, scope: Optional[str] = None, revoke_env: bool = False) -> int:
        """Delete issued tokens (of *scope*, or all). With ``revoke_env`` also
        supersede the static env token(s) so they stop working too."""
        with self._lock:
            if scope:
                cur = self._conn.execute("DELETE FROM issued_tokens WHERE scope=?", (scope,))
                if revoke_env:
                    self._mark_env_revoked(scope)
            else:
                cur = self._conn.execute("DELETE FROM issued_tokens")
                if revoke_env:
                    for s in SCOPES:
                        self._mark_env_revoked(s)
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

    def list_tokens(self) -> list[dict]:
        """Metadata for every stored token (never the token itself) — for the CLI."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT substr(token_hash, 1, 12), scope, created_at, expires_at, label "
                "FROM issued_tokens ORDER BY scope, created_at"
            ).fetchall()
        return [
            {"hash_prefix": h, "scope": s, "created_at": c, "expires_at": e, "label": lbl}
            for (h, s, c, e, lbl) in rows
        ]

    def close(self):
        self._conn.close()


_store: Optional[TokenStore] = None
_store_lock = threading.Lock()


def get_token_store() -> TokenStore:
    """Process-wide managed-token store (lazy singleton)."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = TokenStore()
    return _store


def _main(argv: Optional[list[str]] = None) -> int:
    """Offline owner-recovery CLI — filesystem access is the root of trust.

        python -m agents.core.security.token_store rotate admin [ttl_days]
        python -m agents.core.security.token_store issue  user  [ttl_days]
        python -m agents.core.security.token_store revoke admin|all [--revoke-env]
        python -m agents.core.security.token_store list
    """
    import argparse

    parser = argparse.ArgumentParser(prog="token_store", description=_main.__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("issue", "rotate"):
        p = sub.add_parser(name)
        p.add_argument("scope", choices=SCOPES)
        p.add_argument("ttl_days", nargs="?", type=float, default=None)
    p_rev = sub.add_parser("revoke")
    p_rev.add_argument("scope", choices=(*SCOPES, "all"))
    p_rev.add_argument("--revoke-env", action="store_true",
                       help="also supersede the static env token(s)")
    sub.add_parser("list")

    ns = parser.parse_args(argv)
    store = get_token_store()
    if ns.cmd in ("issue", "rotate"):
        fn = store.issue if ns.cmd == "issue" else store.rotate
        token = fn(ns.scope, ttl_days=ns.ttl_days, label=f"{ns.cmd} via CLI")
        print(token)  # the raw token — shown ONCE
        return 0
    if ns.cmd == "revoke":
        scope = None if ns.scope == "all" else ns.scope
        n = store.revoke_all(scope, revoke_env=ns.revoke_env)
        print(f"revoked {n} token(s)")
        return 0
    if ns.cmd == "list":
        for t in store.list_tokens():
            exp = "never" if t["expires_at"] is None else time.strftime(
                "%Y-%m-%d", time.localtime(t["expires_at"])
            )
            print(f"{t['scope']:<6} {t['hash_prefix']}  expires={exp}  {t['label']}")
        return 0
    return 1


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
