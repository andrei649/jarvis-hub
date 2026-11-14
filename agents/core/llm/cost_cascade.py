"""Governed Cost- & SLA-Aware Adaptive Model Cascade (`cost_cascade.py`).

Routes turns local-first based on prompt complexity and local draft confidence,
escalating to a cloud model **only** when needed and strictly permitted by every
Nerva governance and budget gate:

1. ``JARVIS_STRICT_LOCAL`` process kill-switch
2. Agent privacy floor (``LOCAL_ONLY_AGENTS`` and ``POLICY_LOCAL``)
3. Agent model allowlist (``approved_models`` / ``ModelNotApprovedError``)
4. H513 configuration-bound data-handling consent (``data_handling.authorize``)
5. Vendor-verified pricing + pre-flight per-turn & per-session USD budget caps
   (``cost_estimator.estimate_cost``, honoring ADV-078 ``priced`` fail-closed)
6. Per-tier SLA wall-clock timeout bounds (``asyncio.wait_for``)

Whenever cloud escalation is disallowed, unconsented, over-budget, or times out,
the cascade degrades gracefully to local synthesis (`$0.00` marginal cloud spend,
`0` leaked cloud tokens, `0` USD cap overruns) instead of failing the turn or
silently overspending.
"""

from __future__ import annotations

import asyncio
import collections
import math
import threading
import time
from dataclasses import dataclass
from typing import Any

from agents.core.env_config import env_flag

from .base import LLMBackend, is_backend_failure_reply
from .cost_estimator import estimate_cost
from .data_handling import DataHandlingRefused, authorize
from .hybrid_router import (
    LOCAL_ONLY_AGENTS,
    POLICY_LOCAL,
    LocalBackendUnavailableError,
    is_heavy_request,
)
from .moe_routing import decide_thinking_mode
from .tokenizer import estimate_tokens

MAX_RECENT_CASCADE_RUNS = 100
_CASCADE_LOCK = threading.RLock()
_RECENT_CASCADE_RUNS: collections.deque[dict[str, Any]] = collections.deque(
    maxlen=MAX_RECENT_CASCADE_RUNS
)

_UNCERTAINTY_MARKERS: tuple[str, ...] = (
    "[needs_escalation]",
    "[low_confidence]",
    "insufficient local context",
    "cannot verify without cloud",
    "i am uncertain",
    "i don't have enough confidence",
    "unable to determine with certainty",
)

_BUDGET_REASONS = frozenset({"turn_usd_cap_exceeded", "session_usd_cap_exceeded", "unpriced_cloud_model"})
_GOVERNANCE_REASONS = frozenset(
    {
        "strict_local_env",
        "strict_local_agent",
        "model_not_approved",
        "h513_data_handling_refused",
        "h513_unacknowledged_policy",
        "cloud_unavailable_or_disabled",
    }
)


class CascadeConfigError(ValueError):
    """Invalid adaptive cascade policy or budget configuration."""


def _require_non_negative_finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CascadeConfigError(f"{name} must be numeric")
    fval = float(value)
    if not math.isfinite(fval) or fval < 0.0:
        raise CascadeConfigError(f"{name} must be a finite non-negative number")
    return fval


def _require_positive_finite(name: str, value: float) -> float:
    fval = _require_non_negative_finite(name, value)
    if fval <= 0.0:
        raise CascadeConfigError(f"{name} must be > 0")
    return fval


@dataclass(frozen=True)
class CascadePolicy:
    """Immutable cost, confidence, SLA, and privacy policy for an adaptive cascade."""

    max_turn_usd: float = 0.05
    max_session_usd: float = 0.25
    min_local_confidence: float = 0.72
    local_context_limit_tokens: int = 8_000
    local_sla_timeout_s: float = 15.0
    cloud_sla_timeout_s: float = 20.0
    require_h513_consent: bool = True
    allow_unpriced_cloud: bool = False

    def __post_init__(self) -> None:
        _require_non_negative_finite("max_turn_usd", self.max_turn_usd)
        _require_non_negative_finite("max_session_usd", self.max_session_usd)
        conf = _require_non_negative_finite("min_local_confidence", self.min_local_confidence)
        if conf > 1.0:
            raise CascadeConfigError("min_local_confidence must be between 0.0 and 1.0")
        if isinstance(self.local_context_limit_tokens, bool) or self.local_context_limit_tokens < 64:
            raise CascadeConfigError("local_context_limit_tokens must be >= 64")
        _require_positive_finite("local_sla_timeout_s", self.local_sla_timeout_s)
        _require_positive_finite("cloud_sla_timeout_s", self.cloud_sla_timeout_s)


@dataclass(frozen=True)
class CascadeTurnResult:
    """Structured outcome of a single cascade-routed turn."""

    text: str
    tier_used: str
    model_used: str
    route_used: str
    complexity: str
    local_confidence: float
    escalated_to_cloud: bool
    degraded_gracefully: bool
    block_reason: str | None
    usd_cost: float
    worst_case_reserved_usd: float
    session_spent_usd: float
    input_tokens: int
    output_tokens: int
    latency_ms: float

    def to_metadata(self) -> dict[str, Any]:
        """Return prompt/answer-free telemetry dictionary."""
        return {
            "tier_used": self.tier_used,
            "model_used": self.model_used,
            "route_used": self.route_used,
            "complexity": self.complexity,
            "local_confidence": round(self.local_confidence, 4),
            "escalated_to_cloud": self.escalated_to_cloud,
            "degraded_gracefully": self.degraded_gracefully,
            "block_reason": self.block_reason,
            "usd_cost": round(self.usd_cost, 10),
            "worst_case_reserved_usd": round(self.worst_case_reserved_usd, 10),
            "session_spent_usd": round(self.session_spent_usd, 10),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": round(self.latency_ms, 2),
        }


class CascadeSessionBudget:
    """Thread-safe cumulative USD budget tracker with atomic pre-flight reservation."""

    def __init__(self, max_session_usd: float, *, session_id: str = "default") -> None:
        self.session_id = (session_id or "default").strip() or "default"
        self.max_session_usd = _require_non_negative_finite("max_session_usd", max_session_usd)
        self._lock = threading.RLock()
        self._spent_usd = 0.0
        self._reserved_usd = 0.0
        self.turn_count = 0
        self.cloud_escalations = 0
        self.local_completions = 0
        self.budget_blocks = 0
        self.policy_blocks = 0

    @property
    def spent_usd(self) -> float:
        with self._lock:
            return round(self._spent_usd, 10)

    def try_reserve(self, worst_case_usd: float, *, max_turn_usd: float) -> tuple[bool, str | None]:
        """Atomically reserve *worst_case_usd* if both turn and session caps allow it."""
        amount = _require_non_negative_finite("worst_case_usd", worst_case_usd)
        turn_cap = _require_non_negative_finite("max_turn_usd", max_turn_usd)
        with self._lock:
            if amount > turn_cap + 1e-12:
                self.budget_blocks += 1
                return False, "turn_usd_cap_exceeded"
            if self._spent_usd + self._reserved_usd + amount > self.max_session_usd + 1e-12:
                self.budget_blocks += 1
                return False, "session_usd_cap_exceeded"
            self._reserved_usd = round(self._reserved_usd + amount, 10)
            return True, None

    def settle_cloud(self, reserved_usd: float, actual_usd: float) -> float:
        """Release pre-flight reservation and commit actual billed cloud USD."""
        actual = _require_non_negative_finite("actual_usd", actual_usd)
        with self._lock:
            self._reserved_usd = max(0.0, round(self._reserved_usd - reserved_usd, 10))
            self._spent_usd = round(self._spent_usd + actual, 10)
            self.turn_count += 1
            self.cloud_escalations += 1
            return self._spent_usd

    def release_reservation(self, reserved_usd: float) -> None:
        """Release a pre-flight reservation when a cloud call fails or times out."""
        with self._lock:
            self._reserved_usd = max(0.0, round(self._reserved_usd - reserved_usd, 10))

    def record_local_turn(self, *, block_reason: str | None = None) -> float:
        """Record a $0.00 local completion (and policy block counter if applicable)."""
        with self._lock:
            self.turn_count += 1
            self.local_completions += 1
            if block_reason in _GOVERNANCE_REASONS:
                self.policy_blocks += 1
            return round(self._spent_usd, 10)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            spent = round(self._spent_usd, 10)
            reserved = round(self._reserved_usd, 10)
            return {
                "session_id": self.session_id,
                "max_session_usd": self.max_session_usd,
                "spent_usd": spent,
                "reserved_usd": reserved,
                "remaining_usd": max(0.0, round(self.max_session_usd - spent - reserved, 10)),
                "turn_count": self.turn_count,
                "cloud_escalations": self.cloud_escalations,
                "local_completions": self.local_completions,
                "budget_blocks": self.budget_blocks,
                "policy_blocks": self.policy_blocks,
            }


def recent_cascade_runs() -> list[dict[str, Any]]:
    with _CASCADE_LOCK:
        return list(_RECENT_CASCADE_RUNS)


def clear_cascade_runs() -> None:
    with _CASCADE_LOCK:
        _RECENT_CASCADE_RUNS.clear()


def assess_prompt_complexity(
    prompt: str,
    *,
    local_context_limit: int = 8_000,
) -> dict[str, Any]:
    """Classify a prompt into ``fast``, ``deep``, or ``frontier`` local-first tiers."""
    tokens = estimate_tokens(prompt or "")
    if tokens > local_context_limit:
        return {"tier": "frontier", "input_tokens": tokens, "needs_deep": True}
    heavy = is_heavy_request(prompt or "") or decide_thinking_mode(prompt or "")
    return {
        "tier": "deep" if heavy else "fast",
        "input_tokens": tokens,
        "needs_deep": heavy,
    }


def assess_local_confidence(reply: str, prompt: str = "") -> float:
    """Deterministically score confidence (`0.0..1.0`) of a local model draft."""
    cleaned = (reply or "").strip()
    if not cleaned or is_backend_failure_reply(cleaned):
        return 0.0
    low = cleaned.lower()
    if any(marker in low for marker in _UNCERTAINTY_MARKERS):
        return 0.35
    if cleaned.count("```") % 2 == 1:
        return 0.45
    if len(prompt or "") > 120 and len(cleaned) < 12:
        return 0.50
    return 0.92


def _truncate_to_token_budget(text: str, max_tokens_budget: int) -> str:
    """Deterministically trim oversized prompts to fit local fallback context."""
    if estimate_tokens(text) <= max_tokens_budget:
        return text
    char_limit = max(256, max_tokens_budget * 3)
    return text[:char_limit] + "\n\n[Truncated to local context budget]"


def _build_local_refinement_prompt(prompt: str, draft: str | None) -> str:
    draft_section = f"\n\n## Initial Local Draft\n{draft}" if draft else ""
    return (
        "Synthesize and verify a complete answer using strictly local reasoning. "
        "Resolve any uncertainty concisely and state clear conclusions.\n\n"
        f"## Request\n{prompt}{draft_section}\n\n"
        "## Verified Local Synthesis"
    )


def _check_h513_consent(
    router: Any,
    cloud_backend: LLMBackend,
    cloud_model: str,
    cloud_route: str,
    *,
    principal: Any = None,
    require_ack: bool = True,
) -> tuple[bool, str | None]:
    """Verify H513 data-handling authorization before any cloud escalation."""
    try:
        custom_auth = getattr(cloud_backend, "authorize_data_handling", None)
        if callable(custom_auth):
            res = custom_auth(actual_use=True)
        else:
            res = authorize(
                router,
                cloud_backend,
                cloud_model,
                cloud_route,
                principal=principal,
                actual_use=True,
            )
    except (DataHandlingRefused, PermissionError, ValueError):
        return False, "h513_data_handling_refused"

    if require_ack and isinstance(res, dict) and res.get("warning") and not res.get("acknowledged"):
        return False, "h513_unacknowledged_policy"
    return True, None


class AdaptiveCostCascade(LLMBackend):
    """Governed local-first -> optional cloud LLM cascade with hard USD & H513 gates."""

    def __init__(
        self,
        *,
        router: Any,
        agent_id: str = "jarvis",
        policy: CascadePolicy | None = None,
        session_budget: CascadeSessionBudget | None = None,
        cloud_binding: tuple[LLMBackend, str, str] | None = None,
        approved_models_override: tuple[str, ...] | None = None,
    ) -> None:
        self._router = router
        self._agent_id = (agent_id or "jarvis").strip() or "jarvis"
        self.policy = policy or CascadePolicy()
        self.session_budget = session_budget or CascadeSessionBudget(self.policy.max_session_usd)
        self._cloud_binding = cloud_binding
        self._approved_override = approved_models_override
        self._backend = getattr(router, "_backend", None)
        self.last_turn_result: CascadeTurnResult | None = None

    def _resolve_local_slot(self, *, prefer_deep: bool) -> tuple[LLMBackend, str, str]:
        backend = getattr(self._router, "_backend", None)
        if not getattr(self._router, "_local_available", False) or backend is None:
            raise LocalBackendUnavailableError(
                f"Local backend unavailable for cascade agent '{self._agent_id}'"
            )
        if prefer_deep and getattr(self._router, "_deep_model_available", lambda: False)():
            deep_model = self._router._configured_deep_model()
            if self._is_model_approved_for_agent(deep_model):
                return backend, deep_model, "local-deep"
        fast_model = getattr(self._router, "_local_model", "local")
        if not self._is_model_approved_for_agent(fast_model):
            raise PermissionError(
                f"Local model '{fast_model}' is not in approved_models for '{self._agent_id}'"
            )
        return backend, fast_model, "local"

    def _resolve_cloud_slot(self) -> tuple[LLMBackend | None, str, str]:
        if self._cloud_binding is not None:
            return self._cloud_binding
        if getattr(self._router, "_claude_available", False) and getattr(
            self._router, "_claude_backend", None
        ) is not None:
            return self._router._claude_backend, self._router._claude_model, "claude"
        if getattr(self._router, "_compatible_backend", None) is not None:
            return (
                self._router._compatible_backend,
                getattr(self._router, "_compatible_model", ""),
                "cloud-compatible",
            )
        if getattr(self._router, "_cloud_available", False) and getattr(
            self._router, "_gemini_backend", None
        ) is not None:
            return self._router._gemini_backend, self._router._gemini_model, "cloud"
        return None, "", ""

    def _is_model_approved_for_agent(self, model: str) -> bool:
        if self._approved_override is not None:
            return len(self._approved_override) == 0 or model in self._approved_override
        checker = getattr(self._router, "is_model_approved", None)
        return True if not callable(checker) else bool(checker(self._agent_id, model))

    def _evaluate_cloud_gate(
        self,
        *,
        input_tokens: int,
        max_tokens: int,
        principal: Any = None,
    ) -> tuple[bool, str | None, tuple[LLMBackend | None, str, str], float]:
        """Check strict-local, approved_models, H513 consent, pricing, and USD caps."""
        if env_flag("JARVIS_STRICT_LOCAL", False):
            return False, "strict_local_env", (None, "", ""), 0.0
        agent_policy = getattr(self._router, "get_agent_policy", lambda _a: "auto")(self._agent_id)
        if self._agent_id in LOCAL_ONLY_AGENTS or agent_policy == POLICY_LOCAL:
            return False, "strict_local_agent", (None, "", ""), 0.0

        cloud_backend, cloud_model, cloud_route = self._resolve_cloud_slot()
        fallback_mode = getattr(self._router, "_cloud_fallback_mode", "on-demand")
        if cloud_backend is None or not cloud_model or fallback_mode == "never":
            return False, "cloud_unavailable_or_disabled", (None, "", ""), 0.0

        if not self._is_model_approved_for_agent(cloud_model):
            return False, "model_not_approved", (cloud_backend, cloud_model, cloud_route), 0.0

        consent_ok, consent_reason = _check_h513_consent(
            self._router,
            cloud_backend,
            cloud_model,
            cloud_route,
            principal=principal,
            require_ack=self.policy.require_h513_consent,
        )
        if not consent_ok:
            return False, consent_reason, (cloud_backend, cloud_model, cloud_route), 0.0

        est = estimate_cost(cloud_model, input_tokens, max_tokens)
        if not est["priced"] and not self.policy.allow_unpriced_cloud:
            self.session_budget.budget_blocks += 1
            return False, "unpriced_cloud_model", (cloud_backend, cloud_model, cloud_route), 0.0

        reserved_ok, cap_reason = self.session_budget.try_reserve(
            est["total"], max_turn_usd=self.policy.max_turn_usd
        )
        if not reserved_ok:
            return False, cap_reason, (cloud_backend, cloud_model, cloud_route), 0.0
        return True, None, (cloud_backend, cloud_model, cloud_route), float(est["total"])

    async def _call_bounded(
        self,
        backend: LLMBackend,
        model: str,
        prompt: str,
        *,
        system: str,
        max_tokens: int,
        temperature: float,
        timeout_s: float,
    ) -> tuple[str | None, str | None]:
        try:
            reply = await asyncio.wait_for(
                backend.generate(
                    model,
                    prompt,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ),
                timeout=timeout_s,
            )
        except TimeoutError:
            return None, "sla_timeout"
        except Exception as exc:
            return None, type(exc).__name__
        if not reply or not reply.strip() or is_backend_failure_reply(reply):
            return None, "degraded_or_empty"
        return reply, None

    async def _synthesize_locally_on_fallback(
        self,
        prompt: str,
        *,
        system: str,
        max_tokens: int,
        temperature: float,
        existing_draft: str | None,
    ) -> tuple[str, str, str]:
        """Produce a grounded $0.00 local response when cloud escalation is blocked or fails.

        Runs exactly one bounded local synthesis pass (deep slot when available and
        approved, otherwise the approved fast slot) over the request and any
        low-confidence draft, so an uncertain draft is never returned verbatim when a
        refinement succeeds. Falls back to the draft only if that pass fails.
        """
        local_backend, deep_model, deep_route = self._resolve_local_slot(prefer_deep=True)
        bounded_prompt = _truncate_to_token_budget(prompt, self.policy.local_context_limit_tokens)
        synth_prompt = _build_local_refinement_prompt(bounded_prompt, existing_draft)
        refined, err = await self._call_bounded(
            local_backend,
            deep_model,
            synth_prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_s=self.policy.local_sla_timeout_s,
        )
        if refined is not None:
            return refined, deep_model, deep_route
        if existing_draft:
            return existing_draft, deep_model, deep_route
        raise LocalBackendUnavailableError(
            f"Graceful local fallback failed for '{self._agent_id}': {err or 'unavailable'}"
        )

    def _record_result(self, result: CascadeTurnResult) -> CascadeTurnResult:
        self.last_turn_result = result
        entry = {"ts": round(time.time(), 3), "agent": self._agent_id, **result.to_metadata()}
        with _CASCADE_LOCK:
            _RECENT_CASCADE_RUNS.appendleft(entry)
        return result

    async def execute_turn(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.4,
        principal: Any = None,
    ) -> CascadeTurnResult:
        """Run local-first adaptive cascade with governed cloud escalation and local fallback."""
        t0 = time.perf_counter()
        comp = assess_prompt_complexity(
            prompt, local_context_limit=self.policy.local_context_limit_tokens
        )
        in_tokens = comp["input_tokens"] + estimate_tokens(system or "")
        local_draft: str | None = None
        local_conf = 0.0
        used_deep = False

        if comp["tier"] != "frontier":
            loc_backend, loc_model, loc_route = self._resolve_local_slot(
                prefer_deep=bool(comp["needs_deep"])
            )
            used_deep = loc_route == "local-deep"
            local_draft, _loc_err = await self._call_bounded(
                loc_backend,
                loc_model,
                prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_s=self.policy.local_sla_timeout_s,
            )
            local_conf = assess_local_confidence(local_draft or "", prompt)
            if local_draft is not None and local_conf >= self.policy.min_local_confidence:
                spent = self.session_budget.record_local_turn()
                return self._record_result(
                    CascadeTurnResult(
                        text=local_draft,
                        tier_used="local_deep" if used_deep else "local_fast",
                        model_used=loc_model,
                        route_used=loc_route,
                        complexity=comp["tier"],
                        local_confidence=local_conf,
                        escalated_to_cloud=False,
                        degraded_gracefully=False,
                        block_reason=None,
                        usd_cost=0.0,
                        worst_case_reserved_usd=0.0,
                        session_spent_usd=spent,
                        input_tokens=in_tokens,
                        output_tokens=estimate_tokens(local_draft),
                        latency_ms=(time.perf_counter() - t0) * 1000.0,
                    )
                )

        allowed, block_reason, cloud_slot, reserved_usd = self._evaluate_cloud_gate(
            input_tokens=in_tokens, max_tokens=max_tokens, principal=principal
        )
        if allowed and cloud_slot[0] is not None:
            c_backend, c_model, c_route = cloud_slot
            cloud_reply, cloud_err = await self._call_bounded(
                c_backend,
                c_model,
                prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_s=self.policy.cloud_sla_timeout_s,
            )
            if cloud_reply is not None:
                out_tokens = estimate_tokens(cloud_reply)
                actual_usd = float(estimate_cost(c_model, in_tokens, out_tokens)["total"])
                spent = self.session_budget.settle_cloud(reserved_usd, actual_usd)
                return self._record_result(
                    CascadeTurnResult(
                        text=cloud_reply,
                        tier_used="cloud_escalated",
                        model_used=c_model,
                        route_used=c_route,
                        complexity=comp["tier"],
                        local_confidence=local_conf,
                        escalated_to_cloud=True,
                        degraded_gracefully=False,
                        block_reason=None,
                        usd_cost=actual_usd,
                        worst_case_reserved_usd=reserved_usd,
                        session_spent_usd=spent,
                        input_tokens=in_tokens,
                        output_tokens=out_tokens,
                        latency_ms=(time.perf_counter() - t0) * 1000.0,
                    )
                )
            self.session_budget.release_reservation(reserved_usd)
            block_reason = f"cloud_{cloud_err or 'failed'}"

        fb_text, fb_model, fb_route = await self._synthesize_locally_on_fallback(
            prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            existing_draft=local_draft,
        )
        spent = self.session_budget.record_local_turn(block_reason=block_reason)
        return self._record_result(
            CascadeTurnResult(
                text=fb_text,
                tier_used="local_fallback_synthesis",
                model_used=fb_model,
                route_used=fb_route,
                complexity=comp["tier"],
                local_confidence=local_conf,
                escalated_to_cloud=False,
                degraded_gracefully=True,
                block_reason=block_reason,
                usd_cost=0.0,
                worst_case_reserved_usd=reserved_usd if allowed else 0.0,
                session_spent_usd=spent,
                input_tokens=in_tokens,
                output_tokens=estimate_tokens(fb_text),
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )
        )

    async def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.4,
        **kwargs: Any,
    ) -> str:
        principal = kwargs.get("principal")
        res = await self.execute_turn(
            prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            principal=principal,
        )
        return res.text

    async def is_available(self) -> bool:
        return bool(getattr(self._router, "_local_available", False))

    async def list_models(self) -> list[str]:
        return ["cascade:auto"]

    def context_window(self, model: str | None = None) -> int:
        return self.policy.local_context_limit_tokens
