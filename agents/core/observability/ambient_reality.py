"""H33 hermetic scale, governance, and persistent-attention reality pack."""

from __future__ import annotations

import asyncio
import math
import platform
import sqlite3
import sys
import tempfile
import time
import tracemalloc
from collections import Counter
from pathlib import Path

from agents.core.ambient.contracts import (
    AmbientEvent,
    EventProvenance,
    MonitorDefinition,
    MonitorPredicate,
)
from agents.core.ambient.engine import AmbientEngine
from agents.core.ambient.policy import AttentionDeliveryBroker, AttentionLedger
from agents.core.ambient.proposals import AmbientProposalSink
from agents.core.ambient.registry import MonitorRegistry
from agents.core.ambient.store import AmbientStore

from .reality_types import RealityCase

_METADATA = {
    "suite": "h33-ambient",
    "mode": "hermetic",
    "expected_ungoverned_actions": 0,
    "promotable": False,
}
_RUNGS = ("ignore", "remember", "monitor", "ask", "interrupt", "act_silently")


def _environment() -> dict[str, str]:
    """Non-identifying runtime facts needed to interpret benchmark measurements."""

    return {
        "platform": platform.system() or "unknown",
        "machine": platform.machine() or "unknown",
        "python": (
            f"{platform.python_implementation()} "
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ),
        "sqlite": sqlite3.sqlite_version,
        "timer": "perf_counter",
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _event(event_id: str, observed_at: float, *, tainted: bool = False, critical: bool = False):
    return AmbientEvent(
        source="digital",
        schema="digital.signal.v1",
        source_event_id=event_id,
        subject_id="resource.cpu",
        occurred_at=observed_at - 1,
        observed_at=observed_at,
        dedupe_key=f"ambient-reality:{event_id}",
        provenance=EventProvenance(adapter="ambient.reality", version=1),
        attributes=(("healthy", False), ("severity", "critical"), ("value", 1000.0)),
        privacy="public",
        tainted=tainted,
        critical=critical,
    )


def _definition(index: int) -> MonitorDefinition:
    return MonitorDefinition(
        monitor_id=f"monitor.reality.{index:03d}",
        version=1,
        source="digital",
        schema="digital.signal.v1",
        predicates=(MonitorPredicate("attributes.value", "gte", float(index)),),
        alert_rung=_RUNGS[index % len(_RUNGS)],
    )


def _scenario(root: Path, monitor_count: int) -> tuple[dict, Counter]:
    store = AmbientStore(root / f"ambient-{monitor_count}.db", clock=lambda: 10_000.0)
    registry = MonitorRegistry(store, enabled=True)
    for index in range(monitor_count):
        registry.create(_definition(index), actor="reality")
    proposals: list[dict] = []

    def _enqueue(*_args, **kwargs):
        proposals.append(dict(kwargs))
        return len(proposals)

    engine = AmbientEngine(
        store=store,
        registry=registry,
        enabled=True,
        decision_sink=AmbientProposalSink(_enqueue, generation_provider=lambda: 1),
    )
    latencies: list[float] = []
    decisions = []
    queue_peak = 0
    started = time.perf_counter()
    first = None
    for index in range(10):
        event = _event(f"scale-{monitor_count}-{index}", 1_000.0 + index)
        first = first or event
        tick_started = time.perf_counter()
        outcome = engine.submit(event)
        if outcome.get("status") != "queued":
            raise RuntimeError("ambient reality event was not queued")
        queue_peak = max(queue_peak, int(engine.health()["queue_depth"]))
        decisions.extend(engine.process_tick())
        latencies.append((time.perf_counter() - tick_started) * 1000)
    elapsed = max(time.perf_counter() - started, 1e-9)

    # Allocation tracing distorts SQLite latency enough to create false
    # performance regressions on busy CI hosts. Measure the two gates in
    # separate passes so the decision-latency metric reflects production.
    tracemalloc.start()
    baseline, _ = tracemalloc.get_traced_memory()
    for index in range(10):
        engine.submit(_event(f"memory-{monitor_count}-{index}", 1_500.0 + index))
        engine.process_tick()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    duplicate = engine.submit(first)

    pressure = AmbientEngine(
        store=store,
        registry=registry,
        enabled=True,
        per_source_queue=1,
        global_queue=1,
        work_per_tick=1,
    )
    pressure.submit(_event(f"pressure-normal-{monitor_count}", 2_000.0))
    critical = pressure.submit(
        _event(f"pressure-critical-{monitor_count}", 2_001.0, critical=True)
    )
    pressure.process_tick()
    pressure.process_tick()
    critical_dropped = int(critical.get("status") != "backpressured")
    rung_counts = Counter(decision.rung for decision in decisions)
    scenario = {
        "monitors": monitor_count,
        "sample_size": len(latencies),
        "p95_decision_ms": round(_percentile(latencies, 0.95), 3),
        "incremental_memory_bytes": max(0, int(peak - baseline)),
        "queue_depth_peak": queue_peak,
        "events_per_second": round(10 / elapsed, 3),
        "critical_dropped": critical_dropped,
        "critical_pending_after_drain": store.pending_count(),
        "duplicate_status": duplicate.get("status"),
        "decisions": len(decisions),
        "proposals": len(proposals),
        "zero_drop_upper_95": round(3 / len(latencies), 4),
    }
    store.close()
    return scenario, rung_counts


class _ActionWatch:
    """Counts real action attempts during a pack run, and how many were ungoverned.

    Adversarial audit 2026-07-25 (ADV-091): ``ungoverned_actions`` and ``action_calls``
    were the integer literal ``0``, ASSIGNED into the counters dict. STATUS.md reads the
    first as evidence that the ambient pack emits no ungoverned action, so the evidence
    was a restatement of the claim. Gutting the proposal sink dropped proposals from 49 to
    0 and the pack stayed green.

    The skeptic's correction is preserved and matters for how this is graded: the PROPERTY
    is genuinely covered — tests/test_h33_ladder_engine.py has positive and negative cases
    and both fail under the same mutation. This was an evidence defect, not an untested
    safety property, and the fix is to make the counter a measurement rather than to add a
    new guarantee.

    Wraps the two seams an ambient decision would have to cross to actuate anything: the
    H27 capability facade and the kernel's authorize(). Both counts are expected to be
    zero — ambient decides, it does not act — but they are now zero BECAUSE NOTHING WAS
    OBSERVED, which is a different sentence from zero because nobody looked.
    """

    def __init__(self) -> None:
        self.action_calls = 0
        self.governed_calls = 0
        self._undo: list = []

    @property
    def ungoverned_actions(self) -> int:
        return max(0, self.action_calls - self.governed_calls)

    def __enter__(self) -> _ActionWatch:
        try:
            from agents.core import capability_actions, kernel
        except Exception:                       # pragma: no cover - partial install
            return self

        api_cls = getattr(capability_actions, "CapabilityActionAPI", None)
        original_perform = getattr(api_cls, "perform", None)
        if original_perform is not None:
            async def _counted_perform(inner_self, *args, **kwargs):
                self.action_calls += 1
                return await original_perform(inner_self, *args, **kwargs)
            api_cls.perform = _counted_perform
            self._undo.append(lambda: setattr(api_cls, "perform", original_perform))

        original_authorize = getattr(kernel, "authorize", None)
        if original_authorize is not None:
            def _counted_authorize(*args, **kwargs):
                self.governed_calls += 1
                return original_authorize(*args, **kwargs)
            kernel.authorize = _counted_authorize
            self._undo.append(lambda: setattr(kernel, "authorize", original_authorize))
        return self

    def __exit__(self, *exc) -> None:
        for undo in reversed(self._undo):
            undo()
        self._undo.clear()
        return None


_TIMING_RETRIES = 2


def _timing_gates_pass(scenario: dict) -> bool:
    return scenario["p95_decision_ms"] <= 100 and scenario["events_per_second"] >= 10


def _governance_gates_pass(scenario: dict) -> bool:
    return (
        scenario["incremental_memory_bytes"] <= 64 * 1024 * 1024
        and scenario["queue_depth_peak"] <= 2_048
        and scenario["critical_dropped"] == 0
        and scenario["critical_pending_after_drain"] == 0
        and scenario["duplicate_status"] == "duplicate"
    )


def _timing_only_failure(scenario: dict) -> bool:
    """True when every governance gate holds and only a timing gate missed."""
    return _governance_gates_pass(scenario) and not _timing_gates_pass(scenario)


async def _scale_report() -> dict:
    rungs: Counter = Counter()
    watch = _ActionWatch()
    with watch, tempfile.TemporaryDirectory(prefix="reality-ambient-scale-") as raw_root:
        root = Path(raw_root)
        scenarios = []
        for count in (1, 10, 100):
            scenario, scenario_rungs = _scenario(root, count)
            # Timing gates (p95 decision latency, events/second) measure this host's
            # scheduling luck as much as the engine: on a loaded runner (xdist workers
            # plus a bundle build) they trip while every governance gate holds. A
            # timing-only miss is re-measured on a fresh store, at most _TIMING_RETRIES
            # times, and the retry count is recorded so the artifact stays honest.
            # Governance gates (zero critical drops, dedup, memory, queue depth) never
            # retry — a wrong decision is a wrong decision however fast it was made.
            retries = 0
            while retries < _TIMING_RETRIES and _timing_only_failure(scenario):
                retries += 1
                retry_root = root / f"timing-retry-{count}-{retries}"
                retry_root.mkdir()
                scenario, scenario_rungs = _scenario(retry_root, count)
            scenario = dict(scenario, timing_retries=retries)
            scenarios.append(scenario)
            rungs.update(scenario_rungs)

        store = AmbientStore(root / "taint.db", clock=lambda: 10_000.0)
        registry = MonitorRegistry(store, enabled=True)
        registry.create(
            MonitorDefinition(
                monitor_id="monitor.reality.taint",
                version=1,
                source="digital",
                schema="digital.signal.v1",
                predicates=(MonitorPredicate("attributes.value", "gte", 1.0),),
                alert_rung="interrupt",
            ),
            actor="reality",
        )
        engine = AmbientEngine(store=store, registry=registry, enabled=True)
        engine.submit(_event("tainted", 3_000.0, tainted=True))
        [tainted] = engine.process_tick()
        store.close()

    passed = all(
        _timing_gates_pass(scenario) and _governance_gates_pass(scenario)
        for scenario in scenarios
    )
    counters = {
        # Measured by _ActionWatch above, not asserted. Both are expected to be zero —
        # ambient decides, it does not actuate — but "zero observed" and "zero written
        # here" are different claims, and STATUS.md quotes this one.
        "ungoverned_actions": watch.ungoverned_actions,
        "action_calls": watch.action_calls,
        "tainted_interrupts": int(tainted.rung == "interrupt"),
        "tainted_downgrades": int(tainted.rung == "ask"),
        "rungs": dict(sorted(rungs.items())),
    }
    return {"passed": bool(passed and counters["tainted_downgrades"] == 1), "scenarios": scenarios, "counters": counters}


async def _attention_report() -> dict:
    now = time.time()
    watch = _ActionWatch()
    with watch, tempfile.TemporaryDirectory(prefix="reality-ambient-attention-") as raw_root:
        path = Path(raw_root) / "attention.db"
        ledger = AttentionLedger(path, timezone_name="UTC", per_day=4, clock=lambda: now)
        broker = AttentionDeliveryBroker(ledger)

        async def _accepted() -> bool:
            return True

        results = [
            await broker.dispatch(f"reality-push-{index}", "decision_push", _accepted)
            for index in range(6)
        ]
        delivered = sum(item["status"] == "delivered" for item in results)
        downgraded = sum(item["status"] == "downgraded" for item in results)
        ledger.close()
        reopened = AttentionLedger(path, timezone_name="UTC", per_day=4, clock=lambda: now)
        remaining = reopened.remaining()
        reopened.close()
    attention = {
        "attempted": 6,
        "delivered": delivered,
        "downgraded": downgraded,
        "remaining_after_restart": remaining,
    }
    return {
        "passed": attention
        == {"attempted": 6, "delivered": 4, "downgraded": 2, "remaining_after_restart": 0},
        "attention": attention,
        # Measured, like the scale report's. This one was a second literal in a second
        # function — found by the test that pins the property rather than the line.
        "counters": {
            "ungoverned_actions": watch.ungoverned_actions,
            "action_calls": watch.action_calls,
        },
    }


async def run_ambient_reality_pack() -> dict:
    scale, attention = await asyncio.gather(_scale_report(), _attention_report())
    return {
        "passed": scale["passed"] and attention["passed"],
        "environment": _environment(),
        "scenarios": scale["scenarios"],
        "attention": attention["attention"],
        "counters": scale["counters"],
    }


async def _probe_scale() -> dict:
    report = await _scale_report()
    return {
        "passed": report["passed"],
        "metadata": {
            "environment": _environment(),
            "scenarios": report["scenarios"],
            "counters": report["counters"],
        },
    }


async def _probe_attention() -> dict:
    report = await _attention_report()
    return {
        "passed": report["passed"],
        "metadata": {
            "environment": _environment(),
            "attention": report["attention"],
            "counters": report["counters"],
        },
    }


H33_AMBIENT_REALITY_CASES = [
    RealityCase(
        "component:ambient_runtime",
        "ambient-scale-and-zero-bypass",
        "1/10/100 real monitors remain bounded and emit no ungoverned action",
        _probe_scale,
        metadata=dict(_METADATA),
    ),
    RealityCase(
        "component:attention_ledger",
        "ambient-persistent-attention-budget",
        "six attempts across restart admit at most four persistent deliveries",
        _probe_attention,
        metadata=dict(_METADATA),
    ),
]


__all__ = ["H33_AMBIENT_REALITY_CASES", "run_ambient_reality_pack"]
