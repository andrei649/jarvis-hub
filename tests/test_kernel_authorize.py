"""Unit tests for the ORIZONT-24 Action Kernel facade (K1).

Proves the composition: kill-switch + capability nucleus → policy → audit, mapping
to grant | deny | queue. Covers acceptance criteria 1-3 for the K1 composition.

The later waves ship and are pinned by their own files:

* K3 loop-breaker / budget scheduler — ``agents/core/kernel/budget.py:LoopDetector``,
  threaded through :func:`agents.core.kernel.authorize` via the opt-in
  ``loop_detector`` / ``budget_ledger`` arguments; see
  ``tests/test_kernel_loop_breaker_wave.py``, ``tests/test_kernel_budget.py`` and
  ``tests/test_kernel_budget_binding.py``.
* K4 kill-switch + credential-quarantine syscalls —
  ``agents/core/kernel/syscalls.py`` (``halt`` / ``release`` / ``inject_guarded``);
  see ``tests/test_kernel_syscalls.py``.

The B1/B2/B3 bypass contracts live in ``tests/test_kernel_bypass_regressions.py``;
all three are closed there with real assertions.
"""

from pathlib import Path

from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.kernel import TOKEN_MANDATORY_KINDS, Action, Budget, Capability, Verdict, authorize
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
    """K1: the Budget object is threaded but does not change the verdict — the K3
    scheduler is inert unless a ``budget_ledger``/``loop_detector`` is supplied
    (K3 shipped; see tests/test_kernel_budget_binding.py). A tier-1 action grants
    regardless of the budget passed."""
    d = authorize(
        Action(kind="organize", payload={"risk_tier": 1}),
        budget=Budget(amount=999_999.0),
        kill_switch=_kill(tmp_path), policy=AutonomyPolicy(), audit=FakeAudit(),
    )
    assert d.verdict is Verdict.GRANT


# ── K2 wave-4b: TOKEN_MANDATORY_KINDS ─────────────────────────────────────────

def test_token_mandatory_kinds_are_the_admin_and_kg_write_kinds():
    assert {"admin.kill_switch", "admin.capability_issue", "kg.write"} == TOKEN_MANDATORY_KINDS


def test_mandatory_kind_denies_with_no_token_even_clean(tmp_path):
    """Unlike K1, a mandatory kind with NO presented token is refused even with a
    clean kill-switch and a live broker — the capability nucleus is no longer
    skippable for these kinds by simply not sending a token."""
    audit = FakeAudit()
    d = authorize(
        Action(kind="kg.write", payload={"risk_tier": 1}),
        Capability(),  # empty token
        kill_switch=_kill(tmp_path), capabilities=CapabilityBroker(),
        policy=AutonomyPolicy(), audit=audit,
    )
    assert d.verdict is Verdict.DENY
    assert "token required" in d.reason
    assert len(audit.records) == 1


def test_mandatory_kind_halted_reports_kill_switch_reason_not_missing_token(tmp_path):
    """When both are true (halted AND no token), the kill-switch reason wins —
    matches the presented-token path, where the nucleus checks the kill-switch
    before the capability."""
    kill = _kill(tmp_path)
    kill.engage(GLOBAL, "halt")
    d = authorize(
        Action(kind="admin.kill_switch", payload={}),
        Capability(),
        kill_switch=kill, capabilities=CapabilityBroker(),
        policy=AutonomyPolicy(), audit=FakeAudit(),
    )
    assert d.verdict is Verdict.DENY
    assert "kill-switch" in d.reason


def test_non_mandatory_kind_stays_k1_tolerant_without_token(tmp_path):
    """Every other KERNEL-mediated kind is unaffected by wave-4b — no token still
    falls through to kill-switch-only gating (the K1 contract), so wave-4b can't
    silently widen beyond admin.*/kg.write."""
    d = authorize(
        Action(kind="call.outbound", payload={"risk_tier": 1}),
        Capability(),
        kill_switch=_kill(tmp_path), capabilities=CapabilityBroker(),
        policy=AutonomyPolicy(), audit=FakeAudit(),
    )
    assert d.verdict is Verdict.GRANT


def test_mandatory_kind_with_no_broker_at_all_stays_k1_tolerant(tmp_path):
    """capabilities=None (no broker wired at all — the capability system itself is
    absent, not just an unminted token) falls all the way back to kill-switch-only
    gating, same as any other kind — wave-4b only bites when a broker exists but
    no token reached the nucleus."""
    d = authorize(
        Action(kind="kg.write", payload={"risk_tier": 1}),
        Capability(),
        kill_switch=_kill(tmp_path), capabilities=None,
        policy=AutonomyPolicy(), audit=FakeAudit(),
    )
    assert d.verdict is Verdict.GRANT


# ── docstring honesty guard ───────────────────────────────────────────────────


def test_module_docstring_does_not_claim_unshipped_waves():
    """The module docstring must not describe K3/K4 as deferred or point at an
    xfail scaffold that does not exist: both waves shipped and are pinned by
    real, passing files."""
    doc = __doc__ or ""
    assert doc, "module docstring disappeared"
    assert "xfail" not in doc
    assert "deferred" not in doc.lower()

    from agents.core.kernel.budget import LoopDetector  # K3
    from agents.core.kernel.syscalls import halt, inject_guarded  # K4

    assert LoopDetector is not None and halt is not None and inject_guarded is not None
    for referenced in (
        "tests/test_kernel_loop_breaker_wave.py",
        "tests/test_kernel_syscalls.py",
        "tests/test_kernel_bypass_regressions.py",
    ):
        assert referenced in doc
        assert (Path(__file__).parent.parent / referenced).is_file()


def test_no_kernel_test_is_quarantined_as_xfail():
    """No kernel test file quarantines a contract behind xfail/skip, and none of
    their module docstrings points at such a scaffold."""
    tests_dir = Path(__file__).parent
    for path in sorted(tests_dir.glob("test_kernel_*.py")):
        src = path.read_text(encoding="utf-8")
        decorators = [ln.strip() for ln in src.splitlines() if ln.strip().startswith("@")]
        quarantined = [d for d in decorators if "xfail" in d or ".skip" in d]
        assert not quarantined, f"{path.name}: {quarantined}"
        header = src.split('"""')[1] if src.startswith('"""') else ""
        assert "xfail" not in header, path.name
