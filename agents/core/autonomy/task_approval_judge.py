"""Advisory task opinions for the existing Decision Inbox, without new approvals."""
from __future__ import annotations

import logging

from .advisory_judgements import JUDGE_MAX_PENDING, AdvisoryJudgements
from .queue import TaskQueue, TaskStatus, approval_is_pending

logger = logging.getLogger("jarvis.autonomy.task_approval_judge")


class TaskApprovalJudge(AdvisoryJudgements):
    def __init__(self, queue: TaskQueue):
        self.queue = queue
        self._init_judgements()

    def _snapshot(self, task) -> dict | None:
        from .approval_judge import action_is_tainted, normalise_snapshot

        digest = self.queue.approval_snapshot_digest(task)
        if task.status != TaskStatus.BLOCKED.value or not approval_is_pending(task) or digest is None:
            return None
        # Copy persisted bytes; the worker's caller-owned containers are never sent.
        description = {
            "kind": task.kind, "payload": task.payload,
            "risk_tier": task.risk_tier, "origin": task.origin,
            "autonomy_level": task.autonomy_level,
        }
        snapshot = normalise_snapshot({
            "id": f"{task.id}:{digest}", "task_id": task.id, "snapshot_sha256": digest,
            "tool": task.payload.get("tool") or task.kind, "agent": task.agent,
            "summary": task.title, "args": description,
        })
        if action_is_tainted(description):
            snapshot["tainted"] = True
        return snapshot

    def schedule(self, task_id: int) -> None:
        """Best effort; failures never change task submission or user decisions."""
        try:
            if self._judge is None or not self._judge.status().configured:
                return
            task = self.queue.get(task_id)
            snapshot = self._snapshot(task) if task is not None else None
            if snapshot and self.queue.approval_judgement(task_id, snapshot["snapshot_sha256"]) is None:
                self._schedule_judge(snapshot)
        except Exception:
            logger.debug("task opinion not scheduled for %s", task_id, exc_info=True)

    def resume_pending(self) -> None:
        """One bounded startup pass; opinions never make a task runnable."""
        try:
            if self._judge is None or not self._judge.status().configured:
                return
            for task in self.queue.list(status=TaskStatus.BLOCKED.value, limit=JUDGE_MAX_PENDING):
                self.schedule(task.id)
        except Exception:
            logger.debug("task opinion restart scan unavailable", exc_info=True)

    def _pending_snapshot(self, action_id: str) -> dict | None:
        task_id, expected = action_id.split(":", 1)
        task = self.queue.get(int(task_id))
        snapshot = self._snapshot(task) if task is not None else None
        if (snapshot is None or snapshot["snapshot_sha256"] != expected
                or self.queue.approval_judgement(task.id, expected) is not None):
            return None
        return snapshot

    def _store_judgement(self, snapshot: dict, annotation: dict):
        # A revoke/change during generation cannot attach an old opinion.
        live = self._pending_snapshot(snapshot["id"])
        current = self._judge.status() if self._judge is not None else None
        if (live is None or current is None or not current.configured
                or not self._judge.wants(live, current) or not self._judge.wants(snapshot, current)):
            return None
        return self.queue.store_approval_judgement(
            snapshot["task_id"], snapshot["snapshot_sha256"], annotation,
        )

    def project(self, task) -> dict:
        """Add public advisory fields; the persisted Task schema stays untouched."""
        out = task.to_dict()
        try:
            snapshot = self._snapshot(task)
            if snapshot is None:
                return out
            annotation = self.queue.approval_judgement(task.id, snapshot["snapshot_sha256"])
            if annotation is not None:
                out["judge"] = annotation
            else:
                with self._judge_lock:
                    pending = snapshot["id"] in self._judge_pending
                if pending and self._pending_snapshot(snapshot["id"]) is not None:
                    out["judge_pending"] = True
        except Exception:
            logger.debug("task opinion projection unavailable", exc_info=True)
        return out

    def clear_pending(self, task_id: int) -> None:
        with self._judge_lock:
            self._judge_pending.difference_update(
                key for key in tuple(self._judge_pending) if key.startswith(f"{task_id}:")
            )

    def _record_judgement(self, snapshot: dict, annotation: dict) -> None:
        from .approval_judge import ADVISORY_WHY, rationale_sha256

        if self._audit is None:
            return
        try:
            self._audit.record(
                actor="approval_judge", action="task_approval.judged", why=ADVISORY_WHY,
                cause=f"autonomy_task:{snapshot['task_id']}", metadata={
                    "task_id": snapshot["task_id"], "snapshot_sha256": snapshot["snapshot_sha256"],
                    "tool": snapshot["tool"], "agent": snapshot["agent"],
                    "score": annotation.get("score"), "flags": list(annotation.get("flags") or []),
                    "judge": annotation.get("judge"), "rationale_sha256": rationale_sha256(annotation),
                },
            )
        except Exception:
            logger.warning("task opinion audit unavailable", exc_info=True)
