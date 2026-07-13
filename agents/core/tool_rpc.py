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

import asyncio
import logging
import time
from collections.abc import Mapping
from copy import deepcopy
from typing import Awaitable, Callable, Optional

from .automation_contracts import ContractTemplate, predicate

logger = logging.getLogger("jarvis.tool_rpc")

Handler = Callable[[dict], Awaitable]
Preflight = Callable[[dict], Mapping]

_KIND_PREFIX = "toolrpc."
_RISK_TIER = 2


def _tool_rpc_call_contract_template() -> ContractTemplate:
    """Contract form of the existing gated Tool-RPC approval path."""
    def tool_kind(view, now):
        tool = view.get("tool")
        kind = view.get("kind")
        return isinstance(tool, str) and bool(tool) and kind == f"{_KIND_PREFIX}{tool}"

    def gated_tool(view, now):
        return view.get("gated") is True

    def target_matches_tool(view, now):
        return view.get("target") == view.get("tool")

    def args_keys_are_safe(view, now):
        keys = view.get("args_keys")
        return (
            isinstance(keys, list)
            and all(isinstance(k, str) for k in keys)
            and keys == sorted(keys)
        )

    return ContractTemplate(kind="tool_rpc_call", constraints=(
        predicate("tool_kind", tool_kind, reason="invalid_kind"),
        predicate("gated_tool", gated_tool, reason="not_gated"),
        predicate("target_matches_tool", target_matches_tool,
                  reason="target_mismatch"),
        predicate("args_keys_are_safe", args_keys_are_safe,
                  reason="bad_args_keys"),
    ), description="Admissibility for governed gated Tool-RPC calls.")


TOOL_RPC_CALL_CONTRACT = _tool_rpc_call_contract_template()


class ToolRPCValidationError(ValueError):
    """Bounded public denial raised by a tool-specific argument preflight."""

    def __init__(self, reason: str = "validation_failed") -> None:
        normalized = str(reason or "validation_failed")
        if (
            len(normalized) > 80
            or not normalized.replace("_", "").isalnum()
        ):
            normalized = "validation_failed"
        self.reason = normalized
        super().__init__(normalized)


class ToolRPCServer:
    """Allowlisted, risk-gated, secret-scrubbed tool surface for sandboxed code."""

    def __init__(self, secret_broker=None, enqueue: Optional[Callable] = None,
                 audit=None, agent: str = "jarvis", kernel=None,
                 execution_context_check: Optional[Callable] = None) -> None:
        self._tools: dict[str, dict] = {}
        self._secrets = secret_broker
        self._enqueue = enqueue
        self._audit = audit
        self.agent = agent
        self._kernel = kernel   # ORIZONT-24 K1 wave-3: bound kernel.authorize (default-off)
        self._execution_context_check = execution_context_check

    # ── registration (the allowlist) ─────────────────────────────────────────

    def register_tool(
        self,
        name: str,
        handler: Handler,
        gated: bool = False,
        description: str = "",
        input_schema: Optional[dict] = None,
        capability_id: str | None = None,
        preflight: Preflight | None = None,
        trusted_execution: bool = False,
    ) -> "ToolRPCServer":
        """Expose one tool. ``gated=True`` ⇒ external/mutating ⇒ needs approval."""
        if trusted_execution and not gated:
            raise ValueError("trusted execution is only valid for gated tools")
        if capability_id is not None:
            if (
                not isinstance(capability_id, str)
                or not capability_id
                or len(capability_id) > 128
                or any(not (char.isalnum() or char in ":._-*") for char in capability_id)
            ):
                raise ValueError("capability_id must be a bounded machine identifier")
            if any(
                existing_name != name and spec.get("capability_id") == capability_id
                for existing_name, spec in self._tools.items()
            ):
                raise ValueError(f"capability_id already registered: {capability_id}")
        schema = input_schema if input_schema is not None else {
            "type": "object",
            "properties": {},
        }
        existing = self._tools.get(name)
        if existing is not None and existing.get("active_tasks"):
            raise RuntimeError(f"tool has in-flight calls: {name}")
        self._tools[name] = {
            "handler": handler,
            "gated": bool(gated),
            "description": description,
            "input_schema": deepcopy(schema),
            "capability_id": capability_id,
            "preflight": preflight,
            "trusted_execution": bool(trusted_execution),
            "active_tasks": set(),
        }
        return self

    async def unregister_tool(
        self,
        name: str,
        *,
        cancel_inflight: bool = False,
        timeout: float = 5.0,
    ) -> bool:
        """Deny new calls immediately, then drain or cancel calls already running."""
        spec = self._tools.pop(str(name or ""), None)
        if spec is None:
            return False
        current = asyncio.current_task()
        tasks = [task for task in tuple(spec.get("active_tasks", ())) if task is not current]
        if cancel_inflight:
            for task in tasks:
                task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=max(0.01, min(30.0, float(timeout))),
                )
            except TimeoutError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        return True

    def tools(self) -> "list[dict]":
        tools = []
        for name, spec in sorted(self._tools.items()):
            row = {
                "name": name,
                "gated": spec["gated"],
                "description": spec["description"],
                "input_schema": deepcopy(spec["input_schema"]),
            }
            if spec.get("capability_id"):
                row["capability_id"] = spec["capability_id"]
            tools.append(row)
        return tools

    def allows(self, name: str) -> bool:
        return name in self._tools

    # ── the RPC entry point ──────────────────────────────────────────────────

    async def handle(self, request: dict, *, actor: Optional[str] = None) -> dict:
        effective_actor = actor or self.agent
        name = str((request or {}).get("tool", ""))
        args = (request or {}).get("args") or {}
        if not isinstance(args, dict):
            return {"ok": False, "reason": "bad_args", "tool": name}

        spec = self._tools.get(name)
        if spec is None:
            # Not on the allowlist — the sandbox cannot reach it.
            return {"ok": False, "reason": "tool_not_allowed", "tool": name}

        args, denial = self._run_preflight(spec, args, name)
        if denial is not None:
            return denial

        if spec["gated"]:
            # External/mutating tool: never runs from the sandbox. Enqueue an
            # ask-tier governed task; the script gets back "approval_required".
            contract_payload = {
                "kind": f"{_KIND_PREFIX}{name}",
                "tool": name,
                "target": name,
                "agent": effective_actor,
                "risk_tier": _RISK_TIER,
                "gated": True,
                "args_keys": sorted(args.keys()),
            }
            try:
                decision = TOOL_RPC_CALL_CONTRACT.evaluate(
                    contract_payload, now=time.time())
            except Exception:
                logger.warning("tool-rpc contract evaluation failed", exc_info=True)
                return {"ok": False, "reason": "contract_error", "tool": name}
            if not decision.admissible:
                reason = decision.reason or "contract_denied"
                self._record(
                    "toolrpc.contract_denied",
                    f"{name}: {reason}",
                    agent=effective_actor,
                )
                return {"ok": False, "reason": reason, "tool": name}

            # ORIZONT-24 K1 wave-3: mediate the gated tool through the Action Kernel
            # first (default-off). A DENY (halted kill-switch / over-budget / runaway
            # loop) refuses it before it even reaches the approval queue.
            denied = self._kernel_denial(name, args, effective_actor)
            if denied is not None:
                self._record(
                    "toolrpc.kernel_denied",
                    f"{name}: {denied}",
                    agent=effective_actor,
                )
                return {"ok": False, "reason": "kernel_denied", "tool": name, "detail": denied}
            if self._enqueue is None:
                return {"ok": False, "reason": "approval_required", "tool": name}
            try:
                task_id = self._enqueue(
                    effective_actor, f"toolrpc.{name}", f"Tool '{name}' via RPC",
                    payload={"tool": name, "args": args, "target": name},
                    risk_tier=_RISK_TIER, autonomy_level="ask", origin="generated")
            except Exception:
                logger.warning("tool-rpc gated enqueue failed", exc_info=True)
                return {"ok": False, "reason": "enqueue_failed", "tool": name}
            self._record("toolrpc.gated", name, agent=effective_actor)
            return {"ok": False, "reason": "approval_required", "tool": name, "task_id": task_id}

        try:
            result = await self._invoke_handler(spec, args)
        except Exception:
            logger.warning("tool-rpc handler failed: %s", name, exc_info=True)
            return {"ok": False, "reason": "tool_error", "tool": name}

        self._record("toolrpc.call", name, agent=effective_actor)
        return {"ok": True, "tool": name, "result": self._scrub(result)}

    async def run_pipeline(self, requests: "list[dict]") -> "list[dict]":
        """Run a sequence of tool calls (what a sandboxed script does), returning
        each response. No LLM round-trip happens between steps."""
        return [await self.handle(r) for r in (requests or [])]

    async def execute(self, task, *, execution_context=None) -> dict:
        """Executor handler: run a gated tool AFTER its approval task is approved."""
        effective_actor = getattr(task, "agent", None) or self.agent
        payload = getattr(task, "payload", None)
        if not isinstance(payload, Mapping):
            return {"status": "failed", "reason": "bad_args", "tool": ""}
        name = payload.get("tool")
        if not isinstance(name, str):
            return {"status": "failed", "reason": "bad_args", "tool": ""}
        raw_args = payload.get("args", {})
        if not isinstance(raw_args, Mapping):
            return {"status": "failed", "reason": "bad_args", "tool": name}
        args = dict(raw_args)
        spec = self._tools.get(name)
        if spec is None:
            return {"status": "failed", "reason": "tool_not_allowed", "tool": name}
        args, denial = self._run_preflight(spec, args, name)
        if denial is not None:
            return {
                "status": "failed",
                "reason": denial["reason"],
                "tool": name,
            }
        if spec.get("trusted_execution"):
            try:
                trusted = (
                    self._execution_context_check is not None
                    and self._execution_context_check(execution_context, task) is True
                )
            except Exception:
                trusted = False
            if not trusted:
                return {
                    "status": "failed",
                    "reason": "trusted_execution_required",
                    "tool": name,
                }
        if spec["gated"]:
            denied = self._kernel_denial(name, args, effective_actor)
            if denied is not None:
                self._record(
                    "toolrpc.kernel_denied",
                    f"{name}: {denied}",
                    agent=effective_actor,
                )
                return {
                    "status": "failed",
                    "reason": "kernel_denied",
                    "tool": name,
                    "detail": denied,
                }
        try:
            result = await self._invoke_handler(spec, args)
        except Exception:
            logger.warning("tool-rpc approved execute failed: %s", name, exc_info=True)
            return {"status": "failed", "reason": "tool_error", "tool": name}
        if spec.get("trusted_execution") and not isinstance(result, Mapping):
            return {
                "status": "failed",
                "reason": "invalid_result",
                "tool": name,
            }
        if spec.get("trusted_execution") and result.get("ok") is not True:
            reason = result.get("reason")
            if not isinstance(reason, str) or not reason:
                reason = "invalid_result"
            return {
                "status": "failed",
                "reason": reason,
                "tool": name,
                "result": self._scrub(result),
            }
        self._record("toolrpc.execute", name, agent=effective_actor)
        return {"status": "ok", "tool": name, "result": self._scrub(result)}

    # ── internals ────────────────────────────────────────────────────────────

    @staticmethod
    async def _invoke_handler(spec: dict, args: dict):
        task = asyncio.current_task()
        active = spec["active_tasks"]
        if task is not None:
            active.add(task)
        try:
            return await spec["handler"](args)
        finally:
            if task is not None:
                active.discard(task)

    def _run_preflight(self, spec: dict, args: dict, name: str):
        preflight = spec.get("preflight")
        if preflight is None:
            return dict(args), None
        try:
            sanitized = preflight(dict(args))
        except ToolRPCValidationError as exc:
            return None, {"ok": False, "reason": exc.reason, "tool": name}
        except Exception:
            logger.warning("tool-rpc preflight failed: %s", name, exc_info=True)
            return None, {"ok": False, "reason": "validation_failed", "tool": name}
        if not isinstance(sanitized, Mapping):
            return None, {"ok": False, "reason": "validation_failed", "tool": name}
        return dict(sanitized), None

    def _scrub(self, obj):
        """Recursively mask any known secret value before it crosses to the sandbox."""
        if self._secrets is None:
            return obj
        if isinstance(obj, str):
            return self._secrets.redact(obj)
        if isinstance(obj, dict):
            return {self._scrub(k): self._scrub(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._scrub(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(self._scrub(v) for v in obj)
        if isinstance(obj, set):
            return {self._scrub(v) for v in obj}
        if isinstance(obj, frozenset):
            return frozenset(self._scrub(v) for v in obj)
        return obj

    def _kernel_denial(self, name: str, args: dict, actor: str) -> Optional[str]:
        """ORIZONT-24 K1 wave-3: ask the Action Kernel whether this gated tool may run.

        Returns a deny-reason string (block) or ``None`` (allow). Default-off: no kernel
        bound, or ``JARVIS_ACTION_KERNEL`` unset → ``None`` (unchanged behavior). Only the
        arg *keys* go in the payload, never values (which may carry secrets/PII).
        """
        if self._kernel is None:
            return None
        from agents.core.action_origin import current_action_origin
        from agents.core.kernel import Action, Verdict, kernel_enabled
        if not kernel_enabled():
            return None
        decision = self._kernel(Action(
            kind="tool.rpc", agent=actor,
            title=f"tool-rpc {name}",
            payload={"tool": name, "args_keys": sorted((args or {}).keys()), "target": name},
            origin=current_action_origin()))
        return decision.reason if decision.verdict is Verdict.DENY else None

    def _record(self, action: str, why: str, **meta) -> None:
        if self._audit is None:
            return
        try:
            if hasattr(self._audit, "record"):
                self._audit.record(actor="tool_rpc", action=action, why=why, metadata=meta)
            elif hasattr(self._audit, "log"):
                self._audit.log({"event": action, "why": why, **meta})
        except Exception:  # best-effort observability must not break the tool path
            logger.debug("tool-rpc audit sink failed", exc_info=True)
