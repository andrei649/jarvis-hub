"""Action-auth matrix gate (ORIZONT-24 Gate K seed; mirrors test_route_auth_matrix).

Routes have a runtime registry (app.routes) that the route-auth matrix introspects;
privileged *actions* don't, so this gates a curated registry whose enumeration is
runtime-derived from the brokers' KIND constants. Three tests, same shape as the
route-auth suite:

  1. registry matches its snapshot (a change must be conscious);
  2. every broker action kind is classified (a new privileged broker fails CI) —
     acceptance criterion 5;
  3. honest mediation: KERNEL kinds actually invoke the kernel; PENDING kinds don't.
"""

import inspect
import json
from pathlib import Path

import pytest

from agents.core.kernel import Decision, Verdict
from agents.core.kernel.registry import (
    ACTION_REGISTRY,
    Mediation,
    classify,
    known_broker_action_kinds,
)

SNAP = Path(__file__).parent / "_snapshots" / "action_auth.json"

_KERNEL_KINDS = sorted(k for k, m in ACTION_REGISTRY.items() if m is Mediation.KERNEL)


def test_action_registry_matches_snapshot():
    snap = json.loads(SNAP.read_text())
    live = {k: v.value for k, v in ACTION_REGISTRY.items()}
    new = sorted(set(live) - set(snap))
    gone = sorted(set(snap) - set(live))
    drift = sorted(k for k in live if k in snap and live[k] != snap[k])
    problems = []
    if new:
        problems.append(f"NEW kinds (classify + add to snapshot): {new}")
    if gone:
        problems.append(f"REMOVED kinds (drop from snapshot): {gone}")
    if drift:
        problems.append("DRIFT: " + ", ".join(f"{k}: {snap[k]}->{live[k]}" for k in drift))
    assert not problems, (
        "Action-auth registry changed. If intended, regenerate "
        "tests/_snapshots/action_auth.json from agents/core/kernel/registry.py.\n"
        + "\n".join(problems)
    )


def test_every_broker_kind_classified():
    """A new broker action kind that isn't in ACTION_REGISTRY fails CI — route it
    through the kernel (KERNEL) or list it as PENDING_KERNEL with a reason."""
    unclassified = sorted(k for k in known_broker_action_kinds() if k not in ACTION_REGISTRY)
    assert not unclassified, (
        "Privileged broker action kind(s) with no classification:\n" + "\n".join(unclassified)
    )


class _SpyKernel:
    """Stand-in for the bound kernel.authorize — records the Action it's handed."""

    def __init__(self, verdict=Verdict.GRANT):
        self.calls = []
        self._verdict = verdict

    def __call__(self, action, capability=None, budget=None):
        self.calls.append(action)
        return Decision(self._verdict, reason="spy", tier=(action.payload or {}).get("risk_tier"))


def _exercise(kind, spy, tmp_path):
    """Drive the broker that owns *kind* through its request entry-point."""
    if kind == "call.outbound":
        from agents.core.autonomy.call_broker import CallBroker
        CallBroker(enqueue=lambda *a, **k: 1, kernel=spy).request(
            to="+15551234567", message="hi", provider="twilio")
    elif kind == "social.*":
        from agents.core.social import SocialBroker
        SocialBroker(enqueue=lambda *a, **k: 1, kernel=spy).request("x", "post", {"text": "hi"})
    elif kind == "writeback.*":
        from agents.core.writeback import WriteBackBroker
        wb = WriteBackBroker(enqueue=lambda *a, **k: 1, kernel=spy)
        tgt = wb.targets()[0]
        wb.request(tgt["target"], tgt["action"], dict.fromkeys(tgt["required"], "x"))
    elif kind == "node.dispatch":
        from agents.core.node_mesh import NodeMesh
        from agents.core.security.capability import CapabilityBroker, KillSwitch
        nm = NodeMesh(capability_broker=CapabilityBroker(),
                      kill_switch=KillSwitch(tmp_path / "kill.json"),
                      enqueue=lambda *a, **k: 1, kernel=spy)
        nm.register_node("n1", ["run"])
        nm.dispatch("n1", "run")
    else:  # pragma: no cover - a new KERNEL kind needs an exerciser added here
        raise AssertionError(f"no exerciser for kernel-classified kind {kind!r}")


@pytest.mark.parametrize("kind", _KERNEL_KINDS)
def test_kernel_kinds_actually_invoke_kernel(kind, monkeypatch, tmp_path):
    """Ground truth: a kind declared KERNEL must really route through the facade —
    a snapshot can't claim 'kernel' while the broker bypasses it."""
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    spy = _SpyKernel()
    _exercise(kind, spy, tmp_path)
    assert spy.calls, f"{kind} is classified KERNEL but request() did not invoke the kernel"
    assert spy.calls[-1].kind.split(".")[0] == kind.split(".")[0]


def test_kernel_off_does_not_invoke_kernel(monkeypatch, tmp_path):
    """Default-off: with the flag unset, no broker touches the kernel."""
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    for kind in _KERNEL_KINDS:
        spy = _SpyKernel()
        _exercise(kind, spy, tmp_path)
        assert not spy.calls, f"{kind} invoked the kernel with the flag OFF"


def test_pending_broker_kinds_are_not_wired():
    """Honest-pending: the only broker-backed PENDING kind (payment) must genuinely
    not be kernel-wired yet (no `kernel` ctor param), so the snapshot doesn't lie."""
    from agents.core.payments import PaymentBroker
    assert classify("payment") is Mediation.PENDING_KERNEL
    assert "kernel" not in inspect.signature(PaymentBroker.__init__).parameters
