"""browser_session.py — the owner's browser sign-in for a networked hub (H509, G13).

A networked HUD used to need the admin token pasted into ``localStorage`` and sent as a
header on every call. This module lets the owner sign in once instead: the owner secret
(any valid admin credential — the bootstrap ``JARVIS_ADMIN_TOKEN`` or a managed admin
token) is exchanged at ``POST /api/auth/login`` for a session cookie, and the hub's
guards (``agents/web.py``) accept that cookie as the owner. The design is the Nerva
Workspace session (``agents/core/workspace/auth.py``) cut down to the single owner:

* **Cookie.** A random 256-bit token, ``HttpOnly``, ``SameSite=Strict``, ``Secure``
  whenever the request arrived over HTTPS (a listed proxy's ``X-Forwarded-Proto``
  counts, H691), with ``Max-Age``. Over HTTPS at the root path the name carries the
  ``__Host-`` prefix, so no sibling host or path can plant or shadow it. Only the
  token's SHA-256 is stored, so a copied database cannot be replayed as a cookie.
* **Expiry and revocation.** A session dies when it is signed out, signed out
  everywhere, idle for :data:`IDLE_SECONDS`, past :data:`ABSOLUTE_SECONDS`, or when the
  admin credential it was opened with stops being valid (rotated, revoked, expired):
  the store keeps the credential's hash and the hub re-checks it on every use.
* **CSRF.** Cookie authentication is accepted only with browser evidence of the same
  origin (``Sec-Fetch-Site`` / ``Origin``, also on a WebSocket upgrade), and a mutating
  request must echo the session's synchronizer token in ``X-CSRF-Token``. A request that
  authenticates with a header token never consults the cookie, so the existing token
  routes do not become CSRF-able because a cookie exists.
* **Throttling.** Failed sign-ins are counted per client address (5 per 15 minutes) and
  overall (30 per 15 minutes), and each attempt is counted *before* its secret is
  checked, so a burst of parallel guesses cannot outrun the limit. A lockout never
  locks the owner out of the box: header tokens and the loopback posture are untouched.

Loopback behaviour does not change: with no admin credential configured, a direct
loopback caller is still the owner without signing in, and nothing here runs for it.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from agents.core.paths import data_path

SESSION_COOKIE = "nerva_session"
HOST_SESSION_COOKIE = "__Host-nerva_session"
COOKIE_NAMES = (HOST_SESSION_COOKIE, SESSION_COOKIE)
CSRF_HEADER = "x-csrf-token"
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

ABSOLUTE_SECONDS = 7 * 86400
IDLE_SECONDS = 24 * 3600
TOUCH_INTERVAL_SECONDS = 60
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_IP_LIMIT = 5
LOGIN_GLOBAL_LIMIT = 30
MAX_SECRET_LENGTH = 4096
MAX_USER_AGENT = 300


def token_hash(token: str) -> str:
    """SHA-256 hex of a session token or an owner secret (what the store keeps)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Throttled(Exception):
    """Too many failed sign-ins; ``retry_after`` seconds until the next is counted."""

    def __init__(self, retry_after: int):
        super().__init__("too many failed sign-ins")
        self.retry_after = retry_after


class BrowserSessionStore:
    """SQLite store of owner browser sessions and sign-in attempts."""

    def __init__(self, db_path: str | None = None):
        self._path = Path(db_path) if db_path else data_path("security", "browser_sessions.db")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id_hash      TEXT PRIMARY KEY,
                csrf_token   TEXT NOT NULL,
                cred_hash    TEXT NOT NULL,
                created_at   REAL NOT NULL,
                last_seen_at REAL NOT NULL,
                expires_at   REAL NOT NULL,
                revoked_at   REAL,
                ip           TEXT DEFAULT '',
                user_agent   TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS login_attempts (
                id  INTEGER PRIMARY KEY AUTOINCREMENT,
                ip  TEXT NOT NULL,
                ok  INTEGER NOT NULL,
                ts  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS login_attempts_ts ON login_attempts (ts);
        """)
        self._conn.commit()

    # ── sessions ──────────────────────────────────────────────────────────────────

    def create(self, *, cred_hash: str, ip: str = "", user_agent: str = "",
               now: float | None = None) -> dict[str, Any]:
        """Open a session; returns ``{"token", "csrf", "expires_at"}`` (token in clear once)."""
        stamp = now if now is not None else time.time()
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        expires_at = stamp + ABSOLUTE_SECONDS
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id_hash, csrf_token, cred_hash, created_at, last_seen_at, "
                "expires_at, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (token_hash(token), csrf, cred_hash, stamp, stamp, expires_at, ip[:64],
                 user_agent[:MAX_USER_AGENT]),
            )
            # Dead rows have no further use; keep the table from growing without bound.
            self._conn.execute(
                "DELETE FROM sessions WHERE expires_at < ? OR revoked_at < ? "
                "OR last_seen_at < ?", (stamp, stamp - 86400, stamp - IDLE_SECONDS))
            self._conn.commit()
        return {"token": token, "csrf": csrf, "expires_at": expires_at}

    def resolve(self, token: str, now: float | None = None) -> dict[str, Any] | None:
        """The live session behind *token*, or ``None``; refreshes its idle clock (≤ 1/min)."""
        if not token or len(token) > 256:
            return None
        stamp = now if now is not None else time.time()
        id_hash = token_hash(token)
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE id_hash = ?",
                                     (id_hash,)).fetchone()
            if row is None or row["revoked_at"] is not None or row["expires_at"] <= stamp \
                    or row["last_seen_at"] + IDLE_SECONDS <= stamp:
                return None
            if stamp - row["last_seen_at"] >= TOUCH_INTERVAL_SECONDS:
                self._conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id_hash = ?",
                                   (stamp, id_hash))
                self._conn.commit()
        session = dict(row)
        session["idle_expires_at"] = max(row["last_seen_at"], stamp) + IDLE_SECONDS
        return session

    def revoke(self, id_hash: str, now: float | None = None) -> bool:
        """Revoke one session by its hash; True when it was live."""
        stamp = now if now is not None else time.time()
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE id_hash = ? AND revoked_at IS NULL",
                (stamp, id_hash))
            self._conn.commit()
        return cursor.rowcount == 1

    def revoke_all(self, now: float | None = None) -> int:
        """Sign out everywhere: revoke every live session; returns the count."""
        stamp = now if now is not None else time.time()
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE revoked_at IS NULL AND expires_at > ?",
                (stamp, stamp))
            self._conn.commit()
        return int(cursor.rowcount or 0)

    def live_count(self, now: float | None = None) -> int:
        stamp = now if now is not None else time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE revoked_at IS NULL AND expires_at > ? "
                "AND last_seen_at > ?", (stamp, stamp - IDLE_SECONDS)).fetchone()
        return int(row[0])

    # ── sign-in throttle ──────────────────────────────────────────────────────────

    def reserve_attempt(self, ip: str, now: float | None = None) -> int:
        """Check the throttle and count this attempt as a failure, atomically.

        Raises :class:`Throttled` when the address or the hub as a whole is over its
        limit (a refused attempt is not stored, so the lock lifts as the window slides).
        Returns the attempt id; :meth:`settle_success` flips it on a correct secret.
        """
        stamp = now if now is not None else time.time()
        since = stamp - LOGIN_WINDOW_SECONDS
        with self._lock:
            self._conn.execute("DELETE FROM login_attempts WHERE ts < ?", (since,))
            last_ok = self._conn.execute(
                "SELECT COALESCE(MAX(id), 0) FROM login_attempts WHERE ip = ? AND ok = 1",
                (ip,)).fetchone()[0]
            per_ip = [r[0] for r in self._conn.execute(
                "SELECT ts FROM login_attempts WHERE ip = ? AND ok = 0 AND ts > ? AND id > ? "
                "ORDER BY id DESC LIMIT ?", (ip, since, last_ok, LOGIN_IP_LIMIT))]
            overall = [r[0] for r in self._conn.execute(
                "SELECT ts FROM login_attempts WHERE ok = 0 AND ts > ? ORDER BY id DESC LIMIT ?",
                (since, LOGIN_GLOBAL_LIMIT))]
            waits = [w for w in (_retry_after(per_ip, LOGIN_IP_LIMIT, stamp),
                                 _retry_after(overall, LOGIN_GLOBAL_LIMIT, stamp)) if w]
            if waits:
                self._conn.commit()
                raise Throttled(max(waits))
            cursor = self._conn.execute(
                "INSERT INTO login_attempts (ip, ok, ts) VALUES (?, 0, ?)", (ip, stamp))
            self._conn.commit()
        return int(cursor.lastrowid)

    def settle_success(self, attempt_id: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE login_attempts SET ok = 1 WHERE id = ?", (attempt_id,))
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def _retry_after(times: list[float], limit: int, stamp: float) -> int | None:
    if len(times) < limit:
        return None
    return max(1, math.ceil(times[limit - 1] + LOGIN_WINDOW_SECONDS - stamp))


_store: BrowserSessionStore | None = None
_store_lock = threading.Lock()


def get_session_store() -> BrowserSessionStore:
    """Process-wide session store (lazy singleton)."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = BrowserSessionStore()
    return _store


def reset_session_store(store: BrowserSessionStore | None = None) -> None:
    """Replace the singleton (tests; a restore that moved the data root)."""
    global _store
    with _store_lock:
        _store = store


# ── request helpers (duck-typed: the guards are also called with test stand-ins) ─────

def _headers(request) -> Any:
    return getattr(request, "headers", None) or {}


def _root_path(request) -> str:
    scope = getattr(request, "scope", None)
    root = scope.get("root_path") if isinstance(scope, dict) else ""
    return (root or "").rstrip("/")


def is_https(request) -> bool:
    url = getattr(request, "url", None)
    return getattr(url, "scheme", "") in ("https", "wss")


def cookie_name(request) -> str:
    """``__Host-nerva_session`` over HTTPS at the root path, else ``nerva_session``."""
    return HOST_SESSION_COOKIE if is_https(request) and not _root_path(request) else SESSION_COOKIE


def cookie_path(request) -> str:
    return _root_path(request) or "/"


def cookie_token(request) -> str:
    """The session token the request carries under either name ('' when none).

    The ``__Host-`` name is read only over HTTPS, where a browser would have set it."""
    cookies = getattr(request, "cookies", None)
    if not cookies:
        return ""
    names = COOKIE_NAMES if is_https(request) else (SESSION_COOKIE,)
    for name in names:
        value = cookies.get(name)
        if value:
            return value
    return ""


def _expected_origin(request) -> str:
    base = getattr(request, "base_url", None)
    if base is None:
        return ""
    scheme = {"ws": "http", "wss": "https"}.get(base.scheme, base.scheme)
    return f"{scheme}://{base.netloc}".lower()


def same_origin(request) -> bool:
    """Browser evidence says same-origin, or there is no browser evidence at all.

    ``Sec-Fetch-Site`` is computed by the browser and cannot be set by page script, so
    ``same-origin``/``none`` is believed; ``same-site``/``cross-site`` is refused even
    when ``Origin`` would match. Otherwise ``Origin`` must equal this hub's own origin.
    A request with neither header is not from a browser page (curl, the CLI)."""
    headers = _headers(request)
    site = (headers.get("sec-fetch-site") or "").strip().lower()
    if site in ("same-origin", "none"):
        return True
    if site:
        return False
    origin = headers.get("origin")
    if origin is not None:
        expected = _expected_origin(request)
        return bool(expected) and origin.strip().rstrip("/").lower() == expected
    return True


def is_json(request) -> bool:
    content_type = (_headers(request).get("content-type") or "").split(";", 1)[0]
    return content_type.strip().lower() == "application/json"


def _method(request) -> str:
    method = getattr(request, "method", None)
    if method:
        return str(method).upper()
    scope = getattr(request, "scope", None)
    return str(scope.get("method", "GET")).upper() if isinstance(scope, dict) else "GET"


#: session_state() outcomes.
NONE, OK, CSRF_FAILED = "none", "ok", "csrf_failed"


def session_state(request, credential_valid) -> tuple[str, dict[str, Any] | None]:
    """Classify the request's owner cookie: ``(NONE|OK|CSRF_FAILED, session)``.

    *credential_valid* is ``fn(cred_hash) -> bool``: whether the admin credential the
    session was opened with is still valid (``agents.web`` supplies it). A session
    whose credential died is revoked on the spot. ``CSRF_FAILED`` means a live session
    was presented on a mutating request without its synchronizer token — the guards
    answer 403 rather than 401, so the HUD does not ask the owner to sign in again.
    Never cached: a WebSocket handler re-runs its guard on the same request object to
    notice a sign-out mid-stream, so every call reads the store afresh."""
    result: tuple[str, dict[str, Any] | None] = (NONE, None)
    token = cookie_token(request)
    if token and same_origin(request):
        store = get_session_store()
        session = store.resolve(token)
        if session is not None and not credential_valid(session["cred_hash"]):
            store.revoke(session["id_hash"])
            session = None
        if session is not None:
            if _method(request) in MUTATING_METHODS:
                sent = _headers(request).get(CSRF_HEADER) or ""
                if not sent or not hmac.compare_digest(sent.encode("utf-8"),
                                                       str(session["csrf_token"]).encode("utf-8")):
                    result = (CSRF_FAILED, session)
                else:
                    result = (OK, session)
            else:
                result = (OK, session)
    return result


def set_session_cookie(response, request, token: str) -> None:
    response.set_cookie(
        cookie_name(request), token, max_age=ABSOLUTE_SECONDS, path=cookie_path(request),
        secure=is_https(request), httponly=True, samesite="strict",
    )


def clear_session_cookies(response, request) -> None:
    """Expire every name variant the hub may have set (both prefixes, this path)."""
    secure = is_https(request)
    for name in COOKIE_NAMES:
        if name == HOST_SESSION_COOKIE and not secure:
            continue   # a browser refuses a __Host- cookie without Secure anyway
        response.delete_cookie(name, path=cookie_path(request), secure=secure,
                               httponly=True, samesite="strict")
