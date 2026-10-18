"""The approvals engine of Nerva Workspace: four eyes on every consequential action (spec §6, §7).

An approval is a request to perform one registered *effect* (email a report, publish a
document company-wide, share a report run …). This module owns its life cycle and
knows nothing about the domains: each effect is an :class:`~agents.core.workspace.
effects_api.EffectSpec` its domain module registered, with ``validate`` and ``execute``.

The rules it enforces, and why:

* Nobody decides their own request. The one exception is an admin requesting an
  ``admin``-rule kind: admins are exactly the people who may do it, so it executes at
  once (``decided_by`` = the requester, no decision note — the audit row carries the
  ``admin action`` marker) instead of waiting for a second admin who would add no
  control. Stored notes are what people wrote, in their language; the UI words the
  "decided by the requester" case itself.
* A request nobody else could decide is refused up front (``409 no_eligible_approver``)
  rather than left to expire.
* Deciding is a compare-and-set: ``pending`` → ``executing`` (or ``rejected``) only while
  the row is still pending and unexpired, so two deciders clicking at once yield one
  decision and one execution; the loser gets ``409 already_decided``.
* The effect is validated again, against the requester's current rights and the
  current state, between the decision and the execution — a week-old approval must not
  act on a world that changed. The outcome (``approved`` + result, or ``failed`` +
  ``error_code``) is written in a fresh transaction; no transaction is ever held across
  the effect's I/O.
* Approvals the caller may not see answer ``404``: requesters, the people who may
  decide them, the decider and admins see an approval; nobody else learns it exists.

Domain modules can also register :func:`register_hooks` — ``on_requested`` runs inside
the request's transaction, ``on_closed`` inside the transaction that rejects, expires,
cancels or fails it — so their own state (a report's delivery status) never drifts from
the approval's.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from agents.core.workspace import audit, db, effects_api, identity, notifications
from agents.core.workspace.effects_api import EffectSpec, ValidatedRequest
from agents.core.workspace.errors import WorkspaceError
from agents.core.workspace.http import invalid
from agents.core.workspace.identity import WorkspaceUser

logger = logging.getLogger("nerva.workspace.approvals")

APPROVAL_TTL_SECONDS = 7 * 86400
EXECUTING_TIMEOUT_SECONDS = 10 * 60
STATUSES = ("pending", "executing", "approved", "rejected", "cancelled", "expired", "failed")
BOXES = ("inbox", "mine", "all")
DECISIONS = ("approve", "reject")
#: Marks an admin's immediate action in the audit details (never stored as a decision note).
ADMIN_ACTION_NOTE = "admin action"
SCHEDULER_ACTOR = "scheduler"
MAX_NOTE = 1000
MAX_SUMMARY = 500
LIST_LIMIT = 200
SWEEP_LIMIT = 500

_COLUMNS_SQL = (
    "SELECT a.*, r.name AS requester_name, r.email AS requester_email, "
    "d.name AS decider_name, d.email AS decider_email, dep.name AS department_name "
    "FROM approvals a JOIN users r ON r.id = a.requester_id "
    "LEFT JOIN users d ON d.id = a.decided_by "
    "LEFT JOIN departments dep ON dep.id = a.department_id "
    "WHERE a.id IN (SELECT value FROM json_each(?)) ORDER BY a.id DESC"
)
# The status filters compare the *effective* status: a pending request past its expiry
# is shown as ``expired`` (see item_json), so it is filtered as one too.
_INBOX_IDS_SQL = (
    "SELECT a.id FROM approvals a WHERE (? IS NULL OR (CASE WHEN a.status = 'pending' "
    "AND a.expires_at <= ? THEN 'expired' ELSE a.status END) = ?) AND ("
    "a.decided_by = ? OR (a.requester_id != ? AND (? = 1 OR ("
    "a.kind IN (SELECT value FROM json_each(?)) "
    "AND a.department_id IN (SELECT value FROM json_each(?)))))) "
    "ORDER BY a.id DESC LIMIT ?"
)
_PENDING_INBOX_SQL = (
    "SELECT COUNT(*) FROM approvals a WHERE a.status = 'pending' AND a.expires_at > ? "
    "AND a.requester_id != ? AND (? = 1 OR ("
    "a.kind IN (SELECT value FROM json_each(?)) "
    "AND a.department_id IN (SELECT value FROM json_each(?))))"
)
_MINE_IDS_SQL = (
    "SELECT a.id FROM approvals a WHERE a.requester_id = ? AND (? IS NULL OR (CASE WHEN "
    "a.status = 'pending' AND a.expires_at <= ? THEN 'expired' ELSE a.status END) = ?) "
    "ORDER BY a.id DESC LIMIT ?"
)
_ALL_IDS_SQL = (
    "SELECT a.id FROM approvals a WHERE (? IS NULL OR (CASE WHEN a.status = 'pending' "
    "AND a.expires_at <= ? THEN 'expired' ELSE a.status END) = ?) ORDER BY a.id DESC LIMIT ?"
)
_OPEN_DUPLICATE_SQL = (
    "SELECT id FROM approvals WHERE kind = ? AND payload_json = ? "
    "AND status IN ('pending', 'executing') ORDER BY id DESC LIMIT 1"
)
_USERS_BY_ID_SQL = (
    "SELECT id, name, email, locale FROM users WHERE id IN (SELECT value FROM json_each(?)) "
    "AND status = 'active' ORDER BY name COLLATE NOCASE, id"
)

_TITLES: dict[str, dict[str, str]] = {
    "requested": {"ro": "Cerere nouă de aprobare", "en": "New approval request"},
    "approved": {"ro": "Cerere aprobată", "en": "Request approved"},
    "failed": {"ro": "Cerere aprobată, dar neexecutată",
               "en": "Approved request could not be carried out"},
    "rejected": {"ro": "Cerere respinsă", "en": "Request rejected"},
    "expired": {"ro": "Cerere expirată", "en": "Request expired"},
}


# ── domain hooks ─────────────────────────────────────────────────────────────────────

RequestedHook = Callable[[sqlite3.Connection, int, ValidatedRequest, WorkspaceUser], None]
ClosedHook = Callable[[sqlite3.Connection, sqlite3.Row, str], None]


@dataclass
class Hooks:
    """Optional callbacks of one kind, run inside the engine's transactions."""

    on_requested: RequestedHook | None = None
    on_closed: ClosedHook | None = None


_HOOKS: dict[str, Hooks] = {}


def register_hooks(kind: str, *, on_requested: RequestedHook | None = None,
                   on_closed: ClosedHook | None = None) -> None:
    """Attach life-cycle callbacks to *kind* (replacing earlier ones).

    ``on_requested(conn, approval_id, validated, requester)`` runs right after a new
    request is stored; ``on_closed(conn, row, outcome)`` when one ends without being
    carried out — *outcome* is ``rejected``, ``expired``, ``cancelled`` or ``failed``.
    """
    _HOOKS[kind] = Hooks(on_requested=on_requested, on_closed=on_closed)


def _closed(conn: sqlite3.Connection, row: sqlite3.Row, outcome: str) -> None:
    hooks = _HOOKS.get(row["kind"])
    if hooks is not None and hooks.on_closed is not None:
        hooks.on_closed(conn, row, outcome)


# ── small helpers ────────────────────────────────────────────────────────────────────

def _spec(kind: str) -> EffectSpec | None:
    """The registered spec, or ``None`` for a kind whose module is not loaded."""
    try:
        return effects_api.get_effect(kind)
    except WorkspaceError:
        return None


def _loads(raw: str | None, default: Any) -> Any:
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


def canonical_payload(payload: Mapping[str, Any]) -> str:
    """The stored form of a payload (sorted keys), so equal requests compare equal."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _not_found() -> WorkspaceError:
    return WorkspaceError("not_found", "approval not found", 404)


def _department_kinds() -> list[str]:
    """Registered kinds an approver of the department may decide."""
    return [kind for kind in effects_api.kinds()
            if effects_api.get_effect(kind).decider_rule == "department"]


def _approver_departments(user: WorkspaceUser) -> list[int]:
    return list(user.department_ids) if user.role == "approver" else []


def notify_localized(conn: sqlite3.Connection, user_ids: Iterable[int], *, kind: str,
                     titles: Mapping[str, str], body: str = "", link: str = "",
                     bodies: Mapping[str, str] | None = None) -> None:
    """One notification per active user, titled (and, with *bodies*, worded) in that user's language."""
    ids = sorted({int(uid) for uid in user_ids if uid is not None})
    if not ids:
        return
    rows = conn.execute(_USERS_BY_ID_SQL, (json.dumps(ids),)).fetchall()
    for locale in identity.LOCALES:
        recipients = [int(row["id"]) for row in rows if (row["locale"] or "ro") == locale]
        text = bodies.get(locale, bodies.get("ro", body)) if bodies else body
        notifications.notify(conn, recipients, kind=kind, title=titles.get(locale, titles["ro"]),
                             body=text, link=link)


def _link(approval_id: int) -> str:
    return f"/workspace/approvals/{approval_id}"


def _person(user_id: int | None, name: str | None, email: str | None) -> dict | None:
    if user_id is None:
        return None
    return {"id": int(user_id), "name": name or "", "email": email or ""}


# ── reading ──────────────────────────────────────────────────────────────────────────

def _rows(conn: sqlite3.Connection, ids: list[int]) -> list[sqlite3.Row]:
    if not ids:
        return []
    return conn.execute(_COLUMNS_SQL, (json.dumps(ids),)).fetchall()


def get_row(conn: sqlite3.Connection, approval_id: int) -> sqlite3.Row | None:
    """The approval with requester, decider and department names, or ``None``."""
    rows = _rows(conn, [approval_id])
    return rows[0] if rows else None


def _item(conn: sqlite3.Connection, user: WorkspaceUser, approval_id: int) -> dict:
    """The approval as *user* sees it right after an action on it."""
    row = get_row(conn, approval_id)
    if row is None:
        raise _not_found()
    return item_json(row, user, db.now())


def can_view(user: WorkspaceUser, row: sqlite3.Row) -> bool:
    """Requester, decider, admins, and approvers who may decide it (department rule)."""
    if user.is_admin or row["requester_id"] == user.id or row["decided_by"] == user.id:
        return True
    spec = _spec(row["kind"])
    department_id = row["department_id"]
    return (spec is not None and spec.decider_rule == "department" and department_id is not None
            and user.can_approve_in(int(department_id)))


def visible_row(conn: sqlite3.Connection, user: WorkspaceUser, approval_id: int) -> sqlite3.Row:
    """The approval when *user* may see it, else ``404 not_found``."""
    row = get_row(conn, approval_id)
    if row is None or not can_view(user, row):
        raise _not_found()
    return row


def _lapsed(row: sqlite3.Row, now: float) -> bool:
    return row["status"] == "pending" and row["expires_at"] <= now


def item_json(row: sqlite3.Row, user: WorkspaceUser, now: float) -> dict:
    """An approval as the API shows it to *user*.

    A pending request past its expiry reads as ``expired`` even before the scheduler
    tick has rewritten the row, so nobody is offered a decision the server would refuse.
    """
    spec = _spec(row["kind"])
    lapsed = _lapsed(row, now)
    open_ = row["status"] == "pending" and not lapsed
    can_decide = bool(open_ and spec is not None
                      and effects_api.can_decide(user, spec, row["department_id"],
                                                 int(row["requester_id"])))
    return {
        "id": int(row["id"]), "kind": row["kind"], "department_id": row["department_id"],
        "department_name": row["department_name"], "summary": row["summary"],
        "payload": _loads(row["payload_json"], {}),
        "status": "expired" if lapsed else row["status"],
        "requester": _person(row["requester_id"], row["requester_name"], row["requester_email"]),
        "decider": _person(row["decided_by"], row["decider_name"], row["decider_email"]),
        "decided_at": row["decided_at"], "decision_note": row["decision_note"],
        "result": _loads(row["result_json"], None), "error_code": row["error_code"],
        "created_at": row["created_at"], "expires_at": row["expires_at"],
        "can_decide": can_decide, "can_cancel": open_ and row["requester_id"] == user.id,
    }


def detail_json(conn: sqlite3.Connection, user: WorkspaceUser, approval_id: int) -> dict:
    """One visible approval plus the people who could decide it while it is pending."""
    row = visible_row(conn, user, approval_id)
    item = item_json(row, user, db.now())
    spec = _spec(row["kind"])
    deciders: list[dict] = []
    if spec is not None and item["status"] == "pending":
        ids = effects_api.eligible_decider_ids(conn, spec, row["department_id"],
                                               exclude=int(row["requester_id"]))
        found = conn.execute(_USERS_BY_ID_SQL, (json.dumps(ids),)).fetchall()
        deciders = [{"id": int(r["id"]), "name": r["name"]} for r in found]
    item["eligible_deciders"] = deciders
    return item


def list_items(conn: sqlite3.Connection, user: WorkspaceUser, *, box: str,
               status: str | None) -> dict:
    """``{items, pending_inbox_count}`` for the inbox, the caller's requests or (admins) all."""
    if box not in BOXES:
        raise invalid("box", "invalid_choice")
    if status is not None and status not in STATUSES:
        raise invalid("status", "invalid_choice")
    kinds_json = json.dumps(_department_kinds())
    depts_json = json.dumps(_approver_departments(user))
    is_admin = 1 if user.is_admin else 0
    stamp = db.now()
    if box == "inbox":
        params: tuple = (status, stamp, status, user.id, user.id, is_admin, kinds_json,
                         depts_json, LIST_LIMIT)
        ids_rows = conn.execute(_INBOX_IDS_SQL, params).fetchall()
    elif box == "mine":
        ids_rows = conn.execute(_MINE_IDS_SQL,
                                (user.id, status, stamp, status, LIST_LIMIT)).fetchall()
    else:
        if not user.is_admin:
            raise WorkspaceError("forbidden", "only administrators see every approval", 403)
        ids_rows = conn.execute(_ALL_IDS_SQL, (status, stamp, status, LIST_LIMIT)).fetchall()
    items = [item_json(row, user, stamp) for row in _rows(conn, [int(r["id"]) for r in ids_rows])]
    return {"items": items, "pending_inbox_count": pending_inbox_count(conn, user)}


def pending_inbox_count(conn: sqlite3.Connection, user: WorkspaceUser) -> int:
    """Pending, unexpired requests *user* could decide now."""
    row = conn.execute(_PENDING_INBOX_SQL, (
        db.now(), user.id, 1 if user.is_admin else 0, json.dumps(_department_kinds()),
        json.dumps(_approver_departments(user)),
    )).fetchone()
    return int(row[0])


def eligible(conn: sqlite3.Connection, user: WorkspaceUser, kind: str,
             department_id: int | None) -> dict:
    """``{count, immediate}``: who besides *user* could decide such a request.

    ``immediate`` is true when *user* is an admin and the kind is decided by admins —
    the request would execute at once, whatever ``count`` says.
    """
    spec = effects_api.get_effect(kind)
    if department_id is not None:
        exists = conn.execute("SELECT 1 FROM departments WHERE id = ?", (department_id,)).fetchone()
        if exists is None or not user.can_access_department(department_id):
            raise WorkspaceError("not_found", "department not found", 404)
    ids = effects_api.eligible_decider_ids(conn, spec, department_id, exclude=user.id)
    return {"count": len(ids), "immediate": spec.decider_rule == "admin" and user.is_admin}


# ── requesting ───────────────────────────────────────────────────────────────────────

def _no_eligible_approver() -> WorkspaceError:
    return WorkspaceError("no_eligible_approver",
                          "nobody else can approve this request; ask an administrator", 409)


def create_request(conn: sqlite3.Connection, requester: WorkspaceUser, kind: str,
                   payload: object, *, ip: str = "") -> tuple[int, bool]:
    """Validate and store a request; returns ``(approval_id, immediate)``.

    Joins the caller's transaction (a report created together with its delivery
    request is rolled back when nobody could approve it). ``immediate`` means an admin
    asked for an admin-rule kind: the row is stored ``executing``, already decided by
    the requester, and :func:`request` carries it out right away.
    """
    spec = effects_api.get_effect(kind)
    if not isinstance(payload, dict):
        raise invalid("payload", "not_an_object", "payload must be a JSON object")
    stamp = db.now()
    with db.tx(conn):
        validated = spec.validate(conn, requester, payload)
        payload_json = canonical_payload(validated.payload)
        immediate = spec.decider_rule == "admin" and requester.is_admin
        deciders: list[int] = []
        if not immediate:
            deciders = effects_api.eligible_decider_ids(conn, spec, validated.department_id,
                                                        exclude=requester.id)
            if not deciders:
                raise _no_eligible_approver()
        # Immediate requests are checked too: an admin's double click must not start a
        # second execution of an effect the first one is still carrying out.
        duplicate = conn.execute(_OPEN_DUPLICATE_SQL, (kind, payload_json)).fetchone()
        if duplicate is not None:
            raise WorkspaceError("already_requested", "the same request is already waiting",
                                 409, approval_id=int(duplicate["id"]))
        summary = validated.summary[:MAX_SUMMARY]
        approval_id = int(conn.execute(
            "INSERT INTO approvals (kind, department_id, requester_id, summary, payload_json, "
            "status, decided_by, decided_at, decision_note, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, validated.department_id, requester.id, summary, payload_json,
             "executing" if immediate else "pending", requester.id if immediate else None,
             stamp if immediate else None, None, stamp, stamp + APPROVAL_TTL_SECONDS),
        ).lastrowid)
        hooks = _HOOKS.get(kind)
        if hooks is not None and hooks.on_requested is not None:
            hooks.on_requested(conn, approval_id, validated, requester)
        audit.record(conn, actor=requester, action="approval.requested", target_type="approval",
                     target_id=approval_id, department_id=validated.department_id, ip=ip,
                     details={"kind": kind, "immediate": immediate, "deciders": len(deciders)})
        if immediate:
            audit.record(conn, actor=requester, action="approval.approved", target_type="approval",
                         target_id=approval_id, department_id=validated.department_id, ip=ip,
                         details={"kind": kind, "immediate": True, "note": ADMIN_ACTION_NOTE})
        else:
            notify_localized(conn, deciders, kind="approval.requested", titles=_TITLES["requested"],
                             body=f"{requester.name}: {summary}", link=_link(approval_id))
    return approval_id, immediate


async def request(conn: sqlite3.Connection, requester: WorkspaceUser, kind: str, payload: object,
                  *, ip: str = "") -> dict:
    """``POST /approvals``: store the request (and carry it out at once when immediate)."""
    approval_id, immediate = create_request(conn, requester, kind, payload, ip=ip)
    if immediate:
        await _carry_out(conn, approval_id, decider=requester, ip=ip)
    return _item(conn, requester, approval_id)


# ── deciding ─────────────────────────────────────────────────────────────────────────

def _already_decided(conn: sqlite3.Connection, approval_id: int, now: float) -> WorkspaceError:
    row = conn.execute("SELECT status, expires_at FROM approvals WHERE id = ?",
                       (approval_id,)).fetchone()
    status = row["status"] if row is not None else "unknown"
    if row is not None and status == "pending" and row["expires_at"] <= now:
        status = "expired"
    return WorkspaceError("already_decided", "this request is no longer pending", 409,
                          current_status=status)


async def decide(conn: sqlite3.Connection, user: WorkspaceUser, approval_id: int, *,
                 decision: str, note: str, ip: str = "") -> dict:
    """Approve (and carry out) or reject a pending request *user* may decide."""
    if decision not in DECISIONS:
        raise invalid("decision", "invalid_choice")
    row = visible_row(conn, user, approval_id)
    spec = _spec(row["kind"])
    if spec is None:
        raise WorkspaceError("unknown_kind", "this kind of approval does not exist", 400,
                             kind=row["kind"])
    if not effects_api.can_decide(user, spec, row["department_id"], int(row["requester_id"])):
        raise WorkspaceError("forbidden", "you may not decide this request", 403)
    stamp = db.now()
    approve = decision == "approve"
    with db.tx(conn):
        cursor = conn.execute(
            "UPDATE approvals SET status = ?, decided_by = ?, decided_at = ?, decision_note = ? "
            "WHERE id = ? AND status = 'pending' AND expires_at > ?",
            ("executing" if approve else "rejected", user.id, stamp, note or None, approval_id,
             stamp),
        )
        if cursor.rowcount != 1:
            raise _already_decided(conn, approval_id, stamp)
        audit.record(conn, actor=user, action="approval.approved" if approve else "approval.rejected",
                     target_type="approval", target_id=approval_id,
                     department_id=row["department_id"], ip=ip,
                     details={"kind": row["kind"], "requester_id": row["requester_id"],
                              "has_note": bool(note)})
        if not approve:
            _closed(conn, row, "rejected")
            body = row["summary"] + (f"\n{user.name}: {note}" if note else "")
            notify_localized(conn, [row["requester_id"]], kind="approval.rejected",
                             titles=_TITLES["rejected"], body=body, link=_link(approval_id))
    if approve:
        await _carry_out(conn, approval_id, decider=user, ip=ip)
    return _item(conn, user, approval_id)


async def _carry_out(conn: sqlite3.Connection, approval_id: int, *, decider: WorkspaceUser,
                     ip: str) -> None:
    """Re-validate and execute an ``executing`` approval, then record the outcome."""
    row = get_row(conn, approval_id)
    if row is None:
        return
    payload = _loads(row["payload_json"], {})
    result: dict | None = None
    error_code: str | None = None
    try:
        spec = effects_api.get_effect(row["kind"])
        requester = identity.get_user(conn, int(row["requester_id"]))
        if requester is None or requester.status != "active":
            raise WorkspaceError("requester_inactive", "the requester's account is not active", 409)
        spec.validate(conn, requester, payload)
        outcome = await spec.execute({**dict(row), "payload": payload}, requester, decider)
        result = outcome if isinstance(outcome, dict) else {"value": outcome}
    except WorkspaceError as exc:
        error_code = exc.code
    except Exception:  # an effect bug must end as a failed approval, never a stuck one
        logger.exception("approval %s: the %s effect raised", approval_id, row["kind"])
        error_code = "execution_failed"
    _record_outcome(conn, row, decider=decider, result=result, error_code=error_code, ip=ip)


def _record_outcome(conn: sqlite3.Connection, row: sqlite3.Row, *, decider: WorkspaceUser,
                    result: dict | None, error_code: str | None, ip: str) -> None:
    """Store the outcome (compare-and-set on ``executing``), audit it, tell the requester.

    When the stale-execution sweep already failed the row (``interrupted``), the effect
    still finished: the audit records that (``late``), but the row, the domain hook and
    the requester — already told it failed — are left alone rather than contradicted.
    """
    approval_id = int(row["id"])
    failed = error_code is not None
    with db.tx(conn):
        cursor = conn.execute(
            "UPDATE approvals SET status = ?, result_json = ?, error_code = ? "
            "WHERE id = ? AND status = 'executing'",
            ("failed" if failed else "approved",
             None if failed else json.dumps(result, ensure_ascii=False, default=str),
             error_code, approval_id),
        )
        current = cursor.rowcount == 1
        if not current:
            logger.warning("approval %s finished after it stopped being 'executing'", approval_id)
        audit.record(conn, actor=decider, action="approval.failed" if failed else "approval.executed",
                     target_type="approval", target_id=approval_id,
                     department_id=row["department_id"], ip=ip,
                     details={"kind": row["kind"], **({"error_code": error_code} if failed else {}),
                              **({} if current else {"late": True})})
        if not current:
            return
        if failed:
            _closed(conn, row, "failed")
        if row["requester_id"] != decider.id:
            key = "failed" if failed else "approved"
            notify_localized(conn, [row["requester_id"]], kind=f"approval.{key}",
                             titles=_TITLES[key], body=row["summary"], link=_link(approval_id))


# ── cancelling ───────────────────────────────────────────────────────────────────────

def cancel(conn: sqlite3.Connection, user: WorkspaceUser, approval_id: int, *,
           ip: str = "") -> dict:
    """The requester withdraws their own pending request."""
    row = visible_row(conn, user, approval_id)
    if row["requester_id"] != user.id:
        raise WorkspaceError("forbidden", "only the requester can cancel a request", 403)
    stamp = db.now()
    with db.tx(conn):
        cursor = conn.execute(
            "UPDATE approvals SET status = 'cancelled', decided_at = ? "
            "WHERE id = ? AND requester_id = ? AND status = 'pending' AND expires_at > ?",
            (stamp, approval_id, user.id, stamp),
        )
        if cursor.rowcount != 1:
            raise _already_decided(conn, approval_id, stamp)
        audit.record(conn, actor=user, action="approval.cancelled", target_type="approval",
                     target_id=approval_id, department_id=row["department_id"], ip=ip,
                     details={"kind": row["kind"], "reason": "requester"})
        _closed(conn, row, "cancelled")
    return _item(conn, user, approval_id)


def cancel_superseded(conn: sqlite3.Connection, approval_ids: Iterable[int], *,
                      actor: WorkspaceUser | None, reason: str, ip: str = "") -> list[int]:
    """Cancel pending requests a domain change made pointless; returns the ids cancelled.

    Joins the caller's transaction. No hook runs: the caller is the one changing the
    domain state and sets it itself. *reason* (``superseded``, ``recipients_removed``,
    ``report_deleted`` …) is kept in ``error_code``, so a withdrawn request says why it was
    withdrawn; one the requester cancelled keeps ``error_code`` null.
    """
    cancelled: list[int] = []
    stamp = db.now()
    with db.tx(conn):
        for approval_id in sorted({int(a) for a in approval_ids}):
            cursor = conn.execute(
                "UPDATE approvals SET status = 'cancelled', decided_at = ?, error_code = ? "
                "WHERE id = ? AND status = 'pending'", (stamp, reason, approval_id))
            if cursor.rowcount != 1:
                continue
            row = conn.execute("SELECT kind, department_id FROM approvals WHERE id = ?",
                               (approval_id,)).fetchone()
            audit.record(conn, actor=actor, actor_email="" if actor else SCHEDULER_ACTOR,
                         action="approval.cancelled", target_type="approval",
                         target_id=approval_id, department_id=row["department_id"], ip=ip,
                         details={"kind": row["kind"], "reason": reason})
            cancelled.append(approval_id)
    return cancelled


# ── scheduler sweeps ─────────────────────────────────────────────────────────────────

def expire_due(conn: sqlite3.Connection, now: float) -> int:
    """Pending requests past ``expires_at`` → ``expired``; the requester is told."""
    rows = conn.execute(
        "SELECT * FROM approvals WHERE status = 'pending' AND expires_at <= ? ORDER BY id LIMIT ?",
        (now, SWEEP_LIMIT),
    ).fetchall()
    expired = 0
    for row in rows:
        with db.tx(conn):
            cursor = conn.execute(
                "UPDATE approvals SET status = 'expired' WHERE id = ? AND status = 'pending' "
                "AND expires_at <= ?", (row["id"], now))
            if cursor.rowcount != 1:
                continue
            audit.record(conn, actor=None, actor_email=SCHEDULER_ACTOR, action="approval.expired",
                         target_type="approval", target_id=int(row["id"]),
                         department_id=row["department_id"], details={"kind": row["kind"]})
            _closed(conn, row, "expired")
            notify_localized(conn, [row["requester_id"]], kind="approval.expired",
                             titles=_TITLES["expired"], body=row["summary"],
                             link=_link(int(row["id"])))
            expired += 1
    return expired


def fail_stale_executing(conn: sqlite3.Connection, now: float) -> int:
    """``executing`` rows older than 10 min (a crash mid-effect) → ``failed`` / ``interrupted``."""
    rows = conn.execute(
        "SELECT * FROM approvals WHERE status = 'executing' AND decided_at <= ? ORDER BY id LIMIT ?",
        (now - EXECUTING_TIMEOUT_SECONDS, SWEEP_LIMIT),
    ).fetchall()
    failed = 0
    for row in rows:
        with db.tx(conn):
            cursor = conn.execute(
                "UPDATE approvals SET status = 'failed', error_code = 'interrupted' "
                "WHERE id = ? AND status = 'executing'", (row["id"],))
            if cursor.rowcount != 1:
                continue
            audit.record(conn, actor=None, actor_email=SCHEDULER_ACTOR, action="approval.failed",
                         target_type="approval", target_id=int(row["id"]),
                         department_id=row["department_id"],
                         details={"kind": row["kind"], "error_code": "interrupted"})
            _closed(conn, row, "failed")
            notify_localized(conn, [row["requester_id"]], kind="approval.failed",
                             titles=_TITLES["failed"], body=row["summary"],
                             link=_link(int(row["id"])))
            failed += 1
    return failed
