"""In-app notifications and the "who should hear about this" queries (spec §5).

Notifications are rows, not pushes: the UI polls ``GET /api/workspace/notifications``.
Links are app-relative paths only (``/workspace/approvals/7``) — anything else is
dropped, so a notification can never carry a ``javascript:`` or external URL into the
bell menu.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from agents.core.workspace import db

MAX_TITLE = 200
MAX_BODY = 2000
MAX_LINK = 500


def _safe_link(link: str) -> str:
    """*link* when it is an app-relative path, else ``''``.

    Browsers read ``/\\host`` as ``//host`` and drop tabs and line breaks inside URLs
    (``/<tab>/host`` → ``//host``), so backslashes, whitespace and control characters are
    refused along with ``//`` — any of them could turn the link into an external one.
    """
    link = (link or "").strip()
    if (not link.startswith("/") or link.startswith("//") or len(link) > MAX_LINK
            or "\\" in link or any(ch.isspace() or not ch.isprintable() for ch in link)):
        return ""
    return link


def notify(conn: sqlite3.Connection, user_ids: Iterable[int], *, kind: str, title: str,
           body: str = "", link: str = "") -> None:
    """Add one notification per distinct user id (joins the caller's transaction)."""
    recipients = sorted({int(uid) for uid in user_ids if uid is not None})
    if not recipients:
        return
    created = db.now()
    rows = [(uid, kind, title[:MAX_TITLE], body[:MAX_BODY], _safe_link(link), created)
            for uid in recipients]
    with db.tx(conn):
        conn.executemany(
            "INSERT INTO notifications (user_id, kind, title, body, link, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)", rows,
        )


def admins(conn: sqlite3.Connection, *, exclude: int | None = None) -> list[int]:
    """Ids of active admins, minus *exclude*."""
    rows = conn.execute(
        "SELECT id FROM users WHERE role = 'admin' AND status = 'active' ORDER BY id"
    ).fetchall()
    return [int(row["id"]) for row in rows if row["id"] != exclude]


def department_approvers(conn: sqlite3.Connection, department_id: int, *,
                         exclude: int | None = None) -> list[int]:
    """Active approvers who are members of *department_id*, plus active admins.

    An archived department has no approvers of its own (only admins may see it).
    """
    rows = conn.execute(
        "SELECT u.id FROM users u "
        "JOIN user_departments ud ON ud.user_id = u.id "
        "JOIN departments d ON d.id = ud.department_id "
        "WHERE ud.department_id = ? AND d.archived = 0 "
        "AND u.role = 'approver' AND u.status = 'active'",
        (department_id,),
    ).fetchall()
    ids = {int(row["id"]) for row in rows} | set(admins(conn))
    return sorted(uid for uid in ids if uid != exclude)


def unread_count(conn: sqlite3.Connection, user_id: int) -> int:
    """How many of the user's notifications are unread."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read_at IS NULL",
        (user_id,),
    ).fetchone()
    return int(row["n"])


def to_json(row: sqlite3.Row) -> dict:
    """A notification row as the API shows it."""
    return {
        "id": int(row["id"]), "kind": row["kind"], "title": row["title"], "body": row["body"],
        "link": row["link"], "created_at": row["created_at"], "read_at": row["read_at"],
        "read": row["read_at"] is not None,
    }


def list_for_user(conn: sqlite3.Connection, user_id: int, *, unread_only: bool,
                  limit: int) -> list[dict]:
    """The user's newest notifications first."""
    sql = "SELECT * FROM notifications WHERE user_id = ?"
    if unread_only:
        sql += " AND read_at IS NULL"
    sql += " ORDER BY id DESC LIMIT ?"
    return [to_json(row) for row in conn.execute(sql, (user_id, limit)).fetchall()]


def mark_read(conn: sqlite3.Connection, user_id: int, *, ids: list[int] | None = None,
              all_unread: bool = False) -> int:
    """Mark the user's own notifications read (by id or all); returns how many changed.

    Ids of other users' notifications are ignored, never an error: the call reveals
    nothing about rows the caller does not own.
    """
    if not all_unread and not ids:
        return 0
    stamp = db.now()
    with db.tx(conn):
        if all_unread:
            cursor = conn.execute(
                "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL",
                (stamp, user_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL "
                "AND id IN (SELECT value FROM json_each(?))",
                (stamp, user_id, json.dumps(ids)),
            )
    return int(cursor.rowcount)
