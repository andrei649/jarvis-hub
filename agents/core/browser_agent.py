"""
browser_agent.py — H15.1 Governed local browser-use (lowest-risk entry point).

The *inverse* of an ungoverned shell agent: a browser agent can only act behind
three gates that compose:

* **Egress allowlist.** Navigation is restricted to an explicit domain allowlist
  (suffix match) and run through the SSRF filter (no private-IP / rebinding
  targets). Off-allowlist navigation is **hard-blocked** — not even approvable.
* **Approval queue.** Read-only steps on allowlisted pages (navigate / extract /
  screenshot / wait) run automatically; **mutating** steps (click / type / submit
  / download / execute_js) require out-of-band approval (H10.18 queue), exactly
  like the rest of H6 autonomy. Nothing irreversible happens unsupervised.
* **Injectable driver.** The actual browser is injected, so the governance layer
  is fully offline-testable. A real Playwright driver is a host-gated add-on; the
  default ``NullBrowserDriver`` only records calls.

Pure-Python (governance), offline-testable.
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("jarvis.browser")

# Step taxonomy. Read-only steps are auto on allowlisted pages; risky steps gate.
READ_ONLY = frozenset({"navigate", "extract", "screenshot", "wait"})
RISKY = frozenset({"click", "type", "submit", "download", "execute_js", "upload"})


def classify_step(action: str) -> str:
    """'read' | 'risky' | 'unknown' for a browser action."""
    if action in READ_ONLY:
        return "read"
    if action in RISKY:
        return "risky"
    return "unknown"


class BrowserPolicy:
    """Egress allowlist (suffix match) + SSRF filter. Fail-closed by default."""

    def __init__(self, allowlist: Optional[list[str]] = None) -> None:
        self.allowlist = [d.lower().strip().lstrip(".") for d in (allowlist or []) if d.strip()]

    def domain_allowed(self, url: str) -> tuple[bool, str]:
        host = (urlparse(url or "").hostname or "").lower()
        if not host:
            return False, "no hostname in URL"
        if not any(host == d or host.endswith("." + d) for d in self.allowlist):
            return False, f"{host} not in egress allowlist"
        try:
            from .security.ssrf import check_ssrf
            reason = check_ssrf(url)
        except Exception:
            reason = None
        if reason:
            return False, reason
        return True, ""


class NullBrowserDriver:
    """Records calls; returns canned values. Safe default + test double."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def _do(self, action: str, **kw):
        self.calls.append((action, kw))
        if action == "extract":
            return {"text": ""}
        if action == "screenshot":
            return {"image": "(null)"}
        return {"ok": True}

    def __getattr__(self, name):
        async def _m(**kw):
            return await self._do(name, **kw)
        return _m


class GovernedBrowser:
    """Runs a browser *plan* under egress + approval governance."""

    def __init__(self, driver=None, policy: Optional[BrowserPolicy] = None,
                 approvals=None, agent: str = "browser", approval_timeout: float = 300.0) -> None:
        self.driver = driver or NullBrowserDriver()
        self.policy = policy or BrowserPolicy()
        self.approvals = approvals
        self.agent = agent
        self.approval_timeout = approval_timeout

    def preview(self, plan: list[dict]) -> dict:
        """Dry-run governance: classify each step (no execution, no approval)."""
        steps = []
        for i, step in enumerate(plan or []):
            action = step.get("action", "")
            kind = classify_step(action)
            decision = "run"
            reason = ""
            if kind == "unknown":
                decision, reason = "block", f"unknown action: {action}"
            elif action == "navigate":
                ok, why = self.policy.domain_allowed(step.get("url", ""))
                if not ok:
                    decision, reason = "block", why
            elif kind == "risky":
                decision, reason = "approve", "mutating action requires approval"
            steps.append({"i": i, "action": action, "kind": kind,
                          "decision": decision, "reason": reason})
        return {"steps": steps,
                "needs_approval": sum(1 for s in steps if s["decision"] == "approve"),
                "blocked": sum(1 for s in steps if s["decision"] == "block")}

    async def run_step(self, step: dict) -> dict:
        action = step.get("action", "")
        kind = classify_step(action)
        if kind == "unknown":
            return {"action": action, "status": "blocked", "reason": f"unknown action: {action}"}
        if action == "navigate":
            ok, why = self.policy.domain_allowed(step.get("url", ""))
            if not ok:
                return {"action": action, "status": "blocked", "reason": why}
        if kind == "risky":
            if self.approvals is None:
                return {"action": action, "status": "denied", "reason": "approval required, no queue"}
            req = self.approvals.request({
                "tool": f"browser.{action}", "args": step, "agent": self.agent,
                "summary": f"browser {action}: {step.get('selector') or step.get('url') or ''}"[:120],
                "risk_tier": 2,
            })
            status = await self.approvals.await_decision(req["id"], timeout=self.approval_timeout)
            if status != "approved":
                return {"action": action, "status": "denied", "reason": status, "approval_id": req["id"]}
        try:
            result = await getattr(self.driver, action)(**{k: v for k, v in step.items() if k != "action"})
            return {"action": action, "status": "done", "result": result}
        except Exception:
            logger.warning("browser step %s failed", action, exc_info=True)
            return {"action": action, "status": "error", "reason": "step failed"}

    async def run(self, plan: list[dict], stop_on_block: bool = True) -> dict:
        trace = []
        for step in plan or []:
            res = await self.run_step(step)
            trace.append(res)
            if stop_on_block and res["status"] in ("blocked", "denied"):
                break
        return {"steps": len(trace), "trace": trace,
                "ok": all(s["status"] == "done" for s in trace)}
