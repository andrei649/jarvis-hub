"""Nerva Workspace — approvals and the admin SMTP settings (spec §7).

Approvals: the caller's inbox (requests they may decide), their own requests, and for
admins every request; the eligibility probe the UI runs before offering a request;
requesting, deciding (an atomic compare-and-set, so a double click executes once) and
withdrawing. The rules live in ``agents.core.workspace.approvals``; approvals the caller
may not see answer ``404``.

This router imports every module that registers an approval effect — ``reports``
(report delivery, company sharing, email) and ``documents`` (company-wide publishing) —
so ``kinds()`` is complete whichever routers an app includes.

SMTP (admins): the settings without the password (``has_password`` instead), an update
where ``password: null`` keeps the stored secret and ``""`` clears it, and a test send.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from agents.core.workspace import approvals, audit, auth, documents, mailer, reports
from agents.core.workspace.auth import WsAdmin, WsUser
from agents.core.workspace.db import Db, tx
from agents.core.workspace.http import (
    MAX_ID,
    offload,
    optional_str,
    read_json,
    require_choice,
    require_email,
    require_str,
    ws_json,
)

logger = logging.getLogger("nerva.workspace.routers.approvals")

router = APIRouter(prefix="/api/workspace")

# Imported for their side effect: each registers its approval effects at import time.
EFFECT_MODULES = (documents, reports)

ApprovalId = Annotated[int, Path(ge=1, le=MAX_ID)]
BoxFilter = Annotated[str, Query(pattern="^(inbox|mine|all)$", max_length=5)]
StatusFilter = Annotated[str | None, Query(
    pattern="^(pending|executing|approved|rejected|cancelled|expired|failed)$", max_length=9)]
KindQuery = Annotated[str, Query(min_length=1, max_length=64)]
DepartmentFilter = Annotated[int | None, Query(ge=1, le=MAX_ID)]


@router.get("/approvals")
def list_approvals(user: WsUser, conn: Db, box: BoxFilter = "inbox",
                   status: StatusFilter = None) -> JSONResponse:
    """``{items, pending_inbox_count}``; ``box=all`` is for admins."""
    return ws_json(approvals.list_items(conn, user, box=box, status=status))


@router.get("/approvals/eligible")
def eligible_deciders(user: WsUser, conn: Db, kind: KindQuery,
                      department_id: DepartmentFilter = None) -> JSONResponse:
    """How many people besides the caller could decide such a request, and whether email works."""
    result = approvals.eligible(conn, user, kind, department_id)
    return ws_json({**result, "smtp_configured": mailer.smtp_configured(conn)})


@router.post("/approvals")
async def request_approval(request: Request, user: WsUser, conn: Db) -> JSONResponse:
    """Request an effect; an admin's own admin-rule request is carried out at once."""
    body = await read_json(request, max_bytes=262144)
    kind = require_str(body, "kind", max_len=64, min_len=1)
    item = await approvals.request(conn, user, kind, body.get("payload"),
                                   ip=auth.client_ip(request))
    return ws_json(item, 201)


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: ApprovalId, user: WsUser, conn: Db) -> JSONResponse:
    """One approval with the people who could decide it."""
    return ws_json(approvals.detail_json(conn, user, approval_id))


@router.post("/approvals/{approval_id}/decide")
async def decide_approval(approval_id: ApprovalId, request: Request, user: WsUser,
                          conn: Db) -> JSONResponse:
    """Approve (and carry out) or reject; ``409 already_decided`` for the second click."""
    body = await read_json(request, max_bytes=8192)
    decision = require_choice(body, "decision", approvals.DECISIONS)
    note = optional_str(body, "note", max_len=approvals.MAX_NOTE, multiline=True) or ""
    item = await approvals.decide(conn, user, approval_id, decision=decision, note=note,
                                  ip=auth.client_ip(request))
    return ws_json(item)


@router.post("/approvals/{approval_id}/cancel")
def cancel_approval(approval_id: ApprovalId, request: Request, user: WsUser,
                    conn: Db) -> JSONResponse:
    """The requester withdraws a pending request."""
    return ws_json(approvals.cancel(conn, user, approval_id, ip=auth.client_ip(request)))


@router.get("/admin/smtp")
def get_smtp(admin: WsAdmin, conn: Db) -> JSONResponse:
    """The SMTP settings (never the password)."""
    return ws_json(mailer.smtp_settings(conn))


@router.put("/admin/smtp")
async def put_smtp(request: Request, admin: WsAdmin, conn: Db) -> JSONResponse:
    """Replace the SMTP settings; the password is kept, replaced or cleared."""
    body = await read_json(request, max_bytes=16384)
    stored = await asyncio.to_thread(mailer.has_password)
    settings, password, password_given = mailer.parse_update(body, password_stored=stored)
    if password_given:
        await asyncio.to_thread(mailer.set_password, password or None)

    def _sync_1():
        with tx(conn):
            mailer.save_settings(conn, settings)
            audit.record(conn, actor=admin, action="smtp.updated", target_type="org", target_id=1,
                         ip=auth.client_ip(request),
                         details={"host": settings["host"], "port": settings["port"],
                                  "security": settings["security"],
                                  "has_username": bool(settings["username"]),
                                  "credential": ("replaced" if password else "cleared")
                                  if password_given else "kept",
                                  "allowed_domains": settings["allowed_domains"]})

    await offload(_sync_1)
    return ws_json(await offload(mailer.smtp_settings, conn))


@router.post("/admin/smtp/test")
async def test_smtp(request: Request, admin: WsAdmin, conn: Db) -> JSONResponse:
    """Send a test message → ``{ok}`` or ``{ok: false, error, reason?}``."""
    body = await read_json(request, max_bytes=4096)
    to = require_email(body, "to")
    outcome = await mailer.send_test(to, locale=admin.locale)

    def _sync_1():
        with tx(conn):
            audit.record(conn, actor=admin, action="smtp.tested", target_type="org", target_id=1,
                         ip=auth.client_ip(request),
                         details={"ok": outcome["ok"], **({"error_code": outcome["error"]}
                                                          if not outcome["ok"] else {})})
        return ws_json(outcome)

    return await offload(_sync_1)
