"""Durable, one-shot approval binding for a Kanban worker's child tool call.

This store records intent and board state. The caller must separately prove a
consumed, mediated queue execution before calling ``claim`` or running a tool.
"""

from __future__ import annotations

import json
import secrets
import stat
import time
from pathlib import Path

from . import dispatch_store
from .context import require_mutation
from .upstream import kanban_db as kb
from .workspace_context import current_workspace

_TOOLS = frozenset({"file_write", "file_delete", "terminal_run"})
_ACTIVE = ("prepared", "queued", "executing")


def _json(value, *, maximum=65_536):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":"))
    if len(encoded.encode("utf-8")) > maximum:
        raise ValueError("child approval input exceeds bound")
    return encoded


def _decoded(raw):
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("child approval input is malformed") from exc


def _identity(cwd):
    path = Path(cwd)
    try:
        if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
            raise ValueError("child workspace path changed")
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError("child workspace path changed") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("child workspace is not a directory")
    return str(path), info.st_dev, info.st_ino


def initialize(conn):
    with kb.write_txn(conn):
        conn.execute("""CREATE TABLE IF NOT EXISTS nerva_child_approvals (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            parent_submission_id TEXT NOT NULL,
            parent_queue_id INTEGER NOT NULL,
            parent_enqueue_id TEXT NOT NULL,
            run_id INTEGER NOT NULL,
            profile TEXT NOT NULL,
            session_id TEXT NOT NULL,
            workspace_json TEXT NOT NULL,
            cwd TEXT NOT NULL,
            cwd_dev INTEGER NOT NULL,
            cwd_ino INTEGER NOT NULL,
            intent_json TEXT NOT NULL,
            intent_sha TEXT NOT NULL,
            labels_json TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN
                ('prepared','queued','executing','succeeded','failed')),
            child_queue_id INTEGER,
            child_enqueue_id TEXT,
            error TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nerva_child_active "
                     "ON nerva_child_approvals(task_id, state)")


def get(conn, child_id):
    row = conn.execute("SELECT * FROM nerva_child_approvals WHERE id=?", (child_id,)).fetchone()
    return dict(row) if row else None


def active(conn, task_id):
    return conn.execute(
        "SELECT 1 FROM nerva_child_approvals WHERE task_id=? "
        "AND state IN ('prepared','queued','executing') LIMIT 1", (task_id,)
    ).fetchone() is not None


def _parent(conn, parent_record, parent_queue, *, running):
    context = require_mutation()
    if (not isinstance(parent_record, dict) or parent_queue is None
            or getattr(parent_queue, "kind", None) != "kanban.worker"
            or getattr(parent_queue, "status", None) != "running"):
        raise ValueError("parent execution is unavailable")
    live = dispatch_store.get(conn, parent_record.get("id"))
    if live is None or live["state"] != "running" or any(
        live.get(key) != parent_record.get(key) for key in
        ("task_id", "queue_id", "enqueue_id", "run_id", "profile", "workspace_json")
    ):
        raise ValueError("parent dispatch changed")
    if (getattr(parent_queue, "id", None) != live["queue_id"]
            or getattr(parent_queue, "mediation_enqueue_id", None) != live["enqueue_id"]
            or getattr(parent_queue, "agent", None) != live["profile"]
            or context.profile != live["profile"] or context.task_id != live["task_id"]
            or context.run_id != live["run_id"]
            or context.session_id != "kanban::" + live["id"]):
        raise ValueError("parent worker tuple changed")
    workspace = _decoded(live["workspace_json"])
    if (not isinstance(workspace, dict) or not isinstance(workspace.get("spec"), dict)
            or workspace["spec"].get("board") != kb.get_current_board()
            or workspace["spec"].get("home") != str(context.home.resolve())
            or workspace["spec"].get("task_id") != live["task_id"]
            or dispatch_store.digest(workspace)
            != dispatch_store.digest(dispatch_store.workspace_snapshot(conn, live["task_id"]))):
        raise ValueError("parent workspace binding changed")
    task = kb.get_task(conn, live["task_id"])
    run = kb.get_run(conn, live["run_id"])
    latest = kb.latest_run(conn, live["task_id"])
    if (task is None or run is None or run.task_id != live["task_id"]
            or run.profile != live["profile"] or latest is None or latest.id != run.id):
        raise ValueError("parent run changed")
    if running:
        if (task.status != "running" or task.current_run_id != run.id
                or task.claim_lock != "nerva:" + live["id"]
                or run.status != "running" or run.ended_at is not None):
            raise ValueError("parent run is no longer active")
    elif (task.status != "blocked" or task.block_kind != "needs_input"
          or task.current_run_id is not None or run.outcome != "blocked"
          or run.ended_at is None):
        raise ValueError("parent is not parked for child approval")
    return live, workspace


def prepare(conn, parent_record, parent_queue, cwd, tool, args, labels):
    if type(tool) is not str or tool not in _TOOLS or type(args) is not dict or type(labels) is not dict:
        raise ValueError("unsupported child tool input")
    args_sha = dispatch_store.digest(_decoded(_json(args)))
    labels_json = _json(labels, maximum=16_384)
    with kb.write_txn(conn):
        live, workspace = _parent(conn, parent_record, parent_queue, running=True)
        binding = current_workspace()
        if binding is None:
            raise PermissionError("live worker workspace required")
        binding.check()
        path, dev, ino = _identity(cwd)
        if (binding.cwd != Path(path) or binding.identity != (dev, ino)
                or workspace["spec"].get("path") != path):
            raise ValueError("child cwd differs from parent workspace")
        if active(conn, live["task_id"]):
            raise ValueError("parent already has an active child approval")
        identifier = secrets.token_hex(16)
        intent = {
            "child_id": identifier, "parent_submission_id": live["id"],
            # New child enqueues carry this exact top-level submission_id. Old
            # prepared rows have no complete queue-birth lookup and stay held.
            "queue_birth_lookup": "submission_id",
            "parent_queue_id": live["queue_id"], "parent_enqueue_id": live["enqueue_id"],
            "task_id": live["task_id"], "run_id": live["run_id"],
            "profile": live["profile"], "session_id": "kanban::" + live["id"],
            "board": kb.get_current_board(),
            "workspace_binding_sha256": dispatch_store.digest(workspace),
            "cwd": path, "cwd_dev": dev, "cwd_ino": ino,
            "tool": tool, "args_sha256": args_sha,
        }
        intent_json = _json(intent)
        now = int(time.time())
        conn.execute("""INSERT INTO nerva_child_approvals (
            id, task_id, parent_submission_id, parent_queue_id, parent_enqueue_id,
            run_id, profile, session_id, workspace_json, cwd, cwd_dev, cwd_ino,
            intent_json, intent_sha, labels_json, state, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            identifier, live["task_id"], live["id"], live["queue_id"], live["enqueue_id"],
            live["run_id"], live["profile"], intent["session_id"], _json(workspace), path,
            dev, ino, intent_json, dispatch_store.digest(intent), labels_json,
            "prepared", now, now,
        ))
        return get(conn, identifier)


def _queue_matches(row, child_queue):
    payload = getattr(child_queue, "payload", None)
    if (type(payload) is not dict
            or getattr(child_queue, "agent", None) != row["profile"]
            or type(getattr(child_queue, "id", None)) is not int
            or not getattr(child_queue, "mediation_enqueue_id", None)):
        return False
    try:
        intent = _decoded(row["intent_json"])
        labels = _decoded(row["labels_json"])
        if type(intent) is not dict or type(labels) is not dict:
            return False
        return (
            getattr(child_queue, "kind", None) == "toolrpc." + intent["tool"]
            and payload.get("kanban_child") == intent
            and dispatch_store.digest(intent) == row["intent_sha"]
            and payload.get("tool") == intent["tool"]
            and type(payload.get("args")) is dict
            and dispatch_store.digest(payload["args"]) == intent["args_sha256"]
            and payload.get("labels") == labels
            and all(payload.get(key) == value for key, value in labels.items())
        )
    except (TypeError, ValueError, KeyError):
        return False


def _record_is_current(conn, record, *, state):
    if not isinstance(record, dict) or not record.get("id"):
        raise ValueError("child approval is unavailable")
    live = get(conn, record["id"])
    if live is None or live["state"] != state or any(
        live.get(key) != record.get(key) for key in
        ("task_id", "parent_submission_id", "parent_queue_id", "parent_enqueue_id",
         "run_id", "profile", "session_id", "workspace_json", "cwd", "cwd_dev",
         "cwd_ino", "intent_json", "intent_sha", "labels_json")
    ):
        raise ValueError("child approval record changed")
    return live


def _parked_parent(conn, row):
    parent = dispatch_store.get(conn, row["parent_submission_id"])
    task = kb.get_task(conn, row["task_id"])
    run = kb.get_run(conn, row["run_id"])
    latest = kb.latest_run(conn, row["task_id"])
    if (parent is None or parent["state"] not in {"running", "finished"}
            or parent["task_id"] != row["task_id"]
            or parent["queue_id"] != row["parent_queue_id"]
            or parent["enqueue_id"] != row["parent_enqueue_id"]
            or parent["run_id"] != row["run_id"]
            or parent["profile"] != row["profile"]
            or dispatch_store.digest(_decoded(parent["workspace_json"]))
            != dispatch_store.digest(_decoded(row["workspace_json"]))
            or task is None or task.status != "blocked" or task.block_kind != "needs_input"
            or task.current_run_id is not None or latest is None or latest.id != row["run_id"]
            or run is None or run.ended_at is None or run.outcome != "blocked"
            or run.profile != row["profile"]):
        raise ValueError("parent board run is not the approved blocked run")


def bind_and_park(conn, record, child_queue):
    row = _record_is_current(conn, record, state="prepared")
    if not _queue_matches(row, child_queue):
        raise ValueError("child queue payload differs from prepared intent")
    context = require_mutation()
    if (context.task_id != row["task_id"] or context.run_id != row["run_id"]
            or context.profile != row["profile"] or context.session_id != row["session_id"]
            or kb.get_current_board() != _decoded(row["intent_json"])["board"]):
        raise ValueError("parent worker tuple changed")
    binding = current_workspace()
    if (binding is None or binding.cwd != Path(row["cwd"])
            or binding.identity != (row["cwd_dev"], row["cwd_ino"])):
        raise ValueError("parent worker workspace expired")
    binding.check()
    parent = dispatch_store.get(conn, row["parent_submission_id"])
    if parent is None:
        raise ValueError("parent dispatch vanished")
    parent_queue = type("ParentQueue", (), {
        "id": row["parent_queue_id"], "mediation_enqueue_id": row["parent_enqueue_id"],
        "kind": "kanban.worker", "agent": row["profile"], "status": "running",
    })()
    _parent(conn, parent, parent_queue, running=True)

    def bind_inside_board_txn():
        live = _record_is_current(conn, record, state="prepared")
        _parked_parent(conn, live)
        if (kb.get_current_board() != _decoded(live["intent_json"])["board"]
                or dispatch_store.digest(dispatch_store.workspace_snapshot(conn, live["task_id"]))
                != dispatch_store.digest(_decoded(live["workspace_json"]))
                or _identity(live["cwd"]) != (live["cwd"], live["cwd_dev"], live["cwd_ino"])):
            raise ValueError("child workspace changed during board park")
        if not _queue_matches(live, child_queue):
            raise ValueError("child queue changed before board park")
        if conn.execute(
            "UPDATE nerva_child_approvals SET state='queued', child_queue_id=?, "
            "child_enqueue_id=?, updated_at=? WHERE id=? AND state='prepared'",
            (child_queue.id, child_queue.mediation_enqueue_id, int(time.time()), live["id"]),
        ).rowcount != 1:
            raise ValueError("child approval bind was lost")

    if not kb.block_task(conn, row["task_id"], kind="needs_input",
                         reason="child tool approval", expected_run_id=row["run_id"],
                         _before_commit=bind_inside_board_txn):
        raise ValueError("parent board park was lost")
    return get(conn, row["id"])


def claim(conn, record, child_queue):
    with kb.write_txn(conn):
        row = _record_is_current(conn, record, state="queued")
        if (row["child_queue_id"] != getattr(child_queue, "id", None)
                or row["child_enqueue_id"] != getattr(child_queue, "mediation_enqueue_id", None)
                or getattr(child_queue, "status", None) != "running"
                or not _queue_matches(row, child_queue)):
            raise ValueError("child queue execution differs from approval")
        _parked_parent(conn, row)
        context = require_mutation()
        if (context.board != _decoded(row["intent_json"])["board"]
                or dispatch_store.digest(dispatch_store.workspace_snapshot(conn, row["task_id"]))
                != dispatch_store.digest(_decoded(row["workspace_json"]))):
            raise ValueError("child workspace binding changed")
        path, dev, ino = _identity(row["cwd"])
        if (path, dev, ino) != (row["cwd"], row["cwd_dev"], row["cwd_ino"]):
            raise ValueError("child workspace directory changed")
        if conn.execute(
            "UPDATE nerva_child_approvals SET state='executing', updated_at=? "
            "WHERE id=? AND state='queued'",
            (int(time.time()), row["id"]),
        ).rowcount != 1:
            raise ValueError("child approval claim was lost")
        return get(conn, row["id"])


def validate(conn, record, child_queue):
    """Read-only live proof for each physical effect; queue permit is external."""
    try:
        if not isinstance(record, dict) or not record.get("id"):
            return False
        row = get(conn, record["id"])
        if row is None or row["state"] not in {"queued", "executing"}:
            return False
        _record_is_current(conn, record, state=row["state"])
        if (row["child_queue_id"] != getattr(child_queue, "id", None)
                or row["child_enqueue_id"] != getattr(child_queue, "mediation_enqueue_id", None)
                or getattr(child_queue, "status", None) != "running"
                or not _queue_matches(row, child_queue)):
            return False
        _parked_parent(conn, row)
        context = require_mutation()
        if (context.board != _decoded(row["intent_json"])["board"]
                or dispatch_store.digest(dispatch_store.workspace_snapshot(conn, row["task_id"]))
                != dispatch_store.digest(_decoded(row["workspace_json"]))):
            return False
        return _identity(row["cwd"]) == (row["cwd"], row["cwd_dev"], row["cwd_ino"])
    except (KeyError, OSError, PermissionError, TypeError, ValueError):
        return False


def complete(conn, child_id, success: bool, error=None):
    if type(success) is not bool:
        raise ValueError("child completion needs a boolean outcome")
    with kb.write_txn(conn):
        if conn.execute(
            "UPDATE nerva_child_approvals SET state=?, error=?, updated_at=? "
            "WHERE id=? AND state='executing'",
            ("succeeded" if success else "failed", str(error)[:2000] if error else None,
             int(time.time()), child_id),
        ).rowcount != 1:
            raise ValueError("child approval is not executing")
        return get(conn, child_id)


def _authenticated_queue(queue, queue_id, kind):
    """Return a globally authenticated queue row, or hold on any uncertainty."""
    try:
        if getattr(queue, "mediation_mode", None) != "enforce":
            return None
        task, mediated = queue.execution_snapshot(queue_id, presented_kind=kind)
        if task is None or mediated is not True or task.id != queue_id:
            return None
        if not task.mediation_enqueue_id or not task.mediation_receipt:
            return None
        return task
    except Exception:
        return None


def _terminal_parent(conn, row, queue):
    """A prepared intent is inert only after its exact parent has stopped."""
    parent = dispatch_store.get(conn, row["parent_submission_id"])
    task = kb.get_task(conn, row["task_id"])
    run = kb.get_run(conn, row["run_id"])
    latest = kb.latest_run(conn, row["task_id"])
    if (parent is None or parent["queue_id"] != row["parent_queue_id"]
            or parent["enqueue_id"] != row["parent_enqueue_id"]
            or parent["run_id"] != row["run_id"] or parent["task_id"] != row["task_id"]
            or parent["profile"] != row["profile"] or task is None
            or task.status == "running" or task.current_run_id is not None
            or run is None or run.ended_at is None or run.status == "running"
            or latest is None or latest.id != row["run_id"]):
        return False
    parent_queue = _authenticated_queue(queue, row["parent_queue_id"], "kanban.worker")
    return bool(parent_queue is not None
                and parent_queue.mediation_enqueue_id == row["parent_enqueue_id"]
                and parent_queue.kind == "kanban.worker"
                and parent_queue.agent == row["profile"]
                and parent_queue.status in {"done", "failed", "rejected", "expired", "quarantined"})


def _recovery_error(conn, row, queue):
    try:
        intent = _decoded(row["intent_json"])
        if (type(intent) is not dict or intent.get("child_id") != row["id"]
                or intent.get("board") != kb.get_current_board()
                or dispatch_store.digest(intent) != row["intent_sha"]):
            return None
        kind = "toolrpc." + intent["tool"]
        if intent["tool"] not in _TOOLS:
            return None
        if row["state"] == "prepared":
            if intent.get("queue_birth_lookup") != "submission_id":
                return None
            if not _terminal_parent(conn, row, queue):
                return None
            # Complete durable exact-key lookup. A bounded queue history scan
            # cannot establish absence across the board/queue DB boundary.
            found = queue.find_submission_task(kind, row["id"])
            if found is None:
                return "child_prepared_parent_ended"
            child = _authenticated_queue(queue, found.id, kind)
            if (child is None or child.created_at != found.created_at
                    or child.payload.get("submission_id") != row["id"]
                    or not _queue_matches(row, child)):
                return None
            if child.status in {"rejected", "expired", "quarantined"}:
                return "child_unbound_queue_denied"
            if child.status == "failed" and not child.mediation_execution_id:
                return "child_unbound_queue_failed_before_execution"
            return None
        child = _authenticated_queue(queue, row["child_queue_id"], kind)
        if (child is None or child.mediation_enqueue_id != row["child_enqueue_id"]
                or not _queue_matches(row, child)):
            return None
        if child.status not in {"done", "failed", "rejected", "expired", "quarantined"}:
            return None
        if row["state"] == "queued":
            # Board claim precedes the physical hop. A terminal queue while
            # still queued cannot have passed that board-side effect barrier.
            return "child_queue_ended_without_board_claim"
        if row["state"] == "executing":
            # The effect may have happened. Never replay or infer success.
            return "child_execution_interrupted_ambiguous"
    except Exception:
        # The queue is a separate durable store. Failed lookup, decoding or
        # mediation checks are uncertainty, never proof of nonexecution.
        return None
    return None


def reconcile(conn, queue):
    """Settle only provably inert or terminal child intents; leave parents parked.

    Must run inside a trusted mutating board scope. Queue snapshots and exact
    queue-birth lookups fail closed. Returns only rows changed by this call.
    """
    require_mutation()
    settled = []
    with kb.write_txn(conn):
        rows = conn.execute(
            "SELECT * FROM nerva_child_approvals WHERE state IN "
            "('prepared','queued','executing') ORDER BY created_at, id"
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            reason = _recovery_error(conn, row, queue)
            if reason is None:
                continue
            if conn.execute(
                "UPDATE nerva_child_approvals SET state='failed', error=?, updated_at=? "
                "WHERE id=? AND state=? AND updated_at=?",
                (reason, int(time.time()), row["id"], row["state"], row["updated_at"]),
            ).rowcount == 1:
                settled.append(get(conn, row["id"]))
    return settled
