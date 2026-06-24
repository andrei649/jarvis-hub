"""Unit tests for the ORIZONT-24 Action Kernel facade (K1).

Proves the composition: kill-switch + capability nucleus → policy → audit, mapping
to grant | deny | queue. Covers acceptance criteria 1-3 (the K3 loop-breaker is
criterion 4, deferred; quarantine is the K4 half of criterion 3, scaffolded
xfail in test_kernel_bypass_regressions.py).
"""

from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.kernel import Action, Budget, Capability, Verdict, authorize
from agents.core.security.capability import GLOBAL, CapabilityBroker, KillSwitch


class FakeAudit:
    """Captures record(actor, action, why, metadata) calls (the IntentLog shape)."""

    def __init__(self):
        self.records = []

    def record(self, actor, action, why, metadata=None):
        self.records.append({"actor": actor, "action": action, "why": why,
                             "metadata": metadata})


def _kill(tmp_path):
    return KillSwitch(tmp_path / "kill.json")


def test_no_capability_denies(tmp_path):
    """Criterion 1: a missing/insufficient capability → deny(reason), audited once."""
    broker = CapabilityBroker()
    audit = FakeAudit()
    d = authorize(
        Action(kind="node.dispatch", scope="node:x", payload={"risk_tier": 2}),
        Capability(token_id="does-not-exist", name="run"),
        kill_switch=_kill(tmp_path), capabilities=broker,
        policy=AutonomyPolicy(), audit=audit,
    )
    assert d.verdict is Verdict.DENY
    assert "capability" in d.reason
    assert not d.allowed
    assert len(audit.records) == 1
    assert audit.records[0]["actor"] == "kernel"


def test_valid_capability_then_policy(tmp_path):
    """A valid capability passes the nucleus; the policy then decides the verdict."""
    broker = CapabilityBroker()
    tok = broker.issue(["run"], ttl=3600.0)["id"]
    audit = FakeAudit()
    d = authorize(
        Action(kind="node.dispatch", scope="node:x", payload={"risk_tier": 1}),
        Capability(token_id=tok, name="run"),
        kill_switch=_kill(tmp_path), capabilities=broker,
        policy=AutonomyPolicy(), audit=audit,
    )
    # tier 1 (reversible) → ACT → GRANT
    assert d.verdict is Verdict.GRANT
    assert d.allowed
    assert len(audit.records) == 1


def test_reversible_grants(tmp_path):
    """Criterion 2a: a reversible action (tier 1) under budget → grant."""
    d = authorize(
        Action(kind="organize", payload={"risk_tier": 1}),
        kill_switch=_kill(tmp_path), policy=AutonomyPolicy(), audit=FakeAudit(),
    )
    assert d.verdict is Verdict.GRANT
    assert d.tier == 1


def test_irreversible_queues(tmp_path):
    """Criterion 2b: an irreversible action (tier 3) → queue with an approval card."""
    audit = FakeAudit()
    d = authorize(
        Action(kind="delete_account", payload={"risk_tier": 3}),
        kill_switch=_kill(tmp_path), policy=AutonomyPolicy(), audit=audit,
    )
    assert d.verdict is Verdict.QUEUE
    assert d.tier == 3
    assert d.card is not None and d.card.get("requires_approval") is True
    assert len(audit.records) == 1


def test_kill_switch_halts_grant(tmp_path):
    """Criterion 3 (grant-halt half): engaging the kill-switch denies new grants."""
    kill = _kill(tmp_path)
    kill.engage(GLOBAL, "test halt")
    audit = FakeAudit()
    d = authorize(
        Action(kind="organize", payload={"risk_tier": 1}, scope=GLOBAL),
        kill_switch=kill, policy=AutonomyPolicy(), audit=audit,
    )
    assert d.verdict is Verdict.DENY
    assert "kill-switch" in d.reason
    assert len(audit.records) == 1


def test_scoped_kill_switch_only_halts_its_scope(tmp_path):
    """A node-scoped halt must not block a different scope (carry scope through)."""
    kill = _kill(tmp_path)
    kill.engage("node:phone", "halt one node")
    # a different node scope still grants
    d = authorize(
        Action(kind="organize", payload={"risk_tier": 1}, scope="node:laptop"),
        kill_switch=kill, policy=AutonomyPolicy(), audit=FakeAudit(),
    )
    assert d.verdict is Verdict.GRANT
    # the halted scope is denied
    d2 = authorize(
        Action(kind="organize", payload={"risk_tier": 1}, scope="node:phone"),
        kill_switch=kill, policy=AutonomyPolicy(), audit=FakeAudit(),
    )
    assert d2.verdict is Verdict.DENY


def test_budget_is_inert_in_k1(tmp_path):
    """K1: the Budget object is threaded but does not change the verdict (K3 gives
    it teeth). A tier-1 action grants regardless of the budget passed."""
    d = authorize(
        Action(kind="organize", payload={"risk_tier": 1}),
        budget=Budget(amount=999_999.0),
        kill_switch=_kill(tmp_path), policy=AutonomyPolicy(), audit=FakeAudit(),
    )
    assert d.verdict is Verdict.GRANT
