"""Durable Nerva queue handoff over the pinned Hermes board transaction/CAS."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import asdict

from .upstream import kanban_db as kb
from .upstream import projects_db as pdb
from .workspaces import plan_workspace


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def input_snapshot(conn, task_id):
    task = kb.get_task(conn, task_id)
    if task is None:
        raise ValueError("board task no longer exists")
    parents = [kb.get_task(conn, tid) for tid in kb.parent_ids(conn, task_id)]
    return {
        "task": asdict(task),
        "parents": [asdict(p) if p else None for p in parents],
        "comments": [asdict(c) for c in kb.list_comments(conn, task_id)],
        "attachments": [asdict(a) for a in kb.list_attachments(conn, task_id)],
        "workspace_binding": workspace_snapshot(conn, task_id),
    }


def workspace_snapshot(conn, task_id):
    """Canonical board/project/path authority, unchanged by claim or heartbeat."""
    task = kb.get_task(conn, task_id)
    if task is None:
        raise ValueError("board task no longer exists")
    board = kb.get_current_board()
    metadata = kb.read_board_metadata(board)
    project = None
    if task.project_id:
        try:
            with pdb.connect_closing() as project_conn:
                found = pdb.get_project(project_conn, task.project_id)
        except FileNotFoundError as exc:
            raise ValueError("project no longer exists") from exc
        if found is None or found.archived:
            raise ValueError("project no longer exists or is archived")
        project = found.to_dict()
    return {
        "board": metadata,
        "project": project,
        "spec": plan_workspace(task, board=board,
                               project_root=project["primary_path"] if project else None),
    }


def initialize(conn):
    with kb.write_txn(conn):
        conn.execute("""CREATE TABLE IF NOT EXISTS nerva_dispatches (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, input_sha TEXT NOT NULL,
            lane TEXT NOT NULL, profile TEXT NOT NULL, prompt TEXT NOT NULL,
            prompt_sha TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'prepared',
            queue_id INTEGER, enqueue_id TEXT, run_id INTEGER, error TEXT,
            created_at INTEGER NOT NULL, workspace_json TEXT
        )""")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(nerva_dispatches)")}
        if "workspace_json" not in columns:
            conn.execute("ALTER TABLE nerva_dispatches ADD COLUMN workspace_json TEXT")


def prepare(conn, task, *, resume=None, prompt_suffix=""):
    with kb.write_txn(conn):
        inputs = input_snapshot(conn, task.id)
        if resume is not None:
            inputs["resume"] = resume
        sha = digest(inputs)
        existing = conn.execute(
            "SELECT * FROM nerva_dispatches WHERE task_id=? AND input_sha=? "
            "AND state IN ('prepared','queued') ORDER BY created_at DESC LIMIT 1",
            (task.id, sha),
        ).fetchone()
        if existing:
            return dict(existing, title=inputs["task"]["title"])
        prompt = kb.build_worker_context(conn, task.id) + prompt_suffix
        if len(prompt.encode()) > 512_000:
            raise ValueError("board context exceeds the bounded worker prompt")
        identifier = secrets.token_hex(16)
        conn.execute(
            """INSERT INTO nerva_dispatches
            (id, task_id, input_sha, lane, profile, prompt, prompt_sha, created_at, workspace_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                identifier,
                task.id,
                sha,
                inputs["task"]["status"],
                inputs["task"]["assignee"],
                prompt,
                digest(prompt),
                int(time.time()),
                json.dumps(inputs["workspace_binding"], sort_keys=True, ensure_ascii=False,
                           allow_nan=False, separators=(",", ":")),
            ),
        )
        return dict(get(conn, identifier), title=inputs["task"]["title"])


def get(conn, submission_id):
    row = conn.execute("SELECT * FROM nerva_dispatches WHERE id=?", (submission_id,)).fetchone()
    return dict(row) if row else None


def bind(conn, record, queued):
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE nerva_dispatches SET queue_id=?, enqueue_id=?, state='queued', error=NULL "
            "WHERE id=? AND state IN ('prepared','queued','refused')",
            (queued.id, queued.mediation_enqueue_id, record["id"]),
        )
    return get(conn, record["id"])


def finish(conn, submission_id, *, state, error=None):
    if state not in {"finished", "refused", "interrupted"}:
        raise ValueError("invalid dispatch terminal state")
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE nerva_dispatches SET state=?, error=? WHERE id=?", (state, error, submission_id)
        )


def claim(conn, record, queued, *, ttl_seconds, resume=None, validate_resume=None):
    """Snapshot validation and exact board-run CAS share one write transaction."""
    now = int(time.time())
    with kb.write_txn(conn):
        live = get(conn, record["id"])
        if (
            live is None
            or live["state"] != "queued"
            or live["queue_id"] != queued.id
            or live["enqueue_id"] != queued.mediation_enqueue_id
        ):
            raise ValueError("submission is not the queued current execution")
        task = kb.get_task(conn, record["task_id"])
        inputs = input_snapshot(conn, record["task_id"])
        source_status = record["lane"]
        if record["lane"] == "blocked":
            if not isinstance(resume, dict) or not callable(validate_resume) or validate_resume() != resume:
                raise ValueError("blocked worker requires a current independent resume")
            inputs["resume"] = resume
            source_status = resume["source_lane"]
        elif resume is not None:
            raise ValueError("ordinary worker cannot borrow a resume")
        if (
            task is None
            or task.status != record["lane"]
            or task.claim_lock is not None
            or task.assignee != record["profile"]
            or digest(inputs) != record["input_sha"]
            or not kb._parents_satisfied(conn, task.id)
        ):
            raise ValueError("board input changed since this approval")
        run_id = kb._claim_and_open_run(
            conn,
            task.id,
            record["lane"],
            "nerva:" + record["id"],
            now + max(ttl_seconds, (task.max_runtime_seconds or 1800) + 60),
            now,
            event_extra={"nerva_queue_id": queued.id, "source_status": source_status,
                         **({"resumed_child_id": resume["child_id"],
                             "source_run_id": resume["source_run_id"]} if resume is not None else {})},
        )
        if run_id is None:
            raise ValueError("board claim was lost")
        if resume is not None:
            from . import child_resume

            child_resume.claim(conn, record["id"])
        conn.execute(
            "UPDATE nerva_dispatches SET state='running', run_id=? WHERE id=?",
            (run_id, record["id"]),
        )
        return kb.get_task(conn, task.id)


def submissions(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM nerva_dispatches ORDER BY created_at, id")]
