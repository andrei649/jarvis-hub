"""Canonical, single-use approval state for private Hermes operations."""

from __future__ import annotations

import asyncio
import logging
import secrets
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from functools import wraps

from agents.core.autonomy.mediation import canonical_json
from agents.core.autonomy.queue import TaskQueue, TaskStatus, approval_is_pending

from .bridge import bounded_outcome
from .policy import KIND, RuntimeDenied, classify

APPROVAL_SECONDS = 300
TOOL_POLL_GRACE_SECONDS = 10
logger = logging.getLogger("jarvis.hermes.approvals")


def _same_canonical_action(left, right) -> bool:
    """Compare exact bounded JSON, including boolean and number representation."""
    try:
        return canonical_json(left) == canonical_json(right)
    except ValueError:
        return False


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._state_lock:
            return method(self, *args, **kwargs)
    return call


def public_task(task, *, generation: str | None = None) -> dict:
    """Expose the action the owner is deciding, never bridge or mediation secrets."""
    payload = task.payload if isinstance(task.payload, dict) else {}
    status = task.status
    result = task.result if isinstance(task.result, dict) else {}
    disposition = result.get("disposition") or (
        "queued" if status in {"proposed", "blocked"} else
        "consumed_outcome_unknown" if status == "running" else status
    )
    decision = getattr(task, "decision", None)
    revoked = (decision == "generation-revoked"
               or (generation is not None and payload.get("generation") != generation
                   and status in {"proposed", "blocked", "approved", "running"}))
    if decision == "intake-aborted":
        disposition = "intake_failed"
    elif decision == "dispatch-unavailable":
        disposition = "dispatch_unavailable"
    elif decision == "continuation-lost":
        disposition = "continuation_lost"
    elif revoked:
        disposition = "generation_revoked"
    public = {
        "task_id": task.id, "status": status,
        "operation": payload.get("operation"), "target": payload.get("target"),
        "arguments": payload.get("arguments"), "risk_tier": task.risk_tier,
        "created_at": task.created_at, "expires_at": task.approval_deadline_at,
        "disposition": disposition,
    }
    if result:
        public["result"] = {key: result[key] for key in ("disposition", "value") if key in result}
    if decision == "intake-aborted":
        public["error"] = "Approval intake did not reach the caller"
    elif decision == "dispatch-unavailable":
        public["error"] = "Approved RPC could not be dispatched"
    elif decision == "continuation-lost":
        public["error"] = "Original tool call is no longer waiting"
    elif revoked:
        public["error"] = "Runtime generation revoked"
    elif status == "rejected":
        public["error"] = "Owner denied this operation"
    elif status == "expired":
        public["error"] = "Approval expired"
    elif status == "failed":
        native = result.get("value") if result.get("disposition") == "native_error" else None
        public["error"] = (native.get("message", "Hermes native request failed")
                           if isinstance(native, dict) else "Execution outcome is uncertain")
    return public


class HermesApprovals:
    def __init__(self, *, worker, queue, gate, generation, client):
        self.worker, self.queue, self.gate = worker, queue, gate
        self.generation, self.client = generation, client
        self._permits: dict[str, int] = {}
        self._active: dict[str, int] = {}
        self._tool_last_poll: dict[int, float] = {}
        self._aborted_submissions: set[str] = set()
        self._jobs: set[asyncio.Task] = set()
        self._revoked = False
        self._state_lock = threading.RLock()

    @_serialized
    def revoke(self):
        self._revoked = True
        self._permits.clear()
        self._active.clear()
        self._tool_last_poll.clear()
        self._aborted_submissions.clear()
        # A clean stop closes its canonical cards. A crash cannot run this,
        # which is why public_task also projects stale generations as revoked.
        for task in self.queue.active_kind_tasks(KIND):
            if task.payload.get("generation") != self.generation:
                continue
            try:
                if task.status == "approved":
                    self.queue.transition(task.id, TaskStatus.BLOCKED,
                                          expected_status=TaskStatus.APPROVED)
                    task = self.queue.get(task.id)
                if task.status in {"blocked", "proposed"}:
                    self.queue.transition(task.id, TaskStatus.REJECTED,
                                          expected_status=TaskStatus(task.status),
                                          decided_by="runtime", decision="generation-revoked")
                elif task.status == "running":
                    self.queue.transition(task.id, TaskStatus.FAILED,
                                          expected_status=TaskStatus.RUNNING,
                                          result={"disposition": "revoked_outcome_unknown"})
            except Exception as exc:
                # An expiry or concurrent claim may have won the CAS. Every
                # dispatch still checks the generation and one-use permit.
                logger.warning("Hermes generation revocation could not settle task %s (%s)",
                               task.id, type(exc).__name__)

    async def submit(self, frame: dict) -> dict:
        if self._revoked or self.queue.mediation_mode != "enforce":
            raise RuntimeDenied("Hermes governed approvals require enforced task mediation")
        if frame["generation"] != self.generation:
            raise RuntimeDenied("Hermes generation revoked")
        kind, target, args = frame["kind"], frame["target"], frame["args"]
        tier = classify(kind, target)
        if tier != 3:
            raise RuntimeDenied("Hermes approval is not required for this action")
        payload = {"operation": kind, "target": target, "arguments": args,
                   "generation": self.generation, "risk_tier": tier,
                   "request_nonce": frame["nonce"], "owner": "hub-owner",
                   "session_id": args.get("session_id"),
                   "submission_id": frame["nonce"]}
        deadline = (datetime.now(UTC) + timedelta(seconds=APPROVAL_SECONDS)).isoformat()
        task = await self.worker.submit(
            agent="hermes", kind=KIND, title=f"Hermes {kind}: {target}",
            payload=payload, origin="generated", attention_mode="none", risk_tier=tier,
            approval_deadline_at=deadline,
        )
        if frame["nonce"] in self._aborted_submissions:
            self.abort_submission(frame["nonce"])
            raise RuntimeDenied("Hermes approval intake aborted")
        if (task.kind != KIND or task.status != "blocked"
                or not _same_canonical_action(task.payload, payload)):
            raise RuntimeDenied("Hermes canonical approval intake failed")
        if kind == "tool":
            self._tool_last_poll[task.id] = time.monotonic()
        return {"verdict": "queue", "reason": "Hermes approval required",
                "task_id": task.id, "disposition": "queued"}

    @_serialized
    def abort_submission(self, submission_id: str) -> None:
        """Fence a timed-out bridge intake before or after the queue commit."""
        self._aborted_submissions.add(submission_id)
        try:
            task = self.queue.find_submission_task(KIND, submission_id)
            if task is None or task.payload.get("generation") != self.generation:
                return
            self._settle_undispatched(task, decision="intake-aborted")
        except Exception as exc:
            logger.warning("Hermes timed-out intake could not settle (%s)", type(exc).__name__)

    def _settle_undispatched(self, task, *, decision: str) -> None:
        if task.status == "approved":
            self.queue.transition(task.id, TaskStatus.BLOCKED,
                                  expected_status=TaskStatus.APPROVED)
            task = self.queue.get(task.id)
        if task.status in {"blocked", "proposed"}:
            self.queue.transition(task.id, TaskStatus.REJECTED,
                                  expected_status=TaskStatus(task.status),
                                  decided_by="runtime", decision=decision)
        elif task.status == "running":
            self.queue.transition(task.id, TaskStatus.FAILED,
                                  expected_status=TaskStatus.RUNNING,
                                  result={"disposition": "consumed_outcome_unknown"})

    def list(self) -> dict:
        self._expire_orphan_tools()
        rows = [public_task(t, generation=self.generation) for t in self.queue.list(kind=KIND, limit=100)]
        return {"tasks": rows, "total": len(rows)}

    @_serialized
    def _expire_orphan_tools(self):
        now = time.monotonic()
        for task_id, last in tuple(self._tool_last_poll.items()):
            if now - last <= TOOL_POLL_GRACE_SECONDS:
                continue
            task = self.queue.get(task_id)
            if task is None or task.status not in {"blocked", "proposed", "approved"}:
                self._tool_last_poll.pop(task_id, None)
                continue
            try:
                if task.status == "approved":
                    self.queue.transition(task_id, TaskStatus.BLOCKED,
                                          expected_status=TaskStatus.APPROVED)
                    task = self.queue.get(task_id)
                self.queue.transition(task_id, TaskStatus.REJECTED,
                                      expected_status=TaskStatus(task.status),
                                      decided_by="runtime", decision="continuation-lost")
            except Exception as exc:
                logger.warning("Hermes orphaned tool task %s could not settle (%s)",
                               task_id, type(exc).__name__)
            self._tool_last_poll.pop(task_id, None)

    async def decide(self, task_id: int, approved: bool) -> dict:
        if type(task_id) is not int or task_id <= 0 or type(approved) is not bool:
            raise RuntimeDenied("invalid Hermes approval decision")
        if approved and self._revoked:
            raise RuntimeDenied("Hermes generation revoked")
        self._expire_orphan_tools()
        task = self.queue.get(task_id)
        if task is None or task.kind != KIND or task.status not in {"blocked", "proposed"}:
            raise RuntimeDenied("Hermes approval is no longer pending")
        if task.payload.get("submission_id") in self._aborted_submissions:
            self.abort_submission(task.payload["submission_id"])
            raise RuntimeDenied("Hermes approval intake aborted")
        if approved and task.payload.get("operation") == "tool" and task_id not in self._tool_last_poll:
            raise RuntimeDenied("Hermes tool continuation expired")
        if not approval_is_pending(task):
            raise RuntimeDenied("Hermes approval expired")
        if approved and (self._revoked or task.payload.get("generation") != self.generation):
            raise RuntimeDenied("Hermes generation revoked")
        task = await self.worker.apply_decision(task_id, "accept" if approved else "reject",
                                                decided_by="user")
        if approved and task.payload.get("operation") == "rpc":
            job = asyncio.create_task(self._dispatch(task_id))
            self._jobs.add(job)
            job.add_done_callback(self._jobs.discard)
        return public_task(task)

    async def _dispatch(self, task_id: int):
        task = self.queue.get(task_id)
        if task is None or task.status != "approved" or task.decided_by != "user":
            return
        if self._revoked or task.payload.get("generation") != self.generation:
            return
        if task.payload.get("operation") != "rpc":
            # Tool continuations need their original call frame; never replay a
            # tool outside its upstream turn.
            return
        rid = "hermes-approved-" + secrets.token_hex(24)
        with self._state_lock:
            if self._revoked:
                return
            self._permits[rid] = task_id
        try:
            await self.client.rpc(task.payload["target"], task.payload["arguments"], request_id=rid)
        except Exception as exc:
            # The worker may have dispatched before the reply was lost. A claimed
            # task remains consumed with an explicit unknown outcome.
            logger.warning("Hermes approved RPC task %s reply unavailable (%s)",
                           task_id, type(exc).__name__)
            current = self.queue.get(task_id)
            if current is not None and current.status == "approved":
                try:
                    self._settle_undispatched(current, decision="dispatch-unavailable")
                except Exception as settle_error:
                    logger.warning("Hermes approved RPC task %s could not settle (%s)",
                                   task_id, type(settle_error).__name__)
        finally:
            with self._state_lock:
                self._permits.pop(rid, None)

    @_serialized
    def authorize(self, frame: dict) -> dict:
        """Called by the authenticated bridge; a permit is not an approval."""
        if self._revoked or frame["generation"] != self.generation:
            raise RuntimeDenied("Hermes generation revoked")
        rid = frame.get("request_id")
        task_id = self._permits.pop(rid, None) if isinstance(rid, str) else None
        if task_id is None:
            return self.gate.authorize(frame["kind"], frame["target"],
                                       frame["args"], frame["generation"],
                                       request_nonce=frame["nonce"])
        task = self.queue.get(task_id)
        expected = {"operation": frame["kind"], "target": frame["target"],
                    "arguments": frame["args"], "generation": self.generation,
                    "risk_tier": classify(frame["kind"], frame["target"]),
                    "request_nonce": task.payload.get("request_nonce") if task else None,
                    "owner": "hub-owner", "session_id": frame["args"].get("session_id"),
                    "submission_id": task.payload.get("submission_id") if task else None}
        if (task is None or task.kind != KIND or task.status != "approved"
                or task.decided_by != "user" or task.decision != "accept"
                or not _same_canonical_action(task.payload, expected)
                or self.queue.mediation_mode != "enforce"):
            raise RuntimeDenied("Hermes approved action changed")
        claimed = self.queue.claim_mediated(task_id, execution_id=str(uuid.uuid4()))
        if claimed is None:
            raise RuntimeDenied("Hermes approval claim unavailable")
        fingerprint = TaskQueue.execution_fingerprint(claimed)
        try:
            if not fingerprint or not self.queue.validate_mediated_execution(claimed, fingerprint):
                raise RuntimeDenied("Hermes mediation validation failed")

            def approval_check(action):
                current = self.queue.get(task_id)
                candidate = dict(action.payload) if isinstance(action.payload, dict) else {}
                return (
                    type(candidate.get("approved_task_id")) is int
                    and candidate.pop("approved_task_id") == task_id
                    and _same_canonical_action(candidate, expected)
                    and current is not None and current.status == "running"
                    and current.decided_by == "user" and current.decision == "accept"
                    and TaskQueue.execution_fingerprint(current) == fingerprint
                    and self.queue.validate_mediated_execution(current, fingerprint)
                )

            self.gate.authorize(
                frame["kind"], frame["target"], frame["args"], self.generation,
                request_nonce=expected["request_nonce"], approved_task_id=task_id,
                approval_check=approval_check,
            )
        except Exception:
            # This claim cannot be replayed. No grant reached the native handler.
            self.queue.transition(task_id, TaskStatus.FAILED,
                                  expected_status=TaskStatus.RUNNING,
                                  result={"disposition": "refused_before_dispatch"})
            raise
        # RUNNING is a consumed one-use claim. The response is reported by the
        # original caller after the actual handler returns; lost replies remain
        # RUNNING and can never be retried.
        completion_id = secrets.token_hex(24)
        self._active[completion_id] = task_id
        return {"verdict": "grant", "tier": claimed.risk_tier,
                "task_id": task_id, "completion_id": completion_id}

    @_serialized
    def complete(self, frame: dict) -> dict:
        if self._revoked or frame["generation"] != self.generation:
            raise RuntimeDenied("Hermes generation revoked")
        completion_id, task_id = frame["completion_id"], frame["task_id"]
        if self._active.pop(completion_id, None) != task_id:
            raise RuntimeDenied("Hermes completion permit unavailable")
        task = self.queue.get(task_id)
        if task is None or task.kind != KIND or task.status != "running":
            raise RuntimeDenied("Hermes completion task unavailable")
        fingerprint = TaskQueue.execution_fingerprint(task)
        if not fingerprint or not self.queue.validate_mediated_execution(task, fingerprint):
            raise RuntimeDenied("Hermes completion evidence invalid")
        outcome = bounded_outcome(frame.get("outcome", {"state": "unknown"}))
        ok = frame["ok"] is True and outcome["state"] == "result"
        disposition = ("completed" if ok else "native_error" if outcome["state"] == "error"
                       else "consumed_outcome_unknown")
        stored = {"disposition": disposition}
        if outcome["state"] in {"result", "error"}:
            stored["value"] = outcome["value"]
        self.queue.transition(task_id, TaskStatus.DONE if ok else TaskStatus.FAILED,
                              expected_status=TaskStatus.RUNNING,
                              expected_execution_sha256=fingerprint,
                              result=stored)
        self._tool_last_poll.pop(task_id, None)
        return {"verdict": "grant"}

    @_serialized
    def continue_tool(self, frame: dict) -> dict:
        self._expire_orphan_tools()
        task_id = frame["task_id"]
        task = self.queue.get(task_id)
        if (self._revoked or task is None or task.kind != KIND
                or task.payload.get("operation") != "tool"
                or task.payload.get("request_nonce") != frame["original_nonce"]
                or task.payload.get("generation") != self.generation):
            raise RuntimeDenied("Hermes tool continuation revoked")
        self._tool_last_poll[task_id] = time.monotonic()
        if task.status in {"blocked", "proposed"}:
            if not approval_is_pending(task):
                raise RuntimeDenied("Hermes approval expired")
            return {"verdict": "queue", "task_id": task_id, "disposition": "queued"}
        if task.status != "approved":
            raise RuntimeDenied("Hermes tool approval unavailable")
        # The bridge authenticated the original worker. Its original nonce and
        # the signed canonical task bind this exact paused tool invocation.
        self._permits[frame["request_id"]] = task_id
        try:
            return self.authorize(frame)
        finally:
            self._permits.pop(frame["request_id"], None)
