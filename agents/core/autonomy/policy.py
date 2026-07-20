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
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class RiskTier(IntEnum):
    """Action risk tiers, ordered by severity."""
    READ_ONLY = 0              # read/list/search/summarize — no side effects
    REVERSIBLE = 1             # draft/create-local/organize — easily undone
    EXTERNAL = 2               # reaches third parties (send/post/message)
    IRREVERSIBLE_OR_MONEY = 3  # pay/transfer/delete/deploy/book — hard to undo


def _normalize_tier_floor(
    value: RiskTier | int | None,
) -> tuple[RiskTier | None, bool]:
    """Normalize a trusted tier floor; malformed values fail closed to tier 3."""

    if value is None:
        return None, False
    if isinstance(value, bool):
        return RiskTier.IRREVERSIBLE_OR_MONEY, True
    if isinstance(value, RiskTier):
        return value, False
    if isinstance(value, int) and 0 <= value <= 3:
        return RiskTier(value), False
    return RiskTier.IRREVERSIBLE_OR_MONEY, True


class Outcome(str):
    """Marker base for decision outcomes (kept as plain strings for JSON)."""


# Decision outcomes
ACT = "act"        # execute autonomously, log it
NOTIFY = "notify"  # execute but inform the user (non-urgent)
ASK = "ask"        # block and request human approval

EARNED_MIN_SAMPLES = 20
EARNED_MIN_CONFIDENCE = 0.80


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
    # Per-agent mode overrides (HUD v3 per-agent AUTO/ASK/OFF). An agent listed here
    # uses its own mode; everyone else uses the global ``mode``. Empty by default ⇒
    # every agent behaves exactly as the global mode (zero behavior change).
    agent_modes: dict = field(default_factory=dict)
    # Money guardrails (same currency as the action's `amount`).
    cap_per_action: float = 50.0
    daily_ceiling: float = 200.0
    # H27.7: default-off, evidence-gated one-rung reduction. This never changes
    # the classified risk tier and never applies to IRREVERSIBLE_OR_MONEY.
    earned_autonomy_enabled: bool = False
    outcome_provider: Callable[[str], dict] | None = field(
        default=None, repr=False, compare=False,
    )
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
        kind_value = action["kind"] if "kind" in action else action.get("name", "")
        kind = str(kind_value or "").lower()
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
        # H21.4: calibration-gated autonomy. Optional hook (set by the orchestrator,
        # gated by cognition.learning_enabled) returns a tier *bump* (≥0, never
        # lowers gating). Default: no hook → unchanged behavior.
        hook = getattr(self, "calibration_hook", None)
        if hook is not None and tier < RiskTier.IRREVERSIBLE_OR_MONEY:
            try:
                bump = int(hook(action))
            except Exception:
                bump = 0
            if bump > 0:
                tier = RiskTier(min(int(RiskTier.IRREVERSIBLE_OR_MONEY), int(tier) + bump))
        return tier

    # ── decision ──────────────────────────────────────────────────
    def effective_mode(self, agent: str | None = None) -> str:
        """The mode that applies to *agent* — its per-agent override, else the global
        ``mode``. ``agent=None`` (or an agent with no override) ⇒ the global mode."""
        override = self.agent_modes.get(agent) if agent else None
        return str(override or self.mode).lower()

    def decide(
        self,
        action: dict,
        *,
        tier_floor: RiskTier | int | None = None,
    ) -> Decision:
        classified_tier = self.classify(action)
        normalized_floor, invalid_floor = _normalize_tier_floor(tier_floor)
        tier = max(classified_tier, normalized_floor or RiskTier.READ_ONLY)
        # Mode gate (HUD AUTO/ASK/OFF), resolved per-agent: an agent with its own
        # override uses it; everyone else uses the global mode. OFF makes everything
        # wait; ASK makes everything with a side-effect wait (pure READ_ONLY still
        # auto-acts). AUTO falls through to the balanced per-tier logic below.
        mode = self.effective_mode(action.get("agent"))
        if mode == "off":
            return Decision(ASK, tier, "autonomy mode=off → ask", urgent=False)
        if mode == "ask" and tier != RiskTier.READ_ONLY:
            return Decision(ASK, tier, "autonomy mode=ask → ask", urgent=False)
        if invalid_floor:
            return Decision(ASK, tier, "invalid trusted tier floor → ask", urgent=False)
        # Money special-case: auto-act if within per-action cap AND daily budget.
        amount = _num(action.get("amount"))
        if tier == RiskTier.IRREVERSIBLE_OR_MONEY and amount > 0:
            with self._spend_lock:
                spent_today = self._spent_today
            if amount <= self.cap_per_action and (spent_today + amount) <= self.daily_ceiling:
                return Decision(ACT, tier, f"within caps (≤{self.cap_per_action}, daily ok)")
            return Decision(ASK, tier, f"exceeds cap {self.cap_per_action} or daily ceiling", urgent=True)

        outcome = self.tier_outcomes.get(tier, ASK)
        outcome, earned_reason = self._apply_earned_autonomy(outcome, tier, action)
        urgent = outcome == ASK and _num(action.get("time_sensitivity")) >= 0.7
        reason = earned_reason or f"tier={tier.name} → {outcome}"
        return Decision(outcome, tier, reason, urgent=urgent)

    def _apply_earned_autonomy(
        self, outcome: str, tier: RiskTier, action: dict,
    ) -> tuple[str, str | None]:
        """Lower ASK/NOTIFY by one rung only after conservative outcome proof."""
        if not self.earned_autonomy_enabled or tier == RiskTier.IRREVERSIBLE_OR_MONEY:
            return outcome, None
        if not callable(self.outcome_provider):
            return outcome, None
        try:
            stats = self.outcome_provider(str(action.get("kind") or action.get("name") or ""))
        except Exception:
            return outcome, None
        if not isinstance(stats, dict):
            return outcome, None
        try:
            samples = int(stats.get("total", 0))
            confidence = float(stats.get("confidence", 0.0))
        except (TypeError, ValueError):
            return outcome, None
        if samples < EARNED_MIN_SAMPLES or confidence < EARNED_MIN_CONFIDENCE:
            return outcome, None
        lowered = {ASK: NOTIFY, NOTIFY: ACT}.get(outcome, outcome)
        if lowered == outcome:
            return outcome, None
        return lowered, (
            f"earned autonomy: tier={tier.name} {outcome}→{lowered} "
            f"(n={samples}, confidence={confidence:.3f})"
        )

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
