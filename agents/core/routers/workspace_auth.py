"""Nerva Workspace — sign-in, first-run setup, invites, profile and notifications (spec §7).

Public routes (``/session``, ``/setup``, ``/login``, ``/login/sso``, ``/invites/*``) are
guarded by the ``ws_enabled`` dependency and, for POSTs, by ``check_public_origin``
(same-origin + JSON only). Every other route needs a signed-in user (``WsUser``).

Password hashing and verification run in ``asyncio.to_thread`` and never inside a
database transaction: a 250 ms scrypt must not hold the write lock. Failed attempts
are committed before the error is raised so lockouts survive the error response.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from agents.core import proxy_trust
from agents.core.workspace import audit, auth, config, db, identity, notifications
from agents.core.workspace.auth import Enabled, WsUser
from agents.core.workspace.db import Db, tx
from agents.core.workspace.errors import WorkspaceError
from agents.core.workspace.http import (
    normalize_email,
    optional_bool,
    optional_choice,
    optional_id_list,
    optional_str,
    read_json,
    require_choice,
    require_email,
    require_str,
    ws_json,
    ws_no_content,
)
from agents.core.workspace.identity import WorkspaceUser

logger = logging.getLogger("nerva.workspace.routers.auth")

router = APIRouter(prefix="/api/workspace")

MAX_PASSWORD_INPUT = 1024
GENERAL_DEPARTMENT = "General"


def _invalid_credentials() -> WorkspaceError:
    return WorkspaceError("invalid_credentials", "wrong email or password", 401)


def departments_json(conn: sqlite3.Connection, department_ids: list[int]) -> list[dict]:
    """The given departments with member and document counts, by name.

    ``ready_document_count`` counts only documents the assistant can cite (status ``ready``):
    a department whose uploads all failed or are still processing has documents but nothing
    to answer from, and the chat says so.
    """
    if not department_ids:
        return []
    rows = conn.execute(
        "SELECT d.*, "
        "(SELECT COUNT(*) FROM user_departments ud JOIN users u ON u.id = ud.user_id "
        " WHERE ud.department_id = d.id AND u.status != 'disabled') AS member_count, "
        "(SELECT COUNT(*) FROM documents doc WHERE doc.department_id = d.id) AS document_count, "
        "(SELECT COUNT(*) FROM documents doc WHERE doc.department_id = d.id "
        " AND doc.status = 'ready') AS ready_document_count "
        "FROM departments d WHERE d.id IN (SELECT value FROM json_each(?)) "
        "ORDER BY d.name COLLATE NOCASE, d.id",
        (json.dumps(department_ids),),
    ).fetchall()
    result = []
    for row in rows:
        item = identity.department_to_json(row, counts={
            "member_count": int(row["member_count"]), "document_count": int(row["document_count"]),
            "ready_document_count": int(row["ready_document_count"]),
        })
        item.pop("assistant_instructions", None)
        result.append(item)
    return result


def _org_json(conn: sqlite3.Connection) -> dict | None:
    row = identity.ensure_org(conn)
    return identity.org_to_json(row) if row is not None else None


def _signed_in_payload(conn: sqlite3.Connection, user: WorkspaceUser, csrf: str) -> dict:
    return {"user": identity.user_to_json(user, conn), "org": _org_json(conn), "csrf_token": csrf}


def _loaded_user(conn: sqlite3.Connection, user_id: int) -> WorkspaceUser:
    user = identity.get_user(conn, user_id)
    if user is None:  # the row was written in this very transaction
        raise RuntimeError(f"workspace user {user_id} vanished inside its transaction")
    return user


# ── public ───────────────────────────────────────────────────────────────────────────

@router.get("/session")
def session_state(request: Request, conn: Db, _on: Enabled) -> JSONResponse:
    """What the SPA needs on boot: setup state, SSO availability and the signed-in user."""
    org = identity.ensure_org(conn)
    setup_required = org is None
    if setup_required:
        config.setup_code()  # make sure the operator has a code to read (file or env)
    payload: dict = {
        "enabled": True, "setup_required": setup_required,
        "sso_available": config.sso_configured(), "authenticated": False,
    }
    resolved = None if setup_required else auth.resolve_session(conn, request)
    if resolved is not None:
        session, user = resolved
        payload.update({
            "authenticated": True, "user": identity.user_to_json(user, conn),
            "org": identity.org_to_json(org), "csrf_token": session["csrf_token"],
            "departments": departments_json(conn, user.allowed_department_ids(conn)),
        })
    return ws_json(payload)


@router.post("/setup")
async def setup(request: Request, conn: Db, _on: Enabled) -> JSONResponse:
    """First-run: create the organisation, the „General" department and the first admin."""
    auth.check_public_origin(request)
    body = await read_json(request, max_bytes=8192)
    if identity.ensure_org(conn) is not None:
        raise WorkspaceError("already_setup", "the workspace is already set up", 409)
    ip = auth.client_ip(request)
    auth.check_setup_throttle(conn, ip=ip)
    code = require_str(body, "setup_code", max_len=200, min_len=1)
    if not hmac.compare_digest(code.encode("utf-8"), config.setup_code().encode("utf-8")):
        auth.record_attempt(conn, ip=ip, email="", ok=False, kind="setup")
        raise WorkspaceError("invalid_setup_code", "the setup code is not correct", 403)
    org_name = require_str(body, "org_name", max_len=200, min_len=1)
    name = require_str(body, "name", max_len=200, min_len=1)
    email = require_email(body, "email")
    password = require_str(body, "password", max_len=MAX_PASSWORD_INPUT, min_len=1, strip=False)
    locale = require_choice(body, "locale", identity.LOCALES, default="ro")
    identity.validate_password(password, email=email)
    password_hash = await asyncio.to_thread(identity.hash_password, password)
    holder = Response()
    with tx(conn):
        if identity.ensure_org(conn) is not None:
            raise WorkspaceError("already_setup", "the workspace is already set up", 409)
        stamp = db.now()
        conn.execute(
            "INSERT INTO org (id, name, default_locale, created_at) VALUES (1, ?, ?, ?)",
            (org_name, locale, stamp),
        )
        dept_id = conn.execute(
            "INSERT INTO departments (slug, name, created_at) VALUES (?, ?, ?)",
            (identity.unique_department_slug(conn, GENERAL_DEPARTMENT), GENERAL_DEPARTMENT, stamp),
        ).lastrowid
        user_id = conn.execute(
            "INSERT INTO users (email, name, role, status, password_hash, locale, created_at) "
            "VALUES (?, ?, 'admin', 'active', ?, ?, ?)",
            (email, name, password_hash, locale, stamp),
        ).lastrowid
        conn.execute("INSERT INTO user_departments (user_id, department_id) VALUES (?, ?)",
                     (user_id, dept_id))
        auth.record_attempt(conn, ip=ip, email=email, ok=True, kind="setup")
        csrf = auth.issue_session(conn, holder, request, int(user_id), via="setup")
        user = _loaded_user(conn, int(user_id))
        audit.record(conn, actor=user, action="auth.setup", target_type="org", target_id=1, ip=ip,
                     details={"org_name": org_name, "locale": locale, "department_id": dept_id})
        payload = _signed_in_payload(conn, user, csrf)
    config.clear_setup_code()
    logger.info("workspace set up for organisation %r", org_name)
    return ws_json(payload, 201, cookies_from=holder)


@router.post("/login")
async def login(request: Request, conn: Db, _on: Enabled) -> JSONResponse:
    """Email + password sign-in; one generic 401 for every kind of failure.

    What was typed in the email field is kept (attempt row, audit) only when it is an
    email address: anything else — a password typed into the wrong field, say — is
    recorded as ``''`` with reason ``invalid_identifier``, so it never lands in the
    append-only audit. No account can match it, so it has no per-email lockout of its
    own; the per-IP limit still counts it.
    """
    auth.check_public_origin(request)
    body = await read_json(request, max_bytes=8192)
    typed = require_str(body, "email", max_len=254, min_len=1)
    password = require_str(body, "password", max_len=MAX_PASSWORD_INPUT, min_len=1, strip=False)
    email = normalize_email(typed) or ""
    ip = auth.client_ip(request)
    attempt = auth.reserve_login_attempt(conn, email=email, ip=ip)
    row = identity.get_user_by_email(conn, email) if email else None
    stored = row["password_hash"] if row is not None else None
    ok = await asyncio.to_thread(identity.verify_password, password, stored)
    if not ok or row is None or row["status"] != "active":
        if not email:
            reason = "invalid_identifier"
        elif row is None:
            reason = "unknown_user"
        elif row["status"] != "active":
            reason = f"user_{row['status']}"
        else:
            reason = "wrong_password"
        auth.record_login_failure(conn, request, attempt_id=attempt, email=email, reason=reason,
                                  target_user_id=int(row["id"]) if row is not None else None)
        raise _invalid_credentials()
    holder = Response()
    try:
        with tx(conn):
            auth.settle_login_success(conn, attempt)
            csrf = auth.issue_session(conn, holder, request, int(row["id"]), via="password")
            user = _loaded_user(conn, int(row["id"]))
            audit.record(conn, actor=user, action="auth.login", target_type="user",
                         target_id=user.id, ip=ip, details={"via": "password"})
            payload = _signed_in_payload(conn, user, csrf)
    except audit.AuditKeyError:
        # The server cannot sign the row (503, the sign-in rolled back), but the password
        # was right: the reserved attempt must not count toward this account's lockout,
        # or people retrying during the incident stay locked out after it is fixed.
        auth.settle_login_success(conn, attempt)
        raise
    return ws_json(payload, cookies_from=holder)


def _sso_failure(conn: sqlite3.Connection, request: Request, *, email: str, reason: str,
                 code: str) -> WorkspaceError:
    """Commit the failed SSO attempt (trusted peers only) and build the error to raise."""
    ip = auth.client_ip(request)
    with tx(conn):
        auth.record_attempt(conn, ip=ip, email=email, ok=False, kind="sso")
        audit.record(conn, actor=None, actor_email=email, action="auth.login_failed",
                     target_type="user", ip=ip, details={"via": "sso", "reason": reason})
    if code == "invalid_credentials":
        return _invalid_credentials()
    return WorkspaceError("sso_no_identity", "the proxy did not vouch for a user", 401)


@router.post("/login/sso")
async def login_sso(request: Request, conn: Db, _on: Enabled) -> JSONResponse:
    """Sign in with the email a trusted reverse proxy asserts (header + shared secret)."""
    auth.check_public_origin(request)
    header, secret = config.sso_header(), config.sso_secret()
    if not (header and secret):
        raise WorkspaceError("sso_disabled", "single sign-on is not configured", 404)
    peer = request.client.host if request.client else ""
    try:
        trusted = proxy_trust.is_trusted_peer(peer)
    except ValueError as exc:
        raise WorkspaceError("sso_disabled", "JARVIS_TRUSTED_PROXIES is malformed", 404) from exc
    if not trusted:
        # Untrusted callers leave no rows: they cannot do anything, and must not be able
        # to grow the audit trail either.
        raise WorkspaceError("sso_no_identity", "the proxy did not vouch for a user", 401)
    secrets_sent = request.headers.getlist(auth.PROXY_KEY_HEADER)
    if len(secrets_sent) != 1 or not hmac.compare_digest(secrets_sent[0].encode("utf-8"),
                                                         secret.encode("utf-8")):
        raise _sso_failure(conn, request, email="", reason="bad_proxy_secret", code="sso_no_identity")
    values = request.headers.getlist(header)
    raw = values[0] if len(values) == 1 else ""
    email = normalize_email(raw) if "\r" not in raw and "\n" not in raw else None
    if email is None:
        raise _sso_failure(conn, request, email="", reason="no_identity", code="sso_no_identity")
    row = identity.get_user_by_email(conn, email)
    if row is None or row["status"] != "active":
        reason = "unknown_user" if row is None else f"user_{row['status']}"
        raise _sso_failure(conn, request, email=email, reason=reason, code="invalid_credentials")
    ip = auth.client_ip(request)
    holder = Response()
    with tx(conn):
        auth.record_attempt(conn, ip=ip, email=email, ok=True, kind="sso")
        csrf = auth.issue_session(conn, holder, request, int(row["id"]), via="sso", sso_email=email)
        user = _loaded_user(conn, int(row["id"]))
        audit.record(conn, actor=user, action="auth.sso_login", target_type="user",
                     target_id=user.id, ip=ip)
        payload = _signed_in_payload(conn, user, csrf)
    return ws_json(payload, cookies_from=holder)


@router.post("/invites/lookup")
async def invite_lookup(request: Request, conn: Db, _on: Enabled) -> JSONResponse:
    """Who an invite or reset link is for, so the accept page can greet them."""
    auth.check_public_origin(request)
    body = await read_json(request, max_bytes=4096)
    ip = auth.client_ip(request)
    auth.check_invite_throttle(conn, ip=ip)
    row = auth.find_invite(conn, body.get("token"))
    auth.record_attempt(conn, ip=ip, email=row["email"] if row is not None else "",
                        ok=row is not None, kind="invite_lookup")
    if row is None:
        raise WorkspaceError("invite_invalid", "this link is invalid, used or expired", 404)
    org = identity.ensure_org(conn)
    return ws_json({
        "email": row["email"], "name": row["name"], "org_name": org["name"] if org else "",
        "purpose": row["purpose"], "expires_at": row["expires_at"],
    })


def _consume_invite(conn: sqlite3.Connection, invite: sqlite3.Row, *, password_hash: str,
                    name: str | None) -> None:
    """Inside a tx: mark the link used and apply it (activate, or reset the password)."""
    stamp = db.now()
    claimed = conn.execute(
        "UPDATE invites SET used_at = ? WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
        (stamp, invite["token_hash"], stamp),
    )
    status_row = conn.execute("SELECT status FROM users WHERE id = ?", (invite["user_id"],)).fetchone()
    if (claimed.rowcount != 1 or status_row is None
            or auth.invite_purpose_for(status_row["status"]) != invite["purpose"]):
        raise WorkspaceError("invite_invalid", "this link is invalid, used or expired", 404)
    conn.execute("DELETE FROM invites WHERE user_id = ? AND used_at IS NULL", (invite["user_id"],))
    conn.execute(
        "UPDATE users SET password_hash = ?, status = 'active', name = COALESCE(?, name) "
        "WHERE id = ?",
        (password_hash, name, invite["user_id"]),
    )
    if invite["purpose"] == "reset":
        auth.revoke_user_sessions(conn, int(invite["user_id"]))


@router.post("/invites/accept")
async def invite_accept(request: Request, conn: Db, _on: Enabled) -> JSONResponse:
    """Set a password through an invite (activates the account) or a reset link."""
    auth.check_public_origin(request)
    body = await read_json(request, max_bytes=8192)
    ip = auth.client_ip(request)
    auth.check_invite_throttle(conn, ip=ip)
    invite = auth.find_invite(conn, body.get("token"))
    email = invite["email"] if invite is not None else ""
    try:
        if invite is None:
            raise WorkspaceError("invite_invalid", "this link is invalid, used or expired", 404)
        password = require_str(body, "password", max_len=MAX_PASSWORD_INPUT, min_len=1, strip=False)
        name = optional_str(body, "name", max_len=200, min_len=1)
        identity.validate_password(password, email=invite["email"])
        password_hash = await asyncio.to_thread(identity.hash_password, password)
        holder = Response()
        with tx(conn):
            _consume_invite(conn, invite, password_hash=password_hash, name=name)
            auth.record_attempt(conn, ip=ip, email=email, ok=True, kind="invite_lookup")
            user_id = int(invite["user_id"])
            csrf = auth.issue_session(conn, holder, request, user_id, via="invite")
            user = _loaded_user(conn, user_id)
            if invite["purpose"] == "invite":
                audit.record(conn, actor=user, action="auth.invite_accepted", target_type="user",
                             target_id=user_id, ip=ip, details={"purpose": "invite"})
            else:
                audit.record(conn, actor=user, action="auth.password_changed", target_type="user",
                             target_id=user_id, ip=ip, details={"via": "reset_link"})
            payload = _signed_in_payload(conn, user, csrf)
    except WorkspaceError:
        auth.record_attempt(conn, ip=ip, email=email, ok=False, kind="invite_lookup")
        raise
    return ws_json(payload, cookies_from=holder)


# ── signed-in user ───────────────────────────────────────────────────────────────────

@router.post("/logout")
def logout(request: Request, user: WsUser, conn: Db) -> Response:
    """Revoke the current session and clear its cookie."""
    id_hash = auth.current_session_hash(request) or ""
    with tx(conn):
        auth.revoke_session(conn, id_hash)
        audit.record(conn, actor=user, action="auth.logout", target_type="session",
                     target_id=id_hash[:12], ip=auth.client_ip(request))
    response = ws_no_content()
    auth.clear_session_cookie(response, request)
    return response


@router.get("/me")
def me(user: WsUser, conn: Db) -> JSONResponse:
    """The signed-in user, the organisation and the departments they may use."""
    return ws_json({
        "user": identity.user_to_json(user, conn), "org": _org_json(conn),
        "departments": departments_json(conn, user.allowed_department_ids(conn)),
    })


@router.patch("/me")
async def update_me(request: Request, user: WsUser, conn: Db) -> JSONResponse:
    """Change one's own display name, language or theme."""
    body = await read_json(request, max_bytes=4096)
    changes = {
        "name": optional_str(body, "name", max_len=200, min_len=1),
        "locale": optional_choice(body, "locale", identity.LOCALES),
        "theme": optional_choice(body, "theme", identity.THEMES),
    }
    current = {"name": user.name, "locale": user.locale, "theme": user.theme}
    changed = {key: value for key, value in changes.items()
               if value is not None and value != current[key]}
    if changed:
        with tx(conn):
            conn.execute(
                "UPDATE users SET name = COALESCE(?, name), locale = COALESCE(?, locale), "
                "theme = COALESCE(?, theme) WHERE id = ?",
                (changed.get("name"), changed.get("locale"), changed.get("theme"), user.id),
            )
            audit.record(conn, actor=user, action="user.updated", target_type="user",
                         target_id=user.id, ip=auth.client_ip(request),
                         details={"fields": sorted(changed), "self": True})
    return ws_json({"user": identity.user_to_json(_loaded_user(conn, user.id), conn)})


@router.post("/me/password")
async def change_password(request: Request, user: WsUser, conn: Db) -> Response:
    """Change one's password (needs the current one); every other session is revoked."""
    body = await read_json(request, max_bytes=8192)
    current = require_str(body, "current_password", max_len=MAX_PASSWORD_INPUT, min_len=1,
                          strip=False)
    new = require_str(body, "new_password", max_len=MAX_PASSWORD_INPUT, min_len=1, strip=False)
    ip = auth.client_ip(request)
    attempt = auth.reserve_login_attempt(conn, email=user.email, ip=ip)
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()
    ok = await asyncio.to_thread(identity.verify_password, current, row["password_hash"])
    if not ok:
        auth.record_login_failure(conn, request, attempt_id=attempt, email=user.email,
                                  reason="wrong_current_password", actor=user)
        raise WorkspaceError("wrong_password", "the current password is not correct", 403)
    # The current password is proven even if the new one is refused below.
    auth.settle_login_success(conn, attempt)
    identity.validate_password(new, email=user.email)
    new_hash = await asyncio.to_thread(identity.hash_password, new)
    keep = auth.current_session_hash(request)
    with tx(conn):
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user.id))
        revoked = auth.revoke_user_sessions(conn, user.id, keep=keep)
        audit.record(conn, actor=user, action="auth.password_changed", target_type="user",
                     target_id=user.id, ip=ip, details={"via": "profile", "revoked_sessions": revoked})
    return ws_no_content()


def _live_sessions(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    stamp = db.now()
    return conn.execute(
        "SELECT * FROM sessions WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ? "
        "AND last_seen_at > ? ORDER BY last_seen_at DESC",
        (user_id, stamp, stamp - config.session_idle_seconds()),
    ).fetchall()


@router.get("/me/sessions")
def my_sessions(request: Request, user: WsUser, conn: Db) -> JSONResponse:
    """The caller's live sessions (``id`` = first 12 hex chars of the stored hash)."""
    current = auth.current_session_hash(request)
    return ws_json({"sessions": [
        {"id": row["id_hash"][:12], "current": row["id_hash"] == current,
         "created_at": row["created_at"], "last_seen_at": row["last_seen_at"], "ip": row["ip"],
         "user_agent": row["user_agent"], "via": row["via"]}
        for row in _live_sessions(conn, user.id)
    ]})


@router.delete("/me/sessions/{session_id}")
def revoke_my_session(
    request: Request, user: WsUser, conn: Db,
    session_id: Annotated[str, Path(min_length=12, max_length=12, pattern="^[0-9a-f]{12}$")],
) -> Response:
    """Sign out one other device; the current session is ended through logout instead."""
    match = next((row for row in _live_sessions(conn, user.id)
                  if row["id_hash"].startswith(session_id)), None)
    if match is None:
        raise WorkspaceError("not_found", "no such session", 404)
    if match["id_hash"] == auth.current_session_hash(request):
        raise WorkspaceError("cannot_revoke_current", "use sign out for this session", 409)
    with tx(conn):
        auth.revoke_session(conn, match["id_hash"])
        audit.record(conn, actor=user, action="session.revoked", target_type="session",
                     target_id=session_id, ip=auth.client_ip(request), details={"scope": "one"})
    return ws_no_content()


@router.post("/me/sessions/revoke-others")
def revoke_other_sessions(request: Request, user: WsUser, conn: Db) -> JSONResponse:
    """Sign out every other device of the caller."""
    with tx(conn):
        revoked = auth.revoke_user_sessions(conn, user.id, keep=auth.current_session_hash(request))
        if revoked:
            audit.record(conn, actor=user, action="session.revoked", target_type="user",
                         target_id=user.id, ip=auth.client_ip(request),
                         details={"scope": "others", "count": revoked})
    return ws_json({"revoked": revoked})


@router.get("/departments")
def my_departments(user: WsUser, conn: Db) -> JSONResponse:
    """Departments the caller may work in (admins: every non-archived one)."""
    return ws_json({"departments": departments_json(conn, user.allowed_department_ids(conn))})


@router.get("/notifications")
def my_notifications(
    user: WsUser, conn: Db,
    unread: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JSONResponse:
    """The caller's newest notifications and the unread count for the bell."""
    return ws_json({
        "items": notifications.list_for_user(conn, user.id, unread_only=unread, limit=limit),
        "unread_count": notifications.unread_count(conn, user.id),
    })


@router.post("/notifications/read")
async def read_notifications(request: Request, user: WsUser, conn: Db) -> JSONResponse:
    """Mark some (``ids``) or all (``all: true``) of the caller's notifications read."""
    body = await read_json(request, max_bytes=8192, allow_empty=True)
    ids = optional_id_list(body, "ids")
    everything = bool(optional_bool(body, "all", default=False))
    notifications.mark_read(conn, user.id, ids=ids, all_unread=everything)
    return ws_json({"unread_count": notifications.unread_count(conn, user.id)})
