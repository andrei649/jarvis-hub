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
from .flags import kernel_enabled

# NOTE: autonomy.policy / autonomy.dry_run are imported lazily inside authorize()
# — importing them at module top would pull the whole autonomy package (observer,
# watchers, …) during a broker→kernel import and risk a cycle. security.capability
# and flags are broker-free, so they're safe at top.

__all__ = [
    "Verdict", "Action", "Capability", "Budget", "Decision",
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
    """Best-effort audit of every decision — never blocks the gate."""
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
              now: float | None = None) -> Decision:
    """Mediate a privileged *action*. Composes the existing nucleus + policy + audit.

    Order (mirrors the design diagram): kill-switch + capability → policy → (budget,
    inert in K1) → audit (always). Returns ``Decision ∈ grant | deny | queue``.
    """
    from ..autonomy.dry_run import preview_task
    from ..autonomy.policy import ACT, NOTIFY

    capability = capability or Capability()
    budget = budget or Budget()

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

    # 2) Policy — the single risk-classification + outcome evaluation for this action.
    pdec = policy.decide({"kind": action.kind, **(action.payload or {})})
    tier = int(pdec.tier)
    if pdec.outcome in (ACT, NOTIFY):
        decision = Decision(Verdict.GRANT, reason=pdec.reason, tier=tier)
    else:  # ASK (or anything unexpected) → queue for approval
        card = preview_task({"kind": action.kind, "title": action.title,
                             "payload": action.payload, "risk_tier": tier})
        decision = Decision(Verdict.QUEUE, reason=pdec.reason, tier=tier, card=card)

    # 3) Budget — inert in K1 (no new limits); threaded for K3.
    # 4) Audit — always.
    _emit_audit(audit, action, decision)
    return decision
