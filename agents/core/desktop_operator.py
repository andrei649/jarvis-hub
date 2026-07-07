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
import time

from .automation_contracts import ContractTemplate, predicate

logger = logging.getLogger("jarvis.desktop_operator")

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


class GovernedDesktop:
    def __init__(self, driver=None) -> None:
        self._driver = driver or NullDesktopDriver()

    @staticmethod
    def is_mutating(action: str) -> bool:
        return (action or "").lower() not in _READ_ONLY

    def classify_injection(self, screenshot_text: str) -> bool:
        return bool(_detect_injection(screenshot_text or ""))

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
            res = await self._driver.perform(action, args)
            ran.append({"action": action, "status": "ran", "result": res})
        return {"ok": True, "ran": ran}
