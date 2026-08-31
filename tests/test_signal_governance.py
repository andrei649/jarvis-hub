"""Tests for the Signal Layer → approvals governance bridge.

Verifies it is OFF by default, only queues actionable recommendations, queues
them as preview-only (BLOCKED, awaiting human) and never as approved/running.
"""

import pytest

from agents.core.automation_contracts import ContractDecision
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.signal_governance import SignalGovernanceBridge


@pytest.fixture
def queue(tmp_path):
    q = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    yield q
    q.close()


RECS = [
    {"type": "monitor", "label": "Monitor watched airports again within 24h.", "requiresApproval": True},
    {"type": "review", "label": "Review cyber exposure before action.", "requiresApproval": True},
    {"type": "monitor", "label": "Continue monitoring. No action.", "requiresApproval": False},
]


def test_disabled_by_default_queues_nothing(queue):
    bridge = SignalGovernanceBridge(queue)  # enabled defaults to False
    out = bridge.submit_recommendations(RECS)
    assert out["status"] == "disabled"
    assert out["queued"] == 0
    assert queue.list() == []


def test_from_env_off_unless_flag_set(queue):
    assert SignalGovernanceBridge.from_env(queue, env={}).enabled is False
    assert SignalGovernanceBridge.from_env(queue, env={"JARVIS_SIGNAL_GOVERNANCE": "0"}).enabled is False
    assert SignalGovernanceBridge.from_env(queue, env={"JARVIS_SIGNAL_GOVERNANCE": "true"}).enabled is True


def test_enabled_queues_only_actionable_as_blocked(queue):
    audited = []
    bridge = SignalGovernanceBridge(queue, enabled=True, audit=lambda e, d: audited.append((e, d)))
    out = bridge.submit_recommendations(RECS, context={"scope": "world"})

    assert out["status"] == "ok"
    assert out["queued"] == 2          # two requiresApproval items
    assert out["skipped"] == 1         # the advisory one
    assert len(out["task_ids"]) == 2

    # Every queued task is BLOCKED (awaiting human) — never approved/running/done.
    for tid in out["task_ids"]:
        task = queue.get(tid)
        assert task.status == TaskStatus.BLOCKED.value
        assert task.kind == "signal_recommendation"
        assert task.payload["preview_only"] is True
        assert task.payload["context"]["scope"] == "world"

    # They show up as pending human decisions.
    pending = queue.pending_decisions()
    assert len(pending) == 2

    # Nothing was approved/run.
    assert queue.list(status="approved") == []
    assert queue.list(status="running") == []

    # Audit fired once per queued item.
    assert sum(1 for e, _ in audited if e == "signal_governance.queued") == 2


def test_enabled_bridge_obeys_live_contract_decision(queue, monkeypatch):
    import agents.core.signal_governance as signal_governance

    class FakeSignalContract:
        def __init__(self):
            self.calls = []

        def evaluate(self, payload=None, **kwargs):
            payload = payload or {}
            self.calls.append((payload, kwargs))
            label = payload["recommendation"].get("label")
            reason = "contract_denied" if "Review cyber" in label else None
            return ContractDecision(
                kind="signal_recommendation",
                admissible=reason is None,
                requires_approval=True,
                reason=reason,
                checked=("fake",),
            )

    contract = FakeSignalContract()
    monkeypatch.setattr(signal_governance, "SIGNAL_RECOMMENDATION_CONTRACT", contract)

    audited = []
    bridge = SignalGovernanceBridge(queue, enabled=True, audit=lambda e, d: audited.append((e, d)))
    out = bridge.submit_recommendations(RECS, context={"scope": "world"})

    assert out["queued"] == 1
    assert out["skipped"] == 2
    assert len(out["task_ids"]) == 1
    queued = queue.get(out["task_ids"][0])
    assert queued.title == "Monitor watched airports again within 24h."
    assert "Review cyber" not in queued.payload["recommendation"]["label"]
    assert len(contract.calls) == 2
    payload, kwargs = contract.calls[0]
    assert payload["recommendation"] == RECS[0]
    assert payload["context"] == {"scope": "world"}
    assert "now" in kwargs
    assert ("signal_governance.denied", {"label": RECS[1]["label"], "reason": "contract_denied"}) in audited


def test_submit_from_brief_extracts_recommendations(queue):
    bridge = SignalGovernanceBridge(queue, enabled=True)
    brief = {"scope": "world", "title": "Global Intelligence Brief", "recommendations": RECS}
    out = bridge.submit_from_brief(brief)
    assert out["queued"] == 2
    # Context carried the brief scope/title through to the queued task.
    task = queue.get(out["task_ids"][0])
    assert task.payload["context"]["title"] == "Global Intelligence Brief"


def test_empty_or_missing_recommendations_are_safe(queue):
    bridge = SignalGovernanceBridge(queue, enabled=True)
    assert bridge.submit_recommendations([])["queued"] == 0
    assert bridge.submit_from_brief(None)["queued"] == 0
    assert bridge.submit_from_brief({})["queued"] == 0


# ── DRA-19: the bridge must actually run ──────────────────────────────────────
#
# Everything above tests a module that nothing constructed. `SignalGovernanceBridge`
# shipped complete and contract-gated but had ZERO production constructors, so the
# Signal Layer → approval-inbox path never ran: the HUD rendered `requiresApproval`
# recommendations (frontend/src/world-intelligence.tsx:108) and they went nowhere.
# These pin the production constructor and the surface that drives it.

import asyncio  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from agents.core.routers import signals as signals_router  # noqa: E402

BRIEF = {"scope": "world", "title": "Global Intelligence Brief", "recommendations": RECS}


def _orch(bridge=None, *, brief=None, plugin=True):
    """A stand-in orchestrator carrying the bridge and the sidecar plugin."""
    async def world_brief():
        return brief if brief is not None else {"status": "ok", "brief": BRIEF}

    return SimpleNamespace(
        signal_governance=bridge,
        plugins={"signal-layer": SimpleNamespace(world_brief=world_brief)} if plugin else {},
    )


def _call(coro_fn, orch, monkeypatch):
    monkeypatch.setattr(signals_router, "get_orch", lambda: orch)
    return json.loads(asyncio.run(coro_fn()).body)


def test_governance_status_reports_off_as_a_fact_not_an_error(queue, monkeypatch):
    """Default-off is the honest answer, not a failure — the flag is the owner's."""
    body = _call(
        signals_router.signals_governance_status,
        _orch(SignalGovernanceBridge(queue)),
        monkeypatch,
    )
    assert body["available"] is True
    assert body["enabled"] is False
    assert body["flag"] == "JARVIS_SIGNAL_GOVERNANCE"
    assert body["kind"] == "signal_recommendation"
    assert body["pending"] == 0


def test_governance_status_counts_only_its_own_pending_previews(queue, monkeypatch):
    bridge = SignalGovernanceBridge(queue, enabled=True)
    bridge.submit_recommendations(RECS)
    # An unrelated pending decision must not be counted as a signal preview.
    other = queue.enqueue(agent="x", kind="other_kind", title="unrelated", payload={})
    queue.transition(other, TaskStatus.BLOCKED, decided_by="t", decision="await")

    body = _call(signals_router.signals_governance_status, _orch(bridge), monkeypatch)
    assert body["pending"] == 2
    assert len(queue.pending_decisions()) == 3


def test_governance_submit_is_inert_while_disabled(queue, monkeypatch):
    """The whole point of the default: wiring it changes nothing until the flag flips."""
    body = _call(
        signals_router.signals_governance_submit,
        _orch(SignalGovernanceBridge(queue)),
        monkeypatch,
    )
    assert body["available"] is True
    assert body["status"] == "disabled"
    assert body["queued"] == 0
    assert queue.list() == []


def test_governance_submit_queues_the_brief_as_blocked_previews(queue, monkeypatch):
    bridge = SignalGovernanceBridge(queue, enabled=True)
    body = _call(signals_router.signals_governance_submit, _orch(bridge), monkeypatch)

    assert body["available"] is True
    assert body["status"] == "ok"
    assert body["queued"] == 2      # the two requiresApproval recommendations
    assert body["skipped"] == 1     # the advisory one

    for tid in body["task_ids"]:
        task = queue.get(tid)
        assert task.status == TaskStatus.BLOCKED.value
        assert task.payload["preview_only"] is True
        # The brief's identity rode through to the decision inbox.
        assert task.payload["context"]["title"] == "Global Intelligence Brief"

    # Never approved, never run — this surface has no executor path.
    assert queue.list(status="approved") == []
    assert queue.list(status="running") == []


def test_governance_submit_is_honest_about_every_missing_piece(queue, monkeypatch):
    """No bridge, no sidecar, and a sidecar that says no — three distinct reasons."""
    no_bridge = _call(signals_router.signals_governance_submit, _orch(None), monkeypatch)
    assert no_bridge["available"] is False
    assert no_bridge["reason"] == "signal_governance_unavailable"

    bridge = SignalGovernanceBridge(queue, enabled=True)
    no_sidecar = _call(
        signals_router.signals_governance_submit, _orch(bridge, plugin=False), monkeypatch
    )
    assert no_sidecar["available"] is False
    assert no_sidecar["reason"] == "signal_layer_plugin_unavailable"

    # The sidecar's own status is surfaced verbatim, never replaced with a fake brief.
    refused = _call(
        signals_router.signals_governance_submit,
        _orch(bridge, brief={"status": "unavailable", "detail": "sidecar down"}),
        monkeypatch,
    )
    assert refused["available"] is False
    assert refused["reason"] == "unavailable"

    assert queue.list() == []  # nothing was queued down any of those paths


def test_the_bridge_now_has_production_importers(queue):
    """The finding itself: zero production constructors outside tests."""
    root = Path(__file__).resolve().parent.parent
    importers = {
        path.relative_to(root).as_posix()
        for path in (root / "agents").rglob("*.py")
        if "signal_governance" in path.read_text(encoding="utf-8")
        and path.name != "signal_governance.py"
    }

    assert "agents/core/orchestrator.py" in importers
    assert "agents/core/routers/signals.py" in importers

    # And the constructor is the flag-reading one, not a hardcoded enable.
    source = (root / "agents/core/orchestrator.py").read_text(encoding="utf-8")
    assert "SignalGovernanceBridge.from_env(" in source
    assert "SignalGovernanceBridge(" not in source.replace("SignalGovernanceBridge.from_env(", "")
