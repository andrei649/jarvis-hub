"""browser_kernel.py — the Action Kernel gate for a governed browser step.

The browser agent has an egress allowlist and a durable owner approval queue.
The real runtime also crosses the Action Kernel, as `desktop.step`,
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

* The selected runtime proposes one exact plan before opening the browser; the
  owner approves that durable row. Each mutating step then presents a task-bound
  receipt and the exact Action to the Kernel immediately before the driver call.
* A Kernel GRANT alone cannot open the physical mutating method. Its post-Kernel
  task-bound scope must still be live when the method is entered.

The executor owns no policy of its own. The allowlist, SSRF filter and pinned
transport stay in `browser_agent` and `browser_transport`, where they already are.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from agents.core.automation_contracts import ContractTemplate, predicate
from agents.core.browser_session import SessionRefused
from agents.core.capability_actions import CapabilityActionAPI, PerformContext, PerformResult
from agents.core.kernel import Action, Decision, Verdict

logger = logging.getLogger("jarvis.browser.kernel")

KIND = "browser.step"
CAPABILITY = "action:browser.step"

# Bounds on what reaches the kernel and the driver. A selector or a URL is the
# only thing an attacker controls here, so both are capped before either sees them.
MAX_ACTION_CHARS = 32
MAX_ARG_CHARS = 2_000
MAX_ARGS = 20
APPROVED_MUTATIONS = frozenset({'click', 'type', 'submit', 'scroll', 'back', 'press'})
APPROVED_READS = frozenset({'navigate', 'extract', 'snapshot', 'wait', 'console', 'get_images'})


@dataclass(frozen=True)
class _ApprovedStep:
    task: object
    plan_sha256: str
    index: int
    step: dict
    current: object
    owner_task: object
    session_id: str | None = None
    session_generation: int | None = None


_APPROVED_STEP: ContextVar[_ApprovedStep | None] = ContextVar('browser_approved_step', default=None)
_PHYSICAL_STEP: ContextVar[_ApprovedStep | None] = ContextVar('browser_physical_step', default=None)


@contextmanager
def approved_step_scope(task, plan_sha256, index, step, current, *,
                        session_id=None, session_generation=None):
    """Private lifetime of one exact step in the durable approved plan."""
    receipt = _ApprovedStep(task, plan_sha256, index, deepcopy(step), current,
                            asyncio.current_task(), session_id, session_generation)
    token = _APPROVED_STEP.set(receipt)
    try:
        yield
    finally:
        _APPROVED_STEP.reset(token)


def browser_receipt_matches(action: Action) -> bool:
    receipt = _APPROVED_STEP.get()
    if receipt is None or asyncio.current_task() is not receipt.owner_task:
        return False
    task = receipt.task
    payload = action.payload
    expected = {
        'action': receipt.step['action'],
        'args': {key: value for key, value in receipt.step.items() if key != 'action'},
        'risk_tier': 3,
        'approved_task_id': getattr(task, 'id', None),
        'plan_sha256': receipt.plan_sha256,
        'step_index': receipt.index,
    }
    if receipt.session_id is not None:
        expected['session_id'] = receipt.session_id
        expected['session_generation'] = receipt.session_generation
    try:
        return (action.kind == KIND and action.agent == getattr(task, 'agent', None)
                and action.origin == getattr(task, 'origin', None)
                and payload == expected and receipt.current() is True)
    except Exception:
        return False


@contextmanager
def _physical_step_scope(receipt: _ApprovedStep):
    token = _PHYSICAL_STEP.set(receipt)
    try:
        yield
    finally:
        _PHYSICAL_STEP.reset(token)


def physical_browser_step_allowed(action: str, args: dict) -> bool:
    """The physical driver accepts one exact post-Kernel mutating call."""
    receipt = _APPROVED_STEP.get()
    try:
        return bool(
            receipt is not None and _PHYSICAL_STEP.get() is receipt
            and asyncio.current_task() is receipt.owner_task
            and action == receipt.step.get('action')
            and args == {key: value for key, value in receipt.step.items() if key != 'action'}
            and receipt.current() is True
        )
    except Exception:
        return False


def _action_for(receipt: _ApprovedStep) -> Action:
    step = receipt.step
    payload = {
        'action': step['action'],
        'args': {key: value for key, value in step.items() if key != 'action'},
        'risk_tier': 3,
        'approved_task_id': receipt.task.id,
        'plan_sha256': receipt.plan_sha256,
        'step_index': receipt.index,
    }
    if receipt.session_id is not None:
        payload['session_id'] = receipt.session_id
        payload['session_generation'] = receipt.session_generation
    return Action(
        kind=KIND, agent=receipt.task.agent, title=f"Browser {step['action']}",
        payload=payload, origin=receipt.task.origin,
    )


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

    def __init__(self, driver, *, authorizer, revalidator=None) -> None:
        self.driver = driver
        self.authorizer = authorizer
        self.revalidator = revalidator
        self.api = CapabilityActionAPI(authorizer=authorizer)
        self.api.register(CAPABILITY, self._execute)

    async def _execute(self, step: dict[str, Any], _context: PerformContext) -> Any:
        action = step.get("action")
        args = step.get("args")
        if not isinstance(action, str) or not action.strip():
            return {"ok": False, "reason": "invalid_action"}
        if not isinstance(args, Mapping):
            return {"ok": False, "reason": "invalid_args"}
        if action not in APPROVED_MUTATIONS:
            return {"ok": False, "reason": "unsupported_action"}
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
        if getattr(self.driver, 'requires_kernel', False) is not True:
            return await self.api.perform(CAPABILITY, normalize_step(step), context)
        receipt = _APPROVED_STEP.get()
        if receipt is None or asyncio.current_task() is not receipt.owner_task:
            return PerformResult('refused', CAPABILITY, KIND, 'approved_plan_required')
        if dict(step) != receipt.step or step.get('action') not in APPROVED_MUTATIONS:
            return PerformResult('refused', CAPABILITY, KIND, 'approved_step_changed')
        if not callable(self.authorizer):
            return PerformResult('refused', CAPABILITY, KIND, 'kernel_unavailable')
        action = _action_for(receipt)
        if not browser_receipt_matches(action):
            return PerformResult('refused', CAPABILITY, KIND, 'approved_plan_stale')
        try:
            decision = self.authorizer(action, approval_check=lambda candidate: (
                candidate == action and browser_receipt_matches(candidate)))
            if inspect.isawaitable(decision):
                decision = await decision
        except Exception:
            return PerformResult('refused', CAPABILITY, KIND, 'kernel_error')
        if not isinstance(decision, Decision):
            return PerformResult('refused', CAPABILITY, KIND, 'kernel_error')
        if decision.verdict is not Verdict.GRANT:
            status = 'queued' if decision.verdict is Verdict.QUEUE else 'refused'
            return PerformResult(status, CAPABILITY, KIND, decision.reason, decision.tier,
                                 decision.card, stage='decision')
        if not browser_receipt_matches(action):
            return PerformResult('refused', CAPABILITY, KIND, 'approved_plan_stale')
        try:
            with _physical_step_scope(receipt):
                output = await self._execute({'action': step['action'],
                                              'args': action.payload['args']}, PerformContext())
            return PerformResult('completed', CAPABILITY, KIND, decision.reason,
                                 decision.tier, output=output, stage='handler')
        except SessionRefused as exc:
            return PerformResult('failed', CAPABILITY, KIND,
                                 'stale_browser_ref' if str(exc) == 'stale_browser_ref'
                                 else 'browser_step_failed', stage='handler')
        except Exception:
            return PerformResult('failed', CAPABILITY, KIND, 'browser_step_failed', stage='handler')

    async def check_read(self, step: Mapping[str, Any]) -> PerformResult:
        """Nonconsuming live Kernel floor for one approved read/navigation step."""
        receipt = _APPROVED_STEP.get()
        if (receipt is None or asyncio.current_task() is not receipt.owner_task
                or dict(step) != receipt.step or step.get('action') not in APPROVED_READS):
            return PerformResult('refused', CAPABILITY, KIND, 'approved_plan_required')
        gate = self.revalidator
        if not callable(gate):
            return PerformResult('refused', CAPABILITY, KIND, 'kernel_unavailable')
        action = _action_for(receipt)
        if not browser_receipt_matches(action):
            return PerformResult('refused', CAPABILITY, KIND, 'approved_plan_stale')
        try:
            decision = gate(action, approval_check=lambda candidate: (
                candidate == action and browser_receipt_matches(candidate)))
            if inspect.isawaitable(decision):
                decision = await decision
        except Exception:
            return PerformResult('refused', CAPABILITY, KIND, 'kernel_error')
        if not isinstance(decision, Decision):
            return PerformResult('refused', CAPABILITY, KIND, 'kernel_error')
        if decision.verdict is not Verdict.GRANT:
            status = 'queued' if decision.verdict is Verdict.QUEUE else 'refused'
            return PerformResult(status, CAPABILITY, KIND, decision.reason,
                                 decision.tier, decision.card, stage='decision')
        if not browser_receipt_matches(action):
            return PerformResult('refused', CAPABILITY, KIND, 'approved_plan_stale')
        return PerformResult('completed', CAPABILITY, KIND, decision.reason,
                             decision.tier, stage='decision')


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
