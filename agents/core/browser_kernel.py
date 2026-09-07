"""browser_kernel.py — the Action Kernel gate for a governed browser step.

The browser agent has always had two gates: an egress allowlist that navigation
cannot escape, and an approval queue that mutating steps must pass. What it never
had is the third one every other privileged surface crosses — `desktop.step`,
`terminal.exec`, `file.write` all reach `kernel.authorize` before they touch a
driver, and a browser click did not. That gap matters more than it looks:

* the **kill switch** is honoured by the kernel, so a halted install could still
  have had an already-approved browser plan click through;
* **taint escalation** lives in the kernel — a plan assembled from a web page the
  agent just read is exactly the case that must be forced back to ASK, and the
  browser agent's own approval object has no idea where the plan came from;
* the **policy floor** (money caps, daily ceilings) is applied by the kernel, and
  a browser is the easiest way to spend money without touching the payments kind.

So this module adds `browser.step`, in the same shape as `desktop.step`: one
`CapabilityActionAPI` binding, consulted immediately before the driver call, on
the same `action`/`args` payload the driver will receive — not a summary of it,
because a gate that authorises a summary authorises the wrong thing.

Two orderings are deliberate and tested:

* **The kernel is asked before the approval card is created.** A DENY refuses the
  step outright and the owner is never shown a decision they cannot safely make.
  Asking the queue first would train the owner to approve things the kernel then
  refuses, which teaches them their approvals do not mean anything.
* **A kernel GRANT does not replace the approval.** For a mutating step both
  gates hold: the kernel says the action may be attempted at all, the queue says
  this particular one is wanted. Collapsing them would make a GRANT a blanket
  licence to click anything for the rest of the session.

The executor owns no policy of its own. The allowlist, SSRF filter and pinned
transport stay in `browser_agent` and `browser_transport`, where they already are.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Mapping
from typing import Any

from agents.core.automation_contracts import ContractTemplate, predicate
from agents.core.capability_actions import CapabilityActionAPI, PerformContext, PerformResult

logger = logging.getLogger("jarvis.browser.kernel")

KIND = "browser.step"
CAPABILITY = "action:browser.step"

# Bounds on what reaches the kernel and the driver. A selector or a URL is the
# only thing an attacker controls here, so both are capped before either sees them.
MAX_ACTION_CHARS = 32
MAX_ARG_CHARS = 2_000
MAX_ARGS = 20


def _browser_step_contract_template() -> ContractTemplate:
    return ContractTemplate(
        kind="browser_step",
        description="Mutating browser steps must be explicit browser actions held for approval.",
        constraints=(
            predicate(
                "browser-kind",
                lambda view, _now: str(view.get("kind") or "").startswith("browser."),
                reason="invalid_kind",
            ),
            predicate(
                "has-action",
                lambda view, _now: bool(str(view.get("action") or "").strip()),
                reason="no_action",
            ),
            predicate(
                "target-browser",
                lambda view, _now: view.get("target") == "browser",
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


BROWSER_STEP_CONTRACT = _browser_step_contract_template()


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def normalize_step(step: Mapping[str, Any] | Any) -> dict[str, Any]:
    """The payload the kernel is asked about — the same one the driver receives.

    Bounded, lower-cased and stripped of anything that is not a plain value. A
    kernel asked about a trimmed summary while the driver is handed the full
    thing is a gate on a different action than the one that happens.
    """
    if not isinstance(step, Mapping):
        return {"action": "", "args": {}, "risk_tier": 2}
    action = step.get("action")
    action = action.strip().lower()[:MAX_ACTION_CHARS] if isinstance(action, str) else ""
    args: dict[str, Any] = {}
    for key, value in list(step.items())[: MAX_ARGS + 1]:
        if key in {"action", "risk_tier"}:
            continue
        if isinstance(value, str):
            args[str(key)[:MAX_ACTION_CHARS]] = value[:MAX_ARG_CHARS]
        elif isinstance(value, (int, float, bool)) or value is None:
            args[str(key)[:MAX_ACTION_CHARS]] = value
        if len(args) >= MAX_ARGS:
            break
    return {"action": action, "args": args, "risk_tier": 2}


class BrowserActionExecutor:
    """Kernel-mediated execution boundary for a real browser driver.

    Mirrors :class:`agents.core.desktop_operator.DesktopActionExecutor` on
    purpose: two surfaces that mean "one governed step on the owner's machine"
    should not be two different shapes, or a reviewer has to learn both to check
    either.
    """

    def __init__(self, driver, *, authorizer) -> None:
        self.driver = driver
        self.api = CapabilityActionAPI(authorizer=authorizer)
        self.api.register(CAPABILITY, self._execute)

    async def _execute(self, step: dict[str, Any], _context: PerformContext) -> Any:
        action = step.get("action")
        args = step.get("args")
        if not isinstance(action, str) or not action.strip():
            return {"ok": False, "reason": "invalid_action"}
        if not isinstance(args, Mapping):
            return {"ok": False, "reason": "invalid_args"}
        handler = getattr(self.driver, action, None)
        if not callable(handler):
            # An action the driver does not implement is refused by name rather
            # than reaching __getattr__ on a permissive driver, which would turn
            # a typo into a silently successful no-op.
            return {"ok": False, "reason": "unsupported_action"}
        return await _maybe_await(handler(**dict(args)))

    async def perform(
        self,
        step: Mapping[str, Any],
        context: PerformContext | None = None,
    ) -> PerformResult:
        return await self.api.perform(CAPABILITY, normalize_step(step), context)


__all__ = [
    "BROWSER_STEP_CONTRACT",
    "CAPABILITY",
    "KIND",
    "MAX_ACTION_CHARS",
    "MAX_ARGS",
    "MAX_ARG_CHARS",
    "BrowserActionExecutor",
    "normalize_step",
]
