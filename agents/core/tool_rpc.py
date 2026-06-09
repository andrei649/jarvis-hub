"""
tool_rpc.py — H20.1 Governed Tool-RPC (`execute_code`).

The agent writes a Python script that orchestrates many Jarvis tool calls and
runs it in the sandbox; inside, the script reaches the tools through a local RPC
surface instead of round-tripping every step through the LLM context →
"zero-context-cost pipelines" (the biggest net capability from hermes-agent).

This module is the **governed RPC surface** — the security-critical core:

  * **Allowlist:** only explicitly registered tools are callable; anything else
    is denied (the sandbox can't reach arbitrary host functions).
  * **Risk gating:** read-only tools run inline; *gated* (external/mutating)
    tools never execute from the sandbox — they enqueue an ask-tier governed
    task and return ``approval_required`` (the script can't escalate).
  * **Secret containment:** the sandbox never sees secrets — handlers resolve
    credentials host-side, and every response is run through the secret-scrubber
    (defense-in-depth) before it crosses back.

The Unix-socket transport + the sandbox-side client + actually running the
agent's code in the sandbox are the host seam; the governance core here is pure
and offline-testable. The injected sink/secret-broker keep it decoupled.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("jarvis.tool_rpc")

Handler = Callable[[dict], Awaitable]


class ToolRPCServer:
    """Allowlisted, risk-gated, secret-scrubbed tool surface for sandboxed code."""

    def __init__(self, secret_broker=None, enqueue: Optional[Callable] = None,
                 audit=None, agent: str = "jarvis") -> None:
        self._tools: dict[str, dict] = {}
        self._secrets = secret_broker
        self._enqueue = enqueue
        self._audit = audit
        self.agent = agent

    # ── registration (the allowlist) ─────────────────────────────────────────

    def register_tool(self, name: str, handler: Handler, gated: bool = False) -> "ToolRPCServer":
        """Expose one tool. ``gated=True`` ⇒ external/mutating ⇒ needs approval."""
        self._tools[name] = {"handler": handler, "gated": bool(gated)}
        return self

    def tools(self) -> "list[dict]":
        return [{"name": n, "gated": t["gated"]} for n, t in sorted(self._tools.items())]

    def allows(self, name: str) -> bool:
        return name in self._tools

    # ── the RPC entry point ──────────────────────────────────────────────────

    async def handle(self, request: dict) -> dict:
        name = str((request or {}).get("tool", ""))
        args = (request or {}).get("args") or {}
        if not isinstance(args, dict):
            return {"ok": False, "reason": "bad_args", "tool": name}

        spec = self._tools.get(name)
        if spec is None:
            # Not on the allowlist — the sandbox cannot reach it.
            return {"ok": False, "reason": "tool_not_allowed", "tool": name}

        if spec["gated"]:
            # External/mutating tool: never runs from the sandbox. Enqueue an
            # ask-tier governed task; the script gets back "approval_required".
            if self._enqueue is None:
                return {"ok": False, "reason": "approval_required", "tool": name}
            try:
                task_id = self._enqueue(
                    self.agent, f"toolrpc.{name}", f"Tool '{name}' via RPC",
                    payload={"tool": name, "args": args, "target": name},
                    risk_tier=2, autonomy_level="ask", origin="generated")
            except Exception:
                logger.warning("tool-rpc gated enqueue failed", exc_info=True)
                return {"ok": False, "reason": "enqueue_failed", "tool": name}
            self._record("toolrpc.gated", name)
            return {"ok": False, "reason": "approval_required", "tool": name, "task_id": task_id}

        try:
            result = await spec["handler"](args)
        except Exception as e:
            logger.warning("tool-rpc handler failed: %s", name, exc_info=True)
            return {"ok": False, "reason": "tool_error", "tool": name, "error": str(e)}

        self._record("toolrpc.call", name)
        return {"ok": True, "tool": name, "result": self._scrub(result)}

    async def run_pipeline(self, requests: "list[dict]") -> "list[dict]":
        """Run a sequence of tool calls (what a sandboxed script does), returning
        each response. No LLM round-trip happens between steps."""
        return [await self.handle(r) for r in (requests or [])]

    async def execute(self, task) -> dict:
        """Executor handler: run a gated tool AFTER its approval task is approved."""
        payload = getattr(task, "payload", None) or {}
        name = payload.get("tool")
        args = payload.get("args") or {}
        spec = self._tools.get(name)
        if spec is None:
            return {"status": "failed", "reason": "tool_not_allowed", "tool": name}
        try:
            result = await spec["handler"](args)
        except Exception as e:
            logger.warning("tool-rpc approved execute failed: %s", name, exc_info=True)
            return {"status": "failed", "reason": "tool_error", "tool": name, "error": str(e)}
        self._record("toolrpc.execute", name)
        return {"status": "ok", "tool": name, "result": self._scrub(result)}

    # ── internals ────────────────────────────────────────────────────────────

    def _scrub(self, obj):
        """Recursively mask any known secret value before it crosses to the sandbox."""
        if self._secrets is None:
            return obj
        if isinstance(obj, str):
            return self._secrets.redact(obj)
        if isinstance(obj, dict):
            return {k: self._scrub(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._scrub(v) for v in obj]
        return obj

    def _record(self, action: str, why: str, **meta) -> None:
        if self._audit is None:
            return
        try:
            if hasattr(self._audit, "record"):
                self._audit.record(actor="tool_rpc", action=action, why=why, metadata=meta)
            elif hasattr(self._audit, "log"):
                self._audit.log({"event": action, "why": why, **meta})
        except Exception:  # pragma: no cover - best-effort
            pass
