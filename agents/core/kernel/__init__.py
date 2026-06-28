"""kernel — ORIZONT-24 Track K · the Action Kernel (K1 facade).

One mediated front door so **every** privileged agent action passes through
``authorize(action, capability, budget) -> Decision`` (``grant | deny | queue``).

**Compose, don't replace.** This facade calls the *existing* primitives — it does
not reimplement them:
  * KillSwitch + CapabilityBroker → the ``security.capability.authorize`` nucleus.
  * risk classification → ``autonomy.policy.AutonomyPolicy.decide``.
  * approval card → ``autonomy.dry_run.preview_task`` (the shape brokers build today).
  * audit → an ``IntentLog``-style sink (``.record(actor, action, why, metadata)``).

A ``QUEUE`` decision reuses today's ``TaskQueue`` (the broker still enqueues);
the kernel only decides grant/deny/queue. Default-OFF behind ``JARVIS_ACTION_KERNEL``
(see ``flags.kernel_enabled``); K2/K3/K4 deepen capabilities/budgets/syscalls.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from enum import StrEnum

from ..security.capability import authorize as _capability_authorize
from ..security.taint import is_tainted, is_untrusted_source
from .budget import BudgetLedger, BudgetLimits, LoopDetector
from .flags import kernel_enabled
from .metrics import KERNEL_METRICS

# NOTE: autonomy.policy / autonomy.dry_run are imported lazily inside authorize()
# — importing them at module top would pull the whole autonomy package (observer,
# watchers, …) during a broker→kernel import and risk a cycle. security.capability
# and flags are broker-free, so they're safe at top.

__all__ = [
    "Verdict", "Action", "Capability", "Budget", "Decision",
    "BudgetLimits", "BudgetLedger", "LoopDetector",
    "authorize", "kernel_enabled",
]


class Verdict(StrEnum):
    """The three outcomes of a mediation decision."""
    GRANT = "grant"   # execute now
    DENY = "deny"     # refused (carries a reason)
    QUEUE = "queue"   # routed to the approval queue (an interrupt-budgeted card)


@dataclass(frozen=True)
class Action:
    """A privileged action presented for mediation."""
    kind: str                              # broker KIND, e.g. "call.outbound"
    agent: str = "jarvis"
    title: str = ""
    payload: dict = field(default_factory=dict)
    scope: str = "global"                  # kill-switch scope (node uses "node:<id>")
    origin: str = "generated"


@dataclass(frozen=True)
class Capability:
    """The capability a caller presents. K1 tolerates an empty token (brokers do
    not yet carry one); K2 makes a valid token mandatory for privileged actions."""
    token_id: str = ""
    name: str = ""


@dataclass(frozen=True)
class Budget:
    """Carried on every action. **Inert in K1** — money caps already live in the
    policy and the interrupt budget is checked by the broker; K3 gives this teeth
    (per-task token/wall-time/recursion + a loop-wide circuit breaker)."""
    amount: float = 0.0
    interrupt_remaining: int | None = None


@dataclass(frozen=True)
class Decision:
    """``grant | deny(reason) | queue(card)``."""
    verdict: Verdict
    reason: str = ""
    tier: int | None = None
    card: dict | None = None
    task_id: int | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.GRANT


def _emit_audit(audit, action: Action, decision: Decision) -> None:
    """Best-effort audit of every decision — never blocks the gate.

    This is the universal exit for *every* decision, so it's also where the in-process
    metrics meter tallies (grant/deny/queue per kind), independent of whether a durable
    ``audit`` sink is wired. Both are best-effort: observability must never break the gate.
    """
    with contextlib.suppress(Exception):  # observability tally — never blocks the gate
        KERNEL_METRICS.record(action.kind, decision.verdict.value, decision.reason)
    if audit is None:
        return
    # best-effort: an audit hiccup must never block authorization
    with contextlib.suppress(Exception):  # pragma: no cover
        audit.record(
            actor="kernel",
            action=f"authorize:{action.kind}",
            why=f"{decision.verdict.value}:{decision.reason}" if decision.reason
            else decision.verdict.value,
            metadata={"verdict": decision.verdict.value, "tier": decision.tier,
                      "scope": action.scope, "agent": action.agent},
        )


def authorize(action: Action,
              capability: Capability | None = None,
              budget: Budget | None = None,
              *,
              kill_switch=None,
              capabilities=None,
              policy,
              audit=None,
              budget_ledger: BudgetLedger | None = None,
              loop_detector: LoopDetector | None = None,
              now: float | None = None) -> Decision:
    """Mediate a privileged *action*. Composes the existing nucleus + policy + audit.

    Order (mirrors the design diagram): kill-switch + capability → budget/loop
    scheduler (K3) → policy → audit (always). Returns ``Decision ∈ grant | deny | queue``.

    The K3 scheduler is **inert unless** a ``budget_ledger`` and/or ``loop_detector`` is
    supplied: a runaway loop (breaker tripped) or an over-budget task (token/time/depth)
    is denied *before* policy work, audited. K1 brokers pass neither, so behavior is
    unchanged for them.
    """
    from ..autonomy.dry_run import preview_task
    from ..autonomy.policy import ACT, NOTIFY

    capability = capability or Capability()
    # `budget` is accepted but inert in K1 (money caps live in the policy, the
    # interrupt budget is checked by the broker); K3 gives it teeth. Intentionally
    # not normalized/read here.

    # 1) Kill-switch + capability — via the existing nucleus when a token is
    #    presented (node mesh), else kill-switch only (K1 brokers carry no token;
    #    K2 flips the empty-token case to DENY — tracked in PENDING_KERNEL).
    if capability.token_id and capabilities is not None:
        gate = _capability_authorize(
            capabilities, kill_switch, capability.token_id, capability.name,
            scope=action.scope, now=now,
        )
        if not gate.get("allowed"):
            decision = Decision(Verdict.DENY, reason=gate.get("reason", "denied"))
            _emit_audit(audit, action, decision)
            return decision
    elif kill_switch is not None and kill_switch.is_halted(action.scope):
        decision = Decision(Verdict.DENY,
                            reason=f"kill-switch engaged for scope '{action.scope}'")
        _emit_audit(audit, action, decision)
        return decision

    # 2) Budget + loop circuit breaker (K3, folds H23.1). Inert unless supplied — a
    #    runaway loop or an over-budget task is halted at the front door before any work.
    if loop_detector is not None and not loop_detector.record(action.kind, now):
        decision = Decision(Verdict.DENY, reason="loop circuit breaker tripped (runaway)")
        _emit_audit(audit, action, decision)
        return decision
    if budget_ledger is not None:
        over = budget_ledger.exceeded(now)
        if over:
            decision = Decision(Verdict.DENY, reason=f"budget: {over}")
            _emit_audit(audit, action, decision)
            return decision

    # 3) Policy — the single risk-classification + outcome evaluation for this action.
    pdec = policy.decide({"kind": action.kind, "agent": action.agent, **(action.payload or {})})
    tier = int(pdec.tier)
    if pdec.outcome in (ACT, NOTIFY):
        decision = Decision(Verdict.GRANT, reason=pdec.reason, tier=tier)
    else:  # ASK (or anything unexpected) → queue for approval
        card = preview_task({"kind": action.kind, "title": action.title,
                             "payload": action.payload, "risk_tier": tier})
        decision = Decision(Verdict.QUEUE, reason=pdec.reason, tier=tier, card=card)

    # 3b) Taint (H23.6 / CDX-7) — an action carrying content from an untrusted source
    #     can't auto-execute; escalate a GRANT to approval (indirect-injection guard).
    #     Two signals: a tainted *payload* (marked by an upstream producer, e.g. osint),
    #     OR a declared untrusted *origin* (e.g. an external HTTP write → origin="external",
    #     an inbound channel, a web/rss/worldview feed). The default origin "generated"
    #     (an in-house action) is trusted, so normal actions are unaffected. Origin is the
    #     honest provenance signal: taint can't be propagated *through* an LLM (it launders
    #     content), so the kernel trusts the caller's declared origin rather than guessing.
    if decision.verdict is Verdict.GRANT and (
            is_tainted(action.payload) or is_untrusted_source(action.origin)):
        why = "tainted payload" if is_tainted(action.payload) else f"untrusted origin '{action.origin}'"
        card = preview_task({"kind": action.kind, "title": action.title,
                             "payload": action.payload, "risk_tier": tier})
        decision = Decision(Verdict.QUEUE, reason=f"tainted-source escalation ({why}); {pdec.reason}",
                            tier=tier, card=card)

    # 4) Audit — always.
    _emit_audit(audit, action, decision)
    return decision
