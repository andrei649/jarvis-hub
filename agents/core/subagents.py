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

import logging
import time
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("jarvis.subagents")


class NullRunner:
    """Offline default — echoes the task without a real agent."""

    async def __call__(self, task: str, session_id: str, agent: str) -> dict:
        return {"output": f"[stub:{agent or 'sub'}] {task}", "session_id": session_id}


class SubAgentManager:
    """Gated, isolated, concurrent sub-agent spawning."""

    def __init__(self, runner: Optional[Callable[..., Awaitable[dict]]] = None,
                 max_concurrent: int = 3, parent_agent: str = "jarvis") -> None:
        self._runner = runner or NullRunner()
        self.max_concurrent = max(1, int(max_concurrent))
        self.parent_agent = parent_agent
        self._spawns: dict[str, dict] = {}
        self._active = 0
        self._counter = 0

    def _active_count(self) -> int:
        return self._active

    async def spawn(self, task: str, agent: str = "", parent: str = "") -> dict:
        """Spawn an isolated sub-agent for `task`. Rejected if the cap is reached."""
        if self._active >= self.max_concurrent:
            return {"ok": False, "reason": "concurrency_cap",
                    "active": self._active, "cap": self.max_concurrent}
        self._counter += 1
        parent = parent or self.parent_agent
        spawn_id = f"sub-{parent}-{self._counter}"
        session_id = f"session::{spawn_id}"   # isolated session
        rec = {"id": spawn_id, "parent": parent, "agent": agent or "sub",
               "task": task, "session_id": session_id, "status": "running",
               "created_at": time.time(), "result": None}
        self._spawns[spawn_id] = rec
        self._active += 1
        try:
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
        return {"total": len(self._spawns), "active": self._active,
                "cap": self.max_concurrent}
