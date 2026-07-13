"""
desktop_operator.py — H15.3 Governed desktop operator (isolated desktop).

The desktop analog of the H15.1 browser agent: operates an *isolated* virtual
desktop (PiP, no ambient credentials) under governance —

  * read-only steps (screenshot/read/wait/locate) run inline;
  * mutating/irreversible steps (click/type/exec/delete/…) require approval;
  * an **injection classifier** scans on-screen text so a hostile UI can't steer
    the agent (reuses the H17.1 quarantine detector).

The desktop driver is injectable (``NullDesktopDriver`` offline; a real VM driver
is the host seam), so the whole governance layer is offline-testable.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Mapping
from typing import Any

from .automation_contracts import ContractTemplate, predicate
from .capability_actions import CapabilityActionAPI, PerformContext, PerformResult

logger = logging.getLogger("jarvis.desktop_operator")

_MAX_DESKTOP_STEPS = 100
_MAX_ACTION_CHARS = 64
_MAX_ARG_CHARS = 512
_MAX_TYPE_CHARS = 20_000
_MAX_OBSERVATION_ELEMENTS = 200
_MAX_OBSERVATION_TEXT = 20_000
_APP_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_DESKTOP_ARG_RULES = {
    "observe": (frozenset(), frozenset()),
    "screenshot": (frozenset(), frozenset()),
    "read": (frozenset({"query"}), frozenset({"query"})),
    "locate": (frozenset({"query"}), frozenset({"query"})),
    "click": (frozenset({"name"}), frozenset({"name"})),
    "type": (frozenset({"name", "text"}), frozenset({"name", "text"})),
    "launch": (frozenset({"app"}), frozenset({"app"})),
}

try:
    from .security.quarantine import detect_injection as _detect_injection
except Exception:  # pragma: no cover - security module always present
    def _detect_injection(text):
        return False

# Everything NOT explicitly read-only is treated as mutating (safe default).
_READ_ONLY = {"screenshot", "read", "wait", "locate", "observe"}


def _desktop_step_contract_template() -> ContractTemplate:
    return ContractTemplate(
        kind="desktop_step",
        description="Mutating desktop steps must be explicit desktop actions held for approval.",
        constraints=(
            predicate(
                "desktop-kind",
                lambda view, _now: str(view.get("kind") or "").startswith("desktop."),
                reason="invalid_kind",
            ),
            predicate(
                "has-action",
                lambda view, _now: bool(str(view.get("action") or "").strip()),
                reason="no_action",
            ),
            predicate(
                "target-desktop",
                lambda view, _now: view.get("target") == "desktop",
                reason="target_mismatch",
            ),
            predicate(
                "mutating-only",
                lambda view, _now: view.get("mutating") is True,
                reason="not_mutating",
            ),
        ),
        requires_approval=True,
    )


DESKTOP_STEP_CONTRACT = _desktop_step_contract_template()


class DesktopProposalError(ValueError):
    """Bounded denial for a desktop proposal that cannot be persisted safely."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def validate_desktop_run_args(raw: Mapping[str, Any]) -> dict[str, list[dict]]:
    """Validate and normalize the complete ToolRPC/route desktop proposal."""
    if not isinstance(raw, Mapping):
        raise DesktopProposalError("invalid_args")
    if set(raw) != {"steps"}:
        raise DesktopProposalError("unexpected_args")
    steps = raw.get("steps")
    if not isinstance(steps, list):
        raise DesktopProposalError("invalid_steps")
    if len(steps) > _MAX_DESKTOP_STEPS:
        raise DesktopProposalError("too_many_steps")

    sanitized = []
    for step in steps:
        if not isinstance(step, Mapping) or not set(step).issubset({"action", "args"}):
            raise DesktopProposalError("invalid_step")
        raw_action = step.get("action")
        if not isinstance(raw_action, str):
            raise DesktopProposalError("invalid_action")
        if len(raw_action) > _MAX_ACTION_CHARS:
            raise DesktopProposalError("invalid_action")
        action = raw_action.strip().lower()
        if not action:
            raise DesktopProposalError("invalid_action")
        rule = _DESKTOP_ARG_RULES.get(action)
        if rule is None:
            raise DesktopProposalError("unsupported_action")
        raw_args = step.get("args", {})
        if not isinstance(raw_args, Mapping):
            raise DesktopProposalError("invalid_args")
        required, allowed = rule
        keys = set(raw_args)
        if not all(isinstance(key, str) for key in keys):
            raise DesktopProposalError("unexpected_action_args")
        if keys - allowed:
            raise DesktopProposalError("unexpected_action_args")
        if required - keys:
            raise DesktopProposalError("missing_argument")

        args = {}
        for key in allowed:
            if key not in raw_args:
                continue
            value = raw_args[key]
            if not isinstance(value, str):
                raise DesktopProposalError("invalid_argument")
            if key == "text":
                if len(value) > _MAX_TYPE_CHARS:
                    raise DesktopProposalError("argument_too_large")
                args[key] = value
                continue
            if len(value) > _MAX_ARG_CHARS:
                raise DesktopProposalError("argument_too_large")
            value = value.strip()
            if not value:
                raise DesktopProposalError("invalid_argument")
            if key == "app":
                value = value.lower()
                if not _APP_KEY_RE.fullmatch(value):
                    raise DesktopProposalError("invalid_app_key")
            args[key] = value
        sanitized.append({"action": action, "args": args})
    return {"steps": sanitized}


async def _maybe_await(v):
    import inspect
    return await v if inspect.isawaitable(v) else v


class NullDesktopDriver:
    """Offline default — records actions, performs no real desktop I/O."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def perform(self, action: str, args: dict) -> dict:
        self.calls.append({"action": action, "args": args})
        return {"status": "deferred", "action": action,
                "note": "no desktop driver — host seam"}


class DesktopActionExecutor:
    """Kernel-mediated execution boundary for optional real desktop drivers."""

    def __init__(self, driver, *, authorizer) -> None:
        if not callable(getattr(driver, "perform", None)):
            raise TypeError("desktop driver must expose perform")
        self.driver = driver
        self.api = CapabilityActionAPI(authorizer=authorizer)
        self.api.register("action:desktop.step", self._execute)

    async def _execute(self, step: dict[str, Any], _context: PerformContext) -> Any:
        action = step.get("action")
        args = step.get("args")
        if not isinstance(action, str) or not action.strip():
            return {"ok": False, "reason": "invalid_action"}
        if not isinstance(args, Mapping):
            return {"ok": False, "reason": "invalid_args"}
        return await _maybe_await(self.driver.perform(action, dict(args)))

    async def perform(
        self,
        step: Mapping[str, Any],
        context: PerformContext | None = None,
    ) -> PerformResult:
        action = step.get("action") if isinstance(step, Mapping) else None
        args = step.get("args") if isinstance(step, Mapping) else None
        normalized = {
            "action": action.strip().lower() if isinstance(action, str) else action,
            "args": dict(args) if isinstance(args, Mapping) else args,
            "risk_tier": (
                1
                if isinstance(action, str) and action.strip().lower() in _READ_ONLY
                else 2
            ),
        }
        return await self.api.perform("action:desktop.step", normalized, context)


class GovernedDesktop:
    def __init__(self, driver=None, *, action_executor=None) -> None:
        self._driver = driver or NullDesktopDriver()
        self._action_executor = action_executor

    @staticmethod
    def is_mutating(action: Any) -> bool:
        return not isinstance(action, str) or action.lower() not in _READ_ONLY

    def classify_injection(self, screenshot_text: str) -> bool:
        return bool(_detect_injection(screenshot_text or ""))

    @staticmethod
    def _observation_text(elements: list) -> str:
        """Derive classifier input only from bounded live accessibility data."""
        chunks = []
        remaining = _MAX_OBSERVATION_TEXT
        for element in elements[:_MAX_OBSERVATION_ELEMENTS]:
            if not isinstance(element, Mapping):
                continue
            values = []
            for key in ("name", "role", "text", "value", "automation_id"):
                value = element.get(key)
                if isinstance(value, str) and value:
                    values.append(value[:_MAX_ARG_CHARS])
            chunk = " ".join(values)
            if not chunk:
                continue
            chunks.append(chunk[:remaining])
            remaining -= len(chunks[-1])
            if remaining <= 0:
                break
        return "\n".join(chunks)[:_MAX_OBSERVATION_TEXT]

    async def run_live(self, steps: "list[dict]", *, approver=None) -> dict:
        """Classify a fresh accessibility observation before any requested step."""
        if getattr(self._driver, "requires_kernel", False):
            if self._action_executor is None:
                return {"ok": False, "reason": "kernel_required", "ran": []}
            try:
                outcome = await self._action_executor.perform(
                    {"action": "observe", "args": {}}
                )
            except Exception:
                logger.warning("desktop live observation failed")
                return {"ok": False, "reason": "observation_failed", "ran": []}
            if not isinstance(outcome, PerformResult) or outcome.status != "completed":
                reason = outcome.reason if isinstance(outcome, PerformResult) else ""
                return {
                    "ok": False,
                    "reason": reason or "observation_failed",
                    "ran": [],
                }
            observation = outcome.output
        else:
            try:
                observation = await _maybe_await(self._driver.perform("observe", {}))
            except Exception:
                logger.warning("desktop live observation failed")
                return {"ok": False, "reason": "observation_failed", "ran": []}
        if (
            not isinstance(observation, Mapping)
            or observation.get("ok") is not True
            or not isinstance(observation.get("elements"), list)
        ):
            reason = observation.get("reason") if isinstance(observation, Mapping) else None
            return {
                "ok": False,
                "reason": reason if isinstance(reason, str) and reason else "invalid_observation",
                "ran": [],
            }
        if self.classify_injection(self._observation_text(observation["elements"])):
            return {"ok": False, "reason": "injection_detected", "ran": []}
        return await self.run(steps, approver=approver)

    async def close(self) -> None:
        closer = getattr(self._driver, "close", None)
        if callable(closer):
            try:
                await _maybe_await(closer())
            except Exception:
                logger.warning("desktop driver close failed")

    async def preview(self, steps: "list[dict]") -> dict:
        out = []
        for s in steps or []:
            action = s.get("action", "")
            mut = self.is_mutating(action)
            out.append({"action": action, "mutating": mut,
                        "requires_approval": mut, "would_run": not mut})
        return {"steps": out}

    async def run(self, steps: "list[dict]", screenshot_text: str = "", approver=None) -> dict:
        """Run gated. Mutating steps need `approver(action, args)->bool`; an
        injection-classified screen aborts before anything runs."""
        if screenshot_text and self.classify_injection(screenshot_text):
            return {"ok": False, "reason": "injection_detected", "ran": []}
        ran = []
        for s in steps or []:
            action = s.get("action", "")
            args = s.get("args", {})
            if not isinstance(action, str) or not action.strip():
                ran.append({
                    "action": action,
                    "status": "failed",
                    "reason": "invalid_action",
                })
                continue
            if self.is_mutating(action):
                contract_payload = {
                    "kind": f"desktop.{action}",
                    "action": action,
                    "target": "desktop",
                    "mutating": True,
                    "args_keys": sorted(str(k) for k in args) if isinstance(args, dict) else [],
                }
                try:
                    decision = DESKTOP_STEP_CONTRACT.evaluate(contract_payload, now=time.time())
                except Exception:
                    logger.warning("desktop step contract evaluation failed", exc_info=True)
                    ran.append({"action": action, "status": "blocked", "reason": "contract_error"})
                    continue
                if not decision.admissible:
                    ran.append({
                        "action": action,
                        "status": "blocked",
                        "reason": decision.reason or "contract_denied",
                    })
                    continue
                approved = False
                if approver is not None:
                    try:
                        approved = bool(await _maybe_await(approver(action, args)))
                    except Exception:
                        approved = False
                if not approved:
                    ran.append({"action": action, "status": "blocked", "reason": "approval_required"})
                    continue
            if getattr(self._driver, "requires_kernel", False):
                if self._action_executor is None:
                    ran.append({
                        "action": action,
                        "status": "blocked",
                        "reason": "kernel_required",
                    })
                    continue
                try:
                    outcome = await self._action_executor.perform({"action": action, "args": args})
                except Exception:
                    logger.warning("desktop action executor failed")
                    ran.append({
                        "action": action,
                        "status": "failed",
                        "reason": "kernel_error",
                    })
                    continue
                if not isinstance(outcome, PerformResult):
                    ran.append({
                        "action": action,
                        "status": "failed",
                        "reason": "kernel_error",
                    })
                    continue
                if outcome.status != "completed":
                    if outcome.status == "queued":
                        status = "queued"
                        fallback_reason = "approval_required"
                    elif outcome.status == "failed":
                        status = "failed"
                        fallback_reason = "kernel_error"
                    elif outcome.status in {"disabled", "refused"}:
                        status = "blocked"
                        fallback_reason = "kernel_refused"
                    else:
                        status = "failed"
                        fallback_reason = "kernel_error"
                    ran.append({
                        "action": action,
                        "status": status,
                        "reason": outcome.reason or fallback_reason,
                    })
                    continue
                res = outcome.output
                if not isinstance(res, Mapping) or res.get("ok") is not True:
                    reason = res.get("reason") if isinstance(res, Mapping) else None
                    if not isinstance(reason, str) or not reason:
                        reason = "invalid_result"
                    ran.append({
                        "action": action,
                        "status": "failed",
                        "reason": reason,
                    })
                    continue
            else:
                res = await self._driver.perform(action, args)
            ran.append({"action": action, "status": "ran", "result": res})
        return {"ok": all(item.get("status") == "ran" for item in ran), "ran": ran}
