"""Nerva-scoped port of Hermes Kanban dashboard HTTP API.

Derived from plugins/kanban/dashboard/plugin_api.py at Hermes
59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e (MIT; see dashboard_upstream/LICENSE).
The host supplies authentication and a live KanbanContext. This module supplies no
WebSocket or ambient authorization fallback.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager, suppress
from contextvars import copy_context
from dataclasses import asdict
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from agents.core.app_state import get_orch
from agents.core.commands import Principal
from agents.core.file_tools import FileScope, FileScopeError

from . import projects
from .cli_upstream.board_selection import select_board
from .context import require_context, require_mutation
from .task_creation import create_task as create_scoped_task
from .upstream import kanban_db as kb
from .upstream import kanban_diagnostics as kd
from .workspaces import _git_root

router = APIRouter()
COLUMNS = ("triage", "todo", "scheduled", "ready", "running", "blocked", "review", "done")


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _error(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _scope(*, mutate: bool = False):
    try:
        context = require_mutation() if mutate else require_context()
        if context.delegated or context.task_id is not None or context.run_id is not None:
            raise PermissionError("dashboard API requires the owner request scope")
        return context
    except PermissionError as exc:
        raise _error(403, str(exc)) from exc


def _managed_board(slug: str) -> str:
    context = _scope()
    try:
        slug = kb._normalize_board_slug(slug) or kb.DEFAULT_BOARD
    except ValueError as exc:
        raise _error(400, str(exc)) from exc
    root = context.home.expanduser().resolve()
    boards = kb.boards_root()
    if boards.resolve() != root / "kanban" / "boards":
        raise _error(403, "board root escapes the scoped data home")
    if slug != kb.DEFAULT_BOARD:
        path = kb.board_dir(slug)
        if path.resolve() != boards / slug:
            raise _error(403, "board path escapes the scoped data home")
    return slug


def _board(raw: str | None, *, must_exist: bool = True) -> str:
    context = _scope()
    slug = _managed_board(raw or context.board)
    if context.task_id is not None and slug != context.board:
        raise _error(403, "worker cannot switch boards")
    if must_exist and not kb.board_exists(slug):
        raise _error(404, f"board {slug!r} does not exist")
    return slug


@contextmanager
def _conn(raw: str | None = None, *, mutate: bool = False) -> Iterator[tuple[str, sqlite3.Connection]]:
    _scope(mutate=mutate)
    board = _board(raw)
    expected = (_scope().home.expanduser().resolve() / "kanban.db" if board == kb.DEFAULT_BOARD
                else kb.board_dir(board) / "kanban.db")
    if kb.kanban_db_path(board).resolve() != expected:
        raise _error(403, "board database escapes the scoped data home")
    try:
        with kb.scoped_current_board(board), closing(kb.connect(board=board)) as conn:
            yield board, conn
    except (ValueError, PermissionError) as exc:
        raise _error(400 if isinstance(exc, ValueError) else 403, str(exc)) from exc


def _task(conn, task_id: str):
    task = kb.get_task(conn, task_id)
    if task is None:
        raise _error(404, f"task {task_id} not found")
    return task


def _run(conn, run_id: int):
    run = kb.get_run(conn, run_id)
    if run is None:
        raise _error(404, f"run {run_id} not found")
    return run


def _task_view(task, *, summary=None, run_start=None):
    value = asdict(task)
    value["age"] = kb.task_age(task)
    value["latest_summary"] = summary
    value["current_run_started_at"] = run_start
    return value


def _attachment_view(att):
    return {key: getattr(att, key) for key in
            ("id", "task_id", "filename", "content_type", "size", "uploaded_by", "stored_path", "created_at")}


def _diagnostics(conn, ids: list[str] | None = None):
    if ids is not None and not ids:
        return {}
    if ids is None:
        tasks = conn.execute("SELECT * FROM tasks WHERE status != 'archived'").fetchall()
    else:
        marks = ",".join("?" for _ in ids)
        tasks = conn.execute(f"SELECT * FROM tasks WHERE id IN ({marks})", ids).fetchall()  # nosec B608 - interpolation contains only generated '?' placeholders; ids are bound
    if not tasks:
        return {}
    ids = [r["id"] for r in tasks]
    marks = ",".join("?" for _ in ids)
    def by_task(table):
        if table not in {"task_events", "task_runs"}:
            raise ValueError("unknown diagnostic table")
        out = {task_id: [] for task_id in ids}
        for row in conn.execute(f"SELECT * FROM {table} WHERE task_id IN ({marks}) ORDER BY id", ids):  # nosec B608 - fixed allowlisted tables and generated '?' placeholders; ids are bound
            out[row["task_id"]].append(row)
        return out
    events, runs = by_task("task_events"), by_task("task_runs")
    graph = kb.task_graph_contexts(conn, ids)
    # The pinned diagnostic engine's defaults are static; config-dependent
    # thresholds remain unsupported until Nerva has a scoped config adapter.
    config = kd.config_from_runtime_config({})
    return {r["id"]: [d.to_dict() for d in kd.compute_task_diagnostics(
        r, events[r["id"]], runs[r["id"]], config=config, graph=graph.get(r["id"]))]
            for r in tasks}


def _warnings_summary(diagnostics: list[dict]):
    if not diagnostics:
        return None
    kinds: dict[str, int] = {}
    count = latest = 0
    highest_idx, highest_sev = -1, None
    for diagnostic in diagnostics:
        n = diagnostic.get("count", 1)
        kinds[diagnostic["kind"]] = kinds.get(diagnostic["kind"], 0) + n
        count += n
        latest = max(latest, diagnostic.get("last_seen_at") or 0)
        severity = diagnostic.get("severity")
        if severity in kd.SEVERITY_ORDER and kd.SEVERITY_ORDER.index(severity) > highest_idx:
            highest_idx, highest_sev = kd.SEVERITY_ORDER.index(severity), severity
    return {"count": count, "kinds": kinds, "latest_at": latest, "highest_severity": highest_sev}


def _links(conn, task_id):
    return {"parents": [r[0] for r in conn.execute("SELECT parent_id FROM task_links WHERE child_id = ? ORDER BY parent_id", (task_id,))],
            "children": [r[0] for r in conn.execute("SELECT child_id FROM task_links WHERE parent_id = ? ORDER BY child_id", (task_id,))]}


def _active_guard(conn, task_id: str, *, destructive: bool = False):
    task = _task(conn, task_id)
    if task.status == "running" or (task.current_run_id is not None and
            (run := kb.get_run(conn, task.current_run_id)) is not None and run.ended_at is None):
        raise _error(409, "live run changes require the bound worker controller")
    if destructive and task.status in {"done", "archived"}:
        children = conn.execute("SELECT 1 FROM task_links WHERE parent_id = ? LIMIT 1", (task_id,)).fetchone()
        if children:
            raise _error(503, "descendant invalidation requires the worker controller")
    return task


def _unavailable(name: str):
    raise _error(503, f"{name} requires a Nerva adapter")


@router.get("/board")
def get_board(tenant: str | None = None, include_archived: bool = False, board: str | None = None,
              workflow_template_id: str | None = None, current_step_key: str | None = None):
    with _conn(board) as (_slug, conn):
        tasks = kb.list_tasks(conn, tenant=tenant, include_archived=include_archived,
                              workflow_template_id=workflow_template_id, current_step_key=current_step_key)
        columns = {c: [] for c in COLUMNS}
        if include_archived:
            columns["archived"] = []
        comment_counts = {r["task_id"]: r["n"] for r in conn.execute(
            "SELECT task_id, COUNT(*) n FROM task_comments GROUP BY task_id")}
        link_counts = {}
        progress = {}
        for row in conn.execute("SELECT l.parent_id, l.child_id, t.status FROM task_links l JOIN tasks t ON t.id = l.child_id"):
            link_counts.setdefault(row["parent_id"], {"parents": 0, "children": 0})["children"] += 1
            link_counts.setdefault(row["child_id"], {"parents": 0, "children": 0})["parents"] += 1
            p = progress.setdefault(row["parent_id"], {"done": 0, "total": 0})
            p["total"] += 1
            p["done"] += row["status"] == "done"
        summaries = kb.latest_summaries(conn, [t.id for t in tasks])
        starts = kb.current_run_started_ats(conn, [t.id for t in tasks])
        diags = _diagnostics(conn)
        for task in tasks:
            summary = summaries.get(task.id)
            view = _task_view(task, summary=summary[:200] if summary else None, run_start=starts.get(task.id))
            view.update(link_counts=link_counts.get(task.id, {"parents": 0, "children": 0}),
                        comment_count=comment_counts.get(task.id, 0), progress=progress.get(task.id))
            if diags.get(task.id):
                view["diagnostics"] = diags[task.id]
                view["warnings"] = _warnings_summary(diags[task.id])
            columns[task.status if task.status in columns else "todo"].append(view)
        columns["done"].sort(key=lambda d: d["id"], reverse=True)
        columns["done"].sort(key=lambda d: (d["completed_at"] is None, -(d["completed_at"] or 0)))
        return {"columns": [{"name": name, "tasks": cards} for name, cards in columns.items()],
                "tenants": [r[0] for r in conn.execute("SELECT DISTINCT tenant FROM tasks WHERE tenant IS NOT NULL ORDER BY tenant")],
                "assignees": [r[0] for r in conn.execute("SELECT DISTINCT assignee FROM tasks WHERE assignee IS NOT NULL AND status != 'archived' ORDER BY assignee")],
                "latest_event_id": conn.execute("SELECT COALESCE(MAX(id), 0) FROM task_events").fetchone()[0],
                "now": int(time.time())}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, board: str | None = None, run_state_type: str | None = None,
             run_state_name: str | None = None):
    with _conn(board) as (_slug, conn):
        if (run_state_type is None) != (run_state_name is None) or run_state_type not in (None, "status", "outcome"):
            raise _error(400, "run_state_type and run_state_name must be paired; type is status or outcome")
        task = _task(conn, task_id)
        links = _links(conn, task_id)
        children = [kb.get_task(conn, child) for child in links["children"]]
        summaries = kb.latest_summaries(conn, links["children"])
        view = _task_view(task, summary=kb.latest_summary(conn, task_id),
                          run_start=kb.current_run_started_ats(conn, [task_id]).get(task_id))
        task_diags = _diagnostics(conn, [task_id]).get(task_id, [])
        if task_diags:
            view["diagnostics"] = task_diags
            view["warnings"] = _warnings_summary(task_diags)
        return {"task": view, "comments": [asdict(c) for c in kb.list_comments(conn, task_id)],
                "events": [asdict(e) for e in kb.list_events(conn, task_id)],
                "attachments": [_attachment_view(a) for a in kb.list_attachments(conn, task_id)],
                "links": links,
                "link_tasks": [{"id": t.id, "title": t.title, "status": t.status} for t in
                               (kb.get_task(conn, x) for x in links["parents"] + links["children"]) if t],
                "child_results": [{"id": c.id, "title": c.title, "status": c.status,
                                   "latest_summary": summaries.get(c.id), "result": c.result} for c in children if c],
                "runs": [asdict(r) for r in kb.list_runs(conn, task_id, state_type=run_state_type,
                                                          state_name=run_state_name)]}


class CreateTaskBody(StrictBody):
    title: str
    body: str | None = None
    assignee: str | None = None
    tenant: str | None = None
    priority: int = 0
    workspace_kind: str | None = None
    workspace_path: str | None = None
    parents: list[str] = Field(default_factory=list)
    triage: bool = False
    idempotency_key: str | None = None
    max_runtime_seconds: int | None = None
    skills: list[str] | None = None
    goal_mode: bool = False
    goal_max_turns: int | None = None
    model_override: str | None = None
    provider_override: str | None = None
    reasoning_effort: str | None = None
    project_id: str | None = None


@router.post("/tasks")
def create_task(payload: CreateTaskBody, board: str | None = None):
    context = _scope(mutate=True)
    if payload.goal_mode or payload.goal_max_turns is not None:
        _unavailable("goal judging")
    with _conn(board, mutate=True) as (slug, conn):
        try:
            task_id = create_scoped_task(conn, created_by=context.profile, session_id=context.session_id,
                                         board=slug, **payload.model_dump())
        except ValueError as exc:
            raise _error(400, str(exc)) from exc
        task = kb.get_task(conn, task_id)
        return {"task": _task_view(task, run_start=kb.current_run_started_ats(conn, [task_id]).get(task_id))}


class CommentBody(StrictBody):
    body: str


@router.post("/tasks/{task_id}/comments")
def add_comment(task_id: str, payload: CommentBody, board: str | None = None):
    context = _scope(mutate=True)
    if not payload.body.strip():
        raise _error(400, "body is required")
    with _conn(board, mutate=True) as (_slug, conn):
        _task(conn, task_id)
        kb.add_comment(conn, task_id, author=context.profile, body=payload.body)
        return {"ok": True}


class LinkBody(StrictBody):
    parent_id: str
    child_id: str


@router.post("/links")
def add_link(payload: LinkBody, board: str | None = None):
    with _conn(board, mutate=True) as (_slug, conn):
        _active_guard(conn, payload.parent_id, destructive=True)
        _active_guard(conn, payload.child_id)
        try:
            gated = kb.link_tasks(conn, payload.parent_id, payload.child_id)
        except ValueError as exc:
            raise _error(400, str(exc)) from exc
        return {"ok": True, "gated": gated}


@router.delete("/links")
def delete_link(parent_id: str, child_id: str, board: str | None = None):
    with _conn(board, mutate=True) as (_slug, conn):
        _active_guard(conn, child_id)
        return {"ok": bool(kb.unlink_tasks(conn, parent_id, child_id))}


class UpdateTaskBody(StrictBody):
    status: str | None = None
    assignee: str | None = None
    priority: int | None = None
    title: str | None = None
    body: str | None = None
    result: str | None = None
    block_reason: str | None = None
    summary: str | None = None
    metadata: dict | None = None
    model_override: str | None = None
    provider_override: str | None = None
    clear_model_override: bool = False
    reasoning_effort: str | None = None
    clear_reasoning_effort: bool = False


def _apply_patch(conn, task_id: str, payload: UpdateTaskBody, board: str):
    if payload.title is not None and not payload.title.strip():
        raise _error(400, "title cannot be empty")
    task = _active_guard(conn, task_id, destructive=payload.status in {"triage", "todo", "ready", "archived"})
    if payload.status == "running":
        raise _error(400, "running requires the dispatcher claim path")
    if payload.status in {"review", "done", "archived"} and task.workspace_path:
        _unavailable("workspace lifecycle")
    if payload.status in {"review", "done"} and payload.metadata and payload.metadata.get("artifacts"):
        _unavailable("workspace artifact preservation")
    if payload.status and task.status in {"done", "archived"} and payload.status not in {"done", "archived"}:
        _unavailable("descendant invalidation")
    if payload.status == "review":
        if task.status != "ready":
            raise _error(409, "review requires a ready task")
        ok = kb.request_review(conn, task_id, summary=payload.summary, metadata=payload.metadata,
                               reviewer=payload.assignee or None)
    elif payload.status == "done":
        if task.status not in {"ready", "blocked", "review"}:
            raise _error(409, "completion requires a ready, blocked, or review task")
        ok = kb.complete_task(conn, task_id, result=payload.result, summary=payload.summary,
                              metadata=payload.metadata)
    elif payload.status == "blocked":
        ok = kb.block_task(conn, task_id, reason=payload.block_reason)
    elif payload.status == "scheduled":
        ok = kb.schedule_task(conn, task_id, reason=payload.block_reason)
    elif payload.status == "archived":
        ok = kb.archive_task(conn, task_id)
    elif payload.status in {"triage", "todo", "ready"}:
        if task.status == "review":
            ok = kb.reopen_review_task(conn, task_id)
        elif payload.status == "ready" and task.status in {"blocked", "scheduled"}:
            ok = kb.unblock_task(conn, task_id)
        else:
            with kb.write_txn(conn):
                _active_guard(conn, task_id, destructive=True)
                if payload.status == "ready" and kb.unsatisfied_parents(conn, task_id):
                    raise _error(409, "parent dependencies are not satisfied")
                conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (payload.status, task_id))
                conn.execute("INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'status', ?, ?)",
                             (task_id, json.dumps({"status": payload.status}), int(time.time())))
            ok = True
        kb.recompute_ready(conn)
    elif payload.status is not None:
        raise _error(400, f"unknown status: {payload.status}")
    else:
        ok = True
    if not ok:
        raise _error(409, f"status transition to {payload.status!r} refused")
    if (payload.assignee is not None and payload.status != "review"
            and not kb.assign_task(conn, task_id, payload.assignee or None)):
        raise _error(409, "assignment refused")
    if payload.clear_model_override or payload.model_override is not None:
        kb.set_model_override(conn, task_id, None if payload.clear_model_override else payload.model_override,
                              provider=payload.provider_override)
    if payload.clear_reasoning_effort or payload.reasoning_effort is not None:
        kb.set_reasoning_effort(conn, task_id, None if payload.clear_reasoning_effort else payload.reasoning_effort)
    if any(x is not None for x in (payload.title, payload.body, payload.priority)):
        kb.edit_task(conn, task_id, title=payload.title, body=payload.body, priority=payload.priority, board=board)
    return kb.get_task(conn, task_id)


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, payload: UpdateTaskBody, board: str | None = None):
    with _conn(board, mutate=True) as (slug, conn):
        try:
            task = _apply_patch(conn, task_id, payload, slug)
        except (ValueError, RuntimeError) as exc:
            raise _error(400, str(exc)) from exc
        return {"task": _task_view(task, run_start=kb.current_run_started_ats(conn, [task_id]).get(task_id))}


class BulkTaskBody(UpdateTaskBody):
    ids: list[str]
    archive: bool = False
    reclaim_first: bool = False


@router.post("/tasks/bulk")
def bulk_update(payload: BulkTaskBody, board: str | None = None):
    if not payload.ids:
        raise _error(400, "ids is required")
    if payload.reclaim_first:
        _unavailable("worker reclaim")
    change = UpdateTaskBody(**payload.model_dump(exclude={"ids", "archive", "reclaim_first"}))
    if payload.archive:
        change.status = "archived"
    with _conn(board, mutate=True) as (slug, conn):
        outcomes = []
        for task_id in payload.ids:
            try:
                _apply_patch(conn, task_id, change, slug)
                outcomes.append({"id": task_id, "ok": True})
            except (HTTPException, ValueError, RuntimeError) as exc:
                outcomes.append({"id": task_id, "ok": False, "error": getattr(exc, "detail", str(exc))})
        return {"results": outcomes}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, board: str | None = None):
    with _conn(board, mutate=True) as (_slug, conn):
        _active_guard(conn, task_id, destructive=True)
        if not kb.delete_task(conn, task_id):
            raise _error(404, "task not found")
        return {"deleted": True, "task_id": task_id}


def _task_attachment_root(task_id: str, board: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
        raise _error(404, "attachment path unavailable")
    home = _scope().home.expanduser().resolve()
    expected_root = home / "kanban" / "attachments" if board == kb.DEFAULT_BOARD else kb.board_dir(board) / "attachments"
    root = kb.attachments_root(board)
    if root.resolve() != expected_root:
        raise _error(404, "attachment root unavailable")
    task_root = kb.task_attachments_dir(task_id, board)
    if task_root.resolve() != root / task_id:
        raise _error(404, "task attachment root unavailable")
    return task_root


def _checked_attachment(conn, attachment_id: int, board: str):
    att = kb.get_attachment(conn, attachment_id)
    if att is None:
        raise _error(404, "attachment not found")
    _task(conn, att.task_id)
    task_root = _task_attachment_root(att.task_id, board)
    stored = Path(att.stored_path).resolve()
    if stored.parent != task_root or stored.name != att.filename:
        raise _error(404, "attachment file unavailable")
    return att, stored


@router.get("/tasks/{task_id}/attachments")
def list_task_attachments(task_id: str, board: str | None = None):
    with _conn(board) as (_slug, conn):
        _task(conn, task_id)
        return {"attachments": [_attachment_view(a) for a in kb.list_attachments(conn, task_id)]}


@router.post("/tasks/{task_id}/attachments")
async def upload_task_attachment(task_id: str, request: Request, board: str | None = None):
    # The repo's approved runtime has no python-multipart. Parse one bounded
    # multipart file with stdlib email; never buffer beyond the 25 MiB cap plus
    # a small header envelope. The donor filename sanitizer is still canonical.
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data;"):
        raise _error(415, "multipart/form-data file upload required")
    maximum = kb.KANBAN_ATTACHMENT_MAX_BYTES + 1024 * 1024
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > maximum:
            raise _error(413, "attachment exceeds 25 MB limit")
    header = Message()
    header["Content-Type"] = content_type
    boundary = header.get_boundary()
    if not boundary or not 1 <= len(boundary) <= 70 or not boundary.isascii():
        raise _error(400, "invalid multipart boundary")
    if raw.count(b"--" + boundary.encode("ascii")) > 3:
        raise _error(400, "only one file field is allowed")
    message = BytesParser(policy=policy.default).parsebytes(
        ("MIME-Version: 1.0\r\nContent-Type: " + content_type + "\r\n\r\n").encode() + raw)
    if not message.is_multipart():
        raise _error(400, "invalid multipart upload")
    parts = list(message.iter_parts())
    if len(parts) != 1 or parts[0].is_multipart():
        raise _error(400, "exactly one file field is required")
    part = parts[0]
    if part.get_param("name", header="content-disposition") != "file" or part.get_filename() is None:
        raise _error(400, "exactly one file field is required")
    data = part.get_payload(decode=True)
    if data is None:
        raise _error(400, "invalid file payload")
    if len(data) > kb.KANBAN_ATTACHMENT_MAX_BYTES:
        raise _error(413, "attachment exceeds 25 MB limit")

    def save():
        with _conn(board, mutate=True) as (slug, conn):
            _task(conn, task_id)
            try:
                safe_name = kb._safe_attachment_name(part.get_filename() or "")
            except ValueError as exc:
                raise _error(400, str(exc)) from exc
            dest_dir = _task_attachment_root(task_id, slug)
            dest_dir.mkdir(parents=True, exist_ok=True)
            path = kb._collision_free_path(dest_dir, safe_name)
            try:
                with path.open("xb") as output:
                    output.write(data)
                att_id = kb.add_attachment(conn, task_id, filename=path.name, stored_path=str(path),
                                           content_type=part.get_content_type(), size=len(data),
                                           uploaded_by=_scope().profile)
            except Exception:
                path.unlink(missing_ok=True)
                raise
            att = kb.get_attachment(conn, att_id)
            return {"attachment": _attachment_view(att)}
    return await asyncio.to_thread(save)


@router.get("/attachments/{attachment_id}")
def download_attachment(attachment_id: int, board: str | None = None):
    with _conn(board) as (slug, conn):
        att, stored = _checked_attachment(conn, attachment_id, slug)
        if not stored.is_file():
            raise _error(404, "attachment file missing on disk")
        return FileResponse(str(stored), filename=att.filename, media_type=att.content_type or "application/octet-stream")


@router.delete("/attachments/{attachment_id}")
def remove_attachment(attachment_id: int, board: str | None = None):
    with _conn(board, mutate=True) as (slug, conn):
        att, _stored = _checked_attachment(conn, attachment_id, slug)
        _active_guard(conn, att.task_id)
        if kb.delete_attachment(conn, attachment_id) is None:
            raise _error(404, "attachment not found")
        return {"ok": True, "id": attachment_id}


@router.get("/runs/{run_id}")
def get_run(run_id: int, board: str | None = None):
    with _conn(board) as (_slug, conn):
        return {"run": asdict(_run(conn, run_id))}


@router.get("/workers/active")
def list_active_workers(board: str | None = None):
    with _conn(board) as (_slug, conn):
        rows = conn.execute("SELECT r.id AS run_id, r.task_id, t.title AS task_title, t.status AS task_status, "
                            "t.assignee AS task_assignee, r.profile, r.worker_pid, r.started_at, r.claim_lock, "
                            "r.claim_expires, r.last_heartbeat_at, r.max_runtime_seconds FROM task_runs r "
                            "JOIN tasks t ON t.id = r.task_id WHERE r.ended_at IS NULL "
                            "AND r.worker_pid IS NOT NULL AND t.status = 'running' ORDER BY r.started_at").fetchall()
        return {"workers": [dict(r) for r in rows], "count": len(rows), "checked_at": int(time.time())}


@router.get("/diagnostics")
def list_diagnostics(board: str | None = None, severity: str | None = None):
    with _conn(board) as (_slug, conn):
        diagnoses = _diagnostics(conn)
        result = []
        for task_id, entries in diagnoses.items():
            kept = [d for d in entries if kd.severity_at_or_above(d.get("severity"), severity)]
            if not kept:
                continue
            task = kb.get_task(conn, task_id)
            result.append({"task_id": task_id, "task_title": task.title if task else None,
                           "task_status": task.status if task else None,
                           "task_assignee": task.assignee if task else None, "diagnostics": kept})
        order = {s: i for i, s in enumerate(kd.SEVERITY_ORDER)}
        result.sort(key=lambda row: (-order.get(row["diagnostics"][0]["severity"], -1),
                                     -(row["diagnostics"][0].get("last_seen_at") or 0)))
        return {"diagnostics": result, "count": sum(len(r["diagnostics"]) for r in result)}


@router.get("/stats")
def get_stats(board: str | None = None):
    with _conn(board) as (_slug, conn):
        return kb.board_stats(conn)


@router.get("/assignees")
def get_assignees(board: str | None = None):
    with _conn(board) as (_slug, conn):
        return {"assignees": kb.known_assignees(conn)}


class CreateBoardBody(StrictBody):
    slug: str
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    default_workdir: str | None = None
    project_id: str | None = None
    switch: bool = False


class RenameBoardBody(StrictBody):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    default_workdir: str | None = None
    project_id: str | None = None


def _board_counts(slug: str):
    if not kb.kanban_db_path(slug).exists():
        return {}
    with closing(kb.connect(board=slug)) as conn:
        return {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM tasks GROUP BY status")}


def _board_workspace_path(raw: str) -> str:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValueError("board workdir requires an absolute directory")
    path = FileScope.from_env().resolve(str(candidate))
    if not path.is_dir():
        raise ValueError("board workdir must be an existing directory")
    return str(path)


def _annotate_board(meta: dict) -> dict:
    """Project/workspace projection uses the same current roots as task creation."""
    try:
        primary = None
        project_name = None
        if meta.get("project_id"):
            # An unavailable legacy link remains visible; task creation still
            # refuses it rather than silently choosing another project.
            with suppress(ValueError):
                _, project_name, primary = projects.resolve_project(meta["project_id"])
        workdir = meta.get("default_workdir") or primary
        kind = "scratch"
        if workdir:
            path = Path(_board_workspace_path(str(workdir)))
            kind = "worktree" if _git_root(FileScope.from_env(), path) else "dir"
        return {**meta, "default_workspace_kind": kind, "project_name": project_name}
    except (FileScopeError, PermissionError) as exc:
        raise _error(403, str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise _error(400, str(exc)) from exc


def _board_workspace_updates(payload, current: dict) -> dict:
    """Validate the complete prospective metadata before any board write."""
    changes = {}
    try:
        if "project_id" in payload.model_fields_set:
            requested = (payload.project_id or "").strip()
            project_id, _, primary = projects.resolve_project(requested)
            changes["project_id"] = project_id or ""
            if "default_workdir" not in payload.model_fields_set:
                old_primary = None
                if current.get("project_id"):
                    with suppress(ValueError):
                        _, _, old_primary = projects.resolve_project(current["project_id"])
                previous = current.get("default_workdir")
                if not previous or previous == old_primary:
                    changes["default_workdir"] = primary or ""
        if "default_workdir" in payload.model_fields_set:
            raw = (payload.default_workdir or "").strip()
            changes["default_workdir"] = _board_workspace_path(raw) if raw else ""
        prospective = {**current, **{k: v or None for k, v in changes.items()}}
        _annotate_board(prospective)
        return changes
    except (FileScopeError, PermissionError) as exc:
        raise _error(403, str(exc)) from exc
    except ValueError as exc:
        raise _error(400, str(exc)) from exc


@router.get("/boards")
def list_boards(include_archived: bool = False):
    _scope()
    boards = []
    for meta in kb.list_boards(include_archived=include_archived):
        slug = _managed_board(meta["slug"])
        counts = _board_counts(slug)
        meta.update(is_current=(slug == _board(None)), counts=counts,
                    total=sum(n for status, n in counts.items() if status != "archived"))
        boards.append(_annotate_board(meta))
    return {"boards": boards, "current": _board(None)}


@router.post("/boards")
def create_board(payload: CreateBoardBody):
    _scope(mutate=True)
    slug = _managed_board(payload.slug)
    updates = _board_workspace_updates(payload, kb.read_board_metadata(slug))
    try:
        meta = kb.create_board(slug, name=payload.name, description=payload.description,
                               icon=payload.icon, color=payload.color, **updates)
    except ValueError as exc:
        raise _error(400, str(exc)) from exc
    if payload.switch:
        select_board(slug)
    return {"board": _annotate_board(meta),
            "current": slug if payload.switch else _board(None)}


@router.patch("/boards/{slug}")
def rename_board(slug: str, payload: RenameBoardBody):
    _scope(mutate=True)
    slug = _board(slug)
    updates = _board_workspace_updates(payload, kb.read_board_metadata(slug))
    meta = kb.write_board_metadata(slug, name=payload.name, description=payload.description,
                                   icon=payload.icon, color=payload.color, **updates)
    return {"board": _annotate_board(meta)}


@router.delete("/boards/{slug}")
def delete_board(slug: str, delete: bool = False):
    _scope(mutate=True)
    slug = _board(slug)
    if slug == _board(None):
        raise _error(409, "cannot remove the current scoped board")
    if delete:
        _unavailable("hard board deletion")
    root = kb.board_dir(slug)
    if (root.is_symlink() or root.resolve() != kb.boards_root() / slug
            or (kb.boards_root() / "_archived").resolve() != kb.boards_root() / "_archived"):
        raise _error(403, "board archive path escapes the scoped data home")
    try:
        result = kb.remove_board(slug, archive=True)
    except ValueError as exc:
        raise _error(400, str(exc)) from exc
    return {"result": result, "current": _board(None)}


@router.post("/dispatch")
async def dispatch(dry_run: bool = False, max_n: int = Query(8, alias="max", ge=1, le=16), board: str | None = None):
    _scope(mutate=True)
    slug = _board(board)
    if dry_run:
        _unavailable("dispatch preview")
    orch = get_orch()
    coordinator = getattr(orch, "_autonomy", None) if orch else None
    adapter = coordinator.kanban_dispatcher() if coordinator else None
    if adapter is None:
        _unavailable("signed queue dispatch")
    return await adapter.request(Principal(channel="web", admin=True), board=slug, limit=max_n)


# Preserve the donor route shapes while explicit Nerva adapters are built.
# Unsupported effects never launch local processes, call providers, edit profile
# config, open arbitrary filesystem paths, or claim successful work.
class EmptyBody(StrictBody):
    pass


class ReasonBody(StrictBody):
    reason: str | None = None


class ReassignBody(StrictBody):
    profile: str | None = None
    reclaim_first: bool = False
    reason: str | None = None


class ExportBoardBody(StrictBody):
    output: str = ""
    attachments: bool = True
    logs: bool = False


class ImportBoardBody(StrictBody):
    archive: str
    slug: str | None = None
    switch: bool = False


class EstimateBody(StrictBody):
    title: str = ""
    body: str | None = None


class OrchestrationBody(StrictBody):
    orchestrator_profile: str | None = None
    default_assignee: str | None = None
    auto_decompose: bool | None = None
    auto_promote_children: bool | None = None


class DescribeBody(StrictBody):
    description: str | None = None


class DescribeAutoBody(StrictBody):
    overwrite: bool = False


@router.get("/config")
def get_config():
    _scope()
    _unavailable("scoped dashboard config")


@router.get("/orchestration")
def get_orchestration():
    _scope()
    _unavailable("scoped orchestration config")


@router.put("/orchestration")
def set_orchestration(payload: OrchestrationBody):
    _scope(mutate=True)
    _unavailable("scoped orchestration config")


@router.get("/model-options")
def model_options():
    _scope()
    _unavailable("provider inventory")


@router.get("/projects")
def list_projects():
    _scope()
    try:
        return {"projects": projects.list_projects()}
    except PermissionError as exc:
        raise _error(403, str(exc)) from exc


@router.get("/home-channels")
def home_channels(task_id: str | None = None, board: str | None = None):
    _scope()
    _unavailable("channel notification")


@router.post("/tasks/{task_id}/home-subscribe/{platform}")
def subscribe_home(task_id: str, platform: str, board: str | None = None):
    _scope(mutate=True)
    _unavailable("channel notification")


@router.delete("/tasks/{task_id}/home-subscribe/{platform}")
def unsubscribe_home(task_id: str, platform: str, board: str | None = None):
    _scope(mutate=True)
    _unavailable("channel notification")


@router.get("/tasks/{task_id}/log")
def task_log(task_id: str, tail: int | None = None, board: str | None = None):
    _scope()
    _unavailable("worker log access")


@router.get("/runs/{run_id}/inspect")
def inspect_run(run_id: int, board: str | None = None):
    _scope()
    _unavailable("worker process inspection")


@router.post("/runs/{run_id}/terminate")
def terminate_run(run_id: int, payload: ReasonBody, board: str | None = None):
    _scope(mutate=True)
    _unavailable("worker process termination")


@router.post("/tasks/{task_id}/reclaim")
def reclaim(task_id: str, payload: ReasonBody, board: str | None = None):
    _scope(mutate=True)
    _unavailable("worker reclaim")


@router.post("/tasks/{task_id}/reassign")
def reassign(task_id: str, payload: ReassignBody, board: str | None = None):
    _scope(mutate=True)
    if payload.reclaim_first:
        _unavailable("worker reclaim")
    with _conn(board, mutate=True) as (_slug, conn):
        _active_guard(conn, task_id)
        if not kb.reassign_task(conn, task_id, payload.profile or None, reclaim_first=False, reason=payload.reason):
            raise _error(409, "reassignment refused")
        return {"ok": True, "task_id": task_id, "assignee": payload.profile or None}


@router.post("/tasks/{task_id}/specify")
def specify(task_id: str, payload: EmptyBody, board: str | None = None):
    _scope(mutate=True)
    _unavailable("auxiliary specifier")


@router.post("/tasks/{task_id}/decompose")
def decompose(task_id: str, payload: EmptyBody, board: str | None = None):
    _scope(mutate=True)
    _unavailable("auxiliary decomposer")


@router.post("/estimate")
def estimate(payload: EstimateBody):
    _scope()
    _unavailable("auxiliary estimator")


@router.post("/tasks/{task_id}/estimate")
def estimate_task(task_id: str, board: str | None = None):
    _scope()
    _unavailable("auxiliary estimator")


@router.post("/boards/{slug}/export")
def export_board(slug: str, payload: ExportBoardBody):
    _scope(mutate=True)
    _unavailable("board transfer")


@router.post("/boards/import")
def import_board(payload: ImportBoardBody):
    _scope(mutate=True)
    _unavailable("board transfer")


@router.post("/boards/{slug}/switch")
def switch_board(slug: str):
    _scope(mutate=True)
    slug = _board(slug)
    select_board(slug)
    return {"ok": True, "current": slug}


@router.get("/profiles")
def profiles():
    _scope()
    _unavailable("profile inventory")


@router.patch("/profiles/{profile_name}")
def update_profile(profile_name: str, payload: DescribeBody):
    _scope(mutate=True)
    _unavailable("profile configuration")


@router.post("/profiles/{profile_name}/describe-auto")
def describe_auto(profile_name: str, payload: DescribeAutoBody):
    _scope(mutate=True)
    _unavailable("auxiliary profile description")


# HTTP router has no WebSocket route. The host authenticates upgrades and uses
# these copied polling helpers under the same request-local Nerva scope.
_EVENT_POLL_SECONDS = 0.3


def _since_param(ws: WebSocket) -> int | None:
    raw = ws.query_params.get("since")
    if raw is None or not str(raw).strip():
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None


def _ws_board(raw: str | None) -> str | None:
    try:
        return kb._normalize_board_slug(raw) if raw else None
    except ValueError:
        return None


class _EventTail:
    """One board-local WAL reader on a dedicated thread, with its Nerva scope copied."""

    def __init__(self, board: str | None):
        self._board = _board(board)
        self._conn: sqlite3.Connection | None = None
        self._executor: ThreadPoolExecutor | None = None

    def _connection(self) -> sqlite3.Connection:
        _scope()
        if self._conn is None:
            with kb.scoped_current_board(self._board):
                self._conn = kb.connect(board=self._board)
        return self._conn

    def _latest(self) -> int:
        return int(self._connection().execute("SELECT COALESCE(MAX(id), 0) FROM task_events").fetchone()[0])

    def _fetch(self, cursor: int) -> tuple[int, list[dict]]:
        rows = self._connection().execute(
            "SELECT id, task_id, run_id, kind, payload, created_at "
            "FROM task_events WHERE id > ? ORDER BY id ASC LIMIT 200", (cursor,)).fetchall()
        events = []
        for row in rows:
            try:
                payload = json.loads(row["payload"]) if row["payload"] else None
            except (TypeError, ValueError):
                payload = None
            events.append({**dict(row), "payload": payload})
        return (int(rows[-1]["id"]) if rows else cursor), events

    def _close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def _run(self, fn, *args):
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kanban-events")
        ctx = copy_context()
        return await asyncio.get_running_loop().run_in_executor(self._executor, ctx.run, fn, *args)

    async def latest(self) -> int:
        return await self._run(self._latest)

    async def poll(self, cursor: int) -> tuple[int, list[dict]]:
        return await self._run(self._fetch, cursor)

    async def shutdown(self):
        if self._executor is None:
            return
        try:
            await self._run(self._close)
        finally:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
