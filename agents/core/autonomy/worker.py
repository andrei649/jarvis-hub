"""
worker.py — Autonomy Worker (H6.1 glue + H6.2/H6.3 integration).

Ties the queue, policy and decision inbox together:

  submit()  → enqueue (proposed) → policy.decide → auto-approve (act/notify)
              or block + push a decision card to the inbox (ask), within the
              daily interruption budget.
  tick()    → run approved tasks via the injected executor, with a retry cap.
  apply_decision() → resolve a blocked task from a human's inbox tap.

Executor and notifier are injected (set by web.py at startup) so this module
stays free of orchestrator/Telegram imports and is unit-testable offline.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Awaitable, Callable, Optional

from ..action_origin import current_action_origin
from ..security import taint
from .policy import ACT, ASK, NOTIFY, AutonomyPolicy
from .queue import MAX_ATTEMPTS, Task, TaskQueue, TaskStatus

logger = logging.getLogger("jarvis.autonomy.worker")

INTERRUPT_BUDGET_PER_DAY = 4

# executor(task) -> dict result ; notifier(task) -> bool (pushed ok)
Executor = Callable[[Task], Awaitable[dict]]
Notifier = Callable[[Task], Awaitable[bool]]


def is_night_window(hour: int, start: int = 23, end: int = 6) -> bool:
    """True if `hour` falls in the night window (handles wrap past midnight)."""
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps midnight, e.g. 23→6


class InterruptBudget:
    """Caps urgent push notifications per day to protect the user's attention."""

    def __init__(self, per_day: int = INTERRUPT_BUDGET_PER_DAY, *,
                 ledger=None, dimension: str = "interrupts/day"):
        self.per_day = per_day
        self._day = date.today()
        self._used = 0
        self._ledger = ledger
        self._dimension = dimension
        self._sync_dimension()

    def _sync_dimension(self) -> None:
        if self._ledger is None:
            return
        setter = getattr(self._ledger, "set_dimension_usage", None)
        if setter is None:
            return
        setter(
            self._dimension,
            self._used,
            limit=self.per_day,
            unit="interrupts",
            enforced=True,
            metadata={"period": "day", "day": self._day.isoformat()},
        )

    def _roll(self) -> None:
        today = date.today()
        if today != self._day:
            self._day = today
            self._used = 0
        self._sync_dimension()

    def remaining(self) -> int:
        self._roll()
        return max(0, self.per_day - self._used)

    def consume(self) -> bool:
        self._roll()
        if self._used >= self.per_day:
            return False
        self._used += 1
        self._sync_dimension()
        return True


class AutonomyWorker:
    def __init__(self, queue: TaskQueue, policy: Optional[AutonomyPolicy] = None,
                 executor: Optional[Executor] = None, notifier: Optional[Notifier] = None,
                 budget: Optional[InterruptBudget] = None, audit=None, prefs=None,
                 kill_switch=None):
        self.queue = queue
        self.policy = policy or AutonomyPolicy()
        self.executor = executor
        self.notifier = notifier
        self.budget = budget or InterruptBudget()
        self.audit = audit
        self.prefs = prefs
        # O26-P0.7 (F3): the executor seam honors the global kill-switch
        # KERNEL-INDEPENDENTLY — before this, engaging the halt did not stop an
        # already-approved broker task from executing on a default install.
        self._kill_switch = kill_switch

    def _halted(self) -> bool:
        if self._kill_switch is None:
            try:
                from ..security.capability import KillSwitch
                self._kill_switch = KillSwitch()
            except Exception:
                return False
        try:
            return bool(self._kill_switch.is_halted())
        except Exception:
            return False

    # O26-P0.7 (F3): the governed intake brokers use as their enqueue sink.
    # Before this, social/writeback/call/node/tool-rpc proposals went straight
    # to TaskQueue.enqueue as status='proposed' — bypassing the risk policy
    # (AUTO/ASK/OFF dial + money caps) AND invisible to the decision inbox
    # (pending_decisions filtered status='blocked' only).
    _LEVEL_RANK = {ACT: 0, NOTIFY: 1, ASK: 2}

    def _effective_origin(self, origin: str | None) -> str:
        explicit = str(origin or "generated")
        try:
            active = current_action_origin()
        except Exception:
            active = explicit
        if taint.is_untrusted_source(active):
            return active
        if taint.is_untrusted_source(explicit):
            return explicit
        return explicit or "generated"

    def _mark_payload_for_origin(self, payload: dict | None, origin: str) -> tuple[dict, bool]:
        marked = taint.mark_if_untrusted(payload or {}, origin)
        return marked, taint.is_tainted(marked)

    def _force_ask_for_taint(self, level: str, tainted: bool) -> str:
        return ASK if tainted and level in (ACT, NOTIFY) else level

    def govern_enqueue(self, agent: str, kind: str, title: str, payload: dict = None,
                       risk_tier: int = 2, autonomy_level: str = ASK,
                       origin: str = "generated") -> int:
        """Sync governed intake (drop-in for ``TaskQueue.enqueue``).

        Runs ``policy.decide`` and applies the STRICTER of the caller's
        requested level and the policy outcome (a broker's always-ask can
        never be weakened; a kernel-granted ``act`` can still be tightened
        by the policy's money caps). ``ask`` tasks land BLOCKED so they enter
        the decision inbox; the Telegram push is best-effort (scheduled when
        an event loop is running, else the card waits in the inbox).
        """
        origin = self._effective_origin(origin)
        payload, tainted = self._mark_payload_for_origin(payload, origin)
        decision = self.policy.decide({"kind": kind, **payload})
        rank = self._LEVEL_RANK
        effective = autonomy_level if rank.get(autonomy_level, 2) >= rank.get(
            decision.outcome, 2) else decision.outcome
        effective = self._force_ask_for_taint(effective, tainted)
        tier = max(int(risk_tier), int(decision.tier))
        task_id = self.queue.enqueue(
            agent=agent, kind=kind, title=title, payload=payload,
            risk_tier=tier, autonomy_level=effective, origin=origin,
        )
        if effective in (ACT, NOTIFY):
            task = self.queue.transition(
                task_id, TaskStatus.APPROVED,
                decided_by="policy", decision=f"auto-{effective}",
            )
            self._audit("autonomy.auto_approve", task, decision.reason)
            return task_id
        task = self.queue.transition(
            task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval",
        )
        try:
            import asyncio
            asyncio.get_running_loop().create_task(self._maybe_push(task))
        except RuntimeError:
            logger.debug("no running loop — decision card waits in the inbox")
        return task_id

    # ── intake ────────────────────────────────────────────────────
    async def submit(self, agent: str, kind: str, title: str,
                     payload: dict = None, origin: str = "generated") -> Task:
        """Propose a task, gate it through the policy, and route it."""
        origin = self._effective_origin(origin)
        payload, tainted = self._mark_payload_for_origin(payload, origin)
        action = {"kind": kind, **payload}
        decision = self.policy.decide(action)
        effective = self._force_ask_for_taint(decision.outcome, tainted)
        task_id = self.queue.enqueue(
            agent=agent, kind=kind, title=title, payload=payload,
            risk_tier=int(decision.tier), autonomy_level=effective, origin=origin,
        )

        if effective in (ACT, NOTIFY):
            task = self.queue.transition(
                task_id, TaskStatus.APPROVED,
                decided_by="policy", decision=f"auto-{effective}",
            )
            self._audit("autonomy.auto_approve", task, decision.reason)
            return task

        # ASK → block, then push a decision card if budget allows.
        task = self.queue.transition(
            task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval",
        )
        await self._maybe_push(task)
        return task

    async def _maybe_push(self, task: Task) -> bool:
        if not self.notifier:
            return False
        if not self.budget.consume():
            logger.info(f"Interrupt budget exhausted — task #{task.id} held for daily review")
            return False
        try:
            ok = await self.notifier(task)
        except Exception as e:
            logger.warning(f"Decision push failed for #{task.id}: {e}")
            ok = False
        if ok:
            self.queue.mark_pushed(task.id)
            self._audit("autonomy.push_decision", task, "pushed to inbox")
        return ok

    # ── execution ─────────────────────────────────────────────────
    async def tick(self, limit: int = 10, max_tier: Optional[int] = None) -> dict:
        """Run approved tasks. Returns a small summary dict.

        `max_tier` caps which risk tiers run this pass — used by the night shift
        to batch only reversible/read-only work (max_tier=1).
        """
        ran = done = failed = 0
        # O26-P0.7 (F3): an engaged kill-switch stops execution at THIS seam,
        # kernel-independently — approved tasks stay approved (nothing is lost)
        # and run on the first tick after release.
        if self._halted():
            logger.warning("kill-switch engaged — autonomy tick skipped (tasks held)")
            return {"ran": 0, "done": 0, "failed": 0, "halted": True}
        for task in self.queue.runnable(limit=limit, max_tier=max_tier):
            ran += 1
            self.queue.transition(task.id, TaskStatus.RUNNING)
            attempts = self.queue.increment_attempts(task.id)
            try:
                result = await self._execute(task)
                self.queue.transition(task.id, TaskStatus.DONE, result=result)
                self._settle_spend(task)
                self._audit("autonomy.done", task, "executed")
                done += 1
            except Exception as e:
                if attempts >= MAX_ATTEMPTS:
                    self.queue.transition(task.id, TaskStatus.FAILED,
                                          result={"error": str(e)})
                    self._audit("autonomy.failed", task, f"giving up after {attempts}: {e}")
                    failed += 1
                else:
                    # back to approved for another attempt
                    self.queue.transition(task.id, TaskStatus.APPROVED)
                    logger.info(f"Task #{task.id} failed (attempt {attempts}), will retry: {e}")
        return {"ran": ran, "done": done, "failed": failed}

    async def _execute(self, task: Task) -> dict:
        if self.executor is None:
            # No executor wired → no-op success so the loop is observable.
            return {"status": "noop", "note": "no executor configured"}
        return await self.executor(task)

    def _settle_spend(self, task: Task) -> None:
        amount = task.payload.get("amount") if task.payload else None
        if amount:
            try:
                self.policy.record_spend(float(amount))
            except (TypeError, ValueError):
                pass

    # ── human decisions ───────────────────────────────────────────
    async def apply_decision(self, task_id: int, action: str,
                             decided_by: str = "user", payload: dict = None) -> Task:
        """Resolve a blocked task from an inbox tap (accept/edit/reject/defer)."""
        if action == "accept":
            task = self.queue.transition(task_id, TaskStatus.APPROVED,
                                         decided_by=decided_by, decision="accept")
        elif action == "edit":
            if payload is not None:
                self.queue.update_payload(task_id, payload)
                # BUG-11: an edit must not be auto-approved under the *original*
                # (lower-risk) decision. Re-gate the FULL edited payload — not
                # just the amount — so changing kind/target/reversible/risk_tier
                # (e.g. READ_ONLY → an irreversible kind), or an amount under the
                # per-action cap but over the remaining daily ceiling, is caught.
                edited = self.queue.get(task_id)
                edited_origin = self._effective_origin(edited.origin)
                marked_payload, tainted = self._mark_payload_for_origin(edited.payload or {}, edited_origin)
                if marked_payload != (edited.payload or {}):
                    self.queue.update_payload(task_id, marked_payload)
                    edited = self.queue.get(task_id)
                action_payload = {"kind": edited.kind, **(edited.payload or {})}
                decision = self.policy.decide(action_payload)
                effective = self._force_ask_for_taint(decision.outcome, tainted)
                if effective == ASK:
                    # Edited payload still needs explicit approval — keep the task
                    # in its current BLOCKED state (no transition: BLOCKED→BLOCKED
                    # is illegal) and re-push a fresh decision card to the inbox.
                    logger.warning(
                        "apply_decision: edited payload on task %s still requires "
                        "approval (%s) — kept blocked, re-pushed for re-approval",
                        task_id, decision.reason)
                    await self._maybe_push(edited)
                    self._audit("autonomy.decision.edit", edited, f"by {decided_by} (re-gated, blocked)")
                    if self.prefs:
                        try:
                            self.prefs.record(edited, action, decided_by=decided_by)
                        except Exception as e:
                            logger.warning(f"Preference record failed for #{task_id}: {e}")
                    return edited
            task = self.queue.transition(task_id, TaskStatus.APPROVED,
                                         decided_by=decided_by, decision="edit")
        elif action == "reject":
            task = self.queue.transition(task_id, TaskStatus.REJECTED,
                                         decided_by=decided_by, decision="reject")
        elif action == "defer":
            task = self.queue.transition(task_id, TaskStatus.DEFERRED,
                                         decided_by=decided_by, decision="defer")
        else:
            from .queue import TaskQueueError
            raise TaskQueueError(f"unknown decision action: {action}")
        self._audit(f"autonomy.decision.{action}", task, f"by {decided_by}")
        if self.prefs:
            try:
                self.prefs.record(task, action, decided_by=decided_by)
            except Exception as e:
                logger.warning(f"Preference record failed for #{task_id}: {e}")
        return task

    # ── audit ─────────────────────────────────────────────────────
    def _audit(self, event: str, task: Task, detail: str) -> None:
        if not self.audit:
            return
        try:
            self.audit.log(event, {"task_id": task.id, "agent": task.agent,
                                   "kind": task.kind, "detail": detail})
        except Exception:
            logger.warning("Autonomy audit log failed for event '%s' task #%s", event, task.id, exc_info=True)
