"""Nerva Workspace — admin console API: users, departments, organisation, audit, usage (spec §7).

Every route needs an admin (``WsAdmin``). Two invariants are enforced inside the
write transaction, so two admins acting at once cannot both slip past them: the last
active admin can never be demoted or disabled (``409 last_admin``) and nobody can
disable themself (``409 cannot_disable_self``).

Invite and reset links are returned to the admin (to copy) and, on request, emailed
through the S4 mailer, imported lazily: when the mailer is missing or SMTP is not
configured the user is still created and the answer says ``emailed: false`` with an
``email_error`` the UI can explain.
"""

from __future__ import annotations

import csv
import importlib
import io
import json
import logging
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Annotated
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from agents.core.workspace import audit, auth, db, identity, notifications
from agents.core.workspace.auth import WsAdmin
from agents.core.workspace.db import Db, tx
from agents.core.workspace.errors import WorkspaceError
from agents.core.workspace.http import (
    MAX_ID,
    invalid,
    offload,
    optional_bool,
    optional_choice,
    optional_id_list,
    optional_str,
    read_json,
    require_choice,
    require_email,
    require_id_list,
    require_str,
    ws_json,
    ws_no_content,
)
from agents.core.workspace.identity import WorkspaceUser

logger = logging.getLogger("nerva.workspace.routers.admin")

router = APIRouter(prefix="/api/workspace")

MAX_TEXT = 4000
AUDIT_PAGE_MAX = 200
AUDIT_EXPORT_MAX = 50_000
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
MAILER_MODULE = "agents.core.workspace.mailer"
UserId = Annotated[int, Path(ge=1, le=MAX_ID)]
DepartmentId = Annotated[int, Path(ge=1, le=MAX_ID)]


def _not_found(what: str) -> WorkspaceError:
    return WorkspaceError("not_found", f"no such {what}", 404)


# ── users ────────────────────────────────────────────────────────────────────────────

def _pending_invite(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute(
        "SELECT purpose, created_at, expires_at FROM invites WHERE user_id = ? AND used_at IS NULL "
        "AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
        (user_id, db.now()),
    ).fetchone()
    return dict(row) if row is not None else None


def admin_user_json(conn: sqlite3.Connection, user: WorkspaceUser) -> dict:
    """A user as the admin console shows it: every membership, last login, pending link."""
    row = conn.execute("SELECT last_login_at, created_at FROM users WHERE id = ?",
                       (user.id,)).fetchone()
    data = identity.user_to_json(user)
    data.update({
        "department_ids": identity.member_department_ids(conn, user.id),
        "last_login_at": row["last_login_at"], "created_at": row["created_at"],
        "pending_invite": _pending_invite(conn, user.id),
    })
    return data


def _loaded(conn: sqlite3.Connection, user_id: int) -> WorkspaceUser:
    user = identity.get_user(conn, user_id)
    if user is None:
        raise _not_found("user")
    return user


def _check_departments(conn: sqlite3.Connection, department_ids: list[int], *,
                       already: list[int]) -> None:
    """Every id exists; a new membership may not point at an archived department."""
    rows = conn.execute(
        "SELECT id, archived FROM departments WHERE id IN (SELECT value FROM json_each(?))",
        (json.dumps(department_ids),),
    ).fetchall()
    found = {int(row["id"]): bool(row["archived"]) for row in rows}
    missing = [dept_id for dept_id in department_ids if dept_id not in found]
    if missing:
        raise WorkspaceError("not_found", "no such department", 404, department_ids=missing)
    archived = [dept_id for dept_id in department_ids if found[dept_id] and dept_id not in already]
    if archived:
        raise WorkspaceError("department_archived", "this department is archived", 409,
                             department_ids=archived)


def _set_memberships(conn: sqlite3.Connection, user_id: int, department_ids: list[int]) -> None:
    conn.execute("DELETE FROM user_departments WHERE user_id = ?", (user_id,))
    conn.executemany("INSERT INTO user_departments (user_id, department_id) VALUES (?, ?)",
                     [(user_id, dept_id) for dept_id in department_ids])


def _link_email(locale: str, *, org_name: str, admin_name: str, user_name: str, url: str,
                purpose: str) -> tuple[str, str]:
    """Subject and plain-text body of an invite or reset email, in the user's language."""
    if locale == "en":
        if purpose == "invite":
            subject = f"Invitation to Nerva Workspace — {org_name}"
            lead = f"{admin_name} invited you to Nerva Workspace at {org_name}."
        else:
            subject = f"Nerva Workspace password reset — {org_name}"
            lead = f"{admin_name} issued a password reset link for your Nerva Workspace account."
        text = (f"Hello {user_name},\n\n{lead}\nOpen the link below to set your password "
                f"(valid for 72 hours, single use):\n\n{url}\n\n"
                "If you did not expect this message you can ignore it.\n")
        return subject, text
    if purpose == "invite":
        subject = f"Invitație în Nerva Workspace — {org_name}"
        lead = f"{admin_name} v-a invitat în Nerva Workspace pentru {org_name}."
    else:
        subject = f"Resetarea parolei Nerva Workspace — {org_name}"
        lead = f"{admin_name} a emis un link de resetare a parolei pentru contul dvs. Nerva Workspace."
    text = (f"Bună ziua, {user_name},\n\n{lead}\nDeschideți linkul de mai jos pentru a vă seta "
            f"parola (valabil 72 de ore, o singură utilizare):\n\n{url}\n\n"
            "Dacă nu vă așteptați la acest mesaj, îl puteți ignora.\n")
    return subject, text


async def _email_link(conn: sqlite3.Connection, request: Request, admin: WorkspaceUser,
                      user: WorkspaceUser, url: str, purpose: str) -> str | None:
    """Email *url* to *user*; ``None`` on success, else the error code to show the admin."""
    try:
        mailer = importlib.import_module(MAILER_MODULE)
    except ImportError:
        return "smtp_not_configured"

    def _sync_2():
        org = identity.ensure_org(conn)
        subject, text = _link_email(user.locale, org_name=org["name"] if org else "",
                                    admin_name=admin.name, user_name=user.name, url=url, purpose=purpose)
        error: str | None = None
        return error, subject, text

    error, subject, text = await offload(_sync_2)
    try:
        # Reading the settings can fail too (an unreadable secret store): the user and
        # the link already exist, so any failure is reported, never raised.
        if not mailer.smtp_configured(conn):
            return "smtp_not_configured"
        await mailer.send_mail(to=[user.email], subject=subject, text=text)
    except WorkspaceError as exc:
        error = exc.code
    except Exception:  # an SMTP library failure must never undo the user's creation
        logger.exception("sending the %s email failed", purpose)
        error = "smtp_failed"

    def _sync_1():
        with tx(conn):
            audit.record(conn, actor=admin, action="email.failed" if error else "email.sent",
                         target_type="user", target_id=user.id, ip=auth.client_ip(request),
                         details={"purpose": purpose, "recipients": 1,
                                  **({"error_code": error} if error else {})})
        return error

    return await offload(_sync_1)


async def _link_payload(conn: sqlite3.Connection, request: Request, admin: WorkspaceUser,
                        user: WorkspaceUser, token: str, purpose: str, send_email: bool) -> dict:
    url = auth.invite_url(auth.base_url(request), token)
    payload: dict = {"invite_url": url, "purpose": purpose, "emailed": False}
    if send_email:
        error = await _email_link(conn, request, admin, user, url, purpose)
        payload["emailed"] = error is None
        if error:
            payload["email_error"] = error
    return payload


@router.get("/admin/users")
def list_users(admin: WsAdmin, conn: Db) -> JSONResponse:
    """Every user with memberships, last login and any pending invite/reset link."""
    rows = conn.execute("SELECT id FROM users ORDER BY name COLLATE NOCASE, id").fetchall()
    return ws_json({"users": [admin_user_json(conn, _loaded(conn, int(row["id"]))) for row in rows]})


@router.post("/admin/users")
async def create_user(request: Request, admin: WsAdmin, conn: Db) -> JSONResponse:
    """Invite a new user: created as ``invited`` with a 72 h single-use link."""
    body = await read_json(request)
    email = require_email(body, "email")
    name = require_str(body, "name", max_len=200, min_len=1)
    role = require_choice(body, "role", identity.ROLES)
    department_ids = require_id_list(body, "department_ids", min_items=1)
    send_email = bool(optional_bool(body, "send_email", default=False))
    ip = auth.client_ip(request)

    def _sync_2():
        with tx(conn):
            _check_departments(conn, department_ids, already=[])
            if identity.get_user_by_email(conn, email) is not None:
                raise WorkspaceError("email_taken", "a user with this email already exists", 409,
                                     field="email")
            org = identity.ensure_org(conn)
            user_id = int(conn.execute(
                "INSERT INTO users (email, name, role, status, locale, created_at) "
                "VALUES (?, ?, ?, 'invited', ?, ?)",
                (email, name, role, org["default_locale"] if org else "ro", db.now()),
            ).lastrowid)
            _set_memberships(conn, user_id, department_ids)
            token, expires_at = auth.issue_invite(conn, user_id, purpose="invite", created_by=admin.id)
            audit.record(conn, actor=admin, action="user.created", target_type="user",
                         target_id=user_id, ip=ip,
                         details={"role": role, "department_ids": department_ids})
            audit.record(conn, actor=admin, action="user.invite_issued", target_type="user",
                         target_id=user_id, ip=ip, details={"purpose": "invite", "expires_at": expires_at})
        user = _loaded(conn, user_id)
        return token, user

    token, user = await offload(_sync_2)
    payload = await _link_payload(conn, request, admin, user, token, "invite", send_email)
    payload.pop("purpose")

    def _sync_1():
        return ws_json({"user": admin_user_json(conn, user), **payload}, 201)

    return await offload(_sync_1)


def _next_status(target_status: str, requested: str | None, has_password: bool) -> str:
    """Enabling a user restores ``active`` only when they have a password, else ``invited``."""
    if requested == "disabled":
        return "disabled"
    if requested == "active" and target_status == "disabled":
        return "active" if has_password else "invited"
    return target_status


@router.patch("/admin/users/{user_id}")
async def update_user(request: Request, user_id: UserId, admin: WsAdmin, conn: Db) -> JSONResponse:
    """Rename, change role/departments, disable or enable a user."""
    body = await read_json(request)
    name = optional_str(body, "name", max_len=200, min_len=1)
    role = optional_choice(body, "role", identity.ROLES)
    department_ids = optional_id_list(body, "department_ids", min_items=1)
    status = optional_choice(body, "status", ("active", "disabled"))
    ip = auth.client_ip(request)

    def _sync_1():
        with tx(conn):
            target = _loaded(conn, user_id)
            has_password = conn.execute("SELECT password_hash IS NOT NULL AS p FROM users WHERE id = ?",
                                        (user_id,)).fetchone()["p"]
            new_role = role or target.role
            new_status = _next_status(target.status, status, bool(has_password))
            if new_status == "disabled" and target.id == admin.id:
                raise WorkspaceError("cannot_disable_self", "you cannot disable your own account", 409)
            loses_admin = (target.is_admin and target.status == "active"
                           and (new_role != "admin" or new_status != "active"))
            if loses_admin and not notifications.admins(conn, exclude=target.id):
                raise WorkspaceError("last_admin", "the workspace needs at least one active admin", 409)
            changed: list[str] = []
            current_memberships = identity.member_department_ids(conn, user_id)
            if department_ids is not None and sorted(department_ids) != current_memberships:
                _check_departments(conn, department_ids, already=current_memberships)
                _set_memberships(conn, user_id, department_ids)
                changed.append("department_ids")
            if name is not None and name != target.name:
                changed.append("name")
            conn.execute("UPDATE users SET name = COALESCE(?, name), role = ?, status = ? WHERE id = ?",
                         (name, new_role, new_status, user_id))
            role_changed = new_role != target.role
            status_changed = new_status != target.status
            if role_changed or (status_changed and new_status == "disabled"):
                auth.revoke_user_sessions(conn, user_id)
            if status_changed and new_status == "disabled":
                conn.execute("DELETE FROM invites WHERE user_id = ? AND used_at IS NULL", (user_id,))
            if status_changed:
                audit.record(conn, actor=admin,
                             action="user.disabled" if new_status == "disabled" else "user.enabled",
                             target_type="user", target_id=user_id, ip=ip,
                             details={"from": target.status, "to": new_status})
            if role_changed:
                audit.record(conn, actor=admin,
                             action="user.promoted" if new_role == "admin" else "user.updated",
                             target_type="user", target_id=user_id, ip=ip,
                             details={"fields": ["role"], "from": target.role, "to": new_role})
            if changed:
                details: dict = {"fields": changed}
                if "department_ids" in changed:
                    details["department_ids"] = department_ids
                audit.record(conn, actor=admin, action="user.updated", target_type="user",
                             target_id=user_id, ip=ip, details=details)
        return ws_json({"user": admin_user_json(conn, _loaded(conn, user_id))})

    return await offload(_sync_1)


@router.post("/admin/users/{user_id}/invite")
async def reissue_link(request: Request, user_id: UserId, admin: WsAdmin, conn: Db) -> JSONResponse:
    """A new invite (invited user) or password-reset link (active user); older ones die."""
    body = await read_json(request, max_bytes=4096, allow_empty=True)
    send_email = bool(optional_bool(body, "send_email", default=False))

    def _sync_1():
        with tx(conn):
            target = _loaded(conn, user_id)
            purpose = auth.invite_purpose_for(target.status)
            if purpose is None:
                raise WorkspaceError("user_disabled", "enable the user before issuing a link", 409)
            token, expires_at = auth.issue_invite(conn, user_id, purpose=purpose, created_by=admin.id)
            audit.record(conn, actor=admin,
                         action="user.invite_issued" if purpose == "invite" else "auth.reset_link_issued",
                         target_type="user", target_id=user_id, ip=auth.client_ip(request),
                         details={"purpose": purpose, "expires_at": expires_at})
        return expires_at, purpose, target, token

    expires_at, purpose, target, token = await offload(_sync_1)
    payload = await _link_payload(conn, request, admin, target, token, purpose, send_email)
    return ws_json({**payload, "expires_at": expires_at})


# ── departments ──────────────────────────────────────────────────────────────────────

_DEPARTMENT_COUNTS_SQL = (
    "SELECT d.*, "
    "(SELECT COUNT(*) FROM user_departments ud WHERE ud.department_id = d.id) AS member_count, "
    "(SELECT COUNT(*) FROM documents doc WHERE doc.department_id = d.id) AS document_count, "
    "(SELECT COUNT(*) FROM documents doc WHERE doc.department_id = d.id "
    " AND doc.status = 'ready') AS ready_document_count, "
    "(SELECT COUNT(*) FROM reports r WHERE r.department_id = d.id) AS report_count, "
    "(SELECT COUNT(*) FROM conversations c WHERE c.department_id = d.id) AS conversation_count "
    "FROM departments d WHERE (? IS NULL OR d.id = ?) "
    "ORDER BY d.archived, d.name COLLATE NOCASE, d.id"
)
_COUNT_KEYS = ("member_count", "document_count", "ready_document_count", "report_count",
               "conversation_count")


def _department_rows(conn: sqlite3.Connection, department_id: int | None = None) -> list[dict]:
    rows = conn.execute(_DEPARTMENT_COUNTS_SQL, (department_id, department_id)).fetchall()
    return [identity.department_to_json(row, counts={key: int(row[key]) for key in _COUNT_KEYS})
            for row in rows]


def _department(conn: sqlite3.Connection, department_id: int) -> dict:
    rows = _department_rows(conn, department_id)
    if not rows:
        raise _not_found("department")
    return rows[0]


def _check_unique_name(conn: sqlite3.Connection, name: str, *, exclude: int | None = None) -> None:
    """Names are unique ignoring case — in Python, since SQLite's NOCASE folds ASCII only
    and „VÂNZĂRI" must clash with „Vânzări"."""
    folded = name.casefold()
    for row in conn.execute("SELECT id, name FROM departments").fetchall():
        if row["id"] != exclude and row["name"].casefold() == folded:
            raise WorkspaceError("department_exists", "a department with this name exists", 409,
                                 field="name")


@router.get("/admin/departments")
def list_departments(admin: WsAdmin, conn: Db) -> JSONResponse:
    """Every department, archived included, with member/document/report/conversation counts."""
    return ws_json({"departments": _department_rows(conn)})


@router.post("/admin/departments")
async def create_department(request: Request, admin: WsAdmin, conn: Db) -> JSONResponse:
    """Create a department; its slug is derived from the name and kept stable afterwards."""
    body = await read_json(request)
    name = require_str(body, "name", max_len=200, min_len=1)
    description = require_str(body, "description", max_len=MAX_TEXT, required=False, multiline=True)
    instructions = require_str(body, "assistant_instructions", max_len=MAX_TEXT, required=False,
                               multiline=True)

    def _sync_1():
        with tx(conn):
            _check_unique_name(conn, name)
            slug = identity.unique_department_slug(conn, name)
            dept_id = int(conn.execute(
                "INSERT INTO departments (slug, name, description, assistant_instructions, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (slug, name, description, instructions, db.now()),
            ).lastrowid)
            audit.record(conn, actor=admin, action="department.created", target_type="department",
                         target_id=dept_id, department_id=dept_id, ip=auth.client_ip(request),
                         details={"name": name, "slug": slug})
        return ws_json(_department(conn, dept_id), 201)

    return await offload(_sync_1)


@router.patch("/admin/departments/{department_id}")
async def update_department(request: Request, department_id: DepartmentId, admin: WsAdmin,
                            conn: Db) -> JSONResponse:
    """Rename, re-describe, change assistant instructions, archive or restore."""
    body = await read_json(request)
    changes = {
        "name": optional_str(body, "name", max_len=200, min_len=1),
        "description": optional_str(body, "description", max_len=MAX_TEXT, multiline=True),
        "assistant_instructions": optional_str(body, "assistant_instructions", max_len=MAX_TEXT,
                                               multiline=True),
    }
    archived = optional_bool(body, "archived")
    ip = auth.client_ip(request)

    def _sync_1():
        with tx(conn):
            current = _department(conn, department_id)
            if changes["name"] is not None:
                _check_unique_name(conn, changes["name"], exclude=department_id)
            fields = [key for key, value in changes.items() if value is not None and value != current[key]]
            conn.execute(
                "UPDATE departments SET name = COALESCE(?, name), description = COALESCE(?, description), "
                "assistant_instructions = COALESCE(?, assistant_instructions), "
                "archived = COALESCE(?, archived) WHERE id = ?",
                (changes["name"], changes["description"], changes["assistant_instructions"],
                 None if archived is None else int(archived), department_id),
            )
            if archived is True and not current["archived"]:
                audit.record(conn, actor=admin, action="department.archived", target_type="department",
                             target_id=department_id, department_id=department_id, ip=ip)
            elif archived is False and current["archived"]:
                fields.append("archived")
            if fields:
                audit.record(conn, actor=admin, action="department.updated", target_type="department",
                             target_id=department_id, department_id=department_id, ip=ip,
                             details={"fields": fields})
        return ws_json(_department(conn, department_id))

    return await offload(_sync_1)


@router.delete("/admin/departments/{department_id}")
def delete_department(request: Request, department_id: DepartmentId, admin: WsAdmin,
                      conn: Db) -> Response:
    """Delete an empty department (no members, documents, reports or conversations).

    Approval history pointing at it is kept and detached (``department_id`` → NULL) —
    the audit trail already names the department.
    """
    with tx(conn):
        current = _department(conn, department_id)
        counts = {key: current[key] for key in _COUNT_KEYS}
        if any(counts.values()):
            raise WorkspaceError("department_not_empty", "move or remove its content first", 409,
                                 **counts)
        detached = conn.execute("UPDATE approvals SET department_id = NULL WHERE department_id = ?",
                                (department_id,)).rowcount
        conn.execute("DELETE FROM departments WHERE id = ?", (department_id,))
        audit.record(conn, actor=admin, action="department.deleted", target_type="department",
                     target_id=department_id, ip=auth.client_ip(request),
                     details={"name": current["name"], "slug": current["slug"],
                              "detached_approvals": detached})
    return ws_no_content()


# ── organisation ─────────────────────────────────────────────────────────────────────

def _org(conn: sqlite3.Connection) -> sqlite3.Row:
    row = identity.ensure_org(conn)
    if row is None:
        raise WorkspaceError("setup_required", "the workspace is not set up yet", 409)
    return row


@router.get("/admin/org")
def get_org(admin: WsAdmin, conn: Db) -> JSONResponse:
    """Organisation name, default language and model policy."""
    return ws_json(identity.org_to_json(_org(conn)))


@router.patch("/admin/org")
async def update_org(request: Request, admin: WsAdmin, conn: Db) -> JSONResponse:
    """Change the organisation name, default language or model policy."""
    body = await read_json(request, max_bytes=4096)
    changes = {
        "name": optional_str(body, "name", max_len=200, min_len=1),
        "default_locale": optional_choice(body, "default_locale", identity.LOCALES),
        "model_policy": optional_choice(body, "model_policy", ("local_only", "allow_cloud")),
    }

    def _sync_1():
        with tx(conn):
            current = identity.org_to_json(_org(conn))
            changed = {key: value for key, value in changes.items()
                       if value is not None and value != current[key]}
            if changed:
                conn.execute(
                    "UPDATE org SET name = COALESCE(?, name), default_locale = COALESCE(?, default_locale), "
                    "model_policy = COALESCE(?, model_policy) WHERE id = 1",
                    (changed.get("name"), changed.get("default_locale"), changed.get("model_policy")),
                )
                details: dict = {"fields": sorted(changed)}
                if "model_policy" in changed:
                    details["model_policy"] = {"from": current["model_policy"],
                                               "to": changed["model_policy"]}
                audit.record(conn, actor=admin, action="org.updated", target_type="org", target_id=1,
                             ip=auth.client_ip(request), details=details)
        return ws_json(identity.org_to_json(_org(conn)))

    return await offload(_sync_1)


# ── audit ────────────────────────────────────────────────────────────────────────────

# One static statement with optional filters ("? IS NULL OR …"): no SQL is ever built
# from strings. An action filter matches exactly, or as a group ("auth" → "auth.*").
_AUDIT_SQL = (
    "SELECT a.*, u.name AS actor_name FROM audit a LEFT JOIN users u ON u.id = a.actor_user_id "
    "WHERE (? IS NULL OR a.actor_user_id = ?) "
    "AND (? IS NULL OR a.action = ? OR substr(a.action, 1, length(?) + 1) = ? || '.') "
    "AND (? IS NULL OR a.ts >= ?) AND (? IS NULL OR a.ts < ?) AND (? IS NULL OR a.id < ?) "
    "ORDER BY a.id DESC LIMIT ?"
)
ActorId = Annotated[int | None, Query(ge=1, le=MAX_ID)]
ActionFilter = Annotated[str | None, Query(max_length=64, pattern=r"^[a-z_]+(\.[a-z_]+)*$")]
TimeFilter = Annotated[float | None, Query(ge=0)]
BeforeId = Annotated[int | None, Query(ge=1, le=MAX_ID)]


def _audit_rows(conn: sqlite3.Connection, *, actor_id: int | None, action: str | None,
                since: float | None, until: float | None, before_id: int | None,
                limit: int) -> list[sqlite3.Row]:
    params = (actor_id, actor_id, action, action, action, action, since, since, until, until,
              before_id, before_id, limit)
    return conn.execute(_AUDIT_SQL, params).fetchall()


def _audit_item(row: sqlite3.Row) -> dict:
    try:
        details = json.loads(row["details_json"])
    except ValueError:
        details = {}
    return {
        "id": int(row["id"]), "ts": row["ts"], "actor_user_id": row["actor_user_id"],
        "actor_email": row["actor_email"], "actor_name": row["actor_name"], "action": row["action"],
        "target_type": row["target_type"], "target_id": row["target_id"],
        "department_id": row["department_id"], "ip": row["ip"], "details": details,
    }


@router.get("/admin/audit")
def list_audit(
    admin: WsAdmin, conn: Db, actor_id: ActorId = None, action: ActionFilter = None,
    since: TimeFilter = None, until: TimeFilter = None,
    limit: Annotated[int, Query(ge=1, le=AUDIT_PAGE_MAX)] = 50, before_id: BeforeId = None,
) -> JSONResponse:
    """Newest-first audit page; pass ``next_before_id`` back as ``before_id`` for more."""
    rows = _audit_rows(conn, actor_id=actor_id, action=action, since=since, until=until,
                       before_id=before_id, limit=limit)
    items = [_audit_item(row) for row in rows]
    next_before = items[-1]["id"] if len(items) == limit else None
    return ws_json({"items": items, "next_before_id": next_before})


def csv_cell(value: object) -> str:
    """A CSV cell that spreadsheet apps will not evaluate as a formula."""
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(CSV_FORMULA_PREFIXES) else text


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/admin/audit/export")
def export_audit(
    admin: WsAdmin, conn: Db, actor_id: ActorId = None, action: ActionFilter = None,
    since: TimeFilter = None, until: TimeFilter = None, before_id: BeforeId = None,
) -> Response:
    """The matching rows (newest 50 000, oldest first) as a UTF-8 CSV attachment."""
    rows = _audit_rows(conn, actor_id=actor_id, action=action, since=since, until=until,
                       before_id=before_id, limit=AUDIT_EXPORT_MAX)
    buffer = io.StringIO()
    buffer.write("﻿")  # BOM: Excel then reads Romanian diacritics correctly
    writer = csv.writer(buffer)
    writer.writerow(["id", "time_utc", "ts", "actor_user_id", "actor_email", "actor_name",
                     "action", "target_type", "target_id", "department_id", "ip", "details",
                     "hash"])
    for row in reversed(rows):
        writer.writerow([csv_cell(value) for value in (
            row["id"], _iso(row["ts"]), row["ts"], row["actor_user_id"], row["actor_email"],
            row["actor_name"], row["action"], row["target_type"], row["target_id"],
            row["department_id"], row["ip"], row["details_json"], row["hash"],
        )])
    filename = f"nerva-audit-{datetime.fromtimestamp(db.now(), tz=UTC).strftime('%Y%m%d-%H%M%S')}.csv"
    return Response(buffer.getvalue().encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={
                        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
                        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
                    })


@router.get("/admin/audit/verify")
def verify_audit(admin: WsAdmin, conn: Db) -> JSONResponse:
    """Re-verify the whole HMAC chain with the current key."""
    return ws_json(audit.verify_chain(conn))


# ── usage ────────────────────────────────────────────────────────────────────────────

def _count(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


# Questions asked and report runs started in a period are counted from the audit trail, not
# from the messages and report_runs tables: those rows go away when someone deletes a
# conversation or a report, and a usage figure for a period must not shrink afterwards. The
# trail is append-only (an HMAC chain) and records exactly one row, with its department, per
# question (chat.asked, written with the question) and per run (report.run_started, written
# when a manual or scheduled run is queued); the run-rate limit counts the same rows.
ACTIVITY_ACTIONS = {"questions": "chat.asked", "report_runs": "report.run_started"}
_ACTIVITY_SQL = "SELECT COUNT(*) FROM audit WHERE action = ? AND ts >= ?"


def _totals(conn: sqlite3.Connection, *, since: float, week_ago: float) -> dict:
    return {
        "users": _count(conn, "SELECT COUNT(*) FROM users WHERE status != 'disabled'"),
        "active_users_7d": _count(
            conn, "SELECT COUNT(DISTINCT user_id) FROM sessions WHERE last_seen_at >= ?",
            (week_ago,)),
        "documents": _count(conn, "SELECT COUNT(*) FROM documents"),
        "conversations": _count(conn, "SELECT COUNT(*) FROM conversations"),
        "questions": _count(conn, _ACTIVITY_SQL, (ACTIVITY_ACTIONS["questions"], since)),
        "reports": _count(conn, "SELECT COUNT(*) FROM reports"),
        "report_runs": _count(conn, _ACTIVITY_SQL, (ACTIVITY_ACTIONS["report_runs"], since)),
        "approvals_pending": _count(conn, "SELECT COUNT(*) FROM approvals WHERE status = 'pending'"),
        "feedback_up": _count(
            conn, "SELECT COUNT(*) FROM messages WHERE role = 'assistant' AND feedback = 1 "
            "AND created_at >= ?", (since,)),
        "feedback_down": _count(
            conn, "SELECT COUNT(*) FROM messages WHERE role = 'assistant' AND feedback = -1 "
            "AND created_at >= ?", (since,)),
    }


_PER_DEPARTMENT_SQL = (
    "SELECT d.id, d.slug, d.name, d.archived, "
    "(SELECT COUNT(*) FROM user_departments ud JOIN users u ON u.id = ud.user_id "
    " WHERE ud.department_id = d.id AND u.status != 'disabled') AS members, "
    "(SELECT COUNT(*) FROM documents doc WHERE doc.department_id = d.id) AS documents, "
    "(SELECT COUNT(*) FROM conversations c WHERE c.department_id = d.id) AS conversations, "
    "(SELECT COUNT(*) FROM audit a WHERE a.department_id = d.id AND a.action = ? "
    " AND a.ts >= ?) AS questions, "
    "(SELECT COUNT(*) FROM reports r WHERE r.department_id = d.id) AS reports, "
    "(SELECT COUNT(*) FROM audit a WHERE a.department_id = d.id AND a.action = ? "
    " AND a.ts >= ?) AS report_runs "
    "FROM departments d ORDER BY d.archived, d.name COLLATE NOCASE, d.id"
)


def _per_department(conn: sqlite3.Connection, *, since: float) -> list[dict]:
    rows = conn.execute(_PER_DEPARTMENT_SQL, (ACTIVITY_ACTIONS["questions"], since,
                                              ACTIVITY_ACTIONS["report_runs"], since)).fetchall()
    return [{
        "department_id": int(row["id"]), "slug": row["slug"], "name": row["name"],
        "archived": bool(row["archived"]),
        **{key: int(row[key]) for key in ("members", "documents", "conversations", "questions",
                                          "reports", "report_runs")},
    } for row in rows]


#: The calendar the usage days follow unless the caller names one (``?tz=``): the pilot's
#: (and the reports' default) zone, so work done after 22:00 UTC counts on its local day.
STATS_TIMEZONE = "Europe/Bucharest"
_TIMEZONE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+){0,3}$")


def _stats_zone(requested: str | None) -> tuple[str, tzinfo]:
    """``(name, zone)`` the days are counted in; an unknown ``tz`` is ``422 field=tz``.

    Without ``tz``, :data:`STATS_TIMEZONE` — or UTC, said so in the answer, on a host
    whose time-zone database cannot load it.
    """
    if requested is None or not requested.strip():
        try:
            return STATS_TIMEZONE, ZoneInfo(STATS_TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            logger.warning("time zone %s unavailable; usage days are counted in UTC",
                           STATS_TIMEZONE)
            return "UTC", UTC
    name = requested.strip()
    error = invalid("tz", "invalid", "tz is not a known time zone")
    if len(name) > 64 or not _TIMEZONE_NAME.match(name):
        raise error
    try:
        return name, ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise error from exc


def _local_midnight(day: date, zone: tzinfo) -> float:
    return datetime(day.year, day.month, day.day, tzinfo=zone).timestamp()


def _window_days(days: int, stamp: float, zone: tzinfo) -> list[date]:
    """The *days* calendar days in *zone* ending today, oldest first."""
    today = datetime.fromtimestamp(stamp, tz=zone).date()
    return [today - timedelta(days=days - 1 - offset) for offset in range(days)]


def _window_start(days: int, stamp: float, zone: tzinfo = UTC) -> float:
    """Midnight (in *zone*) of the first day of a *days*-day window ending today."""
    return _local_midnight(_window_days(days, stamp, zone)[0], zone)


_DAILY_SQL = (
    "SELECT CAST(b.key AS INTEGER) AS i, COUNT(a.id) AS n FROM json_each(?) b "
    "JOIN audit a ON a.ts >= json_extract(b.value, '$[0]') AND a.ts < json_extract(b.value, '$[1]') "
    "WHERE a.action = ? GROUP BY b.key"
)


def _daily(conn: sqlite3.Connection, *, days: int, stamp: float,
           zone: tzinfo = UTC) -> list[dict]:
    """One row per calendar day in *zone* (zero days included, so a chart has no gaps).

    Each day runs from its local midnight to the next one, so a DST day is 23 or 25 hours
    long, exactly as the people who worked it lived it.
    """
    window = _window_days(days, stamp, zone)
    bounds = [[_local_midnight(day, zone), _local_midnight(day + timedelta(days=1), zone)]
              for day in window]
    series = [{"date": day.isoformat(), "questions": 0, "report_runs": 0} for day in window]
    for key, action in ACTIVITY_ACTIONS.items():
        for row in conn.execute(_DAILY_SQL, (json.dumps(bounds), action)).fetchall():
            series[int(row["i"])][key] = int(row["n"])
    return series


@router.get("/admin/stats")
def usage_stats(admin: WsAdmin, conn: Db,
                days: Annotated[int, Query(ge=1, le=365)] = 30,
                tz: Annotated[str | None, Query(max_length=64)] = None) -> JSONResponse:
    """Usage KPIs: current totals, window activity per department, and a daily series.

    The window is the last *days* calendar days (today included) in ``timezone`` — the
    ``tz`` asked for (an IANA name, e.g. the admin's browser zone), else
    :data:`STATS_TIMEZONE`: ``questions``, ``report_runs`` and feedback count inside it,
    so the daily series sums to the totals. Questions and runs come from the audit
    trail (see ``ACTIVITY_ACTIONS``), so deleting a conversation or a report does not
    rewrite past usage; feedback is the current rating of the answers still stored. The
    other totals are current counts; ``active_users_7d`` counts users seen in the last
    seven days.
    """
    zone_name, zone = _stats_zone(tz)
    stamp = db.now()
    since = _window_start(days, stamp, zone)
    return ws_json({
        "days": days, "since": since, "timezone": zone_name,
        "totals": _totals(conn, since=since, week_ago=stamp - 7 * 86400),
        "per_department": _per_department(conn, since=since),
        "daily": _daily(conn, days=days, stamp=stamp, zone=zone),
    })
