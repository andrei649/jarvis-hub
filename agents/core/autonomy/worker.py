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

if __name__ != "agents.core.autonomy.worker":
    raise ImportError("AutonomyWorker authority must be imported as agents.core.autonomy.worker")

import inspect
import logging
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import date
from typing import Awaitable, Callable, Optional

from ..action_origin import current_action_origin
from ..ambient.policy import AttentionDeliveryBroker, AttentionLedger
from ..security import taint
from .mediation import (
    DetachedHMACSigner,
    ReceiptExpectation,
    issue_intake_evidence,
    issue_receipt,
)
from .policy import ACT, ASK, NOTIFY, AutonomyPolicy, RiskTier
from .queue import MAX_ATTEMPTS, Task, TaskQueue, TaskQueueError, TaskStatus

logger = logging.getLogger("jarvis.autonomy.worker")

INTERRUPT_BUDGET_PER_DAY = 4

# executor(task) -> dict result ; notifier(task) -> bool (pushed ok)
Executor = Callable[[Task], Awaitable[dict]]
Notifier = Callable[[Task], Awaitable[bool]]


class _ExecutionPermit:
    """Shared one-use permit that cannot be replayed by a copied ContextVar."""

    def __init__(self, task: Task) -> None:
        self._fingerprint = TaskQueue.execution_fingerprint(task)
        self._active = True
        self._lock = threading.Lock()

    def consume(self, task: Task, *, validate: Callable[[Task, str], bool]) -> bool:
        with self._lock:
            if not self._active:
                return False
            self._active = False
            fingerprint = TaskQueue.execution_fingerprint(task)
            if (
                not self._fingerprint
                or fingerprint != self._fingerprint
                or task.status != TaskStatus.RUNNING.value
            ):
                return False
        return validate(task, self._fingerprint)

    def revoke(self) -> None:
        with self._lock:
            self._active = False


def is_night_window(hour: int, start: int = 23, end: int = 6) -> bool:
    """True if `hour` falls in the night window (handles wrap past midnight)."""
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps midnight, e.g. 23→6


class InterruptBudget:
    """Compatibility view over H33's durable global attention ledger."""

    def __init__(
        self,
        per_day: int = INTERRUPT_BUDGET_PER_DAY,
        *,
        ledger=None,
        dimension: str = "interrupts/day",
        attention_ledger: AttentionLedger | None = None,
        timezone_name: str = "UTC",
    ):
        self._k3 = ledger
        self._dimension = dimension
        self._timezone_name = timezone_name
        self._owns_attention_ledger = attention_ledger is None
        self.attention_ledger = attention_ledger or AttentionLedger(
            ":memory:",
            timezone_name=timezone_name,
            per_day=per_day,
            k3=ledger,
        )
        self.attention_ledger.per_day = per_day
        self.delivery_broker = AttentionDeliveryBroker(self.attention_ledger)
        self._day = date.today()
        self._counter = 0

    @property
    def per_day(self) -> int:
        return self.attention_ledger.per_day

    @per_day.setter
    def per_day(self, value: int) -> None:
        self.attention_ledger.per_day = value

    def _roll(self) -> None:
        # Kept solely for the old public test/API that mutates ``_day``. Real
        # rollover is owner-timezone aware and persistent inside AttentionLedger.
        today = date.today()
        if today != self._day and self._owns_attention_ledger:
            self.attention_ledger.close()
            self.attention_ledger = AttentionLedger(
                ":memory:",
                timezone_name=self._timezone_name,
                per_day=self.per_day,
                k3=self._k3,
            )
            self.delivery_broker = AttentionDeliveryBroker(self.attention_ledger)
            self._day = today
            self._counter = 0

    def remaining(self) -> int:
        self._roll()
        return self.attention_ledger.remaining()

    def consume(
        self,
        *,
        delivery_id: str | None = None,
        channel_class: str = "legacy",
    ) -> bool:
        self._roll()
        self._counter += 1
        delivery_id = delivery_id or f"legacy-{self._day.isoformat()}-{self._counter}"
        reservation = self.attention_ledger.reserve(delivery_id, channel_class)
        if reservation.admitted and reservation.state == "reserved":
            self.attention_ledger.start_dispatch(delivery_id)
            self.attention_ledger.delivered(delivery_id)
        return reservation.admitted


class AutonomyWorker:
    def __init__(
        self,
        queue: TaskQueue,
        policy: Optional[AutonomyPolicy] = None,
        executor: Optional[Executor] = None,
        notifier: Optional[Notifier] = None,
        budget: Optional[InterruptBudget] = None,
        audit=None,
        prefs=None,
        kill_switch=None,
        delivery_broker: AttentionDeliveryBroker | None = None,
        clock: Optional[Callable[[], float]] = None,
        running_ttl_seconds: float = 3600.0,
        kernel=None,
        mediation_signer: DetachedHMACSigner | None = None,
        mediation_clock_ms: Optional[Callable[[], int]] = None,
        mediation_receipt_ttl_ms: int = 86_400_000,
    ):
        self.queue = queue
        self.policy = policy or AutonomyPolicy()
        if hasattr(self.policy, "outcome_provider"):
            self.policy.outcome_provider = self._capability_outcome_stats
        self.executor = executor
        self.notifier = notifier
        self.budget = budget or InterruptBudget()
        self.delivery_broker = delivery_broker or getattr(self.budget, "delivery_broker", None)
        self.audit = audit
        self.prefs = prefs
        # O26-P0.7 (F3): the executor seam honors the global kill-switch
        # KERNEL-INDEPENDENTLY — before this, engaging the halt did not stop an
        # already-approved broker task from executing on a default install.
        self._kill_switch = kill_switch
        import time as _time

        self._clock = clock or _time.time
        # Q6: TTL for the stuck-RUNNING reaper; <=0 disables it.
        self.running_ttl_seconds = float(running_ttl_seconds)
        # Strong refs to fire-and-forget push tasks so they aren't GC'd mid-flight.
        self._bg_tasks: set = set()
        self._mediation_kernel = kernel
        self._mediation_signer = mediation_signer or DetachedHMACSigner(None)
        self._mediation_clock_ms = mediation_clock_ms or (lambda: int(time.time() * 1000))
        self._mediation_receipt_ttl_ms = int(mediation_receipt_ttl_ms)
        self._execution_context = ContextVar(
            f"autonomy_mediated_execution_{id(self)}", default=None
        )

    def bind_mediation(self, kernel, signer: DetachedHMACSigner | None) -> None:
        """Bind the existing Action Kernel and detached owner signer to this worker."""

        from ..kernel.binding import MediationKernelBridge

        if kernel is not None and not isinstance(kernel, MediationKernelBridge):
            kernel = MediationKernelBridge(kernel)
        self._mediation_kernel = kernel
        self._mediation_signer = signer or DetachedHMACSigner(None)

    def kernel_gate(self, action, capability=None, budget=None):
        """Broker-facing kernel hook that preserves the exact decision for enqueue."""

        kernel = self._mediation_kernel
        if not callable(kernel):
            raise RuntimeError("action kernel is unavailable")
        from ..kernel import Action

        origin = self._effective_origin(getattr(action, "origin", "generated"))
        payload, _tainted = self._mark_payload_for_origin(getattr(action, "payload", None), origin)
        finalized_action = Action(
            kind=action.kind,
            agent=action.agent,
            title=action.title,
            payload=payload,
            scope=action.scope,
            origin=origin,
        )
        decision = kernel(finalized_action, capability=capability, budget=budget)
        try:
            from ..kernel import Verdict

            if (
                decision.verdict is Verdict.DENY
                and self.queue.mediation_mode in {"enforce", "hold"}
                and self.queue.classify_mediation(finalized_action.kind) is not False
            ):
                self.queue.record_mediation_refusal(finalized_action.kind)
        except Exception:
            logger.warning("could not persist kernel refusal evidence", exc_info=True)
        return decision

    def execution_allowed(self, task: Task) -> bool:
        """Guard a TaskExecutor call with the worker's private validated-claim context."""

        if self.queue.mediation_mode == "off":
            return True
        persisted, mediated = self.queue.execution_snapshot(
            getattr(task, "id", 0), presented_kind=getattr(task, "kind", "")
        )
        persisted_fingerprint = (
            TaskQueue.execution_fingerprint(persisted) if persisted is not None else None
        )
        presented_fingerprint = TaskQueue.execution_fingerprint(task)
        if (
            persisted is None
            or not persisted_fingerprint
            or persisted_fingerprint != presented_fingerprint
        ):
            return False
        if not mediated:
            return True
        if self.queue.mediation_mode != "enforce":
            return False
        permit = self._execution_context.get()
        return isinstance(permit, _ExecutionPermit) and permit.consume(
            task, validate=self.queue.validate_mediated_execution
        )

    def _kernel_action(self, agent: str, kind: str, title: str, payload: dict, origin: str):
        from ..kernel import Action

        return Action(
            kind=kind,
            agent=agent,
            title=title,
            payload=payload,
            scope="global",
            origin=origin,
        )

    def _kernel_decision(self, action):
        from ..kernel import Decision, Verdict, kernel_enabled

        if not kernel_enabled() or not callable(self._mediation_kernel):
            return None
        try:
            consume = getattr(self._mediation_kernel, "consume", None)
            decision = consume(action) if callable(consume) else None
            if decision is None:
                decision = self._mediation_kernel(action)
                decision = consume(action) if callable(consume) else decision
            return self._validated_kernel_decision(decision, Decision, Verdict)
        except Exception:
            logger.warning("Action Kernel mediation failed closed", exc_info=True)
            return None

    @staticmethod
    def _validated_kernel_decision(decision, decision_type=None, verdict_type=None):
        if decision_type is None or verdict_type is None:
            from ..kernel import Decision as decision_type
            from ..kernel import Verdict as verdict_type

        if not isinstance(decision, decision_type) or decision.verdict not in {
            verdict_type.DENY,
            verdict_type.QUEUE,
            verdict_type.GRANT,
        }:
            return None
        if decision.verdict is not verdict_type.DENY and (
            isinstance(decision.tier, bool)
            or not isinstance(decision.tier, int)
            or not 0 <= decision.tier <= int(RiskTier.IRREVERSIBLE_OR_MONEY)
        ):
            return None
        return decision

    def _action_and_decision_for_enqueue(
        self, *, agent: str, kind: str, title: str, payload: dict, origin: str
    ):
        from ..kernel import kernel_enabled
        from ..kernel.binding import MediationDecisionMismatch

        kernel = self._mediation_kernel
        consume = getattr(kernel, "take_intake_evidence", None)
        try:
            if not kernel_enabled():
                if callable(consume):
                    consume(agent=agent, kind=kind, title=title, payload=payload, origin=origin)
                action = self._kernel_action(agent, kind, title, payload, origin)
                return action, None
            if callable(consume):
                pending = consume(
                    agent=agent,
                    kind=kind,
                    title=title,
                    payload=payload,
                    origin=origin,
                )
                if pending is not None:
                    action, decision = pending
                    return action, self._validated_kernel_decision(decision)
        except MediationDecisionMismatch as exc:
            self.queue.record_mediation_refusal(kind)
            raise TaskQueueError("pending kernel decision does not match finalized task") from exc
        action = self._kernel_action(agent, kind, title, payload, origin)
        try:
            if not callable(kernel):
                return action, None
            decision = kernel(action)
            if callable(consume):
                pending = consume(
                    agent=agent, kind=kind, title=title, payload=payload, origin=origin
                )
                if pending is not None:
                    taken_action, taken_decision = pending
                    return taken_action, self._validated_kernel_decision(taken_decision)
            return action, self._validated_kernel_decision(decision)
        except MediationDecisionMismatch as exc:
            self.queue.record_mediation_refusal(kind)
            raise TaskQueueError("pending kernel decision does not match finalized task") from exc
        except Exception:
            logger.warning("Action Kernel mediation failed closed", exc_info=True)
            return action, None

    @staticmethod
    def _apply_kernel_floor(kernel_decision, tier: int, effective: str) -> tuple[int, str]:
        if kernel_decision is None:
            return tier, effective
        from ..kernel import Verdict

        tier = max(tier, int(kernel_decision.tier or 0))
        if kernel_decision.verdict is Verdict.QUEUE:
            effective = ASK
        return tier, effective

    def _classified_mediated_enqueue(
        self,
        *,
        action,
        decision,
        payload: dict,
        risk_tier: int,
        autonomy_level: str,
        attention_mode: str,
    ) -> int:
        from ..kernel import Verdict

        if decision is None:
            self.queue.record_mediation_refusal(action.kind)
            raise TaskQueueError("classified task mediation authority is unavailable")
        if decision.verdict is Verdict.DENY:
            self.queue.record_mediation_refusal(action.kind)
            raise TaskQueueError(f"kernel denied classified task: {decision.reason or 'denied'}")
        now_ms = self._mediation_clock_ms()
        enqueue_id = str(uuid.uuid4())
        expectation = ReceiptExpectation(
            enqueue_id=enqueue_id,
            agent=action.agent,
            kind=action.kind,
            title=action.title,
            origin=action.origin,
            scope=action.scope,
            payload=payload,
            effective_tier=risk_tier,
            policy_revision=self.queue.mediation_policy_revision,
            enqueue_revision=1,
        )
        receipt = issue_receipt(
            self._mediation_signer,
            receipt_id=str(uuid.uuid4()),
            expectation=expectation,
            verdict=decision.verdict.value,
            tier=int(decision.tier),
            reason=str(decision.reason or ""),
            issued_at_ms=now_ms,
            expires_at_ms=now_ms + self._mediation_receipt_ttl_ms,
        )
        if receipt is None:
            self.queue.record_mediation_refusal(action.kind)
            raise TaskQueueError("classified task mediation receipt is unavailable")
        return self.queue.enqueue_mediated(
            action.agent,
            action.kind,
            action.title,
            payload,
            receipt=receipt,
            scope=action.scope,
            autonomy_level=autonomy_level,
            origin=action.origin,
            attention_mode=attention_mode,
        )

    def _persist_intake_evidence(
        self, task_id: int, action, decision, payload: dict, task_tier: int
    ) -> None:
        if action is None or decision is None:
            return
        try:
            from ..kernel import Verdict

            if decision.verdict not in {Verdict.GRANT, Verdict.QUEUE}:
                return
            evidence = issue_intake_evidence(
                self._mediation_signer,
                intake_id=str(uuid.uuid4()),
                agent=action.agent,
                kind=action.kind,
                title=action.title,
                origin=action.origin,
                payload=payload,
                verdict=decision.verdict.value,
                tier=int(decision.tier),
                task_tier=task_tier,
                issued_at_ms=self._mediation_clock_ms(),
                task_id=task_id,
            )
            if evidence is not None and self.queue.attach_kernel_intake_evidence(task_id, evidence):
                return
        except Exception:
            logger.warning("could not seal QA4 intake evidence", exc_info=True)
            return
        logger.warning("could not persist QA4 intake evidence")

    def _halted(self, scope: Optional[str] = None) -> bool:
        if self._kill_switch is None:
            try:
                from ..security.capability import KillSwitch

                self._kill_switch = KillSwitch()
            except Exception:
                return False
        try:
            if scope is None:
                return bool(self._kill_switch.is_halted())
            return bool(self._kill_switch.is_halted(scope))
        except Exception:
            return False

    def _reap_stuck(self) -> int:
        """Fail tasks stranded in RUNNING by a crash, past the TTL (Q6)."""
        ttl = float(getattr(self, "running_ttl_seconds", 0.0) or 0.0)
        if ttl <= 0:
            return 0
        try:
            reaped = self.queue.reap_stuck_running(ttl, now=self._clock())
        except Exception:
            logger.warning("stuck-running reaper failed", exc_info=True)
            return 0
        for task in reaped:
            self._audit(
                "autonomy.reaped", task, f"stuck in running > {int(ttl)}s — failed by the reaper"
            )
        return len(reaped)

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
        # This legacy caller-controlled marker has no authority and must never
        # enter a signed QA4 payload digest or a persisted task payload.
        clean_payload = dict(payload or {})
        clean_payload.pop("kernel_mediation", None)
        marked = taint.mark_if_untrusted(clean_payload, origin)
        return marked, taint.is_tainted(marked)

    def _has_valid_b7_receipt(self, task: Task) -> bool:
        """Exempt only a receipt the B7 execution boundary reauthenticates."""

        fingerprint = TaskQueue.execution_fingerprint(task)
        return bool(fingerprint) and self.queue.validate_mediated_execution(task, fingerprint)

    def _observe_qa4_intake(self, task: Task) -> None:
        """Record missing QA4 evidence, while leaving task execution unchanged."""

        if self._has_valid_b7_receipt(task):
            return
        if self.queue.validate_kernel_intake_evidence(
            task, self._mediation_signer, now_ms=self._mediation_clock_ms()
        ):
            return
        try:
            from ..kernel.metrics import KERNEL_METRICS

            KERNEL_METRICS.record_ungoverned(task.kind)
        except Exception:
            logger.warning("QA4 intake observation failed", exc_info=True)

    def _policy_action(
        self,
        agent: str,
        kind: str,
        payload: dict | None,
        origin: str,
    ) -> dict:
        """Build a policy view with server-owned identity fields authoritative."""
        action = dict(payload or {})
        action.pop("risk_tier", None)
        action["agent"] = agent
        action["kind"] = kind
        action["origin"] = origin
        return action

    @staticmethod
    def _normalize_trusted_tier(tier_floor: int | RiskTier | None) -> tuple[int | None, bool]:
        """Normalize a server-owned tier floor; invalid values fail closed."""
        if tier_floor is None:
            return None, False
        if isinstance(tier_floor, bool):
            return int(RiskTier.IRREVERSIBLE_OR_MONEY), True
        if isinstance(tier_floor, RiskTier):
            return int(tier_floor), False
        if isinstance(tier_floor, int) and 0 <= tier_floor <= int(RiskTier.IRREVERSIBLE_OR_MONEY):
            return tier_floor, False
        return int(RiskTier.IRREVERSIBLE_OR_MONEY), True

    def _policy_accepts_tier_floor(self) -> bool:
        """Detect legacy policy doubles without swallowing policy failures."""
        try:
            parameters = inspect.signature(self.policy.decide).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD or parameter.name == "tier_floor"
            for parameter in parameters
        )

    def _policy_decision(
        self,
        action: dict,
        tier_floor: int | RiskTier | None,
    ) -> tuple[object, int, bool]:
        """Call new and legacy policy interfaces without weakening a tier floor."""
        trusted_tier, invalid_tier = self._normalize_trusted_tier(tier_floor)
        if self._policy_accepts_tier_floor():
            decision = self.policy.decide(action, tier_floor=tier_floor)
        else:
            decision = self.policy.decide(action)

        try:
            decided_tier = int(decision.tier)
        except (AttributeError, TypeError, ValueError):
            return decision, int(RiskTier.IRREVERSIBLE_OR_MONEY), True
        if not 0 <= decided_tier <= int(RiskTier.IRREVERSIBLE_OR_MONEY):
            return decision, int(RiskTier.IRREVERSIBLE_OR_MONEY), True

        effective_tier = max(decided_tier, trusted_tier or 0)
        must_ask = invalid_tier or (trusted_tier is not None and decided_tier < trusted_tier)
        return decision, effective_tier, must_ask

    def _strictest_level(self, requested: str, decided: str) -> str:
        rank = self._LEVEL_RANK
        return requested if rank.get(requested, 2) >= rank.get(decided, 2) else decided

    def _force_ask_for_taint(self, level: str, tainted: bool) -> str:
        return ASK if tainted and level in (ACT, NOTIFY) else level

    def _capability_outcome_stats(self, kind: str) -> dict | None:
        """Resolve a non-spoofable policy confidence input from the durable ledger."""
        try:
            from agents.core.capability_manifests import manifest_for_action

            manifest = manifest_for_action(str(kind or ""))
            stats = getattr(self.queue, "capability_outcome_stats", None)
            if manifest is not None and callable(stats):
                return stats(manifest.id)
        except Exception:
            logger.warning("capability outcome lookup failed closed", exc_info=True)
        return None

    def govern_enqueue(
        self,
        agent: str,
        kind: str,
        title: str,
        payload: dict = None,
        risk_tier: int = 2,
        autonomy_level: str = ASK,
        origin: str = "generated",
        attention_mode: str = "interrupt",
    ) -> int:
        """Sync governed intake (drop-in for ``TaskQueue.enqueue``).

        Runs ``policy.decide`` and applies the STRICTER of the caller's
        requested level and the policy outcome (a broker's always-ask can
        never be weakened; a kernel-granted ``act`` can still be tightened
        by the policy's money caps). ``ask`` tasks land BLOCKED so they enter
        the decision inbox; the Telegram push is best-effort (scheduled when
        an event loop is running, else the card waits in the inbox).
        """
        origin = self._effective_origin(origin)
        proposed_payload = payload or {}
        payload, tainted = self._mark_payload_for_origin(proposed_payload, origin)
        classification = self.queue.classify_mediation(kind)
        mediated = self.queue.mediation_mode in {"enforce", "hold"} and classification is not False
        action = kernel_decision = None
        if mediated and (self.queue.mediation_mode != "enforce" or classification is not True):
            return self.queue.enqueue(
                agent=agent,
                kind=kind,
                title=title,
                payload=proposed_payload,
                risk_tier=risk_tier,
                autonomy_level=autonomy_level,
                origin=origin,
                attention_mode=attention_mode,
            )
        if mediated or self._mediation_kernel is not None:
            action, kernel_decision = self._action_and_decision_for_enqueue(
                agent=agent, kind=kind, title=title, payload=payload, origin=origin
            )
        try:
            decision, tier, must_ask = self._policy_decision(
                self._policy_action(agent, kind, payload, origin),
                risk_tier,
            )
        except Exception as exc:
            if mediated:
                self.queue.record_mediation_refusal(kind)
                raise TaskQueueError("classified task policy is unavailable") from exc
            raise
        effective = self._strictest_level(autonomy_level, decision.outcome)
        if must_ask:
            effective = ASK
        effective = self._force_ask_for_taint(effective, tainted)
        if mediated:
            tier, effective = self._apply_kernel_floor(kernel_decision, tier, effective)
        elif kernel_decision is not None:
            from ..kernel import Verdict

            if kernel_decision.verdict is Verdict.QUEUE:
                effective = ASK
        if mediated:
            task_id = self._classified_mediated_enqueue(
                action=action,
                decision=kernel_decision,
                payload=payload,
                risk_tier=tier,
                autonomy_level=effective,
                attention_mode=attention_mode,
            )
        else:
            task_id = self.queue.enqueue(
                agent=agent,
                kind=kind,
                title=title,
                payload=payload,
                risk_tier=tier,
                autonomy_level=effective,
                origin=origin,
                attention_mode=attention_mode,
            )
            self._persist_intake_evidence(task_id, action, kernel_decision, payload, tier)
        if effective in (ACT, NOTIFY):
            task = self.queue.transition(
                task_id,
                TaskStatus.APPROVED,
                decided_by="policy",
                decision=f"auto-{effective}",
            )
            self._audit("autonomy.auto_approve", task, decision.reason)
            return task_id
        task = self.queue.transition(
            task_id,
            TaskStatus.BLOCKED,
            decided_by="policy",
            decision="needs-approval",
        )
        try:
            import asyncio

            if attention_mode == "interrupt":
                # Keep a reference (else the task can be GC'd mid-flight) and log
                # any failure — otherwise the push exception vanishes silently.
                t = asyncio.get_running_loop().create_task(self._maybe_push(task))
                self._bg_tasks.add(t)
                t.add_done_callback(self._bg_tasks.discard)
                t.add_done_callback(
                    lambda d: (
                        logger.error(
                            "decision push failed: %s", d.exception(), exc_info=d.exception()
                        )
                        if not d.cancelled() and d.exception()
                        else None
                    )
                )
        except RuntimeError:
            logger.debug("no running loop — decision card waits in the inbox")
        return task_id

    # ── intake ────────────────────────────────────────────────────
    async def submit(
        self,
        agent: str,
        kind: str,
        title: str,
        payload: dict = None,
        origin: str = "generated",
        attention_mode: str = "interrupt",
        risk_tier: int | None = None,
    ) -> Task:
        """Propose a task, gate it through the policy, and route it."""
        origin = self._effective_origin(origin)
        proposed_payload = payload or {}
        payload, tainted = self._mark_payload_for_origin(proposed_payload, origin)
        classification = self.queue.classify_mediation(kind)
        mediated = self.queue.mediation_mode in {"enforce", "hold"} and classification is not False
        action = kernel_decision = None
        if mediated and (self.queue.mediation_mode != "enforce" or classification is not True):
            self.queue.enqueue(
                agent=agent,
                kind=kind,
                title=title,
                payload=proposed_payload,
                risk_tier=risk_tier if risk_tier is not None else 3,
                autonomy_level=ASK,
                origin=origin,
                attention_mode=attention_mode,
            )
            raise TaskQueueError("classified task mediation is unavailable")
        if mediated or self._mediation_kernel is not None:
            action, kernel_decision = self._action_and_decision_for_enqueue(
                agent=agent,
                kind=kind,
                title=title,
                payload=payload,
                origin=origin,
            )
        try:
            decision, tier, must_ask = self._policy_decision(
                self._policy_action(agent, kind, payload, origin),
                risk_tier,
            )
        except Exception as exc:
            if mediated:
                self.queue.record_mediation_refusal(kind)
                raise TaskQueueError("classified task policy is unavailable") from exc
            raise
        effective = self._force_ask_for_taint(decision.outcome, tainted)
        if must_ask:
            effective = ASK
        if mediated:
            tier, effective = self._apply_kernel_floor(kernel_decision, tier, effective)
        elif kernel_decision is not None:
            from ..kernel import Verdict

            if kernel_decision.verdict is Verdict.QUEUE:
                effective = ASK
        if mediated:
            task_id = self._classified_mediated_enqueue(
                action=action,
                decision=kernel_decision,
                payload=payload,
                risk_tier=tier,
                autonomy_level=effective,
                attention_mode=attention_mode,
            )
        else:
            task_id = self.queue.enqueue(
                agent=agent,
                kind=kind,
                title=title,
                payload=payload,
                risk_tier=tier,
                autonomy_level=effective,
                origin=origin,
                attention_mode=attention_mode,
            )
            self._persist_intake_evidence(task_id, action, kernel_decision, payload, tier)

        if effective in (ACT, NOTIFY):
            task = self.queue.transition(
                task_id,
                TaskStatus.APPROVED,
                decided_by="policy",
                decision=f"auto-{effective}",
            )
            self._audit("autonomy.auto_approve", task, decision.reason)
            return task

        # ASK → block, then push a decision card if budget allows.
        task = self.queue.transition(
            task_id,
            TaskStatus.BLOCKED,
            decided_by="policy",
            decision="needs-approval",
        )
        if attention_mode == "interrupt":
            await self._maybe_push(task)
        return task

    async def _maybe_push(self, task: Task, *, delivery_id: str | None = None) -> bool:
        if not self.notifier:
            return False
        if self.delivery_broker is None:
            logger.warning(
                "Decision push held for #%s: durable delivery broker unavailable",
                task.id,
            )
            return False
        result = await self.delivery_broker.dispatch(
            delivery_id or f"task-{task.id}",
            "decision_push",
            lambda: self.notifier(task),
        )
        ok = result.get("status") == "delivered"
        if ok:
            self.queue.mark_pushed(task.id)
            self._audit("autonomy.push_decision", task, "pushed to inbox")
        elif result.get("status") == "downgraded":
            logger.info("Interrupt budget exhausted — task #%s held for daily review", task.id)
        else:
            logger.warning("Decision push failed for #%s: %s", task.id, result.get("reason"))
        return ok

    # ── execution ─────────────────────────────────────────────────
    async def tick(self, limit: int = 10, max_tier: Optional[int] = None) -> dict:
        """Run approved tasks. Returns a small summary dict.

        `max_tier` caps which risk tiers run this pass — used by the night shift
        to batch only reversible/read-only work (max_tier=1).
        """
        ran = done = failed = held = 0
        # Q6: reap crash-stranded RUNNING tasks first — bookkeeping, not an
        # action, so it runs even under a halt (the stuck state is honest).
        reaped = 0 if self.queue.mediation_mode == "hold" else self._reap_stuck()
        # O26-P0.7 (F3): an engaged kill-switch stops execution at THIS seam,
        # kernel-independently — approved tasks stay approved (nothing is lost)
        # and run on the first tick after release.
        if self._halted():
            logger.warning("kill-switch engaged — autonomy tick skipped (tasks held)")
            return {"ran": 0, "done": 0, "failed": 0, "halted": True, "held": 0, "reaped": reaped}
        for task in self.queue.runnable(limit=limit, max_tier=max_tier):
            # Q6: a per-agent halt (scope = the agent's name, ch07 GOV-178)
            # holds that agent's tasks at this same kernel-independent seam —
            # they stay APPROVED and run on the first tick after release.
            if self._halted(task.agent):
                held += 1
                continue
            if self.queue.mediation_mode == "off":
                mediated = False
            else:
                persisted, mediated = self.queue.execution_snapshot(
                    task.id, presented_kind=task.kind
                )
                if persisted is None:
                    held += 1
                    continue
                task = persisted
            if mediated and self.queue.mediation_mode == "hold":
                held += 1
                continue
            if mediated and task.mediation_scope and self._halted(task.mediation_scope):
                held += 1
                continue
            if mediated:
                claimed = self.queue.claim_mediated(task.id, execution_id=str(uuid.uuid4()))
                if claimed is None:
                    continue
                task = claimed
            else:
                self.queue.transition(task.id, TaskStatus.RUNNING)
                task = self.queue.get(task.id)
            ran += 1
            attempts = self.queue.increment_attempts(task.id)
            # Bind the permit to the exact durable snapshot after the attempt
            # counter/update timestamp mutation and before handler dispatch.
            task = self.queue.get(task.id)
            if self.queue.mediation_mode != "off":
                persisted, still_mediated = self.queue.execution_snapshot(
                    task.id, presented_kind=task.kind
                )
                fingerprint = TaskQueue.execution_fingerprint(task)
                valid = (
                    persisted is not None
                    and still_mediated == mediated
                    and fingerprint is not None
                    and TaskQueue.execution_fingerprint(persisted) == fingerprint
                    and persisted.status == TaskStatus.RUNNING.value
                )
                if valid and mediated:
                    valid = self.queue.validate_mediated_execution(task, fingerprint)
                if not valid:
                    if mediated:
                        self.queue.transition(
                            task.id,
                            TaskStatus.FAILED,
                            result={"error": "mediation execution validation failed"},
                        )
                        failed += 1
                    else:
                        self.queue.transition(task.id, TaskStatus.APPROVED)
                        held += 1
                    continue
                task = persisted
            self._observe_qa4_intake(task)
            execution_permit = _ExecutionPermit(task) if mediated else None
            execution_token = self._execution_context.set(execution_permit)
            try:
                result = await self._execute(task)
                if result.get("status") == "refused" and result.get("reason") == (
                    "mediation_execution_context_required"
                ):
                    raise TaskQueueError("mediation execution context refused")
                self.queue.transition(task.id, TaskStatus.DONE, result=result)
                self._record_capability_outcome(task, success=True, result=result)
                self._settle_spend(task)
                self._audit("autonomy.done", task, "executed")
                done += 1
            except Exception as e:
                if mediated or attempts >= MAX_ATTEMPTS:
                    self.queue.transition(task.id, TaskStatus.FAILED, result={"error": str(e)})
                    self._record_capability_outcome(task, success=False)
                    self._audit("autonomy.failed", task, f"giving up after {attempts}: {e}")
                    failed += 1
                else:
                    # back to approved for another attempt
                    self.queue.transition(task.id, TaskStatus.APPROVED)
                    logger.info(f"Task #{task.id} failed (attempt {attempts}), will retry: {e}")
            finally:
                if execution_permit is not None:
                    execution_permit.revoke()
                self._execution_context.reset(execution_token)
        return {"ran": ran, "done": done, "failed": failed, "held": held, "reaped": reaped}

    async def _execute(self, task: Task) -> dict:
        if self.executor is None:
            # No executor wired → no-op success so the loop is observable.
            return {"status": "noop", "note": "no executor configured"}
        if self.queue.mediation_mode == "off":
            return await self.executor(task)
        dispatch_task = TaskQueue.detach_execution_task(task)
        if dispatch_task is None:
            raise TaskQueueError("could not snapshot execution task")
        return await self.executor(dispatch_task)

    def _settle_spend(self, task: Task) -> None:
        amount = task.payload.get("amount") if task.payload else None
        if amount:
            try:
                self.policy.record_spend(float(amount))
            except (TypeError, ValueError):
                pass

    def _record_capability_outcome(
        self,
        task: Task,
        *,
        success: bool,
        result: dict | None = None,
    ) -> None:
        """Record one terminal REAL execution; ignore no-ops, mocks and unknown actions.

        ADV-094 (adversarial audit 2026-07-25): this skipped only a literal
        ``status == "noop"``, while ``is_degraded()`` — which recognises the ``_mock`` /
        ``_degraded`` markers every mock-falling-back plugin stamps on its return — had
        zero production callers. So a capability that returned a MOCK recorded a success,
        and ``GET /api/capabilities`` showed ``success_rate: 1.0`` and rising confidence
        for capabilities that had never delivered anything.

        Grade it as the audit did, and the correction matters: this is a misleading
        dashboard, NOT a live loosening of governance. The claimed autonomy escalation
        does not occur — every degraded seam hardcodes ``autonomy_level = "ask"`` and
        ``govern_enqueue`` takes the stricter of the two — so a rising score could not
        widen what an agent may do. It could only mislead the human reading the board.
        """
        if success and isinstance(result, dict):
            if result.get("status") == "noop":
                return
            from agents.core.plugins.degradation import is_degraded

            if is_degraded(result):
                logger.debug("capability outcome skipped: degraded/mock result for %s", task.kind)
                return
        try:
            from agents.core.capability_manifests import manifest_for_action

            manifest = manifest_for_action(task.kind)
            record = getattr(self.queue, "record_capability_outcome", None)
            if manifest is not None and callable(record):
                record(manifest.id, success=success)
        except Exception:
            logger.warning("capability outcome record failed", exc_info=True)

    # ── human decisions ───────────────────────────────────────────
    async def apply_decision(
        self, task_id: int, action: str, decided_by: str = "user", payload: dict = None
    ) -> Task:
        """Resolve a blocked task from an inbox tap (accept/edit/reject/defer)."""
        current = self.queue.get(task_id)
        if (
            action == "edit"
            and payload is not None
            and current is not None
            and self.queue.mediation_mode in {"enforce", "hold"}
            and self.queue.classify_mediation(current.kind) is not False
        ):
            raise TaskQueueError("mediated edit requires a new enqueue revision")
        if action == "accept":
            task = self.queue.transition(
                task_id, TaskStatus.APPROVED, decided_by=decided_by, decision="accept"
            )
        elif action == "edit":
            if payload is not None:
                edited = self.queue.get(task_id)
                edited_origin = self._effective_origin(edited.origin)
                marked_payload, tainted = self._mark_payload_for_origin(
                    payload,
                    edited_origin,
                )
                # BUG-11: an edit must not be auto-approved under the *original*
                # (lower-risk) decision. Re-gate the FULL edited payload — not
                # just the amount — so changing kind/target/reversible/risk_tier
                # (e.g. READ_ONLY → an irreversible kind), or an amount under the
                # per-action cap but over the remaining daily ceiling, is caught.
                action_payload = self._policy_action(
                    edited.agent,
                    edited.kind,
                    marked_payload,
                    edited_origin,
                )
                decision, tier, must_ask = self._policy_decision(
                    action_payload,
                    edited.risk_tier,
                )
                effective = self._force_ask_for_taint(decision.outcome, tainted)
                effective = self._strictest_level(edited.autonomy_level, effective)
                if must_ask:
                    effective = ASK
                edited = self.queue.update_payload_policy(
                    task_id,
                    marked_payload,
                    risk_tier=tier,
                    autonomy_level=effective,
                )
                if effective == ASK:
                    # Edited payload still needs explicit approval — keep the task
                    # in its current BLOCKED state (no transition: BLOCKED→BLOCKED
                    # is illegal) and re-push a fresh decision card to the inbox.
                    logger.warning(
                        "apply_decision: edited payload on task %s still requires "
                        "approval (%s) — kept blocked, re-pushed for re-approval",
                        task_id,
                        decision.reason,
                    )
                    await self._maybe_push(
                        edited,
                        delivery_id=f"task-{edited.id}-edit-{edited.updated_at}",
                    )
                    self._audit(
                        "autonomy.decision.edit", edited, f"by {decided_by} (re-gated, blocked)"
                    )
                    if self.prefs:
                        try:
                            self.prefs.record(edited, action, decided_by=decided_by)
                        except Exception as e:
                            logger.warning(f"Preference record failed for #{task_id}: {e}")
                    return edited
            task = self.queue.transition(
                task_id, TaskStatus.APPROVED, decided_by=decided_by, decision="edit"
            )
        elif action == "reject":
            task = self.queue.transition(
                task_id, TaskStatus.REJECTED, decided_by=decided_by, decision="reject"
            )
        elif action == "defer":
            task = self.queue.transition(
                task_id, TaskStatus.DEFERRED, decided_by=decided_by, decision="defer"
            )
        else:
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
            self.audit.log(
                event,
                {"task_id": task.id, "agent": task.agent, "kind": task.kind, "detail": detail},
            )
        except Exception:
            logger.warning(
                "Autonomy audit log failed for event '%s' task #%s", event, task.id, exc_info=True
            )
