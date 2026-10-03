"""Default advisory opinions and opt-in sealed terminal decisions for Decision Inbox."""
from __future__ import annotations

import logging
import re

from .advisory_judgements import JUDGE_MAX_PENDING, AdvisoryJudgements
from .queue import TaskQueue, TaskStatus, approval_is_pending

logger = logging.getLogger("jarvis.autonomy.task_approval_judge")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


class TaskApprovalJudge(AdvisoryJudgements):
    def __init__(self, queue: TaskQueue, *, worker=None):
        self.queue = queue
        self._worker = worker
        self._smart_promotions = {}
        self._init_judgements()

    def _snapshot(self, task) -> dict | None:
        from ..security import taint
        from ..signal_governance import TASK_KIND as SIGNAL_RECOMMENDATION
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
        # Review F4, defence in depth: a row queued outside the worker's origin marking
        # (or before a producer tainted at ingest) is still untrusted by its origin or,
        # for Signal Layer recommendations, by its kind. A remote judge never sees it.
        if (action_is_tainted(description) or taint.is_untrusted_source(task.origin)
                or task.kind == SIGNAL_RECOMMENDATION):
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
        """One bounded startup pass; only opted-in sealed terminal approvals can promote."""
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
        from .smart_approvals import SmartApprovalResult

        if not self._judgement_task_current(snapshot['id']):
            return None
        if type(annotation) is SmartApprovalResult:
            judge = self._judge
            if judge is None:
                return None
            stored, group_id = self.queue.store_smart_terminal_judgement(
                snapshot['task_id'], snapshot['snapshot_sha256'], annotation,
                check=lambda: (self._judgement_task_current(snapshot['id'])
                               and self._judge is judge and judge.smart_current(annotation, snapshot)),
            )
            if stored is not None and stored.get('decision') == 'approve':
                self._smart_promotions[snapshot['id']] = group_id
            return stored
        # A revoke/change during generation cannot attach an old opinion.
        live = self._pending_snapshot(snapshot["id"])
        current = self._judge.status() if self._judge is not None else None
        if (live is None or current is None or not current.configured
                or not self._judge.wants(live, current) or not self._judge.wants(snapshot, current)):
            return None
        return self.queue.store_approval_judgement(
            snapshot["task_id"], snapshot["snapshot_sha256"], annotation,
        )

    def verify_smart_approval(self, task_id: int) -> bool:
        """Check a signed machine decision with the current dedicated judge policy."""
        from .approval_judge import action_is_tainted, normalise_snapshot
        from .smart_approvals import SmartApprovalResult

        try:
            task = self.queue.get(task_id)
            judge = self._judge
            if task is None or judge is None:
                return False
            description = {'kind': task.kind, 'payload': task.payload, 'risk_tier': task.risk_tier,
                           'origin': task.origin, 'autonomy_level': task.autonomy_level}
            snapshot = normalise_snapshot({'task_id': task.id, 'tool': task.payload.get('tool'),
                                           'agent': task.agent, 'args': description})
            if action_is_tainted(description):
                snapshot['tainted'] = True

            def current(receipt):
                result = SmartApprovalResult('approve', receipt['policy_revision'], receipt['judge_revision'],
                                             receipt['judge'], receipt['at'])
                return self._judge is judge and judge.smart_current(result, snapshot)

            return self.queue.verify_smart_terminal_approval(task_id, check=current)
        except Exception:
            return False

    async def _after_judgement(self, snapshot: dict, annotation: dict) -> None:
        if snapshot['id'] not in self._smart_promotions:
            return
        group_id = self._smart_promotions.pop(snapshot['id'])
        worker = self._worker
        task = self.queue.get(snapshot['task_id'])
        if worker is None or task is None or task.decision != 'smart-approve':
            return
        worker._audit('autonomy.smart_approve', task, 'one operation approved by the configured guardian')
        worker._reconcile_waiting_run(task)
        await worker._push_promoted_group(group_id)

    def project(self, task) -> dict:
        """Add public review fields; the persisted Task schema stays untouched."""
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
                    from .smart_approvals import smart_policy, terminal_args

                    if smart_policy(getattr(self._judge, '_env', None)).enabled and terminal_args(snapshot):
                        out['judge_mode'] = 'smart'
        except Exception:
            logger.debug("task opinion projection unavailable", exc_info=True)
        return out

    def clear_pending(self, task_id: int) -> None:
        if type(task_id) is not int or task_id <= 0:
            return
        with self._judge_lock:
            attempts = tuple(attempt for key, attempt in self._judge_attempts.items()
                             if key.startswith(f"{task_id}:"))
        for attempt in attempts:
            self._cancel_attempt(attempt)
        with self._judge_lock:
            self._judge_pending.difference_update(
                key for key in tuple(self._judge_pending) if key.startswith(f"{task_id}:")
            )

    async def wait_for_review(self, task_id: int, snapshot_sha256: str, *, timeout: float) -> bool:
        """Join an already scheduled exact snapshot; completion is never authority."""
        if (type(task_id) is not int or task_id <= 0 or type(snapshot_sha256) is not str
                or _SHA256_HEX.fullmatch(snapshot_sha256) is None):
            return False
        return await self._wait_judgement(f"{task_id}:{snapshot_sha256}", timeout=timeout)

    def _record_judgement(self, snapshot: dict, annotation: dict) -> None:
        from .approval_judge import ADVISORY_WHY, rationale_sha256

        if self._audit is None:
            return
        try:
            self._audit.record(
                actor="approval_judge", action="task_approval.judged",
                why=(ADVISORY_WHY if annotation.get('advisory', True) else 'configured guardian terminal verdict'),
                cause=f"autonomy_task:{snapshot['task_id']}", metadata={
                    "task_id": snapshot["task_id"], "snapshot_sha256": snapshot["snapshot_sha256"],
                    "tool": snapshot["tool"], "agent": snapshot["agent"],
                    "score": annotation.get("score"), "flags": list(annotation.get("flags") or []),
                    "judge": annotation.get("judge"), "rationale_sha256": rationale_sha256(annotation),
                    **({'decision': annotation['decision']} if 'decision' in annotation else {}),
                },
            )
        except Exception:
            logger.warning("task opinion audit unavailable", exc_info=True)
