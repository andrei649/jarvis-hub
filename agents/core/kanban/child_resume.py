"""A completed child can propose one fresh, independently governed worker run."""

from __future__ import annotations

import json
import time

from . import child_store
from . import dispatch_store as store
from .context import require_mutation
from .upstream import kanban_db as kb


def initialize(conn):
    child_store.initialize(conn)
    with kb.write_txn(conn):
        conn.execute("""CREATE TABLE IF NOT EXISTS nerva_child_resumes (
            child_id TEXT PRIMARY KEY,
            submission_id TEXT NOT NULL UNIQUE,
            descriptor_json TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('prepared','claimed')),
            created_at INTEGER NOT NULL
        )""")


def _authenticated(queue, identifier, kind):
    current, mediated = queue.execution_snapshot(identifier, presented_kind=kind)
    if not mediated or current is None or current.kind != kind:
        raise ValueError("completed queue identity cannot be authenticated")
    return current


def descriptor(conn, queue, child):
    """Read exact successful effect and parked source, never mint permission."""
    context = require_mutation()
    live = child_store.get(conn, child["id"])
    if live is None or live != child or child["state"] != "succeeded":
        raise ValueError("child success changed")
    intent = json.loads(child["intent_json"])
    if context.board != intent["board"]:
        raise ValueError("child board changed")
    child_store._parked_parent(conn, child)
    parent = store.get(conn, child["parent_submission_id"])
    if parent["state"] != "finished" or parent["lane"] not in {"ready", "review"}:
        raise ValueError("parent source has not finished")
    completed = _authenticated(queue, child["child_queue_id"], "toolrpc." + intent["tool"])
    source = _authenticated(queue, child["parent_queue_id"], "kanban.worker")
    if (completed.status != "done" or completed.mediation_enqueue_id != child["child_enqueue_id"]
            or not child_store._queue_matches(child, completed)
            or source.status != "done" or source.agent != child["profile"]
            or source.mediation_enqueue_id != child["parent_enqueue_id"]
            or source.payload.get("submission_id") != parent["id"]
            or not isinstance(source.result, dict) or source.result.get("status") != "ok"
            or source.result.get("task_id") != child["task_id"]
            or source.result.get("run_id") != child["run_id"]
            or not isinstance(completed.result, dict) or completed.result.get("status") != "ok"
            or not isinstance(completed.result.get("result"), dict)
            or completed.result["result"].get("ok") is not True):
        raise ValueError("durable queue outcomes do not prove completed child")
    if (store.digest(store.workspace_snapshot(conn, child["task_id"]))
            != store.digest(json.loads(child["workspace_json"]))
            or child_store._identity(child["cwd"])
            != (child["cwd"], child["cwd_dev"], child["cwd_ino"])):
        raise ValueError("child workspace changed before resume")
    task = kb.get_task(conn, child["task_id"])
    if task.assignee != child["profile"] or not kb._parents_satisfied(conn, task.id):
        raise ValueError("parent assignee or dependencies changed")
    return {
        "child_id": child["id"], "child_queue_id": completed.id,
        "child_enqueue_id": completed.mediation_enqueue_id,
        "result_sha256": store.digest(completed.result),
        "parent_submission_id": parent["id"], "source_run_id": child["run_id"],
        "source_lane": parent["lane"], "task_id": child["task_id"],
        "board": intent["board"], "profile": child["profile"],
        "workspace_sha256": store.digest(json.loads(child["workspace_json"])),
        "cwd": child["cwd"], "cwd_dev": child["cwd_dev"], "cwd_ino": child["cwd_ino"],
    }


def candidates(conn, queue):
    ready = {}
    for row in conn.execute("SELECT * FROM nerva_child_approvals WHERE state='succeeded' "
                            "ORDER BY created_at,id"):
        try:
            current = descriptor(conn, queue, dict(row))
            ready[current["task_id"]] = current
        except (KeyError, OSError, PermissionError, TypeError, ValueError):
            continue
    return ready


def prepare(conn, task, resume, queue):
    child = child_store.get(conn, resume["child_id"])
    if descriptor(conn, queue, child) != resume:
        raise ValueError("resume input changed")
    bound = conn.execute("SELECT * FROM nerva_child_resumes WHERE child_id=?",
                         (child["id"],)).fetchone()
    if bound is not None:
        if bound["state"] != "prepared" or json.loads(bound["descriptor_json"]) != resume:
            raise ValueError("resume is already claimed or changed")
        record = store.get(conn, bound["submission_id"])
        if record is None:
            raise ValueError("resume submission vanished")
        return dict(record, title=task.title)
    completed = _authenticated(queue, child["child_queue_id"], "toolrpc." + json.loads(child["intent_json"])["tool"])
    # Tool output remains data. Escaped angle brackets cannot close the fence.
    result = json.dumps(completed.result, ensure_ascii=True, allow_nan=False)
    result = result[:4096].replace("<", "\\u003c").replace(">", "\\u003e")
    suffix = ("\n## Continuation after an independently approved child\n"
              "The child operation is already completed. Do not replay it. "
              "Continue this task under this new worker approval.\n"
              f"Child: {child['id']}; source run: {child['run_id']}.\n"
              "<untrusted_tool_result>\n" + result + "\n</untrusted_tool_result>\n")
    record = store.prepare(conn, task, resume=resume, prompt_suffix=suffix)
    with kb.write_txn(conn):
        # The normal input snapshot deduplicates a crash before this binding;
        # this durable unique child reference deduplicates later process restarts.
        conn.execute("INSERT INTO nerva_child_resumes "
                     "(child_id,submission_id,descriptor_json,state,created_at) "
                     "VALUES (?,?,?,'prepared',?)",
                     (child["id"], record["id"], json.dumps(resume, sort_keys=True), int(time.time())))
    return record


def validate_bound(conn, record, task, queue):
    bound = conn.execute("SELECT * FROM nerva_child_resumes WHERE submission_id=?",
                         (record["id"],)).fetchone()
    if bound is None or bound["state"] != "prepared":
        raise ValueError("durable resume binding is unavailable")
    expected = json.loads(bound["descriptor_json"])
    if (task.payload.get("resume") != expected or record["task_id"] != expected["task_id"]
            or record["profile"] != expected["profile"]
            or descriptor(conn, queue, child_store.get(conn, bound["child_id"])) != expected):
        raise ValueError("resume no longer belongs to its completed child")
    return expected


def claim(conn, submission_id):
    """Caller holds the board claim transaction; do not compose nested writes."""
    if conn.execute("UPDATE nerva_child_resumes SET state='claimed' "
                    "WHERE submission_id=? AND state='prepared'", (submission_id,)).rowcount != 1:
        raise ValueError("resume claim was lost")
