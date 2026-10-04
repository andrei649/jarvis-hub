"""Durable Nerva queue handoff over the pinned Hermes board transaction/CAS."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import asdict

from .upstream import kanban_db as kb


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
    }


def initialize(conn):
    with kb.write_txn(conn):
        conn.execute("""CREATE TABLE IF NOT EXISTS nerva_dispatches (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, input_sha TEXT NOT NULL,
            lane TEXT NOT NULL, profile TEXT NOT NULL, prompt TEXT NOT NULL,
            prompt_sha TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'prepared',
            queue_id INTEGER, enqueue_id TEXT, run_id INTEGER, error TEXT,
            created_at INTEGER NOT NULL
        )""")


def prepare(conn, task):
    with kb.write_txn(conn):
        inputs = input_snapshot(conn, task.id)
        sha = digest(inputs)
        existing = conn.execute(
            "SELECT * FROM nerva_dispatches WHERE task_id=? AND input_sha=? "
            "AND state IN ('prepared','queued') ORDER BY created_at DESC LIMIT 1",
            (task.id, sha),
        ).fetchone()
        if existing:
            return dict(existing, title=inputs["task"]["title"])
        prompt = kb.build_worker_context(conn, task.id)
        if len(prompt.encode()) > 512_000:
            raise ValueError("board context exceeds the bounded worker prompt")
        identifier = secrets.token_hex(16)
        conn.execute(
            """INSERT INTO nerva_dispatches
            (id, task_id, input_sha, lane, profile, prompt, prompt_sha, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                identifier,
                task.id,
                sha,
                inputs["task"]["status"],
                inputs["task"]["assignee"],
                prompt,
                digest(prompt),
                int(time.time()),
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


def claim(conn, record, queued, *, ttl_seconds):
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
        if (
            task is None
            or task.status != record["lane"]
            or task.claim_lock is not None
            or task.assignee != record["profile"]
            or digest(input_snapshot(conn, task.id)) != record["input_sha"]
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
            event_extra={"nerva_queue_id": queued.id, "source_status": record["lane"]},
        )
        if run_id is None:
            raise ValueError("board claim was lost")
        conn.execute(
            "UPDATE nerva_dispatches SET state='running', run_id=? WHERE id=?",
            (run_id, record["id"]),
        )
        return kb.get_task(conn, task.id)


def submissions(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM nerva_dispatches ORDER BY created_at, id")]
