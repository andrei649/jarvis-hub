"""
Tests for the Proactive OS Observer (agents/core/autonomy/observer.py).

The whole pipeline — probe → debounce → policy → queue — runs offline here:
probes are fakes, the worker is a real AutonomyWorker over an in-memory queue
with no notifier/executor, so we assert on the resulting task rows.
"""

import asyncio
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy import (  # noqa: E402
    AutonomyPolicy, AutonomyWorker, ProactiveObserver, RiskTier,
    ResourceProbe, ServiceProbe, ServiceSpec, Severity, Signal, TaskQueue,
)
from agents.core.autonomy.observer import Remediation  # noqa: E402


def _worker() -> AutonomyWorker:
    queue = TaskQueue(db_path=":memory:").initialize()
    return AutonomyWorker(queue, policy=AutonomyPolicy())


def _probe(*signals):
    return lambda: list(signals)


# ── debouncing: the headline anti-spam property ─────────────────────────────
def test_alert_fires_once_until_recovered():
    obs = ProactiveObserver(_worker(), probes=[])
    broken = Signal("service.docker", healthy=False, severity=Severity.CRITICAL)
    healthy = Signal("service.docker", healthy=True)

    assert len(obs.evaluate([broken])) == 1     # healthy→broken: fires
    assert len(obs.evaluate([broken])) == 0     # still broken: silent
    assert len(obs.evaluate([broken])) == 0
    rec = obs.evaluate([healthy])
    assert len(rec) == 1 and rec[0].transition == "recovery"
    assert len(obs.evaluate([broken])) == 1     # breaks again: fires again


def test_first_sample_down_still_fires():
    # Unknown key is assumed healthy, so an already-down service alerts once.
    obs = ProactiveObserver(_worker(), probes=[])
    findings = obs.evaluate([Signal("service.qdrant", healthy=False)])
    assert len(findings) == 1 and findings[0].is_alert


def test_recovery_notices_can_be_disabled():
    obs = ProactiveObserver(_worker(), probes=[], recovery_notices=False)
    obs.evaluate([Signal("resource.cpu", healthy=False)])
    assert obs.evaluate([Signal("resource.cpu", healthy=True)]) == []


# ── observations inform, decisions interrupt (policy routing) ───────────────
def test_plain_alert_is_auto_approved_read_only():
    w = _worker()
    obs = ProactiveObserver(w, probes=[_probe(
        Signal("resource.disk", healthy=False, severity=Severity.WARN,
               detail="Disk / at 88.0%"))])
    summary = asyncio.run(obs.observe())
    assert summary["submitted"] == 1
    task = w.queue.list()[0]
    assert task.kind == "monitor.alert"
    assert task.risk_tier == int(RiskTier.READ_ONLY)
    assert task.status == "approved"            # READ_ONLY → ACT, no human needed


def test_remediation_proposal_is_blocked_for_decision():
    w = _worker()
    down = Signal("service.docker", healthy=False, severity=Severity.CRITICAL,
                  detail="docker not responding",
                  remediation=Remediation(kind="restart_service",
                                           title="Restart docker?",
                                           payload={"service": "docker"}))
    obs = ProactiveObserver(w, probes=[_probe(down)])
    asyncio.run(obs.observe())
    task = w.queue.list()[0]
    assert task.kind == "restart_service"
    assert task.risk_tier == int(RiskTier.IRREVERSIBLE_OR_MONEY)
    assert task.status == "blocked"             # ASK → decision inbox
    assert task.payload["service"] == "docker"
    assert task.payload["reversible"] is False


def test_recovery_is_recorded_as_read_only():
    w = _worker()
    obs = ProactiveObserver(w, probes=[])
    obs.evaluate([Signal("service.n8n", healthy=False)])   # prime the broken state
    obs.probes = [_probe(Signal("service.n8n", healthy=True, detail="n8n up on :5678"))]
    asyncio.run(obs.observe())
    task = w.queue.list()[0]
    assert task.kind == "monitor.recovery"
    assert task.status == "approved"


# ── robustness ──────────────────────────────────────────────────────────────
def test_probe_exception_is_isolated():
    def boom():
        raise RuntimeError("nvidia-smi exploded")

    w = _worker()
    good = _probe(Signal("resource.ram", healthy=False, severity=Severity.WARN,
                         detail="RAM at 91%"))
    obs = ProactiveObserver(w, probes=[boom, good])
    summary = asyncio.run(obs.observe())        # must not raise
    assert summary["submitted"] == 1            # the healthy probe still landed


def test_status_reports_unhealthy_signals():
    obs = ProactiveObserver(_worker(), probes=[])
    obs.evaluate([
        Signal("service.docker", healthy=False, severity=Severity.CRITICAL,
               detail="docker down"),
        Signal("resource.cpu", healthy=True, detail="CPU at 20%"),
    ])
    status = obs.status()
    assert status["tracked"] == 2
    keys = {u["key"] for u in status["unhealthy"]}
    assert keys == {"service.docker"}


# ── built-in probes ──────────────────────────────────────────────────────────
def test_resource_probe_degrades_without_psutil(monkeypatch):
    probe = ResourceProbe()
    monkeypatch.setattr(probe, "_psutil", lambda: None)
    assert probe() == []                        # graceful, like the rest of the code


def test_service_probe_uses_injected_checker():
    specs = [ServiceSpec("up_svc", 1111), ServiceSpec("down_svc", 2222,
                                                       restart_cmd="systemctl restart down_svc")]
    # Only port 1111 is "listening".
    probe = ServiceProbe(specs, checker=lambda host, port: port == 1111)
    signals = {s.key: s for s in probe()}
    assert signals["service.up_svc"].healthy is True
    assert signals["service.down_svc"].healthy is False
    assert signals["service.down_svc"].remediation.kind == "restart_service"


def test_service_probe_down_without_restart_cmd_has_no_remediation():
    probe = ServiceProbe([ServiceSpec("qdrant", 6333)],
                         checker=lambda host, port: False)
    sig = probe()[0]
    assert sig.healthy is False
    assert sig.remediation is None              # alert only, no auto-restart proposal


def test_observe_summary_counts():
    w = _worker()
    obs = ProactiveObserver(w, probes=[_probe(
        Signal("resource.cpu", healthy=False, severity=Severity.WARN, detail="CPU 95%"),
        Signal("resource.ram", healthy=True, detail="RAM 40%"),
    )])
    summary = asyncio.run(obs.observe())
    assert summary["sampled"] == 2
    assert summary["findings"] == 1             # only the unhealthy CPU transitions
    assert summary["unhealthy"] == ["resource.cpu"]
