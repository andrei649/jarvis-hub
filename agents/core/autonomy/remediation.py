"""
remediation.py — executes APPROVED autonomy remediation tasks.

The Proactive OS Observer proposes `restart_service` tasks (tier-3, ASK → the
decision inbox). Once a human taps *Approve*, the autonomy worker runs the task
through this runner so the "Sir, Docker is down — restart it?" loop actually
*completes* instead of falling through to the LLM fallback.

Restarting a **host** service is a different trust domain from the Docker code
sandbox (`core/sandbox.py`): you cannot restart a host daemon from inside a
`--network none --read-only` container — that's the whole point of isolation.
So host control is guarded by four independent layers (human approval is a
fifth, already applied upstream):

  1. **Allowlist** — only services in the allowlist can be restarted, and we run
     the *allowlisted argv*, never a `cmd` string from the task payload (which a
     compromised proposal could poison). The proposal may *suggest*; only the
     allowlist *authorizes*.
  2. **Permission gate** — the task's agent must be served by the
     `system-control` plugin (steve / ultron / jarvis by default).
  3. **No shell** — commands run via `asyncio.create_subprocess_exec(*argv)`, so
     there is no shell interpolation and nothing to inject.
  4. **Bounded + audited** — every attempt has a timeout, a recovery probe, and
     an audit-log entry.

Everything I/O is injectable (`exec_fn`, `probe_fn`) so the whole runner is
unit-tested offline without spawning processes or opening sockets.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from ..automation_contracts import (
    ContractTemplate,
    contract_denial,
    field_present,
    one_of,
    predicate,
)

logger = logging.getLogger("jarvis.autonomy.remediation")


@dataclass
class ExecResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class ServiceCommand:
    """An allowlisted restart command for one service.

    `argv` is run literally (no shell). `detach=True` is for daemons that run in
    the foreground (e.g. `ollama serve`) — they are started in a new session and
    not waited on; success is then judged purely by the recovery probe.
    """
    argv: list[str]
    detach: bool = False
    verify_host: str = "127.0.0.1"
    verify_port: Optional[int] = None


# Host- and init-system-specific — edit for your machine. Defaults assume the
# cabinet's Docker-hosted services (Pi 5: Qdrant/Neo4j/n8n) + a foreground
# Ollama. `docker restart <name>` is portable and returns promptly; verify ports
# match `observer.default_probes()`.
DEFAULT_ALLOWLIST: dict[str, ServiceCommand] = {
    "ollama": ServiceCommand(["ollama", "serve"], detach=True, verify_port=11434),
    "qdrant": ServiceCommand(["docker", "restart", "qdrant"], verify_port=6333),
    "neo4j":  ServiceCommand(["docker", "restart", "neo4j"], verify_port=7474),
    "n8n":    ServiceCommand(["docker", "restart", "n8n"], verify_port=5678),
    "docker": ServiceCommand(["systemctl", "restart", "docker"]),  # the daemon itself
}


def _host_target_safe(view, now) -> bool:
    target = str(view.get("target") or view.get("service") or view.get("model") or "").strip()
    return "\x00" not in target and len(target) <= 240


def _host_control_contract_template() -> ContractTemplate:
    return ContractTemplate(
        kind="host.control",
        description="Host subprocess control gate for remediation and local model control.",
        constraints=(
            field_present("action", "agent"),
            one_of("action", {
                "restart_service",
                "lmstudio.start",
                "lmstudio.load",
                "lmstudio.unload",
                "ollama.start",
                "ollama.load",
                "ollama.unload",
            }),
            predicate("host_target_safe", _host_target_safe, reason="invalid_host_target"),
        ),
    )


HOST_CONTROL_CONTRACT_KIND = "host.control"
HOST_CONTROL_CONTRACT = _host_control_contract_template()

ExecFn = Callable[[list[str], float, bool], Awaitable[ExecResult]]
ProbeFn = Callable[[str, int], bool]


class RemediationRunner:
    def __init__(self, allowlist: Optional[dict[str, ServiceCommand]] = None, *,
                 permission_gate=None, audit=None,
                 exec_fn: Optional[ExecFn] = None, probe_fn: Optional[ProbeFn] = None,
                 timeout: float = 20.0, verify_attempts: int = 5, verify_delay: float = 0.6):
        self.allowlist = dict(DEFAULT_ALLOWLIST) if allowlist is None else dict(allowlist)
        self.permission_gate = permission_gate
        self.audit = audit
        self._exec_fn = exec_fn or _default_exec
        self._probe_fn = probe_fn or _default_probe
        self.timeout = timeout
        self.verify_attempts = verify_attempts
        self.verify_delay = verify_delay

    async def restart(self, service: str, agent: str = "steve") -> dict:
        """Restart an allowlisted service. Returns a structured result dict.

        Note: `service` is taken from the task — the payload's `cmd`, if any, is
        deliberately ignored (the allowlist is the only source of what runs).
        """
        service = (service or "").strip().lower()

        if self.permission_gate is not None and not self.permission_gate.check_call("system-control", agent):
            return self._done("blocked", service, reason=f"agent '{agent}' not permitted for system-control")

        blocked = self._contract_blocked("restart_service", agent=agent, service=service)
        if blocked:
            return blocked

        cmd = self.allowlist.get(service)
        if cmd is None:
            return self._done("rejected", service,
                              reason=f"service '{service}' not in restart allowlist")

        before = self._probe(cmd)
        try:
            result = await self._exec_fn(list(cmd.argv), self.timeout, cmd.detach)
        except Exception as e:  # never let a remediation crash the worker tick
            logger.warning(f"restart {service}: exec error: {e}")
            return self._done("failed", service, reason=str(e), before=before)

        recovered = await self._verify(cmd)
        # Foreground daemons: trust the probe. One-shot commands: also require ok exit.
        ok = recovered if cmd.verify_port is not None else result.ok
        status = "ok" if ok else "failed"
        return self._done(
            status, service,
            argv=cmd.argv, exit_code=result.exit_code, timed_out=result.timed_out,
            before=before, after=recovered,
            output=(result.stdout or result.stderr)[:500],
        )

    # ── helpers ───────────────────────────────────────────────────
    def _probe(self, cmd: ServiceCommand) -> Optional[bool]:
        if cmd.verify_port is None:
            return None
        try:
            return bool(self._probe_fn(cmd.verify_host, cmd.verify_port))
        except Exception:
            logger.warning("Service probe failed for %s:%s", cmd.verify_host, cmd.verify_port, exc_info=True)
            return None

    async def _verify(self, cmd: ServiceCommand) -> Optional[bool]:
        if cmd.verify_port is None:
            return None
        for _ in range(max(1, self.verify_attempts)):
            if self._probe(cmd):
                return True
            await asyncio.sleep(self.verify_delay)
        return False

    def _done(self, status: str, service: str, **extra) -> dict:
        result = {"status": status, "service": service, "kind": "restart_service", **extra}
        if self.audit is not None:
            try:
                self.audit.log("autonomy.remediation", result)
            except Exception:
                logger.warning("Remediation audit log failed for service '%s'", service, exc_info=True)
        log = logger.info if status == "ok" else logger.warning
        log(f"restart_service {service}: {status} ({extra.get('reason', '')})".rstrip())
        return result

    def _contract_blocked(self, action: str, *, agent: str, service: str) -> Optional[dict]:
        try:
            decision = HOST_CONTROL_CONTRACT.evaluate({
                "kind": HOST_CONTROL_CONTRACT_KIND,
                "action": action,
                "agent": agent,
                "service": service,
                "target": service,
            })
        except Exception:
            logger.warning("host-control contract evaluation failed", exc_info=True)
            return self._done("blocked", service, reason="contract_error")
        reason = contract_denial(decision)
        if reason:
            return self._done("blocked", service, reason=reason)
        return None


# ── default real implementations ────────────────────────────────────
async def _default_exec(argv: list[str], timeout: float, detach: bool) -> ExecResult:
    """Run argv with no shell. Detached daemons are started and not awaited."""
    if detach:
        await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        return ExecResult(exit_code=0, stdout=f"started detached: {' '.join(argv)}")
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except OSError:
            pass
        await proc.wait()
        return ExecResult(exit_code=-1, timed_out=True)
    return ExecResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout=out.decode("utf-8", "replace"), stderr=err.decode("utf-8", "replace"),
    )


def _default_probe(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
