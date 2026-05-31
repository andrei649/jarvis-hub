"""
observer.py — Proactive OS Observer (ORIZONT 6 follow-up: the trigger layer).

The autonomy rails (queue → policy → inbox → worker) already exist, but until
now every task had to be proposed by a human or a heartbeat prompt. This module
is the missing *event source*: a daemon-style component that samples the host
(resources, service liveness) and turns state changes into autonomy tasks.

Two design rules, both straight from `docs/research/2026-05-31-autonomous-
proactive-agents.md`:

  1. **State-change debouncing.** A probe only emits when it *transitions*
     healthy→unhealthy (alert) or unhealthy→healthy (recovery). Re-sampling a
     still-broken service does NOT re-fire. This is what keeps the observer
     from burning the daily interruption budget.
  2. **Observations inform, decisions interrupt.** A plain alert ("disk at
     88%") is submitted as a READ_ONLY task → auto-approved, surfaced in the
     HUD / morning brief, no push. A *remediation proposal* ("Docker is down —
     restart it?") is submitted as an IRREVERSIBLE task → the policy blocks it
     and the decision inbox pushes the card: the canonical "Sir, the Docker
     server is down. Shall I restart it?" moment.

Everything is injected (probes, worker, clock) so the whole pipeline runs
offline in unit tests without psutil, sockets, or a live LM.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional

from .policy import RiskTier

logger = logging.getLogger("jarvis.autonomy.observer")


class Severity(IntEnum):
    INFO = 0
    WARN = 1
    CRITICAL = 2


@dataclass
class Signal:
    """A single point-in-time reading from a probe.

    `key` is a stable identifier (e.g. "resource.cpu", "service.docker") used to
    track state across samples. `healthy=False` means the reading breached a
    threshold. `remediation`, when set, names an action the observer may propose
    to fix it (which routes the finding through the decision inbox).
    """
    key: str
    healthy: bool
    severity: Severity = Severity.INFO
    detail: str = ""
    value: Optional[float] = None
    agent: str = "steve"
    remediation: Optional["Remediation"] = None


@dataclass
class Remediation:
    """A proposed fix for an unhealthy signal — becomes an ASK autonomy task."""
    kind: str                     # verb-first; e.g. "restart_service"
    title: str                    # human prompt, e.g. "Restart the Docker daemon?"
    payload: dict = field(default_factory=dict)


@dataclass
class Finding:
    """A state transition worth acting on."""
    signal: Signal
    transition: str               # "alert" (healthy→broken) | "recovery" (broken→healthy)

    @property
    def is_alert(self) -> bool:
        return self.transition == "alert"


# A probe is any zero-arg callable returning the signals it observed this tick.
Probe = Callable[[], "list[Signal]"]


# ── built-in probes ─────────────────────────────────────────────────
DEFAULT_THRESHOLDS = {
    "cpu_warn": 90.0,
    "ram_warn": 85.0, "ram_critical": 95.0,
    "disk_warn": 85.0, "disk_critical": 95.0,
}


class ResourceProbe:
    """CPU / RAM / disk pressure via psutil. Emits nothing if psutil is absent."""

    def __init__(self, thresholds: Optional[dict] = None, disk_path: str = "/"):
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.disk_path = disk_path

    def _psutil(self):
        try:
            import psutil
            return psutil
        except ImportError:
            return None

    def __call__(self) -> list[Signal]:
        ps = self._psutil()
        if ps is None:
            return []
        t = self.thresholds
        out: list[Signal] = []
        try:
            cpu = ps.cpu_percent(interval=None)
            out.append(_threshold_signal(
                "resource.cpu", cpu, t["cpu_warn"], None,
                "CPU", "%", agent="steve"))
        except Exception as e:                       # pragma: no cover - defensive
            logger.debug(f"cpu probe failed: {e}")
        try:
            ram = ps.virtual_memory().percent
            out.append(_threshold_signal(
                "resource.ram", ram, t["ram_warn"], t["ram_critical"],
                "RAM", "%", agent="steve"))
        except Exception as e:                       # pragma: no cover
            logger.debug(f"ram probe failed: {e}")
        try:
            disk = ps.disk_usage(self.disk_path).percent
            out.append(_threshold_signal(
                "resource.disk", disk, t["disk_warn"], t["disk_critical"],
                f"Disk {self.disk_path}", "%", agent="steve"))
        except Exception as e:                       # pragma: no cover
            logger.debug(f"disk probe failed: {e}")
        return out


def _threshold_signal(key: str, value: float, warn: float,
                      critical: Optional[float], label: str, unit: str,
                      agent: str) -> Signal:
    value = round(float(value), 1)
    if critical is not None and value >= critical:
        return Signal(key, healthy=False, severity=Severity.CRITICAL,
                      detail=f"{label} at {value}{unit} (≥{critical}{unit})",
                      value=value, agent=agent)
    if value >= warn:
        return Signal(key, healthy=False, severity=Severity.WARN,
                      detail=f"{label} at {value}{unit} (≥{warn}{unit})",
                      value=value, agent=agent)
    return Signal(key, healthy=True, severity=Severity.INFO,
                  detail=f"{label} at {value}{unit}", value=value, agent=agent)


# How to reach a service and (optionally) how to bring it back.
@dataclass
class ServiceSpec:
    name: str
    port: int
    host: str = "127.0.0.1"
    restart_cmd: Optional[str] = None   # if set, a down service proposes a restart
    agent: str = "steve"


class ServiceProbe:
    """Liveness of TCP services. A down service with a `restart_cmd` proposes a
    remediation (→ decision inbox); without one it is a plain alert."""

    def __init__(self, services: "list[ServiceSpec]",
                 checker: Optional[Callable[[str, int], bool]] = None,
                 timeout: float = 1.0):
        self.services = services
        self.timeout = timeout
        self._is_listening = checker or self._tcp_probe

    def _tcp_probe(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=self.timeout):
                return True
        except OSError:
            return False

    def __call__(self) -> list[Signal]:
        out: list[Signal] = []
        for svc in self.services:
            up = self._is_listening(svc.host, svc.port)
            if up:
                out.append(Signal(f"service.{svc.name}", healthy=True,
                                  detail=f"{svc.name} up on :{svc.port}", agent=svc.agent))
                continue
            remediation = None
            if svc.restart_cmd:
                remediation = Remediation(
                    kind="restart_service",
                    title=f"Restart {svc.name}?",
                    payload={"service": svc.name, "cmd": svc.restart_cmd},
                )
            out.append(Signal(
                f"service.{svc.name}", healthy=False, severity=Severity.CRITICAL,
                detail=f"{svc.name} not responding on {svc.host}:{svc.port}",
                agent=svc.agent, remediation=remediation,
            ))
        return out


# ── the observer ────────────────────────────────────────────────────
class ProactiveObserver:
    """Samples probes, debounces on state change, and feeds the autonomy worker.

    `worker` must expose `async submit(agent, kind, title, payload, origin)` —
    i.e. the existing `AutonomyWorker`. Pass `recovery_notices=False` to stay
    silent when things come back up.
    """

    def __init__(self, worker, probes: Optional["list[Probe]"] = None, *,
                 recovery_notices: bool = True):
        self.worker = worker
        self.probes = probes or []
        self.recovery_notices = recovery_notices
        self._state: dict[str, bool] = {}     # key → last-known healthy
        self._last_signals: dict[str, Signal] = {}

    # ── pure evaluation (no I/O, fully unit-testable) ─────────────
    def evaluate(self, signals: "list[Signal]") -> "list[Finding]":
        """Diff `signals` against the last known state, returning transitions.

        Unknown keys are assumed healthy, so a service that is *already* down on
        the first sample still fires once.
        """
        findings: list[Finding] = []
        for sig in signals:
            self._last_signals[sig.key] = sig
            was_healthy = self._state.get(sig.key, True)
            if was_healthy and not sig.healthy:
                findings.append(Finding(sig, "alert"))
            elif not was_healthy and sig.healthy and self.recovery_notices:
                findings.append(Finding(sig, "recovery"))
            self._state[sig.key] = sig.healthy
        return findings

    def _gather(self) -> "list[Signal]":
        signals: list[Signal] = []
        for probe in self.probes:
            try:
                signals.extend(probe() or [])
            except Exception as e:                  # one bad probe can't break the tick
                logger.warning(f"observer probe {getattr(probe, '__name__', probe)} failed: {e}")
        return signals

    # ── full tick (sample → evaluate → submit) ────────────────────
    async def observe(self) -> dict:
        signals = self._gather()
        findings = self.evaluate(signals)
        submitted = 0
        for finding in findings:
            try:
                await self._submit(finding)
                submitted += 1
            except Exception as e:                  # never let submission break the loop
                logger.warning(f"observer submit failed for {finding.signal.key}: {e}")
        return {
            "sampled": len(signals),
            "findings": len(findings),
            "submitted": submitted,
            "unhealthy": [k for k, ok in self._state.items() if not ok],
        }

    async def _submit(self, finding: Finding):
        sig = finding.signal
        if finding.transition == "recovery":
            return await self.worker.submit(
                agent=sig.agent, kind="monitor.recovery",
                title=f"✓ {sig.detail}",
                payload={"key": sig.key, "risk_tier": int(RiskTier.READ_ONLY),
                         "signal": _signal_payload(sig)},
                origin="generated",
            )

        # Actionable: propose the fix → IRREVERSIBLE tier → policy blocks → inbox.
        if sig.remediation:
            rem = sig.remediation
            urgent = sig.severity >= Severity.CRITICAL
            return await self.worker.submit(
                agent=sig.agent, kind=rem.kind,
                title=f"⚠️ {sig.detail}. {rem.title}",
                payload={
                    **rem.payload,
                    "key": sig.key,
                    "risk_tier": int(RiskTier.IRREVERSIBLE_OR_MONEY),
                    "reversible": False,
                    "time_sensitivity": 0.9 if urgent else 0.5,
                    "signal": _signal_payload(sig),
                },
                origin="generated",
            )

        # Plain alert: READ_ONLY → auto-approved → shows in HUD / morning brief.
        prefix = "⚠️ " if sig.severity >= Severity.CRITICAL else ""
        return await self.worker.submit(
            agent=sig.agent, kind="monitor.alert",
            title=f"{prefix}{sig.detail}",
            payload={"key": sig.key, "severity": sig.severity.name,
                     "risk_tier": int(RiskTier.READ_ONLY), "signal": _signal_payload(sig)},
            origin="generated",
        )

    # ── introspection (for the /autonomy/observer endpoint + HUD) ─
    def status(self) -> dict:
        return {
            "probes": len(self.probes),
            "tracked": len(self._state),
            "unhealthy": [
                {"key": k, "detail": self._last_signals[k].detail,
                 "severity": self._last_signals[k].severity.name}
                for k, ok in self._state.items()
                if not ok and k in self._last_signals
            ],
        }


def _signal_payload(sig: Signal) -> dict:
    return {"key": sig.key, "healthy": sig.healthy, "severity": sig.severity.name,
            "detail": sig.detail, "value": sig.value}


def default_probes(services: Optional["list[ServiceSpec]"] = None,
                   thresholds: Optional[dict] = None,
                   disk_path: str = "/") -> "list[Probe]":
    """Standard probe set: resource pressure + liveness for the cabinet's
    backing services (Qdrant, Neo4j, n8n, LM Studio, Ollama)."""
    if services is None:
        services = [
            ServiceSpec("lmstudio", 1234),
            ServiceSpec("ollama", 11434, restart_cmd="ollama serve"),
            ServiceSpec("qdrant", 6333),
            ServiceSpec("neo4j", 7474),
            ServiceSpec("n8n", 5678),
        ]
    return [ResourceProbe(thresholds=thresholds, disk_path=disk_path),
            ServiceProbe(services)]
