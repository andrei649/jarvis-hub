"""Sessions, CSRF, throttling and invites of Nerva Workspace (spec §5, §6).

The FastAPI dependencies here are what every workspace route is guarded by, and their
``__name__``s (``ws_enabled``, ``ws_user_guard``, ``ws_admin_guard``) are what the hub's
route-auth matrix reads — never rename them or reuse the hub's guard names.

Sessions. The browser holds a random token in the ``nerva_ws_session`` cookie
(HttpOnly, SameSite=Lax, scoped to ``<root>/api/workspace``); the database stores only
its SHA-256, so a leaked database cannot be replayed as cookies. A session dies when it
is revoked, idle for too long, or past its absolute lifetime — whichever comes first.

CSRF. Each session carries a synchronizer token the client echoes in ``X-CSRF-Token``
on every mutating request. Independently, a mutating request that a browser marks as
cross-origin (``Origin`` / ``Sec-Fetch-Site``) is refused before anything else, which
also protects the public login/setup routes that have no session yet.

Throttling. Failed logins are counted per lower-cased email (existing or not, so the
answer never tells which accounts exist) and per IP. Each attempt is counted *before*
its password is verified (:func:`reserve_login_attempt`), so a burst of parallel
requests cannot outrun the limit, and the rows are committed before any error is
raised, so a lockout survives the 401 that reports the failure.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import secrets
import sqlite3
from typing import Annotated

from fastapi import Depends, Request, Response

from agents.core import proxy_trust
from agents.core.workspace import audit, config, db, identity
from agents.core.workspace.db import Db
from agents.core.workspace.errors import WorkspaceError
from agents.core.workspace.identity import WorkspaceUser

logger = logging.getLogger("nerva.workspace.auth")

SESSION_COOKIE = "nerva_ws_session"
CSRF_HEADER = "X-CSRF-Token"
PROXY_KEY_HEADER = "X-Nerva-Proxy-Secret"
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
TOUCH_INTERVAL_SECONDS = 60
MAX_USER_AGENT = 300

LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_EMAIL_LIMIT = 5
LOGIN_IP_LIMIT = 20
SETUP_WINDOW_SECONDS = 3600
SETUP_IP_LIMIT = 10
SETUP_GLOBAL_LIMIT = 50
INVITE_WINDOW_SECONDS = 3600
INVITE_IP_LIMIT = 30
INVITE_TTL_SECONDS = 72 * 3600
MIN_INVITE_TOKEN = 20
MAX_INVITE_TOKEN = 128


# ── small primitives ─────────────────────────────────────────────────────────────────

def token_hash(token: str) -> str:
    """SHA-256 hex of a session or invite token (what the database stores)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _root_path(request: Request) -> str:
    return (request.scope.get("root_path") or getattr(request.app, "root_path", "") or "").rstrip("/")


def base_url(request: Request) -> str:
    """``request.base_url`` without the trailing slash (root-path aware)."""
    return str(request.base_url).rstrip("/")


def client_ip(request: Request) -> str:
    """The client address; forwarding headers count only from a trusted proxy peer."""
    peer = request.client.host if request.client else ""
    headers = request.headers
    if not any(name in headers for name in ("x-forwarded-for", "x-real-ip", "forwarded")):
        return peer
    try:
        if not proxy_trust.is_trusted_peer(peer):
            return peer
        resolved = proxy_trust.forwarded_client(
            peer, xff=headers.get("x-forwarded-for", ""), x_real_ip=headers.get("x-real-ip", ""),
        )
    except ValueError:
        return peer
    return resolved or peer


def _expected_origin(request: Request) -> str:
    base = request.base_url
    return f"{base.scheme}://{base.netloc}".lower()


def _same_origin(request: Request) -> bool:
    """Browser evidence says same-origin, or there is no browser evidence at all.

    ``Sec-Fetch-Site`` is computed by the browser and cannot be set by page script, so
    ``same-origin``/``none`` is trusted even when a misconfigured proxy makes ``Origin``
    look different from ``base_url``. Without either header the caller is not a
    browser (curl, the CLI, tests) and CSRF does not apply.
    """
    site = request.headers.get("sec-fetch-site", "").strip().lower()
    if site in ("same-origin", "none"):
        return True
    origin = request.headers.get("origin")
    if origin is not None:
        return origin.strip().rstrip("/").lower() == _expected_origin(request)
    return not site


def check_same_origin(request: Request) -> None:
    """``403 csrf_failed`` for a mutating request a browser marks as cross-origin."""
    if request.method in MUTATING_METHODS and not _same_origin(request):
        raise WorkspaceError("csrf_failed", "cross-origin request refused", 403)


def check_public_origin(request: Request) -> None:
    """Public POSTs: same-origin rule plus ``Content-Type: application/json``.

    A cross-site HTML form can only send form encodings or ``text/plain``, so requiring
    JSON closes the login-CSRF hole even for browsers that send no ``Origin``.
    """
    check_same_origin(request)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise WorkspaceError("unsupported_media_type", "send application/json", 415)


# ── cookies and sessions ─────────────────────────────────────────────────────────────

def _cookie_path(request: Request) -> str:
    return f"{_root_path(request)}/api/workspace"


def _cookie_secure(request: Request) -> bool:
    mode = config.cookie_secure_mode()
    if mode == "on":
        return True
    if mode == "off":
        return False
    return request.url.scheme == "https"


def current_session_hash(request: Request) -> str | None:
    """SHA-256 of the session cookie the request carries, or ``None``."""
    token = request.cookies.get(SESSION_COOKIE)
    return token_hash(token) if token else None


def issue_session(conn: sqlite3.Connection, response: Response, request: Request, user_id: int,
                  *, via: str, sso_email: str | None = None) -> str:
    """Create a session for *user_id*, set its cookie on *response*; returns the CSRF token.

    Runs inside the caller's transaction. The session the request presented (if any) is
    revoked: every login, setup and invite acceptance rotates the session.
    """
    if not conn.in_transaction:
        raise RuntimeError("issue_session must run inside a transaction (use db.tx)")
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    stamp = db.now()
    previous = current_session_hash(request)
    if previous:
        revoke_session(conn, previous)
    conn.execute(
        "INSERT INTO sessions (id_hash, user_id, csrf_token, created_at, last_seen_at, expires_at, "
        "ip, user_agent, via, sso_email) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (token_hash(token), user_id, csrf, stamp, stamp, stamp + config.session_max_seconds(),
         client_ip(request), request.headers.get("user-agent", "")[:MAX_USER_AGENT], via, sso_email),
    )
    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (stamp, user_id))
    response.set_cookie(
        SESSION_COOKIE, token, max_age=config.session_max_seconds(), path=_cookie_path(request),
        secure=_cookie_secure(request), httponly=True, samesite="lax",
    )
    return csrf


def clear_session_cookie(response: Response, request: Request) -> None:
    """Expire the session cookie (same path/flags it was set with)."""
    response.delete_cookie(SESSION_COOKIE, path=_cookie_path(request),
                           secure=_cookie_secure(request), httponly=True, samesite="lax")


def revoke_session(conn: sqlite3.Connection, id_hash: str) -> bool:
    """Revoke one session; True when it was live."""
    with db.tx(conn):
        cursor = conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE id_hash = ? AND revoked_at IS NULL",
            (db.now(), id_hash),
        )
    return cursor.rowcount == 1


def revoke_user_sessions(conn: sqlite3.Connection, user_id: int, *,
                         keep: str | None = None) -> int:
    """Revoke every live session of *user_id* except the *keep* hash; returns the count."""
    with db.tx(conn):
        cursor = conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL "
            "AND id_hash != ?",
            (db.now(), user_id, keep or ""),
        )
    return int(cursor.rowcount)


def _session_alive(row: sqlite3.Row, stamp: float) -> bool:
    return (row["revoked_at"] is None and row["expires_at"] > stamp
            and row["last_seen_at"] + config.session_idle_seconds() > stamp)


def _sso_identity_changed(request: Request, row: sqlite3.Row) -> bool:
    """A trusted proxy now vouches for a different email than the session was made for."""
    header = config.sso_header()
    if not row["sso_email"] or not header:
        return False
    values = request.headers.getlist(header)
    if not values:
        return False
    peer = request.client.host if request.client else ""
    try:
        trusted = proxy_trust.is_trusted_peer(peer)
    except ValueError:
        return False
    return trusted and any(v.strip().lower() != row["sso_email"].lower() for v in values)


def resolve_session(conn: sqlite3.Connection,
                    request: Request) -> tuple[sqlite3.Row, WorkspaceUser] | None:
    """The live session and active user behind the request's cookie, or ``None``.

    Side effects, each in its own short transaction: ``last_seen_at`` is refreshed at
    most every 60 s, and an SSO session whose proxy-asserted email changed is revoked.
    """
    id_hash = current_session_hash(request)
    if id_hash is None:
        return None
    row = conn.execute("SELECT * FROM sessions WHERE id_hash = ?", (id_hash,)).fetchone()
    stamp = db.now()
    if row is None or not _session_alive(row, stamp):
        return None
    user = identity.get_user(conn, int(row["user_id"]))
    if user is None or user.status != "active":
        return None
    if _sso_identity_changed(request, row):
        with db.tx(conn):
            revoke_session(conn, id_hash)
            audit.record(conn, actor=user, action="session.revoked", target_type="session",
                         target_id=id_hash[:12], ip=client_ip(request),
                         details={"reason": "sso_identity_changed"})
        return None
    if stamp - row["last_seen_at"] >= TOUCH_INTERVAL_SECONDS:
        with db.tx(conn):
            conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id_hash = ?", (stamp, id_hash))
    return row, user


# ── dependencies ─────────────────────────────────────────────────────────────────────

def ws_enabled() -> None:
    """``404 workspace_disabled`` unless ``NERVA_WORKSPACE`` is on (read per request)."""
    if not config.enabled():
        raise WorkspaceError("workspace_disabled", "Nerva Workspace is not enabled", 404)


Enabled = Annotated[None, Depends(ws_enabled)]


def ws_user_guard(request: Request, conn: Db,
                  _on: Annotated[None, Depends(ws_enabled)]) -> WorkspaceUser:
    """The signed-in, active user; mutating requests also pass the Origin + CSRF checks."""
    resolved = resolve_session(conn, request)
    if resolved is None:
        raise WorkspaceError("auth_required", "sign in to continue", 401)
    row, user = resolved
    if request.method in MUTATING_METHODS:
        check_same_origin(request)
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not hmac.compare_digest(sent.encode("utf-8"),
                                               str(row["csrf_token"]).encode("utf-8")):
            raise WorkspaceError("csrf_failed", "missing or wrong CSRF token", 403)
    return user


WsUser = Annotated[WorkspaceUser, Depends(ws_user_guard)]


def ws_admin_guard(user: Annotated[WorkspaceUser, Depends(ws_user_guard)]) -> WorkspaceUser:
    """The signed-in user when they are an admin, else ``403 forbidden``."""
    if not user.is_admin:
        raise WorkspaceError("forbidden", "administrators only", 403)
    return user


WsAdmin = Annotated[WorkspaceUser, Depends(ws_admin_guard)]


# ── throttling ───────────────────────────────────────────────────────────────────────

def record_attempt(conn: sqlite3.Connection, *, ip: str, email: str, ok: bool, kind: str) -> None:
    """Store one attempt row (commits on its own unless the caller holds a transaction)."""
    with db.tx(conn):
        conn.execute(
            "INSERT INTO login_attempts (ip, email, ok, kind, ts) VALUES (?, ?, ?, ?, ?)",
            (ip, _normalized_email(email), 1 if ok else 0, kind, db.now()),
        )


def _retry_after(times: list[float], limit: int, window: float, stamp: float) -> int | None:
    """Seconds until fewer than *limit* of *times* (newest first) remain in the window."""
    if len(times) < limit:
        return None
    return max(1, math.ceil(times[limit - 1] + window - stamp))


def _times(conn: sqlite3.Connection, sql: str, params: tuple) -> list[float]:
    return [float(row[0]) for row in conn.execute(sql, params).fetchall()]


def _normalized_email(email: str) -> str:
    return email.strip().lower()[:254]


# Row ids order the attempts (the clock may tie or be frozen); ``id <= ?`` lets the same
# queries answer "how many failures up to this attempt" for the once-only throttled audit.
_LAST_ROW_ID = 2 ** 63 - 1
_EMAIL_FAILURES_SQL = (
    "SELECT ts FROM login_attempts WHERE email = ? AND kind = 'login' AND ok = 0 AND ts > ? "
    "AND id <= ? AND id > COALESCE((SELECT MAX(id) FROM login_attempts "
    "WHERE email = ? AND kind = 'login' AND ok = 1 AND id <= ?), 0) ORDER BY id DESC LIMIT ?"
)
_IP_FAILURES_SQL = (
    "SELECT ts FROM login_attempts WHERE ip = ? AND kind = 'login' AND ok = 0 AND ts > ? "
    "AND id <= ? ORDER BY id DESC LIMIT ?"
)


def _email_failure_times(conn: sqlite3.Connection, email: str, stamp: float, *,
                         up_to: int = _LAST_ROW_ID) -> list[float]:
    """Failures for *email* in the window since its last success (newest first)."""
    return _times(conn, _EMAIL_FAILURES_SQL, (email, stamp - LOGIN_WINDOW_SECONDS, up_to, email,
                                              up_to, LOGIN_EMAIL_LIMIT))


def _ip_failure_times(conn: sqlite3.Connection, ip: str, stamp: float, *,
                      up_to: int = _LAST_ROW_ID) -> list[float]:
    """Failures from *ip* in the window (newest first)."""
    return _times(conn, _IP_FAILURES_SQL, (ip, stamp - LOGIN_WINDOW_SECONDS, up_to,
                                           LOGIN_IP_LIMIT))


def too_many(retry_after: int) -> WorkspaceError:
    """The shared ``429 too_many_attempts`` error."""
    return WorkspaceError("too_many_attempts", "too many attempts; try again later", 429,
                          retry_after_seconds=retry_after)


def check_login_throttle(conn: sqlite3.Connection, *, email: str, ip: str) -> None:
    """``429`` after 5 consecutive failures for the email or 20 failures from the IP."""
    stamp = db.now()
    waits = [
        _retry_after(_email_failure_times(conn, _normalized_email(email), stamp),
                     LOGIN_EMAIL_LIMIT, LOGIN_WINDOW_SECONDS, stamp),
        _retry_after(_ip_failure_times(conn, ip, stamp), LOGIN_IP_LIMIT,
                     LOGIN_WINDOW_SECONDS, stamp),
    ]
    blocking = [wait for wait in waits if wait is not None]
    if blocking:
        raise too_many(max(blocking))


def reserve_login_attempt(conn: sqlite3.Connection, *, email: str, ip: str) -> int:
    """Check the login throttle and count this attempt as a failure, atomically.

    Password verification runs in a worker thread, off the event loop. Were the
    attempt stored only after it, a burst of parallel requests would all pass the
    check before the first failure lands and get far more than five guesses. The row
    is therefore written up front, in the same ``BEGIN IMMEDIATE`` as the check, and a
    correct password flips it with :func:`settle_login_success`. A refused attempt
    (``429``) writes nothing, so the lock lifts as the window slides. Returns the row id.
    """
    normalized = _normalized_email(email)
    with db.tx(conn):
        check_login_throttle(conn, email=normalized, ip=ip)
        cursor = conn.execute(
            "INSERT INTO login_attempts (ip, email, ok, kind, ts) VALUES (?, ?, 0, 'login', ?)",
            (ip, normalized, db.now()),
        )
    return int(cursor.lastrowid)


def settle_login_success(conn: sqlite3.Connection, attempt_id: int) -> None:
    """Mark a reserved attempt as a success (joins the caller's transaction)."""
    with db.tx(conn):
        conn.execute("UPDATE login_attempts SET ok = 1 WHERE id = ?", (attempt_id,))


def _limit_reached_by(conn: sqlite3.Connection, attempt_id: int, *, email: str, ip: str) -> str:
    """``'email'``/``'ip'`` when the failures up to *attempt_id* hit a limit exactly, else ''."""
    stamp = db.now()
    if len(_email_failure_times(conn, email, stamp, up_to=attempt_id)) == LOGIN_EMAIL_LIMIT:
        return "email"
    if len(_ip_failure_times(conn, ip, stamp, up_to=attempt_id)) == LOGIN_IP_LIMIT:
        return "ip"
    return ""


def record_login_failure(conn: sqlite3.Connection, request: Request, *, attempt_id: int,
                         email: str, reason: str, target_user_id: int | None = None,
                         actor: WorkspaceUser | None = None) -> None:
    """Commit ``auth.login_failed`` for a reserved attempt (and ``auth.throttled`` on lockout).

    The attempt row itself was stored by :func:`reserve_login_attempt`. *actor* is set
    only when a signed-in user mistyped their current password; a failed login has no
    actor, just the email it tried. ``auth.throttled`` is written once, by the failure
    that reaches a limit — counted up to this attempt's row, so parallel failures agree
    on which one that is — and a hammering client cannot flood the audit trail.
    """
    ip = client_ip(request)
    normalized = _normalized_email(email)
    target = target_user_id if target_user_id is not None else (actor.id if actor else "")
    with db.tx(conn):
        audit.record(conn, actor=actor, actor_email=normalized, action="auth.login_failed",
                     target_type="user", target_id=target, ip=ip, details={"reason": reason})
        scope = _limit_reached_by(conn, attempt_id, email=normalized, ip=ip)
        if scope:
            audit.record(conn, actor=actor, actor_email=normalized, action="auth.throttled",
                         target_type="user", target_id=target, ip=ip, details={"scope": scope})


def check_setup_throttle(conn: sqlite3.Connection, *, ip: str) -> None:
    """``429`` after 10 failed setup codes per IP or 50 overall within an hour."""
    stamp = db.now()
    since = stamp - SETUP_WINDOW_SECONDS
    per_ip = _times(conn, "SELECT ts FROM login_attempts WHERE kind = 'setup' AND ok = 0 "
                    "AND ip = ? AND ts > ? ORDER BY ts DESC LIMIT ?", (ip, since, SETUP_IP_LIMIT))
    overall = _times(conn, "SELECT ts FROM login_attempts WHERE kind = 'setup' AND ok = 0 "
                     "AND ts > ? ORDER BY ts DESC LIMIT ?", (since, SETUP_GLOBAL_LIMIT))
    waits = [_retry_after(per_ip, SETUP_IP_LIMIT, SETUP_WINDOW_SECONDS, stamp),
             _retry_after(overall, SETUP_GLOBAL_LIMIT, SETUP_WINDOW_SECONDS, stamp)]
    blocking = [wait for wait in waits if wait is not None]
    if blocking:
        raise too_many(max(blocking))


def check_invite_throttle(conn: sqlite3.Connection, *, ip: str) -> None:
    """``429`` after 30 invite lookups/accepts (any outcome) per IP within an hour."""
    stamp = db.now()
    times = _times(conn, "SELECT ts FROM login_attempts WHERE kind = 'invite_lookup' AND ip = ? "
                   "AND ts > ? ORDER BY ts DESC LIMIT ?",
                   (ip, stamp - INVITE_WINDOW_SECONDS, INVITE_IP_LIMIT))
    wait = _retry_after(times, INVITE_IP_LIMIT, INVITE_WINDOW_SECONDS, stamp)
    if wait is not None:
        raise too_many(wait)


# ── invites ──────────────────────────────────────────────────────────────────────────

def invite_purpose_for(status: str) -> str | None:
    """``invite`` for an invited user, ``reset`` for an active one, ``None`` when disabled."""
    return {"invited": "invite", "active": "reset"}.get(status)


def issue_invite(conn: sqlite3.Connection, user_id: int, *, purpose: str,
                 created_by: int | None) -> tuple[str, float]:
    """A fresh single-use link token (72 h) for *user_id*; older unused ones are revoked.

    Runs inside the caller's transaction; returns ``(token, expires_at)``. Only the
    token's hash is stored.
    """
    if not conn.in_transaction:
        raise RuntimeError("issue_invite must run inside a transaction (use db.tx)")
    conn.execute("DELETE FROM invites WHERE user_id = ? AND used_at IS NULL", (user_id,))
    token = secrets.token_urlsafe(32)
    stamp = db.now()
    expires_at = stamp + INVITE_TTL_SECONDS
    conn.execute(
        "INSERT INTO invites (token_hash, user_id, purpose, created_by, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (token_hash(token), user_id, purpose, created_by, stamp, expires_at),
    )
    return token, expires_at


def invite_url(base: str, token: str) -> str:
    """``<base>/workspace/invite#t=<token>`` — the token rides in the fragment only."""
    return f"{base.rstrip('/')}/workspace/invite#t={token}"


def find_invite(conn: sqlite3.Connection, token: object) -> sqlite3.Row | None:
    """The live invite for *token* joined with its user, or ``None``.

    Live means unused, unexpired, and still matching the user's state: an ``invite``
    needs an invited user, a ``reset`` an active one (a disabled user has no live link).
    """
    if (not isinstance(token, str) or not token.isascii()
            or not MIN_INVITE_TOKEN <= len(token) <= MAX_INVITE_TOKEN):
        return None
    row = conn.execute(
        "SELECT i.token_hash, i.user_id, i.purpose, i.expires_at, u.email, u.name, u.status "
        "FROM invites i JOIN users u ON u.id = i.user_id "
        "WHERE i.token_hash = ? AND i.used_at IS NULL AND i.expires_at > ?",
        (token_hash(token), db.now()),
    ).fetchone()
    if row is None or invite_purpose_for(row["status"]) != row["purpose"]:
        return None
    return row
