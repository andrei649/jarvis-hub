"""Governed execution transport for named terminal targets (GAP-9).

`targets.py` shipped the whole policy plane — named targets, per-agent/
per-capability authorization, a tamper-evident audit chain — but nothing ever
executed through it: ``TargetRegistry`` had no production consumer and no
transport existed. This module is that transport, deliberately minimal:

- ``authorize`` runs FIRST, so the audit chain records every decision before
  any process can exist; DENY and APPROVAL_REQUIRED never spawn anything.
- The only wired backend is ``docker`` — the sole default-enabled target
  (``isolated-sandbox``) — executed through the existing ``Sandbox`` engine
  with a hard ``active_backend() == "docker"`` re-check so a docker-target
  command can never silently land on the host.
- ``local`` and ``ssh`` return explicit not-implemented refusals (both
  inventory targets are disabled by default anyway). Shipping SSH means a new
  hash-pinned dependency plus a credential design that does not exist yet;
  saying so beats pretending.

The runner performs no gating of its own beyond target policy: reach it
through the gated ``terminal_run`` ToolRPC tool, which carries the allowlist,
kernel mediation, ask-tier approval queue, and trusted-execution rail.
"""

from __future__ import annotations

from .targets import ALLOW, APPROVAL_REQUIRED, TargetRegistry

_MAX_COMMAND_CHARS = 4000
_MAX_OUTPUT_CHARS = 16_000


class GovernedTargetRunner:
    """Authorize against the target policy plane, then execute — docker only."""

    def __init__(self, registry: TargetRegistry, sandbox) -> None:
        if not isinstance(registry, TargetRegistry):
            raise ValueError("registry must be a TargetRegistry")
        self._registry = registry
        self._sandbox = sandbox

    async def run(
        self,
        *,
        target: str,
        agent: str,
        command: str,
        capability: str = "terminal.exec",
        correlation_id: str | None = None,
    ) -> dict:
        if not isinstance(command, str) or not command.strip():
            return {"ok": False, "reason": "empty_command", "target": str(target)[:64]}
        if len(command) > _MAX_COMMAND_CHARS:
            return {"ok": False, "reason": "command_too_long", "target": str(target)[:64]}

        # Policy first: the audit chain records the decision before any
        # process exists, and a refusal never spawns one.
        try:
            decision = self._registry.authorize(
                target, agent, capability, correlation_id=correlation_id
            )
        except ValueError as exc:
            return {"ok": False, "reason": f"invalid_request:{exc}"[:200], "target": ""}
        base = {
            "target": decision.target,
            "backend": decision.backend,
            "outcome": decision.outcome,
        }
        if decision.outcome == APPROVAL_REQUIRED:
            return {"ok": False, "reason": "target_policy_requires_approval", **base}
        if decision.outcome != ALLOW:
            return {"ok": False, "reason": decision.reason, **base}

        if decision.backend == "docker":
            # Never let a docker-target command silently degrade onto the
            # host: the sandbox engine's active backend must actually be
            # docker at execution time.
            active = self._sandbox.active_backend()
            if active != "docker":
                return {
                    "ok": False,
                    "reason": f"docker_backend_unavailable:{active}",
                    **base,
                }
            result = await self._sandbox.execute_shell(command)
            return {
                "ok": result.exit_code == 0,
                "exit_code": result.exit_code,
                "stdout": result.stdout[:_MAX_OUTPUT_CHARS],
                "stderr": result.stderr[:_MAX_OUTPUT_CHARS],
                "duration": result.duration,
                **base,
            }
        if decision.backend == "local":
            return {"ok": False, "reason": "local_transport_not_implemented", **base}
        if decision.backend == "ssh":
            return {"ok": False, "reason": "ssh_transport_not_implemented", **base}
        return {"ok": False, "reason": "backend_unknown", **base}


__all__ = ["GovernedTargetRunner"]
