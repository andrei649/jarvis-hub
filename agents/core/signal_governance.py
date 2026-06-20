"""signal_governance.py — bridge Signal Layer recommendations into Jarvis approvals.

Turns the Signal Layer's *preview-only* recommendations into items in the
existing human-approval queue. It is deliberately conservative:

- **Off by default.** Gated behind ``JARVIS_SIGNAL_GOVERNANCE`` (or an injected
  ``enabled`` flag). When off, it queues nothing and reports ``disabled``.
- **Preview-only, never executed.** Each queued item is created and immediately
  moved to ``BLOCKED`` — i.e. it sits in the human decision inbox awaiting
  approval. This bridge never approves, runs, or executes anything; there is no
  executor path here. Raw OSINT is never turned into an action automatically.
- **Only actionable recommendations are queued** (``requiresApproval`` truthy);
  purely advisory "keep monitoring" items are skipped.
- **Audited.** An optional ``audit`` callable records every queued item.

This keeps the project's invariant intact: facts, raw leads, model inference,
forecasts, and recommendations stay separate, and nothing acts without approval.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from .autonomy.queue import TaskQueue, TaskStatus

logger = logging.getLogger("jarvis.signal_governance")

GOVERNANCE_FLAG = "JARVIS_SIGNAL_GOVERNANCE"
TASK_KIND = "signal_recommendation"
# EXTERNAL tier: a human must decide. We also force BLOCKED regardless, so this is
# defense-in-depth, not the only guard.
RISK_TIER_EXTERNAL = 2


class SignalGovernanceBridge:
    """Submit Signal Layer recommendations into the approval queue as previews."""

    def __init__(
        self,
        queue: TaskQueue,
        *,
        enabled: bool = False,
        audit: Optional[Callable[[str, dict], None]] = None,
        agent: str = "signal-layer",
    ):
        self.queue = queue
        self.enabled = bool(enabled)
        self.audit = audit
        self.agent = agent

    @classmethod
    def from_env(cls, queue: TaskQueue, env=None, **kwargs) -> "SignalGovernanceBridge":
        env = env if env is not None else os.environ
        enabled = str(env.get(GOVERNANCE_FLAG, "")).strip().lower() in ("1", "true", "yes", "on")
        return cls(queue, enabled=enabled, **kwargs)

    def _audit(self, event: str, detail: dict) -> None:
        if self.audit is None:
            return
        try:
            self.audit(event, detail)
        except Exception as e:  # auditing must never break the bridge
            logger.debug("signal_governance audit failed (%s): %s", event, e)

    def submit_recommendations(
        self, recommendations: list[dict], *, context: Optional[dict] = None
    ) -> dict[str, Any]:
        """Queue actionable recommendations as preview-only approval items.

        Returns a summary; never raises for ordinary input.
        """
        if not self.enabled:
            return {"status": "disabled", "queued": 0, "task_ids": [], "skipped": 0}

        recs = recommendations or []
        actionable = [r for r in recs if isinstance(r, dict) and r.get("requiresApproval")]
        skipped = len(recs) - len(actionable)
        task_ids: list[int] = []

        for rec in actionable:
            label = str(rec.get("label") or "Signal Layer recommendation")
            payload = {
                "recommendation": rec,
                "context": context or {},
                "preview_only": True,
                "source": "signal-layer",
            }
            try:
                task_id = self.queue.enqueue(
                    agent=self.agent,
                    kind=TASK_KIND,
                    title=label,
                    payload=payload,
                    risk_tier=RISK_TIER_EXTERNAL,
                    autonomy_level="ask",
                    origin="generated",
                )
                # Preview-only: move straight to BLOCKED (awaiting human decision).
                # Never APPROVED/RUNNING from this bridge.
                self.queue.transition(
                    task_id, TaskStatus.BLOCKED, decided_by="signal-governance",
                    decision="await_human_approval",
                )
                task_ids.append(task_id)
                self._audit("signal_governance.queued", {"task_id": task_id, "label": label})
            except Exception as e:
                logger.debug("Failed to queue recommendation %r: %s", label, e)
                self._audit("signal_governance.error", {"label": label, "error": str(e)})

        return {
            "status": "ok",
            "queued": len(task_ids),
            "task_ids": task_ids,
            "skipped": skipped,
            "note": "Preview only. Route through Jarvis approval before action.",
        }

    def submit_from_brief(self, brief: Optional[dict], *, context: Optional[dict] = None) -> dict[str, Any]:
        """Convenience: pull ``recommendations`` out of a brief/assessment dict."""
        recommendations = (brief or {}).get("recommendations") or []
        ctx = {"scope": (brief or {}).get("scope"), "title": (brief or {}).get("title")}
        if context:
            ctx.update(context)
        return self.submit_recommendations(recommendations, context=ctx)
