"""
policy.py — Risk Gate & Autonomy Dial (H6.3).

Classifies a proposed action into a risk tier and decides whether Jarvis may
act autonomously, merely notify, or must ask for approval.

Default policy is BALANCED (the user's choice): act autonomously on
reversible/safe actions (research, drafting, organizing), require approval for
irreversible or money-spending actions.

Research basis: reversibility is the #1 factor; score also on blast radius,
signal quality and time sensitivity; money gets a per-action cap + daily
ceiling. See docs/research/2026-05-31-autonomous-proactive-agents.md.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class RiskTier(IntEnum):
    """Action risk tiers, ordered by severity."""
    READ_ONLY = 0              # read/list/search/summarize — no side effects
    REVERSIBLE = 1             # draft/create-local/organize — easily undone
    EXTERNAL = 2               # reaches third parties (send/post/message)
    IRREVERSIBLE_OR_MONEY = 3  # pay/transfer/delete/deploy/book — hard to undo


class Outcome(str):
    """Marker base for decision outcomes (kept as plain strings for JSON)."""


# Decision outcomes
ACT = "act"        # execute autonomously, log it
NOTIFY = "notify"  # execute but inform the user (non-urgent)
ASK = "ask"        # block and request human approval


# Keyword → tier classification. First match wins, highest tier first so that
# e.g. "send_payment" is money, not merely external.
_MONEY_OR_IRREVERSIBLE = (
    "pay", "payment", "purchase", "buy", "transfer", "invoice", "checkout",
    "delete", "remove", "destroy", "drop", "wipe", "deploy", "release",
    "cancel", "unsubscribe", "book", "sign", "submit_order", "withdraw",
)
_EXTERNAL = (
    "send", "post", "publish", "message", "reply", "email", "tweet", "dm",
    "notify_contact", "share", "invite", "call", "sms",
)
_REVERSIBLE = (
    "draft", "create_draft", "organize", "label", "tag", "save", "note",
    "plan", "schedule_local", "rename", "move", "categorize", "prepare",
)
_READ_ONLY = (
    "read", "list", "get", "search", "fetch", "summarize", "research",
    "analyze", "status", "check", "monitor", "scan", "lookup", "review",
)


@dataclass
class Decision:
    outcome: str            # ACT / NOTIFY / ASK
    tier: RiskTier
    reason: str
    urgent: bool = False    # whether an ASK should push immediately

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome,
            "tier": int(self.tier),
            "tier_name": self.tier.name,
            "reason": self.reason,
            "urgent": self.urgent,
        }


@dataclass
class AutonomyPolicy:
    """Balanced-by-default autonomy policy."""

    # Global autonomy mode (HUD AUTO/ASK/OFF):
    #   "auto" — balanced default (per-tier outcomes below).
    #   "ask"  — anything with a side-effect waits for approval (pure reads still act).
    #   "off"  — nothing auto-executes (every decision → ASK); the proactive loop is
    #            also paused upstream (orchestrator skips the observe pass).
    mode: str = "auto"
    # Money guardrails (same currency as the action's `amount`).
    cap_per_action: float = 50.0
    daily_ceiling: float = 200.0
    # Per-tier default outcome (balanced).
    tier_outcomes: dict = field(default_factory=lambda: {
        RiskTier.READ_ONLY: ACT,
        RiskTier.REVERSIBLE: ACT,
        RiskTier.EXTERNAL: NOTIFY,
        RiskTier.IRREVERSIBLE_OR_MONEY: ASK,
    })
    _spent_today: float = 0.0
    # BUG-12: guard the read-modify-write on `_spent_today` so concurrent
    # `record_spend` calls (and the daily-ceiling read in `decide`) can't lose
    # an increment. Excluded from repr/eq/hash — it's internal mutable state.
    _spend_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    # ── classification ────────────────────────────────────────────
    def classify(self, action: dict) -> RiskTier:
        """Map an action dict → RiskTier.

        `action` may carry an explicit `risk_tier` (int/str/RiskTier), an
        `amount` (money), a `reversible` flag, and scoring factors
        (`blast_radius`, `signal_quality`, `time_sensitivity` in [0,1]).
        Otherwise the `kind`/`name` keyword decides.
        """
        tier = self._base_tier(action)
        tier = self._apply_scoring(tier, action)
        return tier

    def _base_tier(self, action: dict) -> RiskTier:
        explicit = action.get("risk_tier")
        if explicit is not None:
            return _coerce_tier(explicit)
        # Money always escalates to the top tier.
        amount = action.get("amount") or 0
        try:
            if float(amount) > 0:
                return RiskTier.IRREVERSIBLE_OR_MONEY
        except (TypeError, ValueError):
            pass
        kind = str(action.get("kind") or action.get("name") or "").lower()
        # Token-based, verb-first: the leading verb decides (so "draft_email" is
        # reversible, not external). Avoids substring traps like "widget"→"get".
        for token in re.split(r"[^a-z0-9]+", kind):
            if not token:
                continue
            tier = _tier_for_token(token)
            if tier is not None:
                return tier
        # Unknown action → conservative default: ask.
        return RiskTier.IRREVERSIBLE_OR_MONEY

    def _apply_scoring(self, tier: RiskTier, action: dict) -> RiskTier:
        """Optionally bump the tier upward based on 4 risk factors."""
        # Explicit irreversibility forces at least EXTERNAL.
        if action.get("reversible") is False and tier < RiskTier.EXTERNAL:
            tier = RiskTier.EXTERNAL
        # Large blast radius bumps one tier.
        if _num(action.get("blast_radius")) >= 0.7 and tier < RiskTier.IRREVERSIBLE_OR_MONEY:
            tier = RiskTier(tier + 1)
        # Low signal quality (high uncertainty) bumps one tier → prefer asking.
        sig = action.get("signal_quality")
        if sig is not None and _num(sig) < 0.3 and tier < RiskTier.IRREVERSIBLE_OR_MONEY:
            tier = RiskTier(tier + 1)
        return tier

    # ── decision ──────────────────────────────────────────────────
    def decide(self, action: dict) -> Decision:
        tier = self.classify(action)
        # Global mode gate (HUD AUTO/ASK/OFF). OFF makes everything wait; ASK makes
        # everything with a side-effect wait (pure READ_ONLY still auto-acts). AUTO
        # falls through to the balanced per-tier logic below.
        if self.mode == "off":
            return Decision(ASK, tier, "autonomy mode=off → ask", urgent=False)
        if self.mode == "ask" and tier != RiskTier.READ_ONLY:
            return Decision(ASK, tier, "autonomy mode=ask → ask", urgent=False)
        # Money special-case: auto-act if within per-action cap AND daily budget.
        amount = _num(action.get("amount"))
        if tier == RiskTier.IRREVERSIBLE_OR_MONEY and amount > 0:
            with self._spend_lock:
                spent_today = self._spent_today
            if amount <= self.cap_per_action and (spent_today + amount) <= self.daily_ceiling:
                return Decision(ACT, tier, f"within caps (≤{self.cap_per_action}, daily ok)")
            return Decision(ASK, tier, f"exceeds cap {self.cap_per_action} or daily ceiling", urgent=True)

        outcome = self.tier_outcomes.get(tier, ASK)
        urgent = outcome == ASK and _num(action.get("time_sensitivity")) >= 0.7
        reason = f"tier={tier.name} → {outcome}"
        return Decision(outcome, tier, reason, urgent=urgent)

    def record_spend(self, amount: float) -> None:
        # Atomic read-modify-write so concurrent callers can't lose increments.
        with self._spend_lock:
            self._spent_today += max(0.0, _num(amount))

    def reset_daily(self) -> None:
        with self._spend_lock:
            self._spent_today = 0.0


# Risk sets in priority order (highest tier first) for token classification.
_TIER_SETS = (
    (RiskTier.IRREVERSIBLE_OR_MONEY, _MONEY_OR_IRREVERSIBLE),
    (RiskTier.EXTERNAL, _EXTERNAL),
    (RiskTier.REVERSIBLE, _REVERSIBLE),
    (RiskTier.READ_ONLY, _READ_ONLY),
)


# ── helpers ───────────────────────────────────────────────────────
def _tier_for_token(token: str) -> Optional[RiskTier]:
    """Classify a single verb token, checking higher-risk sets first."""
    for tier, keywords in _TIER_SETS:
        for kw in keywords:
            if token == kw or token.startswith(kw):
                return tier
    return None


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _coerce_tier(value) -> RiskTier:
    if isinstance(value, RiskTier):
        return value
    if isinstance(value, int):
        return RiskTier(max(0, min(3, value)))
    name = str(value).strip().upper()
    aliases = {
        "READ_ONLY": RiskTier.READ_ONLY, "READONLY": RiskTier.READ_ONLY,
        "REVERSIBLE": RiskTier.REVERSIBLE, "SAFE": RiskTier.REVERSIBLE,
        "EXTERNAL": RiskTier.EXTERNAL,
        "IRREVERSIBLE_OR_MONEY": RiskTier.IRREVERSIBLE_OR_MONEY,
        "IRREVERSIBLE": RiskTier.IRREVERSIBLE_OR_MONEY, "MONEY": RiskTier.IRREVERSIBLE_OR_MONEY,
    }
    return aliases.get(name, RiskTier.IRREVERSIBLE_OR_MONEY)
