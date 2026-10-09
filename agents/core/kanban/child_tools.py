"""Coordinator-owned, independently mediated effects of a parked board worker."""

from __future__ import annotations

import json
from pathlib import Path

from agents.core.autonomy.queue import TaskQueue
from agents.core.file_tools import FileScopeError
from agents.core.tool_rpc import ToolRPCValidationError

from . import child_store
from .context import KanbanContext, current_context, kanban_scope, scope_is_bound
from .upstream import kanban_db as kb
from .workspace_context import current_workspace, workspace_scope


class ChildToolAdapter:
    def __init__(self, controller):
        self.controller = controller

    def _runtime(self):
        return self.controller._runtime()

    def prepare(self, actor, tool, args, labels):
        context = current_context()
        if not scope_is_bound() or (context is not None and context.task_id is None
                                    and context.run_id is None):
            return None
        worker, queue = self._runtime()
        try:
            if (context is None or not context.can_mutate or context.delegated
                    or context.profile != actor or not context.task_id
                    or context.home.resolve() != self.controller.home.resolve()
                    or worker is None or queue is None):
                raise ValueError("worker child context is unavailable")
            binding = current_workspace()
            if binding is None:
                raise ValueError("worker child workspace is unavailable")
            binding.check()
            if tool == "terminal_run":
                if args.get("target") != "local-host":
                    raise ValueError("worker terminal target needs a scoped adapter")
                if args.get("cwd") not in (None, str(binding.cwd)):
                    raise ValueError("worker terminal cwd differs from approved workspace")
                args["cwd"] = str(binding.cwd)
            with kb.connect_closing(board=context.board) as conn:
                parent_row = conn.execute(
                    "SELECT * FROM nerva_dispatches WHERE task_id=? AND run_id=? AND state='running'",
                    (context.task_id, context.run_id),
                ).fetchone()
                if parent_row is None:
                    raise ValueError("worker parent submission is unavailable")
                parent = dict(parent_row)
                queued = queue.get(parent["queue_id"])
                if queued is None or not self.controller._execution_is_current(queued, worker, queue):
                    raise ValueError("worker parent permit is unavailable")
                child_store.initialize(conn)
                return child_store.prepare(conn, parent, queued, binding.cwd, tool, dict(args), dict(labels or {}))
        except (FileScopeError, KeyError, OSError, PermissionError, TypeError, ValueError) as exc:
            raise ToolRPCValidationError("kanban_child_intake_refused") from exc

    def bind(self, record, queue_id):
        if record is None:
            return
        worker, queue = self._runtime()
        if worker is None or queue is None:
            raise ToolRPCValidationError("kanban_child_binding_refused")
        try:
            context = current_context()
            with kb.connect_closing(board=context.board) as conn:
                child_store.bind_and_park(conn, record, queue.get(queue_id))
        except (AttributeError, KeyError, OSError, PermissionError, TypeError, ValueError) as exc:
            # Queue birth and board park are separate databases. An unbound queue
            # task remains inert even if intake crashed after creating its row.
            raise ToolRPCValidationError("kanban_child_binding_refused") from exc

    def payload(self, record):
        return {"submission_id": record["id"], "kanban_child": json.loads(record["intent_json"]),
                "labels": json.loads(record["labels_json"])} if record is not None else {}

    def _permit_current(self, task, worker, queue):
        live_worker, live_queue = self._runtime()
        if live_worker is not worker or live_queue is not queue:
            return False
        fingerprint = TaskQueue.execution_fingerprint(task)
        permit = worker._execution_context.get()
        live, mediated = queue.execution_snapshot(task.id, presented_kind=task.kind)
        return bool(permit is not None and permit.consumed and fingerprint
                    and getattr(permit, "_fingerprint", None) == fingerprint
                    and mediated and live is not None and live.status == "running"
                    and live.kind == task.kind and live.agent == task.agent
                    and TaskQueue.execution_fingerprint(live) == fingerprint
                    and queue.validate_mediated_execution(live, fingerprint))

    async def execute(self, task, invoke):
        worker, queue = self._runtime()
        try:
            if worker is None or queue is None or not self._permit_current(task, worker, queue):
                raise ValueError("independent child permit required")
            intent = task.payload["kanban_child"]
            if type(intent) is not dict or intent.get("tool") not in {"file_write", "file_delete", "terminal_run"}:
                raise ValueError("invalid child tool intent")
            context = KanbanContext(self.controller.home, task.agent, board=intent["board"],
                                    task_id=intent["task_id"], run_id=intent["run_id"],
                                    session_id=intent["session_id"], can_mutate=True)
            with kanban_scope(context), kb.connect_closing(board=context.board) as conn:
                record = child_store.get(conn, intent["child_id"])
                if record is None:
                    raise ValueError("durable child binding required")
                record = child_store.claim(conn, record, task)

                def still_current():
                    if not self._permit_current(task, worker, queue):
                        return False
                    with kb.connect_closing(board=context.board) as live_conn:
                        live = child_store.get(live_conn, record["id"])
                        return bool(live is not None and live["state"] == "executing"
                                    and child_store.validate(live_conn, record, queue.get(task.id)))

                workspace = json.loads(record["workspace_json"])["spec"]
                project = workspace.get("project_root")
                try:
                    # A new scope expires at the end of this child effect. It
                    # never borrows the closed parent worker's scope or permit.
                    with workspace_scope(Path(record["cwd"]), still_current=still_current,
                                         project_root=Path(project) if project else None):
                        result = await invoke(task)
                    success = (isinstance(result, dict) and result.get("status") == "ok"
                               and isinstance(result.get("result"), dict)
                               and result["result"].get("ok") is True)
                    child_store.complete(conn, record["id"], success,
                                         error=None if success else "child_tool_failed")
                    return result
                except BaseException:
                    # Executing state before the physical hop prevents crash or
                    # cancellation from blindly replaying an ambiguous effect.
                    child_store.complete(conn, record["id"], False, error="child_tool_interrupted")
                    raise
        except (FileScopeError, KeyError, OSError, PermissionError, TypeError, ValueError):
            return {"status": "refused", "reason": "kanban_child_execution_refused"}
