"""
subagents.py — H20.6 Dynamic sub-agent delegation.

Extends the author-defined parallelism of the WorkflowEngine (H5.6) to
**agent-initiated** spawning: at runtime an agent can delegate a piece of work to
an **isolated** sub-agent (its own session), **concurrently**, under a
configurable **cap** (the gate — an agent can't fork unbounded work). Each
sub-agent runs through an INJECTABLE runner (the orchestrator's dispatch in
prod; a stub offline), so the governance/isolation layer is offline-testable.
"""

from __future__ import annotations

import inspect
import logging
import time
from typing import Awaitable, Callable, Optional

from .iteration_budget import IterationBudget

logger = logging.getLogger("jarvis.subagents")

# Capabilities a sub-agent must NOT exercise, regardless of what the runner can
# do. Adapted from hermes-agent `DELEGATE_BLOCKED_TOOLS` (Nous Research, MIT):
# no recursive delegation, no writes to shared memory cores, no outbound
# channel sends, no skill authoring, no user clarification round-trips. The
# list is recorded on every spawn and handed to runners that accept a
# `blocked` kwarg; runners that don't are unchanged (additive contract).
DELEGATE_BLOCKED_CAPABILITIES = frozenset({
    "delegate", "memory_write", "channel_send", "skill_manage", "clarify",
})


class NullRunner:
    """Offline default — echoes the task without a real agent."""

    async def __call__(self, task: str, session_id: str, agent: str) -> dict:
        return {"output": f"[stub:{agent or 'sub'}] {task}", "session_id": session_id}


def _runner_accepts_blocked(runner) -> bool:
    """Whether the injected runner declares a `blocked` kwarg (additive opt-in)."""
    try:
        if inspect.isfunction(runner) or inspect.ismethod(runner):
            target = runner
        elif callable(runner):
            target = runner.__call__
        else:
            target = runner
        params = inspect.signature(target).parameters
        return "blocked" in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    except (TypeError, ValueError):
        return False


class SubAgentManager:
    """Gated, isolated, concurrent sub-agent spawning."""

    def __init__(self, runner: Optional[Callable[..., Awaitable[dict]]] = None,
                 max_concurrent: int = 3, parent_agent: str = "jarvis",
                 max_depth: Optional[int] = 8,
                 budget: Optional["IterationBudget"] = None,
                 blocked: Optional[frozenset] = None) -> None:
        self._runner = runner or NullRunner()
        self.max_concurrent = max(1, int(max_concurrent))
        self.parent_agent = parent_agent
        # H20.6 hardening: total-spawn budget (refundable IterationBudget) on top
        # of the concurrency cap — None keeps today's unbounded-total behavior.
        self.budget = budget
        # Capability scoping for children (hermes DELEGATE_BLOCKED_TOOLS analog).
        self.blocked = frozenset(blocked) if blocked is not None else DELEGATE_BLOCKED_CAPABILITIES
        self._runner_takes_blocked = _runner_accepts_blocked(self._runner)
        # K3 (OWASP unbounded-consumption): cap the recursion DEPTH of agent-initiated
        # delegation — an agent spawning sub-agents that spawn sub-agents can't tower up
        # forever. None = unbounded. Depth is inferred from the recorded parent-chain, so
        # it needs no runner cooperation (the spawning sub-agent just passes its own id as
        # `parent`, which it already does to attribute the spawn).
        self.max_depth = max_depth if (max_depth is None or max_depth > 0) else None
        self._spawns: dict[str, dict] = {}
        self._active = 0
        self._counter = 0

    def _active_count(self) -> int:
        return self._active

    def _depth_of(self, parent: str) -> int:
        """How deep a spawn under *parent* would sit (0 = top-level, i.e. parent is the
        root agent, not a recorded sub-agent). Walks the recorded parent links; the `seen`
        guard makes a malformed cycle terminate instead of spinning."""
        depth, cur, seen = 0, parent, set()
        while cur in self._spawns and cur not in seen:
            seen.add(cur)
            depth += 1
            cur = self._spawns[cur].get("parent", "")
        return depth

    async def spawn(self, task: str, agent: str = "", parent: str = "") -> dict:
        """Spawn an isolated sub-agent for `task`. Rejected if the concurrency cap is
        reached, or if the parent-chain is already `max_depth` deep (recursion guard)."""
        parent = parent or self.parent_agent
        depth = self._depth_of(parent)
        if self.max_depth is not None and depth >= self.max_depth:
            return {"ok": False, "reason": "recursion_depth_cap",
                    "depth": depth, "max_depth": self.max_depth}
        if self._active >= self.max_concurrent:
            return {"ok": False, "reason": "concurrency_cap",
                    "active": self._active, "cap": self.max_concurrent}
        if self.budget is not None and not self.budget.consume():
            return {"ok": False, "reason": "spawn_budget_exhausted",
                    "used": self.budget.used, "max_total": self.budget.max_total}
        self._counter += 1
        spawn_id = f"sub-{parent}-{self._counter}"
        session_id = f"session::{spawn_id}"   # isolated session
        rec = {"id": spawn_id, "parent": parent, "agent": agent or "sub",
               "task": task, "session_id": session_id, "status": "running",
               "created_at": time.time(), "result": None,
               "blocked": sorted(self.blocked)}
        self._spawns[spawn_id] = rec
        self._active += 1
        try:
            if self._runner_takes_blocked:
                result = await self._runner(task, session_id, agent or "sub",
                                            blocked=self.blocked)
            else:
                result = await self._runner(task, session_id, agent or "sub")
            rec["status"] = "done"
            rec["result"] = result
        except Exception:
            logger.warning("sub-agent run failed", exc_info=True)
            rec["status"] = "failed"
            rec["result"] = {"error": "run failed"}
        finally:
            self._active -= 1
        return {"ok": rec["status"] == "done", "id": spawn_id,
                "session_id": session_id, "status": rec["status"], "result": rec["result"]}

    def list(self) -> "list[dict]":
        return [{k: v for k, v in r.items() if k != "result"} for r in self._spawns.values()]

    def get(self, spawn_id: str) -> Optional[dict]:
        r = self._spawns.get(spawn_id)
        return dict(r) if r else None

    def stats(self) -> dict:
        out = {"total": len(self._spawns), "active": self._active,
               "cap": self.max_concurrent, "max_depth": self.max_depth,
               "blocked": sorted(self.blocked)}
        if self.budget is not None:
            out["budget"] = self.budget.status()
        return out
