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
  never silently land on the host. An opted-in machine or manual approval
  additionally crosses the ``terminal.exec`` contract and kernel GRANT.
  Unsupported cwd/timeout options are refused.
- ``local`` executes through ``LocalHostTransport`` only when
  ``JARVIS_TERMINAL_LOCAL_HOST`` is on AND the command parses to a plain argv
  (no shell operators) AND the ``terminal.exec`` contract admits it AND the
  Action Kernel (bound ``authorizer``, kernel flag on) GRANTs it. Any missing
  piece is a named refusal; with the flag off the refusal is byte-identical to
  the pre-transport behaviour.
- ``ssh`` executes through ``SshTransport`` on the same terms as ``local``:
  ``JARVIS_TERMINAL_SSH_HOST`` on, a plain argv, the ``terminal.exec``
  contract (against the roots the operator declared for that remote host) and
  an Action Kernel GRANT. It adds no dependency — OpenSSH is the client — and
  no credential store: the key is a file path the operator names, never a
  secret this process reads.

The runner performs no gating of its own beyond target policy + contract +
kernel: reach it through the gated ``terminal_run`` ToolRPC tool, which carries
the allowlist, ask-tier approval queue, and trusted-execution rail. Its injected
request check verifies the exact task, actor and live policy again after an
awaited kernel decision, immediately before handing off to the transport.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from agents.core.env_config import env_flag

from .targets import ALLOW, APPROVAL_REQUIRED, TargetDecision, TargetRegistry
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
SSH_HOST_FLAG = "JARVIS_TERMINAL_SSH_HOST"


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
        ssh_transport=None,
        authorizer: Callable[..., Any] | None = None,
        approval_check: Callable[[int], bool] | None = None,
        request_check: Callable[[int | None, dict], bool] | None = None,
        smart_approval_check: Callable[[int], bool] | None = None,
        owner_approval_check: Callable[[int], bool] | None = None,
        owner_kernel_check: Callable[..., Any] | None = None,
        consent_approval_check: Callable[[int], bool] | None = None,
        consent_kernel_check: Callable[..., Any] | None = None,
        legacy_kernel_check: Callable[..., Any] | None = None,
    ) -> None:
        if not isinstance(registry, TargetRegistry):
            raise ValueError("registry must be a TargetRegistry")
        if local_transport is not None and not callable(getattr(local_transport, "run", None)):
            raise TypeError("local_transport must expose an async run(argv, ...)")
        if ssh_transport is not None and not callable(getattr(ssh_transport, "run", None)):
            raise TypeError("ssh_transport must expose an async run(argv, ...)")
        if authorizer is not None and not callable(authorizer):
            raise TypeError("authorizer must be callable")
        if approval_check is not None and not callable(approval_check):
            raise TypeError("approval_check must be callable")
        if request_check is not None and not callable(request_check):
            raise TypeError("request_check must be callable")
        if smart_approval_check is not None and not callable(smart_approval_check):
            raise TypeError("smart_approval_check must be callable")
        if owner_approval_check is not None and not callable(owner_approval_check):
            raise TypeError("owner_approval_check must be callable")
        if owner_kernel_check is not None and not callable(owner_kernel_check):
            raise TypeError("owner_kernel_check must be callable")
        if consent_approval_check is not None and not callable(consent_approval_check):
            raise TypeError("consent_approval_check must be callable")
        if consent_kernel_check is not None and not callable(consent_kernel_check):
            raise TypeError("consent_kernel_check must be callable")
        if legacy_kernel_check is not None and not callable(legacy_kernel_check):
            raise TypeError("legacy_kernel_check must be callable")
        self._registry = registry
        self._sandbox = sandbox
        self._local_transport = local_transport
        self._ssh_transport = ssh_transport
        self._authorizer = authorizer
        self._approval_check = approval_check
        self._request_check = request_check
        self._smart_approval_check = smart_approval_check
        self._owner_approval_check = owner_approval_check
        self._owner_kernel_check = owner_kernel_check
        self._consent_approval_check = consent_approval_check
        self._consent_kernel_check = consent_kernel_check
        self._legacy_kernel_check = legacy_kernel_check

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

        request = {"target": target, "command": command}
        if cwd is not None:
            request["cwd"] = cwd
        if timeout is not None:
            request["timeout"] = timeout
        if not self._request_current(approved_task_id, request):
            return {"ok": False, "reason": "terminal_request_changed", "target": target_label}

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
        owner_marked = self._is_owner_approval(approved_task_id)
        consent_marked = self._is_consent_approval(approved_task_id)
        smart_marked = self._is_smart_approval(approved_task_id)
        legacy_manual = (decision.backend == "docker"
                         and type(approved_task_id) is int and approved_task_id > 0
                         and not (smart_marked or owner_marked or consent_marked))
        if decision.outcome not in {APPROVAL_REQUIRED, ALLOW}:
            return {"ok": False, "reason": decision.reason, **base}
        if owner_marked and consent_marked:
            return {"ok": False, "reason": "mixed_approval_authority", **base}
        if (owner_marked or consent_marked) and self._request_check is None:
            return {"ok": False, "reason": "owner_request_check_unbound" if owner_marked
                    else "consent_request_check_unbound", **base}
        if legacy_manual and self._request_check is None:
            return {"ok": False, "reason": "terminal_request_check_unbound", **base}
        if decision.outcome == APPROVAL_REQUIRED or owner_marked or consent_marked or legacy_manual:
            durable = self._durable_approval(approved_task_id)
            if durable is not None:
                return {"ok": False, "reason": durable, **base}

        if decision.backend == "docker":
            if owner_marked or consent_marked:
                from agents.core.sandbox import Sandbox

                if type(self._sandbox) is not Sandbox:
                    return {"ok": False, "reason": "consent_transport_unsupported" if consent_marked
                            else "owner_transport_unsupported", **base}
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
            if smart_marked or owner_marked or consent_marked or legacy_manual:
                # Sandbox executes sh -c in /workspace with its configured
                # timeout. Do not approve options this transport cannot honor.
                actual_timeout = getattr(self._sandbox, "timeout", None)
                if (cwd is not None and cwd != "/workspace") or (
                    timeout is not None and timeout != actual_timeout
                ):
                    return {"ok": False, "reason": "docker_runtime_options_unsupported", **base}
                legacy_runtime_names = ('timeout', 'docker_image', 'max_memory_mb',
                                        'work_dir', 'allow_subprocess')
                legacy_runtime = (tuple(getattr(self._sandbox, name, None)
                                        for name in legacy_runtime_names)
                                  if legacy_manual else None)
                payload = terminal_exec_payload(
                    target=base["target"], backend="docker", argv=["sh", "-c", command],
                    cwd="/workspace", roots=["/workspace"], timeout=actual_timeout,
                    approved_task_id=approved_task_id, max_timeout=600,
                )
                verdict = TERMINAL_EXEC_CONTRACT.evaluate(payload)
                if not verdict.admissible:
                    return {"ok": False, "reason": f"contract_denied:{verdict.reason}", **base}
                owner_kernel_rechecks: list[Callable[[], bool]] = []
                consent_kernel_rechecks: list[Callable[[], bool]] = []
                legacy_kernel_rechecks: list[Callable[[], bool]] = []
                kernel_refusal = await self._kernel_grant(
                    decision.agent, payload, request=request,
                    owner_rechecks=owner_kernel_rechecks if owner_marked else None,
                    consent_rechecks=consent_kernel_rechecks if consent_marked else None,
                    legacy_rechecks=legacy_kernel_rechecks if legacy_manual else None,
                )
                if kernel_refusal is not None:
                    return {"ok": False, **kernel_refusal, **base}
                if not self._kernel_live():
                    return {"ok": False, "reason": "action_kernel_disabled", **base}
                if getattr(self._sandbox, 'timeout', None) != actual_timeout:
                    return {"ok": False, "reason": "docker_runtime_changed", **base}
                if (legacy_manual and tuple(getattr(self._sandbox, name, None)
                                            for name in legacy_runtime_names) != legacy_runtime):
                    return {"ok": False, "reason": "docker_runtime_changed", **base}
            if not self._request_current(approved_task_id, request):
                return {"ok": False, "reason": "terminal_request_changed", **base}
            active = self._sandbox.active_backend()
            if active != "docker":
                return {"ok": False, "reason": f"docker_backend_unavailable:{active}", **base}
            if consent_marked:
                from .consent_dispatch import ConsentDispatchScope, bind_consent_dispatch

                expected_runtime = (self._sandbox.timeout, self._sandbox.docker_image,
                                    self._sandbox.max_memory_mb, str(self._sandbox.work_dir),
                                    self._sandbox.allow_subprocess)

                def current():
                    return (self._consent_current(approved_task_id, request)
                            and self._policy_current(decision)
                            and len(consent_kernel_rechecks) == 1
                            and consent_kernel_rechecks[0]()
                            and self._kernel_live() and self._sandbox.active_backend() == "docker"
                            and (self._sandbox.timeout, self._sandbox.docker_image,
                                 self._sandbox.max_memory_mb, str(self._sandbox.work_dir),
                                 self._sandbox.allow_subprocess) == expected_runtime)

                scope = ConsentDispatchScope(
                    approved_task_id, "docker", base["target"], ("sh", "-c", command),
                    "/workspace", self._sandbox.timeout, self._sandbox, dict(request), current,
                )
                context = bind_consent_dispatch(scope)
            elif owner_marked:
                from .owner_once_dispatch import OwnerOnceDispatchScope, bind_owner_once_dispatch

                expected_runtime = (self._sandbox.timeout, self._sandbox.docker_image,
                                    self._sandbox.max_memory_mb, str(self._sandbox.work_dir),
                                    self._sandbox.allow_subprocess)

                def current():
                    return (self._owner_current(approved_task_id, request)
                            and self._policy_current(decision)
                            and len(owner_kernel_rechecks) == 1
                            and owner_kernel_rechecks[0]()
                            and self._kernel_live() and self._sandbox.active_backend() == "docker"
                            and (self._sandbox.timeout, self._sandbox.docker_image,
                                 self._sandbox.max_memory_mb, str(self._sandbox.work_dir),
                                 self._sandbox.allow_subprocess) == expected_runtime)

                scope = OwnerOnceDispatchScope(
                    approved_task_id, "docker", base["target"], ("sh", "-c", command),
                    "/workspace", self._sandbox.timeout, self._sandbox, dict(request), current,
                )
                context = bind_owner_once_dispatch(scope)
            elif legacy_manual:
                from .legacy_terminal_dispatch import (
                    LegacyTerminalDispatchScope,
                    bind_legacy_terminal_dispatch,
                )

                def current():
                    return (self._manual_current(approved_task_id, request)
                            and self._policy_current(decision)
                            and len(legacy_kernel_rechecks) == 1
                            and legacy_kernel_rechecks[0]()
                            and self._kernel_live() and self._sandbox.active_backend() == 'docker'
                            and tuple(getattr(self._sandbox, name, None)
                                      for name in legacy_runtime_names) == legacy_runtime)

                if not current():
                    return {"ok": False, "reason": "legacy_terminal_dispatch_unavailable", **base}
                scope = LegacyTerminalDispatchScope(
                    approved_task_id, 'docker', base['target'], ('sh', '-c', command),
                    '/workspace', actual_timeout, self._sandbox, dict(request), current,
                )
                context = bind_legacy_terminal_dispatch(scope)
            else:
                context = nullcontext()
            with context:
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
                request=request,
                owner_marked=owner_marked,
                consent_marked=consent_marked,
                expected_decision=decision,
            )
        if decision.backend == "ssh":
            if not env_flag(SSH_HOST_FLAG):
                return {"ok": False, "reason": "ssh_transport_not_implemented", **base}
            return await self._run_ssh(
                base,
                agent=decision.agent,
                command=command,
                approved_task_id=approved_task_id,
                cwd=cwd,
                timeout=timeout,
                request=request,
                owner_marked=owner_marked,
                consent_marked=consent_marked,
                expected_decision=decision,
            )
        return {"ok": False, "reason": "backend_unknown", **base}

    def _request_current(self, task_id: int | None, request: dict) -> bool:
        if self._request_check is None:
            return True
        try:
            return self._request_check(task_id, dict(request)) is True
        except Exception:
            return False

    def _is_smart_approval(self, task_id: int | None) -> bool:
        if self._smart_approval_check is None or task_id is None:
            return False
        try:
            return self._smart_approval_check(task_id) is True
        except Exception:
            # A broken classifier cannot downgrade an operation to the
            # legacy Docker path; require the stricter contract/kernel path.
            return True

    def _is_owner_approval(self, task_id: int | None) -> bool:
        if self._owner_approval_check is None or type(task_id) is not int or task_id <= 0:
            return False
        try:
            return self._owner_approval_check(task_id) is True
        except Exception:
            # Unknown owner marker is never permission to use legacy Docker.
            return True

    def _is_consent_approval(self, task_id: int | None) -> bool:
        from agents.core.autonomy.consent_execution import consent_scope_present

        if consent_scope_present():
            return True
        if self._consent_approval_check is None or type(task_id) is not int or task_id <= 0:
            return False
        try:
            return self._consent_approval_check(task_id) is True
        except Exception:
            # A failed marker lookup must not reach the ordinary Docker lane.
            return True

    def _consent_current(self, task_id: int, request: dict) -> bool:
        from agents.core.autonomy.consent_execution import consent_current

        if (not self._is_consent_approval(task_id) or self._is_owner_approval(task_id)
                or self._approval_check is None
                or not self._request_current(task_id, request)
                or not consent_current(task_id)):
            return False
        try:
            return self._approval_check(task_id) is True
        except Exception:
            return False

    def _owner_current(self, task_id: int, request: dict) -> bool:
        if (not self._is_owner_approval(task_id) or self._approval_check is None
                or not self._request_current(task_id, request)):
            return False
        try:
            return self._approval_check(task_id) is True
        except Exception:
            return False

    def _manual_current(self, task_id: int, request: dict) -> bool:
        if (type(task_id) is not int or task_id <= 0 or self._request_check is None
                or self._is_smart_approval(task_id) or self._is_owner_approval(task_id)
                or self._is_consent_approval(task_id)
                or not self._request_current(task_id, request)):
            return False
        return self._durable_approval(task_id) is None

    def _policy_current(self, expected: TargetDecision) -> bool:
        """Audit and recheck the exact target decision at physical dispatch."""
        try:
            current = self._registry.authorize(
                expected.target, expected.agent, expected.capability,
                correlation_id=expected.correlation_id,
            )
        except Exception:
            return False
        return current == expected and current.outcome in {ALLOW, APPROVAL_REQUIRED}

    @staticmethod
    def _kernel_live() -> bool:
        from agents.core.kernel import kernel_enabled

        return kernel_enabled()

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
        request: dict,
        owner_marked: bool = False,
        consent_marked: bool = False,
        expected_decision: TargetDecision | None = None,
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
        if owner_marked or consent_marked:
            from .local_transport import LocalHostTransport

            if type(transport) is not LocalHostTransport:
                return {"ok": False, "reason": "consent_transport_unsupported" if consent_marked
                        else "owner_transport_unsupported", **base}

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

        owner_kernel_rechecks: list[Callable[[], bool]] = []
        consent_kernel_rechecks: list[Callable[[], bool]] = []
        kernel_refusal = await self._kernel_grant(
            agent, payload, request=request,
            owner_rechecks=owner_kernel_rechecks if owner_marked else None,
            consent_rechecks=consent_kernel_rechecks if consent_marked else None,
        )
        if kernel_refusal is not None:
            return {"ok": False, **kernel_refusal, **base}
        if not self._kernel_live() or not env_flag(LOCAL_HOST_FLAG):
            return {"ok": False, "reason": "terminal_transport_revoked", **base}

        if not self._request_current(approved_task_id, request):
            return {"ok": False, "reason": "terminal_request_changed", **base}

        if consent_marked:
            from .consent_dispatch import ConsentDispatchScope, bind_consent_dispatch

            expected_roots = transport.roots

            def current():
                return (self._consent_current(approved_task_id, request)
                        and expected_decision is not None
                        and self._policy_current(expected_decision)
                        and len(consent_kernel_rechecks) == 1
                        and consent_kernel_rechecks[0]()
                        and self._kernel_live() and env_flag(LOCAL_HOST_FLAG)
                        and transport.roots == expected_roots
                        and transport.resolve_cwd(cwd) == workdir)

            scope = ConsentDispatchScope(
                approved_task_id, "local", base["target"], tuple(argv), str(workdir),
                bounded, transport, dict(request), current,
            )
            context = bind_consent_dispatch(scope)
        elif owner_marked:
            from .owner_once_dispatch import OwnerOnceDispatchScope, bind_owner_once_dispatch

            expected_roots = transport.roots

            def current():
                return (self._owner_current(approved_task_id, request)
                        and expected_decision is not None
                        and self._policy_current(expected_decision)
                        and len(owner_kernel_rechecks) == 1
                        and owner_kernel_rechecks[0]()
                        and self._kernel_live() and env_flag(LOCAL_HOST_FLAG)
                        and transport.roots == expected_roots
                        and transport.resolve_cwd(cwd) == workdir)

            scope = OwnerOnceDispatchScope(
                approved_task_id, "local", base["target"], tuple(argv), str(workdir),
                bounded, transport, dict(request), current,
            )
            context = bind_owner_once_dispatch(scope)
        else:
            context = nullcontext()
        with context:
            result = await transport.run(argv, cwd=str(workdir), timeout=bounded)
        return {**result, **base, "approved_task_id": approved_task_id}

    async def _run_ssh(
        self,
        base: dict,
        *,
        agent: str,
        command: str,
        approved_task_id: int | None,
        cwd: str | None,
        timeout: int | None,
        request: dict,
        owner_marked: bool = False,
        consent_marked: bool = False,
        expected_decision: TargetDecision | None = None,
    ) -> dict:
        """Same gate order as the local host; only the wire at the end differs."""
        argv, refusal = parse_argv(command)
        if refusal is not None:
            return {"ok": False, "reason": refusal, **base}
        transport = self._ssh_transport
        if transport is None:
            from .ssh_transport import SshTransport

            try:
                transport = SshTransport.from_env()
            except (ValueError, OSError):
                return {"ok": False, "reason": "ssh_transport_unavailable", **base}
            self._ssh_transport = transport
        if owner_marked or consent_marked:
            from .ssh_transport import SshTransport

            if type(transport) is not SshTransport:
                return {"ok": False, "reason": "consent_transport_unsupported" if consent_marked
                        else "owner_transport_unsupported", **base}

        host = transport.host_for(base["target"])
        if host is None:
            return {"ok": False, "reason": "ssh_target_not_declared", **base}
        bounded = transport.bound_timeout(timeout)
        if bounded is None:
            return {"ok": False, "reason": "invalid_timeout", **base}
        workdir = transport.resolve_cwd(host.target, cwd)
        if workdir is None:
            return {"ok": False, "reason": "cwd_outside_roots", **base}

        payload = terminal_exec_payload(
            target=base["target"],
            backend="ssh",
            argv=argv,
            cwd=workdir,
            roots=host.roots,
            timeout=bounded,
            approved_task_id=approved_task_id,
            max_timeout=transport.max_timeout,
        )
        verdict = TERMINAL_EXEC_CONTRACT.evaluate(payload)
        if not verdict.admissible:
            return {"ok": False, "reason": f"contract_denied:{verdict.reason}", **base}

        owner_kernel_rechecks: list[Callable[[], bool]] = []
        consent_kernel_rechecks: list[Callable[[], bool]] = []
        kernel_refusal = await self._kernel_grant(
            agent, payload, request=request,
            owner_rechecks=owner_kernel_rechecks if owner_marked else None,
            consent_rechecks=consent_kernel_rechecks if consent_marked else None,
        )
        if kernel_refusal is not None:
            return {"ok": False, **kernel_refusal, **base}
        if not self._kernel_live() or not env_flag(SSH_HOST_FLAG):
            return {"ok": False, "reason": "terminal_transport_revoked", **base}

        if not self._request_current(approved_task_id, request):
            return {"ok": False, "reason": "terminal_request_changed", **base}

        if consent_marked:
            from .consent_dispatch import ConsentDispatchScope, bind_consent_dispatch

            expected_known_hosts = transport._known_hosts
            expected_ssh_path = transport.ssh_path
            expected_connect_timeout = transport.connect_timeout

            def current():
                return (self._consent_current(approved_task_id, request)
                        and expected_decision is not None
                        and self._policy_current(expected_decision)
                        and len(consent_kernel_rechecks) == 1
                        and consent_kernel_rechecks[0]()
                        and self._kernel_live() and env_flag(SSH_HOST_FLAG)
                        and transport.host_for(host.target) == host
                        and transport._known_hosts == expected_known_hosts
                        and transport.ssh_path == expected_ssh_path
                        and transport.connect_timeout == expected_connect_timeout
                        and transport.resolve_cwd(host.target, cwd) == workdir)

            scope = ConsentDispatchScope(
                approved_task_id, "ssh", base["target"], tuple(argv), workdir,
                bounded, transport, dict(request), current,
            )
            context = bind_consent_dispatch(scope)
        elif owner_marked:
            from .owner_once_dispatch import OwnerOnceDispatchScope, bind_owner_once_dispatch

            expected_known_hosts = transport._known_hosts
            expected_ssh_path = transport.ssh_path
            expected_connect_timeout = transport.connect_timeout

            def current():
                return (self._owner_current(approved_task_id, request)
                        and expected_decision is not None
                        and self._policy_current(expected_decision)
                        and len(owner_kernel_rechecks) == 1
                        and owner_kernel_rechecks[0]()
                        and self._kernel_live() and env_flag(SSH_HOST_FLAG)
                        and transport.host_for(host.target) == host
                        and transport._known_hosts == expected_known_hosts
                        and transport.ssh_path == expected_ssh_path
                        and transport.connect_timeout == expected_connect_timeout
                        and transport.resolve_cwd(host.target, cwd) == workdir)

            scope = OwnerOnceDispatchScope(
                approved_task_id, "ssh", base["target"], tuple(argv), workdir,
                bounded, transport, dict(request), current,
            )
            context = bind_owner_once_dispatch(scope)
        else:
            context = nullcontext()
        with context:
            result = await transport.run(argv, target=host.target, cwd=workdir, timeout=bounded)
        return {**result, **base, "approved_task_id": approved_task_id}

    async def _kernel_grant(
        self, agent: str, payload: dict, *, request: dict | None = None,
        owner_rechecks: list[Callable[[], bool]] | None = None,
        consent_rechecks: list[Callable[[], bool]] | None = None,
        legacy_rechecks: list[Callable[[], bool]] | None = None,
    ) -> dict | None:
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
        approval_check = None
        task_id = payload.get('approved_task_id')
        owner_marked = self._is_owner_approval(task_id)
        consent_marked = self._is_consent_approval(task_id)
        legacy_manual = legacy_rechecks is not None
        if owner_marked and consent_marked:
            return {"reason": "mixed_approval_authority"}
        if legacy_manual and (owner_marked or consent_marked or self._is_smart_approval(task_id)):
            return {"reason": "mixed_approval_authority"}
        if (request is not None and self._request_check is not None
                and (self._is_smart_approval(task_id) or owner_marked or consent_marked
                     or legacy_manual)):
            from copy import deepcopy

            expected = deepcopy(action)
            reviewed_request = dict(request)

            def approval_check(candidate):
                return (candidate == expected and self._request_current(task_id, reviewed_request)
                        and ((owner_marked and self._owner_current(task_id, reviewed_request))
                             or (consent_marked and self._consent_current(task_id, reviewed_request))
                             or (not owner_marked and not consent_marked
                                 and (self._manual_current(task_id, reviewed_request)
                                      if legacy_manual else self._is_smart_approval(task_id)))))

        if owner_marked and (self._owner_kernel_check is None or owner_rechecks is None
                             or approval_check is None):
            return {"reason": "kernel_revalidator_unavailable"}
        if consent_marked and (self._consent_kernel_check is None or consent_rechecks is None
                               or approval_check is None):
            return {"reason": "kernel_revalidator_unavailable"}
        if legacy_manual and (self._legacy_kernel_check is None or approval_check is None):
            return {"reason": "kernel_revalidator_unavailable"}

        capability = Capability(name=TERMINAL_EXEC_KIND)

        try:
            if approval_check is None:
                decision = self._authorizer(action, capability=capability)
            else:
                decision = self._authorizer(action, capability=capability,
                                            approval_check=approval_check)
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
        if owner_marked or consent_marked or legacy_manual:
            from copy import deepcopy
            from inspect import isawaitable, iscoroutine

            bound_action = deepcopy(action)
            bound_capability = capability
            bound_approval_check = approval_check
            checker = (self._owner_kernel_check if owner_marked else
                       self._consent_kernel_check if consent_marked else
                       self._legacy_kernel_check)

            def recheck() -> bool:
                try:
                    candidate = deepcopy(bound_action)
                    if bound_approval_check(candidate) is not True:
                        return False
                    if legacy_manual and current_action_origin() != bound_action.origin:
                        return False
                    fresh = checker(candidate, capability=bound_capability,
                                    approval_check=bound_approval_check)
                    if isawaitable(fresh):
                        if iscoroutine(fresh):
                            fresh.close()
                        return False
                    return (type(fresh) is Decision and fresh.verdict is Verdict.GRANT
                            and candidate == bound_action)
                except Exception:
                    return False

            (owner_rechecks if owner_marked else
             consent_rechecks if consent_marked else legacy_rechecks).append(recheck)
        return None


__all__ = ["GovernedTargetRunner", "LOCAL_HOST_FLAG", "SSH_HOST_FLAG", "parse_argv"]
