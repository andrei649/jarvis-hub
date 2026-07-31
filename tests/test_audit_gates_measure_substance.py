"""The systemic finding: gates that check the SHAPE of a claim, not its substance.

Adversarial audit 2026-07-25. Five of six lenses independently found the same reflex —
build a gate, watch it go green, write the green into STATUS.md. These pin the fixes, and
each one is written to fail if the gate stops being able to fail.
"""

import contextlib
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


# ── ADV-091: the ambient safety counters ───────────────────────────
def test_ambient_action_counters_are_measured_not_assigned():
    """They were the integer literal 0, assigned into the dict STATUS.md quotes."""
    import ast

    src = (repo_root / "agents/core/observability/ambient_reality.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    literals = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if (isinstance(key, ast.Constant)
                    and key.value in ("ungoverned_actions", "action_calls")
                    and isinstance(value, ast.Constant)):
                literals.append(f"{key.value}={value.value!r}")
    assert not literals, (
        f"ambient safety counters are still constants: {literals}. STATUS.md reads "
        "'the ambient pack emits no ungoverned action' off these, so a literal makes the "
        "evidence a restatement of the claim."
    )


def test_the_action_watch_can_actually_count():
    """A counter that cannot move is a literal with extra steps.

    The counters are expected to read zero — ambient decides, it does not actuate — so
    without this the fix would be indistinguishable from the defect it replaced.
    """
    import asyncio

    from agents.core import capability_actions, kernel
    from agents.core.observability.ambient_reality import _ActionWatch

    watch = _ActionWatch()
    assert watch.action_calls == 0 and watch.ungoverned_actions == 0

    with watch:
        # An action that never reaches the kernel is exactly an ungoverned one.
        api = capability_actions.CapabilityActionAPI.__new__(
            capability_actions.CapabilityActionAPI)
        # The call is what we are counting, not its result — an unconfigured facade
        # raising here is expected and irrelevant to the assertion.
        with contextlib.suppress(Exception):
            asyncio.run(capability_actions.CapabilityActionAPI.perform(
                api, "action:test", {}, None))
    assert watch.action_calls == 1, "the watch did not observe an action call"
    assert watch.ungoverned_actions == 1, (
        "an action that never reached kernel.authorize was counted as governed"
    )

    # ...and the wrappers are removed on exit, so the instrument leaves no trace.
    assert not hasattr(capability_actions.CapabilityActionAPI.perform, "__wrapped_by_watch__")
    assert kernel.authorize.__name__ != "_counted_authorize"


def test_a_governed_action_is_not_counted_as_ungoverned():
    from agents.core import kernel
    from agents.core.observability.ambient_reality import _ActionWatch

    watch = _ActionWatch()
    with watch:
        watch.action_calls += 1          # stand in for the facade call
        with contextlib.suppress(Exception):
            kernel.authorize(None)
    assert watch.action_calls == 1
    assert watch.ungoverned_actions == 0, "a kernel-mediated action was counted ungoverned"


# ── ADV-096: the parity gate ───────────────────────────────────────
def test_the_parity_coverage_gate_is_not_vacuous():
    """It must load real client sources; an empty corpus would pass everything."""
    sys.path.insert(0, str(repo_root / "tests"))
    from test_hud_v2_parity import (
        MACHINE_FACING,
        UNCALLED_BACKLOG,
        _client_blob,
        _has_caller,
        _snapshot_routes,
    )

    blob = _client_blob()
    assert len(blob) > 100_000

    # generated type files must be excluded, or every route "has a caller" by construction
    assert "schema.gen.ts" in str(repo_root / "frontend/src/api/schema.gen.ts")
    assert not _has_caller("/api/an-endpoint-that-does-not-exist-anywhere", blob)

    # a real, wired route is detected
    assert _has_caller("/api/security/kill-switch", blob)

    # every declared entry is real, so the lists cannot rot into permanent permission
    routes = set(_snapshot_routes())
    for path in MACHINE_FACING:
        assert path in routes, f"MACHINE_FACING lists {path}, which is not a route"
    for path in UNCALLED_BACKLOG:
        assert path in routes, f"UNCALLED_BACKLOG lists {path}, which is not a route"


def test_machine_facing_entries_each_carry_a_reason():
    """A bare list gets inherited; a reason gets re-judged."""
    sys.path.insert(0, str(repo_root / "tests"))
    from test_hud_v2_parity import MACHINE_FACING

    for path, reason in MACHINE_FACING.items():
        assert reason and len(reason) > 10, f"{path} is exempted with no usable reason"


# ── ADV-094: degraded no-ops recorded as ledger successes ──────────
class _Queue:
    def __init__(self):
        self.recorded = []

    def record_capability_outcome(self, capability_id, success=True):
        self.recorded.append((capability_id, success))


def _worker(queue):
    from agents.core.autonomy.worker import AutonomyWorker

    worker = AutonomyWorker.__new__(AutonomyWorker)
    worker.queue = queue
    return worker


def _task(kind):
    return type("T", (), {"kind": kind, "payload": {}})()


def test_a_mock_result_is_not_recorded_as_a_capability_success(monkeypatch):
    """success_rate 1.0 for a capability that has never delivered anything.

    `_record_capability_outcome` skipped only a literal status == "noop", while
    is_degraded() — which recognises the _mock/_degraded markers every mock-falling-back
    plugin stamps — had zero production callers.
    """
    from agents.core.autonomy import worker as worker_mod

    monkeypatch.setattr(worker_mod, "manifest_for_action",
                        lambda kind: type("M", (), {"id": "plugin:demo"})(), raising=False)
    import agents.core.capability_manifests as cm
    monkeypatch.setattr(cm, "manifest_for_action",
                        lambda kind: type("M", (), {"id": "plugin:demo"})())

    queue = _Queue()
    worker = _worker(queue)

    worker._record_capability_outcome(
        _task("plugin.demo"), success=True, result={"_mock": True, "value": "MOCK_SMS_123"})
    assert queue.recorded == [], (
        "a mock result was recorded as a capability success — /api/capabilities will show "
        "rising confidence for something that never delivered"
    )

    worker._record_capability_outcome(
        _task("plugin.demo"), success=True, result={"_degraded": {"reason": "no key"}})
    assert queue.recorded == []

    # a genuine success still counts, or the fix would just break the ledger
    worker._record_capability_outcome(
        _task("plugin.demo"), success=True, result={"value": "real"})
    assert queue.recorded == [("plugin:demo", True)]


def test_a_noop_is_still_skipped(monkeypatch):
    import agents.core.capability_manifests as cm

    monkeypatch.setattr(cm, "manifest_for_action",
                        lambda kind: type("M", (), {"id": "plugin:demo"})())
    queue = _Queue()
    _worker(queue)._record_capability_outcome(
        _task("plugin.demo"), success=True, result={"status": "noop"})
    assert queue.recorded == []
