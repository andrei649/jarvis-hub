"""Nerva Workspace — reports, report runs, exports and the shared-reports feed (spec §7, §9).

Every route needs a signed-in user (``WsUser``); what they may touch is decided in
``agents.core.workspace.reports``: reports of their own departments (admins: all), edits
by the owner, the department's approvers or an admin, runs visible to the report's
department plus company-shared runs to everyone. Anything out of scope answers ``404``.

A run is queued in the request's transaction and started after it commits
(``202 {run}``); the client polls ``GET /report-runs/{id}`` until it finishes. Exports are
attachments with a sandboxing CSP, so a downloaded HTML report can never run script.
Importing ``reports`` registers the ``report.delivery``, ``report.share_company`` and
``email.send`` approval effects.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from agents.core.workspace import auth, reports
from agents.core.workspace.auth import WsUser
from agents.core.workspace.db import Db
from agents.core.workspace.http import MAX_ID, read_json, ws_json, ws_no_content

logger = logging.getLogger("nerva.workspace.routers.reports")

router = APIRouter(prefix="/api/workspace")

ReportId = Annotated[int, Path(ge=1, le=MAX_ID)]
RunId = Annotated[int, Path(ge=1, le=MAX_ID)]
DepartmentFilter = Annotated[int | None, Query(ge=1, le=MAX_ID)]
ExportFormat = Annotated[str, Query(pattern="^(md|html)$", max_length=4)]


@router.get("/reports")
def list_reports(user: WsUser, conn: Db, department_id: DepartmentFilter = None) -> JSONResponse:
    """Reports of one department, or of every department the caller may use."""
    return ws_json({"reports": reports.list_reports(conn, user, department_id)})


@router.post("/reports")
async def create_report(request: Request, user: WsUser, conn: Db) -> JSONResponse:
    """Define a report; recipients open a delivery approval in the same transaction."""
    body = await read_json(request)
    report_id = reports.create_report(conn, user, body, ip=auth.client_ip(request))
    return ws_json(reports.get_report(conn, user, report_id), 201)


@router.get("/reports/{report_id}")
def get_report(report_id: ReportId, user: WsUser, conn: Db) -> JSONResponse:
    """One report with its schedule, delivery state and next run."""
    return ws_json(reports.get_report(conn, user, report_id))


@router.patch("/reports/{report_id}")
async def update_report(report_id: ReportId, request: Request, user: WsUser,
                        conn: Db) -> JSONResponse:
    """Edit a report; changed recipients re-open the delivery approval."""
    body = await read_json(request)
    reports.update_report(conn, user, report_id, body, ip=auth.client_ip(request))
    return ws_json(reports.get_report(conn, user, report_id))


@router.delete("/reports/{report_id}")
def delete_report(report_id: ReportId, request: Request, user: WsUser, conn: Db) -> Response:
    """Delete a report with its runs (pending approvals about it are withdrawn)."""
    reports.delete_report(conn, user, report_id, ip=auth.client_ip(request))
    return ws_no_content()


@router.post("/reports/{report_id}/run")
async def run_report(report_id: ReportId, request: Request, user: WsUser,
                     conn: Db) -> JSONResponse:
    """Queue a run now (``202``); it executes in the background."""
    run_id = reports.start_manual_run(conn, user, report_id, ip=auth.client_ip(request))
    reports.spawn_run(run_id)
    return ws_json({"run": reports.get_run(conn, user, run_id)}, 202)


@router.get("/reports/{report_id}/runs")
def list_runs(report_id: ReportId, user: WsUser, conn: Db) -> JSONResponse:
    """The report's newest runs, without their content."""
    return ws_json({"runs": reports.list_runs(conn, user, report_id)})


@router.get("/report-runs/{run_id}")
def get_run(run_id: RunId, user: WsUser, conn: Db) -> JSONResponse:
    """One run with its Markdown, citations and what the caller may do with it."""
    return ws_json(reports.get_run(conn, user, run_id))


@router.get("/report-runs/{run_id}/export")
def export_run(run_id: RunId, user: WsUser, conn: Db, format: ExportFormat = "md") -> Response:
    """A finished run as a Markdown file or a standalone, print-ready HTML page."""
    export = reports.export_run(conn, user, run_id, format)
    return Response(export.content, media_type=export.media_type, headers={
        "Content-Disposition": reports.content_disposition(export.filename),
        "Content-Security-Policy": reports.EXPORT_CSP,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    })


@router.get("/shared-reports")
def shared_reports(user: WsUser, conn: Db) -> JSONResponse:
    """Runs shared with the whole company (readable by everyone signed in)."""
    return ws_json({"runs": reports.list_shared(conn, user)})
