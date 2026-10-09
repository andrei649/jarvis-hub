"""Adapt pinned board scheduling to durable, kernel-mediated Nerva workers."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from pathlib import Path

from agents.core.autonomy.queue import TaskQueue, TaskQueueError, TaskStatus
from agents.core.commands import CommandContext
from agents.core.kernel import Action, Decision, Verdict, kernel_enabled
from agents.core.paths import data_path
from agents.core.tool_profiles import classify_turn

from . import child_resume, child_store
from . import dispatch_store as store
from .context import KanbanContext, kanban_scope, require_mutation
from .upstream import kanban_db as kb
from .upstream import kanban_db_connect as kbc
from .upstream import kanban_db_dispatch as kbd
from .workspace_context import workspace_scope
from .workspaces import cleanup_workspace, materialize_workspace

_ACTIVE_QUEUE_STATES = frozenset({"proposed", "approved", "blocked", "deferred", "running"})
_LOCKS: dict[str, asyncio.Lock] = {}
_APPROVED_LOCKS: dict[str, asyncio.Lock] = {}
logger = logging.getLogger(__name__)


class KanbanExecutionRefused(RuntimeError):
    """A board refusal must become a failed queue attempt, never DONE prose."""


def _refused(reason):
    return {"ok": False, "status": "refused", "reason": reason, "queued": []}


def _bounded_worker_cap(value):
    try:
        return max(0, min(int(value), 16)) if not isinstance(value, bool) else 0
    except (TypeError, ValueError):
        return 0


class KanbanDispatcher:
    KIND = "kanban.worker"
    _HEARTBEAT_SECONDS = 30

    def __init__(self, orch, *, home=None, runner=None):
        self.orch = orch
        self.home = Path(home) if home is not None else data_path("kanban")
        self.runner = runner

    def _enabled(self):
        return all(
            self.orch.get_setting(k, False) is True
            for k in ("llm.kanban", "llm.kanban_dispatch", "llm.tool_loop_enabled")
        )

    def _runtime(self):
        worker, queue = (
            getattr(self.orch, "autonomy", None),
            getattr(self.orch, "autonomy_queue", None),
        )
        if (
            not self._enabled()
            or not kernel_enabled()
            or worker is None
            or not isinstance(queue, TaskQueue)
            or worker.queue is not queue
            or queue.mediation_mode != "enforce"
            or queue.classify_mediation(self.KIND) is not True
            or getattr(worker, "_mediation_kernel", None) is None
            or not callable(getattr(worker, "kernel_gate", None))
            or not callable(getattr(worker, "govern_enqueue", None))
        ):
            return None, None
        return worker, queue

    async def request(self, principal, *, board="default", limit=4):
        if classify_turn(principal).key != "operator/owner":
            return _refused("owner_required")
        return await self._dispatch(board=board, limit=limit)

    async def request_owner_command(self, command, *, board="default", limit=4):
        """Explicit owner slash commands may propose work from authenticated chat.

        This entry is not registered as a model tool. Ordinary inbound tool
        requests retain the operator-only rule in request(). All proposals still
        use the same signed queue and kernel approval path.
        """
        if (not isinstance(command, CommandContext) or command.name != "kanban"
                or command.orch is not self.orch
                or classify_turn(command.principal).key not in {"operator/owner", "inbound/owner"}):
            return _refused("owner_required")
        try:
            scope = require_mutation()
        except PermissionError:
            return _refused("owner_required")
        if (scope.task_id is not None or scope.run_id is not None or scope.profile != "owner"
                or scope.home.resolve() != self.home.resolve() or scope.board != board):
            return _refused("owner_required")
        return await self._dispatch(board=board, limit=limit)

    async def tick(self):
        return await self._dispatch(board="default", limit=4)

    async def approved_tick(self, max_tier=None):
        """Execute approved tasks with board-only capacity under one host owner."""
        key = str(self.home.resolve())
        lock = _APPROVED_LOCKS.setdefault(key, asyncio.Lock())
        if lock.locked():
            return {"ok": True, "status": "busy", "queued": []}
        await lock.acquire()
        try:
            with kbc._dispatch_tick_lock(self.home / "nerva-host-workers", strict=True) as held:
                if not held:
                    return {"ok": True, "status": "busy", "queued": []}
                worker = getattr(self.orch, "autonomy", None)
                total = per_agent = 0
                try:
                    runtime_worker, _ = self._runtime()
                    if runtime_worker is not None:
                        total = _bounded_worker_cap(
                            self.orch.get_setting("llm.kanban_max_workers", 2)
                        )
                        per_agent = min(
                            total,
                            _bounded_worker_cap(
                                self.orch.get_setting("llm.kanban_max_workers_per_agent", 1)
                            ),
                        )
                except Exception:
                    # Keep ordinary queue work moving while board execution is held.
                    total = per_agent = 0
                return await worker.tick(
                    max_tier=max_tier,
                    parallel_kind=self.KIND,
                    parallel_limit=total,
                    parallel_agent_limit=per_agent,
                )
        finally:
            lock.release()

    async def _dispatch(self, *, board, limit):
        worker, queue = self._runtime()
        if worker is None:
            return _refused("governed_worker_unavailable")
        if type(limit) is not int or not 1 <= limit <= 16:
            return _refused("invalid_limit")
        key = str(self.home.resolve())
        lock = _LOCKS.setdefault(key, asyncio.Lock())
        async with lock:
            with kanban_scope(KanbanContext(self.home, "dispatcher", board=board, can_mutate=True)):
                try:
                    board_path = kb.kanban_db_path(board=board)
                    # Serialize host capacity across boards as well as each
                    # board's donor writer boundary, including other processes.
                    with (
                        kbc._dispatch_tick_lock(self.home / "nerva-host", strict=True) as host_held,
                        kbc._dispatch_tick_lock(board_path, strict=True) as held,
                    ):
                        if not host_held or not held:
                            return {"ok": True, "status": "busy", "queued": []}
                        return self._dispatch_locked(worker, queue, board, limit)
                except (ValueError, PermissionError, TaskQueueError) as exc:
                    return _refused(str(exc))

    def _dispatch_locked(self, worker, queue, board, limit):
        with kb.connect_closing(board=board) as conn:
            store.initialize(conn)
            child_resume.initialize(conn)
            child_store.reconcile(conn, queue)
            kb.recompute_ready(conn)
            resumes = child_resume.candidates(conn, queue)
            pending = {}
            for record in store.submissions(conn):
                if record["state"] == "prepared" and record["queue_id"] is None:
                    recovered = queue.find_submission_task(self.KIND, record["id"])
                    if recovered is not None:
                        if (
                            recovered.agent != record["profile"]
                            or recovered.payload.get("board") != board
                            or recovered.payload.get("task_id") != record["task_id"]
                            or recovered.payload.get("input_sha256") != record["input_sha"]
                        ):
                            raise ValueError("recovered queue submission input is inconsistent")
                        record = store.bind(conn, record, recovered)
                if record["queue_id"] is not None:
                    q = queue.get(record["queue_id"])
                    if (
                        q
                        and q.status in _ACTIVE_QUEUE_STATES
                        and q.payload.get("submission_id") == record["id"]
                    ):
                        pending[record["task_id"]] = record
                    elif record["state"] in {"queued", "running"}:
                        if record["run_id"] is not None:
                            kbd._record_task_failure(
                                conn,
                                record["task_id"],
                                "queue execution ended",
                                outcome="nerva_worker_interrupted",
                                release_claim=True,
                                end_run=True,
                                expected_run_id=record["run_id"],
                            )
                        store.finish(
                            conn, record["id"], state="interrupted", error="queue execution ended"
                        )
            profiles = set(getattr(self.orch, "agents", {}) or {})
            cap = int(self.orch.get_setting("llm.kanban_max_workers", 2))
            cap = max(0, min(cap, 16))
            agent_cap = int(self.orch.get_setting("llm.kanban_max_workers_per_agent", 1))
            agent_cap = max(0, min(agent_cap, cap))
            running = kb.list_tasks(conn, status="running")
            active_queue = queue.active_kind_tasks(self.KIND)
            untracked_running = [t for t in running if t.id not in pending]
            counts = Counter(t.agent for t in active_queue)
            counts.update(t.assignee for t in untracked_running)
            slots = max(0, cap - len(active_queue) - len(untracked_running))
            ready = kb.list_tasks(conn, status="ready")
            reviews = kb.list_tasks(conn, status="review")
            # Same reservation as Hermes: one spawnable review precedes
            # ready work so a sustained ready backlog cannot starve it.
            available = [
                t
                for t in reviews
                if t.assignee in profiles
                and not t.claim_lock
                and (t.id in pending or counts[t.assignee] < agent_cap)
            ]
            continuations = [task for task in kb.list_tasks(conn, status="blocked") if task.id in resumes]
            tasks = available[:1] + continuations + ready + available[1:]
            queued = []
            for task in tasks:
                if len(queued) >= limit:
                    break
                if task.assignee not in profiles or task.claim_lock is not None:
                    continue
                previous = pending.get(task.id)
                if previous is not None:
                    if (
                        previous["state"] != "queued"
                        or store.digest({**store.input_snapshot(conn, task.id),
                                         **({"resume": resumes[task.id]} if task.id in resumes else {})})
                        != previous["input_sha"]
                    ):
                        continue
                    queued.append(
                        {
                            "task_id": task.id,
                            "queue_id": previous["queue_id"],
                            "status": queue.get(previous["queue_id"]).status,
                        }
                    )
                    continue
                if slots <= 0 or counts[task.assignee] >= agent_cap:
                    continue
                if kbd.check_respawn_guard(conn, task.id, lane=task.status) is not None:
                    continue
                resume = resumes.get(task.id)
                record = (child_resume.prepare(conn, task, resume, queue)
                          if resume is not None else store.prepare(conn, task))
                q = queue.find_submission_task(self.KIND, record["id"])
                if q is None:
                    payload = {
                        "submission_id": record["id"],
                        "task_id": task.id,
                        "board": board,
                        "input_sha256": record["input_sha"],
                        "prompt": record["prompt"],
                        "prompt_sha256": record["prompt_sha"],
                        "workspace_spec": json.loads(record["workspace_json"])["spec"],
                        "workspace_binding_sha256": store.digest(json.loads(record["workspace_json"])),
                        "risk_tier": 2,
                        **({"resume": resume} if resume is not None else {}),
                    }
                    try:
                        # This is a new producer intake, independent of any
                        # physical child check left in the caller's context.
                        # Governed enqueue consumes this exact typed decision;
                        # the bridge's mismatch guard remains intact.
                        decision = worker.kernel_gate(Action(
                            kind=self.KIND, agent=record["profile"],
                            title=("Kanban " + record["title"])[:512],
                            payload=payload, origin="generated",
                        ))
                        if not isinstance(decision, Decision) or decision.verdict is Verdict.DENY:
                            raise TaskQueueError("worker intake kernel refused")
                        qid = worker.govern_enqueue(
                            agent=record["profile"],
                            kind=self.KIND,
                            title=("Kanban " + record["title"])[:512],
                            payload=payload,
                            risk_tier=2,
                            autonomy_level="ask",
                            origin="generated",
                        )
                    except TaskQueueError:
                        store.finish(
                            conn, record["id"], state="refused", error="kernel_or_policy_refused"
                        )
                        continue
                    q = queue.get(qid)
                if (
                    q is None
                    or q.kind != self.KIND
                    or q.payload.get("input_sha256") != record["input_sha"]
                ):
                    raise ValueError("queue submission binding is unavailable")
                if q.status not in _ACTIVE_QUEUE_STATES:
                    continue
                store.bind(conn, record, q)
                queued.append({"task_id": task.id, "queue_id": q.id, "status": q.status})
                if task.id not in pending:
                    slots -= 1
                    counts[task.assignee] += 1
            return {"ok": True, "status": "queued", "queued": queued}

    def _execution_is_current(self, task, worker, queue):
        permit = worker._execution_context.get()
        fingerprint = TaskQueue.execution_fingerprint(task)
        persisted, mediated = queue.execution_snapshot(task.id, presented_kind=self.KIND)
        return (
            permit is not None
            and permit.consumed
            and fingerprint is not None
            and getattr(permit, "_fingerprint", None) == fingerprint
            and persisted is not None
            and mediated
            and persisted.kind == self.KIND
            and persisted.status == "running"
            and task.agent == persisted.agent
            and TaskQueue.execution_fingerprint(persisted) == fingerprint
            and queue.validate_mediated_execution(persisted, fingerprint)
        )

    async def _heartbeat(self, claimed, task, worker, queue, board):
        while True:
            await asyncio.sleep(self._HEARTBEAT_SECONDS)
            with kb.connect_closing(board=board) as conn:
                run = kb.get_run(conn, claimed.current_run_id)
                if run is not None and run.ended_at is not None:
                    return
                if not self._execution_is_current(task, worker, queue) or not kbd.heartbeat_worker(
                    conn, claimed.id, expected_run_id=claimed.current_run_id
                ):
                    raise KanbanExecutionRefused("worker lost its queue or board run")

    def _workspace_is_current(self, claimed, task, worker, queue, record, binding, *, terminal=False):
        """Prove both the consumed queue permit and live exact board/path inputs."""
        runtime_worker, runtime_queue = self._runtime()
        if (runtime_worker is not worker or runtime_queue is not queue
                or not self._execution_is_current(task, worker, queue)):
            return False
        try:
            context = require_mutation()
            if (context.home.resolve() != self.home.resolve()
                    or context.board != binding["spec"]["board"]
                    or context.task_id != claimed.id or context.run_id != claimed.current_run_id
                    or context.profile != task.agent):
                return False
            with kb.connect_closing(board=context.board) as conn:
                live = store.get(conn, record["id"])
                current = kb.get_task(conn, claimed.id)
                run = kb.get_run(conn, claimed.current_run_id)
                if current is None or run is None:
                    return False
                if terminal:
                    latest = conn.execute("SELECT MAX(id) FROM task_runs WHERE task_id=?", (claimed.id,)).fetchone()[0]
                    run_current = (latest == claimed.current_run_id
                                   and current.current_run_id in (None, claimed.current_run_id)
                                   and current.status != "running" and run.status != "running"
                                   and run.ended_at is not None)
                else:
                    run_current = (current.status == "running"
                                   and current.current_run_id == claimed.current_run_id
                                   and current.claim_lock == "nerva:" + record["id"]
                                   and run.status == "running" and run.ended_at is None)
                return bool(
                    live is not None and live["state"] == "running"
                    and live["run_id"] == claimed.current_run_id
                    and live["queue_id"] == task.id
                    and live["enqueue_id"] == task.mediation_enqueue_id
                    and live["workspace_json"] == record["workspace_json"]
                    and run.task_id == claimed.id and run.profile == task.agent and run_current
                    and store.digest(store.workspace_snapshot(conn, claimed.id)) == store.digest(binding)
                )
        except (OSError, ValueError, PermissionError, TaskQueueError):
            return False

    async def execute(self, task):
        worker, queue = self._runtime()
        if worker is None or not self._execution_is_current(task, worker, queue):
            return {"status": "refused", "reason": "mediation_execution_context_required"}
        payload = task.payload or {}
        board, sid = payload.get("board"), payload.get("submission_id")
        with kanban_scope(KanbanContext(self.home, "dispatcher", board=board, can_mutate=True)):
            try:
                with kb.connect_closing(board=board) as conn:
                    store.initialize(conn)
                    record = store.get(conn, sid)
                    if (
                        record is None
                        or task.agent != record["profile"]
                        or task.agent not in self.orch.agents
                        or payload.get("task_id") != record["task_id"]
                        or payload.get("input_sha256") != record["input_sha"]
                        or payload.get("prompt") != record["prompt"]
                        or payload.get("prompt_sha256") != record["prompt_sha"]
                        or store.digest(record["prompt"]) != record["prompt_sha"]
                        or not record["workspace_json"]
                        or store.digest(json.loads(record["workspace_json"]))
                        != payload.get("workspace_binding_sha256")
                        or store.digest(json.loads(record["workspace_json"])["spec"])
                        != store.digest(payload.get("workspace_spec"))
                    ):
                        raise ValueError("submission input binding changed")
                    binding = json.loads(record["workspace_json"])
                    resume = payload.get("resume")
                    claimed = store.claim(
                        conn, record, task, ttl_seconds=3600, resume=resume,
                        validate_resume=lambda: child_resume.validate_bound(conn, record, task, queue),
                    )
                worker_session = "kanban::" + sid
                from .worker_runner import run_worker_turn

                run = self.runner or run_worker_turn
                owned = KanbanContext(
                    self.home,
                    task.agent,
                    board=board,
                    task_id=claimed.id,
                    run_id=claimed.current_run_id,
                    session_id=worker_session,
                    can_mutate=True,
                )
                try:
                    with kanban_scope(owned):
                        def still_current():
                            return self._workspace_is_current(
                                claimed, task, worker, queue, record, binding
                            )
                        cwd = materialize_workspace(binding["spec"], still_current=still_current,
                                                    expected_run_id=claimed.current_run_id)
                        project_root = binding["spec"].get("project_root")
                        with workspace_scope(cwd, still_current=still_current,
                                             project_root=Path(project_root) if project_root else None):
                            async with asyncio.timeout(claimed.max_runtime_seconds or 1800):
                                async with asyncio.TaskGroup() as group:
                                    heartbeat = group.create_task(
                                        self._heartbeat(claimed, task, worker, queue, board)
                                    )
                                    try:
                                        output = await run(
                                            self.orch,
                                            prompt=record["prompt"],
                                            agent_id=task.agent,
                                            session_id=worker_session,
                                        )
                                    finally:
                                        heartbeat.cancel()
                    with kb.connect_closing(board=board) as conn:
                        ended = kb.get_run(conn, claimed.current_run_id)
                        if (
                            ended is None
                            or ended.ended_at is None
                            or ended.outcome
                            not in {"completed", "review_requested", "blocked", "changes_requested"}
                        ):
                            raise ValueError("worker returned without a terminal board transition")
                    with kanban_scope(owned), kb.connect_closing(board=board) as conn:
                        def cleanup_current():
                            return self._workspace_is_current(
                                claimed, task, worker, queue, record, binding, terminal=True
                            )

                        try:
                            cleanup = cleanup_workspace(
                                conn, claimed.id, expected_run_id=claimed.current_run_id,
                                still_current=cleanup_current, workspace_spec=binding["spec"],
                            )
                        except (OSError, PermissionError, ValueError):
                            cleanup = {"removed": False, "reason": "scope_changed", "path": str(cwd)}
                        store.finish(conn, sid, state="finished")
                    return {
                        "status": "ok",
                        "task_id": claimed.id,
                        "run_id": claimed.current_run_id,
                        "output": output,
                        "workspace_cleanup": cleanup,
                    }
                except BaseException as exc:
                    try:
                        with kb.connect_closing(board=board) as conn:
                            kbd._record_task_failure(
                                conn,
                                claimed.id,
                                type(exc).__name__,
                                outcome="nerva_worker_failed",
                                release_claim=True,
                                end_run=True,
                                expected_run_id=claimed.current_run_id,
                            )
                            store.finish(conn, sid, state="interrupted", error=type(exc).__name__)
                    except Exception:
                        if not isinstance(exc, asyncio.CancelledError):
                            raise
                        logger.warning("Cancelled Kanban board cleanup unavailable")
                    if isinstance(exc, asyncio.CancelledError):
                        # Status plus execution identity are compared in the queue's
                        # write transaction; a replacement/settled run is untouched.
                        fingerprint = TaskQueue.execution_fingerprint(task)
                        if fingerprint is not None:
                            try:
                                queue.transition(
                                    task.id, TaskStatus.FAILED,
                                    result={"error": "kanban_worker_cancelled"},
                                    expected_status=TaskStatus.RUNNING,
                                    expected_execution_sha256=fingerprint,
                                )
                            except Exception:
                                # Storage failure retains the existing crash reaper;
                                # it must never suppress the caller's cancellation.
                                logger.warning("Cancelled Kanban queue settlement unavailable")
                        raise
                    if not isinstance(exc, Exception):
                        raise
                    raise KanbanExecutionRefused(type(exc).__name__) from exc
            except (ValueError, PermissionError, TaskQueueError) as exc:
                raise KanbanExecutionRefused(str(exc)) from exc
