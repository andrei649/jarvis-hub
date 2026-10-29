"""
browser_agent.py — H15.1 Governed local browser-use (lowest-risk entry point).

The *inverse* of an ungoverned shell agent: a browser agent can only act behind
three gates that compose:

* **Egress allowlist.** Navigation is restricted to an explicit domain allowlist
  (suffix match) and run through the SSRF filter (no private-IP / rebinding
  targets). Off-allowlist navigation is **hard-blocked** — not even approvable.
* **Approval queue.** The selected ToolRPC runtime requires one exact durable
  owner approval for its entire bounded plan. The older injectable offline path
  keeps its per-step queue behavior for non-real drivers.
* **The Action Kernel.** Every real driver declares ``requires_kernel``. Its
  mutating calls need both a live approved-plan receipt and a Kernel GRANT for
  that exact step; a bare GRANT never supplies owner approval.
* **Injectable driver.** The actual browser is injected, so the governance layer
  is fully offline-testable. A real Playwright driver is a host-gated add-on; the
  default ``NullBrowserDriver`` only records calls.

Pure-Python (governance), offline-testable.
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlsplit

logger = logging.getLogger("jarvis.browser")

# Step taxonomy. Read-only steps are auto on allowlisted pages; risky steps gate.
READ_ONLY = frozenset({"navigate", "extract", "snapshot", "screenshot", "wait"})

# Two facts that used to share one sentence, and should not: NOT CONFIGURED means
# the owner never enabled the IP-pinned transport (a config fix), while
# browser_playwright's "unavailable" means a configured one could not bind (a bug
# report). Naming them apart is the difference between the two answers.
TRANSPORT_NOT_CONFIGURED = "browser transport not configured"
RISKY = frozenset({"click", "type", "submit", "scroll", "back", "press",
                   "download", "execute_js", "upload"})


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
        try:
            if type(url) is not str or not 0 < len(url) <= 2000:
                return False, "invalid URL"
            if any(ord(char) <= 32 or ord(char) == 127 for char in url):
                return False, "invalid URL"
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower().rstrip(".")
            port = parsed.port
            if (parsed.scheme not in {'http', 'https'} or parsed.username is not None
                    or parsed.password is not None or parsed.fragment
                    or port is not None and not 1 <= port <= 65535):
                return False, "invalid URL"
        except ValueError:
            return False, "invalid URL"
        if not host:
            return False, "no hostname in URL"
        if not any(host == d or host.endswith("." + d) for d in self.allowlist):
            return False, f"{host} not in egress allowlist"
        try:
            from .security.ssrf import check_ssrf
            reason = check_ssrf(url)
        except Exception:
            return False, "browser SSRF check unavailable"
        if reason:
            return False, reason
        return True, ""


class FixtureBrowserPolicy(BrowserPolicy):
    """Injected test seam: two exact synthetic hosts on one ephemeral port."""

    def __init__(self, origin: str) -> None:
        parsed = urlsplit(origin)
        if (parsed.scheme != 'http' or parsed.hostname != 'fixture.browser.test'
                or not parsed.port or parsed.path not in {'', '/'} or parsed.query
                or parsed.fragment or parsed.username is not None):
            raise ValueError('invalid browser fixture origin')
        self.origin = f'http://fixture.browser.test:{parsed.port}'
        self.port = parsed.port
        super().__init__(['fixture.browser.test', 'frame.other.test'])

    def domain_allowed(self, url: str) -> tuple[bool, str]:
        try:
            if type(url) is not str or any(ord(char) <= 32 or ord(char) == 127 for char in url):
                return False, 'fixture_only'
            parsed = urlsplit(url)
            if (parsed.scheme == 'http' and parsed.hostname in {'fixture.browser.test', 'frame.other.test'}
                    and parsed.port == self.port
                    and parsed.username is None and parsed.password is None
                    and not parsed.fragment and len(url) <= 2000):
                return True, ''
        except ValueError:
            pass
        return False, 'fixture_only'


class NullBrowserDriver:
    """Records calls; returns canned values. Safe default + test double.

    ``requires_kernel`` is spelled out rather than left to ``__getattr__``: this
    class answers *any* attribute with a coroutine, so a probe for a capability
    flag would come back as a truthy function and every offline driver would
    claim to need a kernel binding it does not have.
    """

    requires_kernel = False

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
        # Only browser actions. A catch-all that also answers capability probes
        # ("requires_kernel", "close", "_is_something") turns every question about
        # this driver into "yes", which is the wrong default for a governance flag.
        if name.startswith("_"):
            raise AttributeError(name)

        async def _m(**kw):
            return await self._do(name, **kw)
        return _m


# A kernel verdict, in this module's vocabulary. Spelled the same way as
# desktop_operator's mapping on purpose: two surfaces that both mean "one governed
# step on the owner's machine" must not report the same verdict differently, or a
# reader has to learn both to trust either. ``None`` means "the step ran".
_KERNEL_STATUS = {
    "queued": ("queued", "approval_required"),
    "failed": ("error", "kernel_error"),
    "disabled": ("blocked", "kernel_refused"),
    "refused": ("blocked", "kernel_refused"),
}


def _kernel_outcome(action: str, outcome) -> Optional[dict]:
    """The step result for a non-completed kernel verdict, or None if it ran."""
    status = getattr(outcome, "status", None)
    if status is None:
        # Not a PerformResult at all. An unrecognised object is never read as
        # success: the whole point of this gate is that it fails closed.
        return {"action": action, "status": "error", "reason": "kernel_error"}
    if status == "completed":
        return None
    mapped, fallback = _KERNEL_STATUS.get(status, ("error", "kernel_error"))
    return {"action": action, "status": mapped,
            "reason": str(getattr(outcome, "reason", "") or fallback)}


class GovernedBrowser:
    """Runs a browser *plan* under egress + approval governance."""

    def __init__(self, driver=None, policy: Optional[BrowserPolicy] = None,
                 approvals=None, agent: str = "browser", approval_timeout: float = 300.0,
                 action_executor=None, transport=None) -> None:
        self.driver = driver or NullBrowserDriver()
        self.policy = policy or BrowserPolicy()
        self.approvals = approvals
        self.agent = agent
        self.approval_timeout = approval_timeout
        # The browser.step kernel binding. Optional so the offline NullBrowserDriver
        # keeps working with nothing wired; a driver that declares requires_kernel
        # refuses by name rather than falling back to the legacy direct path.
        self.action_executor = action_executor
        # The IP-pinned transport (SEC-B4). Its absence is why navigation refuses,
        # and saying WHICH is missing is the difference between a bug report and a
        # config fix.
        self.transport = transport

    def requires_kernel(self) -> bool:
        """True only when the driver says so with a literal ``True``.

        Not ``bool(...)``: a driver with a permissive ``__getattr__`` answers this
        probe with a coroutine function, which is truthy — so a loose check makes
        every such driver demand a kernel binding, and the honest-looking failure
        ("kernel_required") would be wrong about which driver it came from.
        """
        return getattr(self.driver, "requires_kernel", False) is True

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
        human = {}
        kind = classify_step(action)
        if kind == "unknown":
            return {"action": action, "status": "blocked", "reason": f"unknown action: {action}"}
        if action == "navigate":
            # Refuse before policy URL parsing or any driver startup so every scheme
            # has the same fail-closed edge. The IP-pinned transport is what closes
            # the DNS-rebinding gap between "this URL resolved to a public IP" and
            # "the browser dialled it" — without one, an allowlist check proves
            # nothing about where the connection actually goes.
            if self.transport is None:
                return {
                    "action": action,
                    "status": "blocked",
                    "reason": TRANSPORT_NOT_CONFIGURED,
                }
            ok, why = self.policy.domain_allowed(step.get("url", ""))
            if not ok:
                return {"action": action, "status": "blocked", "reason": why}
        if kind == "risky":
            # The kernel first: a DENY must never reach the owner as a decision.
            # Asking the queue first would train them to approve things the kernel
            # then refuses, which teaches them their approvals do not mean anything.
            if self.requires_kernel():
                if self.action_executor is None:
                    return {"action": action, "status": "blocked", "reason": "kernel_required"}
                outcome = await self.action_executor.perform(step)
                mapped = _kernel_outcome(action, outcome)
                if mapped is not None:
                    return mapped
                # The kernel already invoked the driver through the bound capability,
                # so returning here is what stops the step running twice.
                return {"action": action, "status": "done",
                        "result": getattr(outcome, "output", None)}
            if self.approvals is None:
                return {"action": action, "status": "denied", "reason": "approval required, no queue"}
            req = self.approvals.request({
                "tool": f"browser.{action}", "args": step, "agent": self.agent,
                "summary": f"browser {action}: {step.get('selector') or step.get('url') or ''}"[:120],
                "risk_tier": 2,
            })
            status = await self.approvals.await_decision(req["id"], timeout=self.approval_timeout)
            get_item = getattr(self.approvals, "get", None)
            decided = get_item(req["id"]) if callable(get_item) else None
            if decided and decided.get("human_reason") is not None:
                human["human_reason"] = decided["human_reason"]
            if status != "approved":
                reason = "expired_unanswered" if status == "expired" else status
                return {"action": action, "status": "denied", "reason": reason,
                        "approval_id": req["id"], **human}
        try:
            result = await getattr(self.driver, action)(**{k: v for k, v in step.items() if k != "action"})
            return {"action": action, "status": "done", "result": result, **human}
        except Exception:
            logger.warning("browser step %s failed", action)
            return {"action": action, "status": "error", "reason": "step failed", **human}

    async def run(self, plan: list[dict], stop_on_block: bool = True) -> dict:
        trace = []
        for step in plan or []:
            res = await self.run_step(step)
            trace.append(res)
            if stop_on_block and res["status"] in ("blocked", "denied"):
                break
        return {"steps": len(trace), "trace": trace,
                "ok": all(s["status"] == "done" for s in trace)}
