"""Owner checkpoint effects through the signed queue and live Action Kernel.

An intent, preview or task ID never grants authority. The worker's authenticated
RUNNING human task, current configuration and physical effect checks do.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import stat
from pathlib import Path

from .checkpoint_inventory import CheckpointInventory
from .checkpoint_maintenance import CheckpointMaintenance
from .checkpoint_operations import CheckpointOperationStore
from .checkpoint_selection import CheckpointSelection
from .commands import Principal
from .file_checkpoint_history import FileCheckpointHistory
from .file_tools import FileScope, SnapshotStore
from .kernel import Action, Verdict, kernel_enabled
from .memory import persistence
from .memory.manager import _turn_digest

logger = logging.getLogger("jarvis.checkpoint_controller")
CHECKPOINT_KINDS = ("checkpoint.restore", "checkpoint.maintenance")
_OWNER = Principal(channel="web", admin=True)
_MACHINE = frozenset({"", "policy", "system", "kernel", "auto", "worker", "scheduler",
                      "smart_approval", "owner_once", "consent"})


def _refused(reason: str, *, unavailable: bool = False) -> dict:
    return {"ok": False, "status": "unavailable" if unavailable else "refused", "reason": reason}


def _scope() -> FileScope:
    from .environments.local_transport import default_roots
    return FileScope([*FileScope.from_env().roots, *default_roots()])


def _binding(ticket) -> dict:
    """Stable accepted tail identity; no nonce or conversation content is persisted."""
    clock = ticket.clock
    return {"session_id": ticket.session_id, "instance_id": ticket.instance_id,
            "revision": ticket.revision, "snapshot_digest": ticket.snapshot_digest,
            "tail_digest": ticket.tail_digest, "cut_index": ticket.cut_index,
            "removed_turns": ticket.removed_turns, "expected_missing": ticket.expected_missing,
            "clock": {"session_id": clock.session_id, "instance_id": clock.instance_id,
                      "started_at": clock.started_at.isoformat(),
                      "rebuilt_at": clock.rebuilt_at.isoformat(), "revision": clock.revision}}


def _json_copy(value):
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


class CheckpointController:
    def __init__(self, orch) -> None:
        self.orch = orch

    def _runtime(self):
        worker = getattr(self.orch, "autonomy", None)
        queue = getattr(self.orch, "autonomy_queue", None)
        if (not kernel_enabled() or worker is None or queue is None
                or worker.queue is not queue or queue.mediation_mode != "enforce"
                or not callable(getattr(worker, "govern_enqueue", None))
                or getattr(worker, "_mediation_kernel", None) is None):
            return None, None
        return worker, queue

    async def _ticket(self, sid):
        memory = self.orch.memory
        clock = self.orch.checkpoints.clock_snapshot(sid)
        if clock is None:
            raise ValueError("session_clock_unavailable")
        return await memory.prepare_rollback_rewind(sid, clock.instance_id, clock)

    async def request(self, principal: Principal, query: dict) -> dict:
        CheckpointInventory._authorize(principal)  # Before configuration, store or session probes.
        worker, queue = self._runtime()
        if worker is None or not callable(getattr(self.orch, "turn_lease", None)):
            return _refused("approval_executor_unavailable", unavailable=True)
        if type(query) is not dict or query.get("action") not in {"restore", "prune", "clear", "clear-legacy"}:
            return _refused("invalid_action")
        if type(query.get("force")) is not bool:
            return _refused("invalid_force")
        sid = getattr(self.orch, "session_id", None)
        if type(sid) is not str or not sid or len(sid) > 512:
            return _refused("session_unavailable")
        ticket = None
        ticket_memory = None
        try:
            async with self.orch.turn_lease(sid) as acquired:
                if not acquired:
                    return _refused("session_busy")
                scope, snapshots = _scope(), SnapshotStore()
                intent = {"action": query["action"], "project": query.get("project"),
                          "force": query["force"], "paths": query.get("paths"),
                          "session_id": sid, "configured_roots": [str(root) for root in scope.roots],
                          "snapshot_directory": str(snapshots.directory)}
                if query["action"] == "restore":
                    plan = await asyncio.to_thread(
                        CheckpointSelection(snapshots, scope).plan, principal, query.get("identifier"),
                        project=query.get("project"), paths=query.get("paths"), force=query["force"])
                    if plan.get("ok") is not True:
                        return _refused(plan.get("reason", "checkpoint_unavailable"))
                    ticket_memory = self.orch.memory
                    ticket = await self._ticket(sid)
                    intent.update(checkpoint_id=plan["checkpoint_id"], plan=_json_copy(plan),
                                  rewind=_binding(ticket))
                    await ticket_memory.discard_rollback_rewind(ticket)
                    ticket = None
                    tier = 3 if query["force"] or plan["instruction_sensitive_paths"] else 1
                    kind = "checkpoint.restore"
                    storage = plan["storage_plan"]
                    preview = {"checkpoint_id": plan["checkpoint_id"], "root": plan["root"],
                               "paths": ([storage["path"]] if "path" in storage else
                                         [item["path"] for item in storage["paths"]]),
                               "force": query["force"],
                               "instruction_sensitive_paths": plan["instruction_sensitive_paths"],
                               "skipped": storage.get("skipped", 0),
                               "conversation_removed_turns": intent["rewind"]["removed_turns"]}
                else:
                    plan = await asyncio.to_thread(
                        CheckpointInventory(snapshots, scope).maintenance_preview, principal,
                        query["action"], project=query.get("project"), limit=500,
                        keep_orphans=not query["force"])
                    if (plan.get("ok") is not True or plan.get("complete") is not True
                            or plan.get("truncated") is not False):
                        return _refused("maintenance_preview_incomplete")
                    intent.update(generation=plan["generation"],
                                  candidates=[row["id"] for row in plan["candidates"]],
                                  keep_orphans=not query["force"])
                    tier, kind = 3, "checkpoint.maintenance"
                    preview = {"action": query["action"], "generation": intent["generation"],
                               "candidates": intent["candidates"],
                               "keep_orphans": intent["keep_orphans"], "retained_shared_data": True}
                if self._runtime() != (worker, queue):
                    return _refused("approval_executor_changed")
                intent.update(kind=kind, risk_tier=tier, preview=preview)
                journal = CheckpointOperationStore(snapshots)
                record = await asyncio.to_thread(journal.prepare, intent)
                # Always ask, even when reversible policy would ordinarily ACT.
                task_id = worker.govern_enqueue(
                    agent="owner", kind=kind, title="Owner checkpoint " + query["action"],
                    payload={"request_id": record["request_id"], "intent_sha": record["intent_sha"],
                             "action": query["action"], "risk_tier": tier,
                             "reversible": tier == 1, "preview": preview},
                    risk_tier=tier, autonomy_level="ask", origin="manual")
                bound = await asyncio.to_thread(
                    journal.bind_task, record["request_id"], task_id, record["intent_sha"])
                # Even a binding failure must report the actual queued card, never success.
                from .turn_approvals import record_pending_approval
                record_pending_approval(task_id)
                if bound.get("ok") is not True:
                    return {**_refused("operation_binding_failed"), "task_id": task_id}
                return {"ok": True, "status": "queued", "task_id": task_id,
                        "request_id": record["request_id"], "preview": preview}
        except Exception as exc:  # noqa: BLE001 — dependency failures must never fall through to effects
            logger.warning("Checkpoint request refused (%s)", type(exc).__name__)
            return _refused("checkpoint_request_refused")
        finally:
            if ticket is not None:
                await ticket_memory.discard_rollback_rewind(ticket)

    def _tail_current(self, ticket, memory, cp) -> bool:
        sid = ticket.session_id
        try:
            from .session_continuation import history_identity, identity

            if (self.orch.memory is not memory or self.orch.checkpoints is not cp
                    or getattr(memory, "_checkpoint_mgr", None) is not cp or cp._conn is None):
                return False
            # clock_snapshot can seed/update a clock. A physical approval predicate
            # must only read the existing durable session and history bindings.
            with cp._lock:
                if (history_identity(cp._conn, sid)[0] != ticket.instance_id
                        or identity(cp._conn, sid) != (ticket.clock.started_at, ticket.instance_id)):
                    return False
                clock = cp._conn.execute(
                    "SELECT birth_at,rebuilt_at,revision,instance_id FROM session_clock WHERE session_id=?",
                    (sid,)).fetchone()
            if clock != (ticket.clock.started_at.isoformat(), ticket.clock.rebuilt_at.isoformat(),
                         ticket.clock.revision, ticket.instance_id):
                return False
            if (memory._rollback_tickets.get(ticket.nonce) is not ticket
                    or sid in memory._rewind_inconsistent
                    or memory.conversation.instances.get(sid) != ticket.instance_id
                    or memory.conversation.revisions.get(sid, 0) != ticket.revision):
                return False
            rows = [turn.to_dict() for turn in memory.conversation.sessions[sid]]
            if _turn_digest(rows) != ticket.tail_digest:
                return False
            try:
                snapshot, digest = persistence.read_snapshot_for_rewind(sid)
            except FileNotFoundError:
                return ticket.expected_missing is True
            return (not ticket.expected_missing and digest == ticket.snapshot_digest
                    and snapshot.get("instance_id") == ticket.instance_id
                    and snapshot.get("revision", 0) == ticket.revision
                    and snapshot["turns"] == rows)
        except Exception:  # noqa: BLE001 — an unreadable tail cannot authorize a physical effect
            return False

    async def execute(self, task) -> dict:
        worker, queue = self._runtime()
        if worker is None:
            return _refused("approval_executor_unavailable")
        if (getattr(task, "kind", None) not in CHECKPOINT_KINDS
                or type(getattr(task, "id", None)) is not int or task.id <= 0
                or task.status != "running" or task.agent != "owner"
                or str(task.decided_by or "").strip().lower() in _MACHINE
                or task.decision not in {"accept", "approve", "edit"}):
            return _refused("current_human_task_required")
        fingerprint = queue.execution_fingerprint(task)

        def queued_current():
            try:
                return (self._runtime() == (worker, queue) and bool(fingerprint)
                        and worker.policy.effective_mode("owner") == "auto"
                        and queue.validate_mediated_execution(task, fingerprint) is True)
            except Exception:  # noqa: BLE001 — every broken authority provider fails closed
                return False

        if not queued_current():
            return _refused("current_human_task_required")
        ticket = None
        ticket_memory = ticket_checkpoints = None
        claimed = False
        journal = record = None
        try:
            snapshots, scope = SnapshotStore(), _scope()
            journal = CheckpointOperationStore(snapshots)
            record = await asyncio.to_thread(journal.get, task.payload.get("request_id"))
            if (record is None or record["task_id"] != task.id
                    or record["intent_sha"] != task.payload.get("intent_sha")):
                return _refused("operation_identity_mismatch")
            intent = record["intent"]
            if (intent["kind"] != task.kind or intent["risk_tier"] != task.payload.get("risk_tier")
                    or intent["action"] != task.payload.get("action")
                    or intent["preview"] != task.payload.get("preview")
                    or task.payload.get("reversible") is not (intent["risk_tier"] == 1)
                    or task.risk_tier < intent["risk_tier"]
                    or intent["configured_roots"] != [str(root) for root in scope.roots]
                    or intent["snapshot_directory"] != str(snapshots.directory)):
                return _refused("operation_scope_changed")
            action = Action(kind=task.kind, agent=task.agent, title=task.title,
                            payload={**task.payload, "approved_task_id": task.id},
                            scope=task.mediation_scope or "global", origin=task.origin)

            def kernel_current():
                if not queued_current():
                    return False
                decision = worker.kernel_dispatch_current(
                    action, approval_check=lambda actual: actual == action and queued_current())
                return decision.verdict is Verdict.GRANT and queued_current()

            async with self.orch.turn_lease(intent["session_id"]) as acquired:
                if not acquired or not kernel_current():
                    return _refused("current_kernel_refused")
                if record["state"] == "completed":
                    return {**record["result"], "replay": True}
                if intent["action"] == "restore":
                    current = await asyncio.to_thread(
                        CheckpointSelection(snapshots, scope).plan, _OWNER, intent["checkpoint_id"],
                        project=intent["project"], paths=intent["paths"], force=intent["force"])
                    if _json_copy(current) != intent["plan"]:
                        return _refused("checkpoint_preview_changed")
                    ticket_memory, ticket_checkpoints = self.orch.memory, self.orch.checkpoints
                    ticket = await self._ticket(intent["session_id"])
                    if _binding(ticket) != intent["rewind"]:
                        return _refused("conversation_tail_changed")

                def effect_current():
                    try:
                        if [str(root) for root in _scope().roots] != intent["configured_roots"]:
                            return False
                        if ticket is not None:
                            root = Path(intent["plan"]["root"])
                            info = os.stat(root, follow_symlinks=False)
                            if (not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) !=
                                    (intent["plan"]["root_dev"], intent["plan"]["root_ino"])):
                                return False
                            if not self._tail_current(ticket, ticket_memory, ticket_checkpoints):
                                return False
                        return kernel_current()
                    except Exception:  # noqa: BLE001 — the physical fence must return a refusal
                        return False

                if not effect_current():
                    return _refused("authority_changed")
                claim = await asyncio.to_thread(journal.claim, record["request_id"],
                                                task_id=task.id, intent_sha=record["intent_sha"])
                if claim.get("ok") is not True:
                    return _refused(claim.get("reason", "operation_claim_refused"))
                if claim["replay"]:
                    return {**claim["result"], "replay": True}
                claimed = True
                if intent["action"] == "restore":
                    history = FileCheckpointHistory(snapshots, FileScope([intent["plan"]["root"]]))
                    ident = intent["checkpoint_id"]
                    kwargs = {"force": intent["force"], "effect_check": effect_current,
                              "expected_current": (intent["plan"]["storage_plan"].get("current")
                                                   if intent["force"] else None)}
                    if ident.startswith("file:"):
                        filesystem = await asyncio.to_thread(history.restore, int(ident[5:]), **kwargs)
                    else:
                        filesystem = await asyncio.to_thread(history.restore_group, ident[6:],
                                                              paths=intent["paths"], **kwargs)
                    complete = (filesystem.get("ok") is True
                                and filesystem.get("complete", True) is True
                                and filesystem.get("skipped", 0) == 0)
                    if complete and effect_current():
                        try:
                            rewind = await ticket_memory.commit_rollback_rewind(ticket)
                            result = {"ok": True, "status": "ok", "filesystem": filesystem,
                                      "conversation": {"removed_turns": rewind.removed_turns,
                                                       "revision": rewind.revision}}
                        except Exception:  # noqa: BLE001 — preserve the already completed file result
                            result = {"ok": False, "status": "partial", "filesystem": filesystem,
                                      "reason": "conversation_rewind_not_committed"}
                    else:
                        result = {"ok": False, "status": "partial", "filesystem": filesystem,
                                  "reason": "restore_not_complete"}
                else:
                    operation_key = hashlib.sha256((record["request_id"] + record["intent_sha"]).encode()).hexdigest()
                    filesystem = await asyncio.to_thread(
                        CheckpointMaintenance(snapshots, scope).apply, _OWNER, action=intent["action"],
                        project=intent["project"], generation=intent["generation"],
                        candidates=intent["candidates"], operation_key=operation_key,
                        keep_orphans=intent["keep_orphans"], authority_check=effect_current)
                    result = {"ok": filesystem.get("ok") is True,
                              "status": "ok" if filesystem.get("ok") is True else "partial",
                              "filesystem": filesystem}
                finished = await asyncio.to_thread(journal.finish, record["request_id"],
                                                    task_id=task.id, intent_sha=record["intent_sha"],
                                                    result=result)
                if finished.get("ok") is not True:
                    return {**result, "ok": False, "status": "partial", "reason": "operation_finish_failed"}
                return result
        except asyncio.CancelledError:
            if claimed:
                await asyncio.shield(asyncio.to_thread(journal.mark_uncertain, record["request_id"],
                                                       task_id=task.id, intent_sha=record["intent_sha"]))
            raise
        except Exception as exc:  # noqa: BLE001 — unexpected post-claim failures remain uncertain
            logger.warning("Checkpoint execution stopped (%s)", type(exc).__name__)
            if claimed:
                try:
                    await asyncio.to_thread(journal.mark_uncertain, record["request_id"],
                                            task_id=task.id, intent_sha=record["intent_sha"])
                except Exception as journal_error:  # noqa: BLE001 — RUNNING still forbids replay
                    logger.warning("Checkpoint uncertainty could not be recorded (%s)",
                                   type(journal_error).__name__)
            return {"ok": False, "status": "partial" if claimed else "refused",
                    "reason": "checkpoint_execution_stopped"}
        finally:
            if ticket is not None:
                await asyncio.shield(ticket_memory.discard_rollback_rewind(ticket))
