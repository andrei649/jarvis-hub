"""Governed execution transport for named terminal targets (GAP-9 + local host).

`targets.py` shipped the whole policy plane — named targets, per-agent/
per-capability authorization, a tamper-evident audit chain — but nothing ever
executed through it: ``TargetRegistry`` had no production consumer and no
transport existed. This module is that transport, deliberately minimal:

- ``HARDLINE`` (``terminal_contract.py``) is screened FIRST — before authorize,
  before any policy or autonomy level, for every backend including docker. A
  hardline hit never reaches the audit chain as a policy decision: there is
  nothing to decide.
- ``authorize`` runs next, so the audit chain records every decision before
  any process can exist; DENY never spawns. APPROVAL_REQUIRED spawns only when
  the caller presents a durable accepted task (``approved_task_id``) that the
  injected ``approval_check`` confirms — the runner never decides approval
  itself.
- ``docker`` executes through the existing ``Sandbox`` engine with a hard
  ``active_backend() == "docker"`` re-check so a docker-target command can
  never silently land on the host.
- ``local`` executes through ``LocalHostTransport`` only when
  ``JARVIS_TERMINAL_LOCAL_HOST`` is on AND the command parses to a plain argv
  (no shell operators) AND the ``terminal.exec`` contract admits it AND the
  Action Kernel (bound ``authorizer``, kernel flag on) GRANTs it. Any missing
  piece is a named refusal; with the flag off the refusal is byte-identical to
  the pre-transport behaviour.
- ``ssh`` returns an explicit not-implemented refusal. Shipping SSH means a
  new hash-pinned dependency plus a credential design that does not exist
  yet; saying so beats pretending.

The runner performs no gating of its own beyond target policy + contract +
kernel: reach it through the gated ``terminal_run`` ToolRPC tool, which carries
the allowlist, ask-tier approval queue, and trusted-execution rail.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Callable
from typing import Any

from agents.core.env_config import env_flag

from .targets import ALLOW, APPROVAL_REQUIRED, TargetRegistry
from .terminal_contract import (
    TERMINAL_EXEC_CONTRACT,
    TERMINAL_EXEC_KIND,
    hardline_match,
    terminal_exec_payload,
)

_MAX_COMMAND_CHARS = 4000
_MAX_OUTPUT_CHARS = 16_000
_SHELL_PUNCTUATION = frozenset("();<>|&")
LOCAL_HOST_FLAG = "JARVIS_TERMINAL_LOCAL_HOST"


def parse_argv(command: str, *, windows: bool | None = None) -> tuple[list[str] | None, str | None]:
    """Split a command string into an argv; refuse anything that needs a shell.

    Returns ``(argv, None)`` or ``(None, reason)``. Unquoted shell operators
    (``|``, ``;``, ``&&``, ``>``, ``<`` …) become standalone punctuation tokens
    under ``punctuation_chars`` and are refused as ``shell_syntax_unsupported``:
    the local transport never runs a shell, so honouring them is impossible and
    silently passing them as literal arguments would be misleading. Quoted
    operators inside an argument stay literal and pass. On Windows a backslash
    is a path separator, not an escape, so it is preserved literally.
    """
    if windows is None:
        windows = os.name == "nt"
    if windows:
        command = command.replace("\\", "\\\\")
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None, "command_unparseable"
    if not tokens:
        return None, "empty_command"
    for token in tokens:
        if all(char in _SHELL_PUNCTUATION for char in token):
            return None, "shell_syntax_unsupported"
        if "`" in token or "$(" in token:
            return None, "shell_syntax_unsupported"
    return tokens, None


class GovernedTargetRunner:
    """Authorize against the target policy plane, then execute — docker or local host."""

    def __init__(
        self,
        registry: TargetRegistry,
        sandbox,
        *,
        local_transport=None,
        authorizer: Callable[..., Any] | None = None,
        approval_check: Callable[[int], bool] | None = None,
    ) -> None:
        if not isinstance(registry, TargetRegistry):
            raise ValueError("registry must be a TargetRegistry")
        if local_transport is not None and not callable(getattr(local_transport, "run", None)):
            raise TypeError("local_transport must expose an async run(argv, ...)")
        if authorizer is not None and not callable(authorizer):
            raise TypeError("authorizer must be callable")
        if approval_check is not None and not callable(approval_check):
            raise TypeError("approval_check must be callable")
        self._registry = registry
        self._sandbox = sandbox
        self._local_transport = local_transport
        self._authorizer = authorizer
        self._approval_check = approval_check

    async def run(
        self,
        *,
        target: str,
        agent: str,
        command: str,
        capability: str = "terminal.exec",
        correlation_id: str | None = None,
        approved_task_id: int | None = None,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> dict:
        target_label = str(target)[:64]
        if not isinstance(command, str) or not command.strip():
            return {"ok": False, "reason": "empty_command", "target": target_label}
        if len(command) > _MAX_COMMAND_CHARS:
            return {"ok": False, "reason": "command_too_long", "target": target_label}

        # Hardline first: a catastrophic command is refused before any policy,
        # autonomy level or approval can be consulted — and before the audit
        # chain records a decision, because there is none to record.
        hardline = hardline_match(command)
        if hardline is not None:
            return {
                "ok": False,
                "reason": f"hardline_denied:{hardline}",
                "target": target_label,
            }

        # Policy next: the audit chain records the decision before any
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
            durable = self._durable_approval(approved_task_id)
            if durable is not None:
                return {"ok": False, "reason": durable, **base}
        elif decision.outcome != ALLOW:
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
            if not env_flag(LOCAL_HOST_FLAG):
                return {"ok": False, "reason": "local_transport_not_implemented", **base}
            return await self._run_local(
                base,
                agent=decision.agent,
                command=command,
                approved_task_id=approved_task_id,
                cwd=cwd,
                timeout=timeout,
            )
        if decision.backend == "ssh":
            return {"ok": False, "reason": "ssh_transport_not_implemented", **base}
        return {"ok": False, "reason": "backend_unknown", **base}

    def _durable_approval(self, approved_task_id: int | None) -> str | None:
        """Return a refusal reason unless a durable accepted task is confirmed."""
        if approved_task_id is None:
            return "target_policy_requires_approval"
        if isinstance(approved_task_id, bool) or not isinstance(approved_task_id, int) \
                or approved_task_id <= 0:
            return "target_policy_requires_approval"
        if self._approval_check is None:
            return "approval_check_unbound"
        try:
            confirmed = self._approval_check(approved_task_id) is True
        except Exception:
            confirmed = False
        return None if confirmed else "approval_not_durable"

    async def _run_local(
        self,
        base: dict,
        *,
        agent: str,
        command: str,
        approved_task_id: int | None,
        cwd: str | None,
        timeout: int | None,
    ) -> dict:
        argv, refusal = parse_argv(command)
        if refusal is not None:
            return {"ok": False, "reason": refusal, **base}
        transport = self._local_transport
        if transport is None:
            from .local_transport import LocalHostTransport

            try:
                transport = LocalHostTransport.from_env()
            except (ValueError, OSError):
                return {"ok": False, "reason": "local_transport_unavailable", **base}
            self._local_transport = transport

        bounded = transport.bound_timeout(timeout)
        if bounded is None:
            return {"ok": False, "reason": "invalid_timeout", **base}
        workdir = transport.resolve_cwd(cwd)
        if workdir is None:
            return {"ok": False, "reason": "cwd_outside_roots", **base}

        payload = terminal_exec_payload(
            target=base["target"],
            backend="local",
            argv=argv,
            cwd=str(workdir),
            roots=transport.roots,
            timeout=bounded,
            approved_task_id=approved_task_id,
            max_timeout=transport.max_timeout,
        )
        verdict = TERMINAL_EXEC_CONTRACT.evaluate(payload)
        if not verdict.admissible:
            return {"ok": False, "reason": f"contract_denied:{verdict.reason}", **base}

        kernel_refusal = await self._kernel_grant(agent, payload)
        if kernel_refusal is not None:
            return {"ok": False, **kernel_refusal, **base}

        result = await transport.run(argv, cwd=str(workdir), timeout=bounded)
        return {**result, **base, "approved_task_id": approved_task_id}

    async def _kernel_grant(self, agent: str, payload: dict) -> dict | None:
        """Cross the Action Kernel; return a refusal dict unless it GRANTs."""
        from agents.core.action_origin import current_action_origin
        from agents.core.kernel import Action, Capability, Decision, Verdict, kernel_enabled

        if self._authorizer is None:
            return {"reason": "kernel_unavailable"}
        if not kernel_enabled():
            return {"reason": "action_kernel_disabled"}
        action = Action(
            kind=TERMINAL_EXEC_KIND,
            agent=agent,
            title=f"terminal.exec on {payload['target']}",
            payload=dict(payload),
            origin=current_action_origin(),
        )
        try:
            decision = self._authorizer(action, capability=Capability(name=TERMINAL_EXEC_KIND))
            if hasattr(decision, "__await__"):
                decision = await decision
        except Exception:
            return {"reason": "kernel_error"}
        if not isinstance(decision, Decision):
            return {"reason": "kernel_error"}
        if decision.verdict is Verdict.DENY:
            return {"reason": "kernel_denied", "detail": str(decision.reason or "")[:200]}
        if decision.verdict is not Verdict.GRANT:
            return {"reason": "kernel_queued", "detail": str(decision.reason or "")[:200]}
        return None


__all__ = ["GovernedTargetRunner", "LOCAL_HOST_FLAG", "parse_argv"]
