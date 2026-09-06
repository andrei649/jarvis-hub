"""E1.3 / B4 — ``nerva.ledger.v1`` cognitive-ledger chain (hermetic).

The chain is built over a real ``ShadowDecisionRouter`` record, a real sealed
``issue_receipt()`` receipt and a real ``compare_outcome()`` observation, so
the tests prove the ledger points at the records that already exist rather
than at synthetic stand-ins.  No network, no filesystem, no OS permissions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from dataclasses import FrozenInstanceError, replace

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "agents"))

from agents.core.autonomy.mediation import (  # noqa: E402
    DetachedHMACSigner,
    ReceiptExpectation,
    issue_receipt,
    payload_digest,
)
from agents.core.cognitive_ledger import (  # noqa: E402
    AUTHORITY,
    SCHEMA,
    ActionIntent,
    AuthorizationRecord,
    EvidenceRecord,
    ExecutionRecord,
    GoalBudget,
    GoalScope,
    GoalSpec,
    LedgerChain,
    LedgerRef,
    OutcomeRecord,
    VerificationRecord,
    load_chain,
    load_record,
    summarize,
)
from agents.core.cortex_decision import DecisionRecord, ShadowDecisionRouter  # noqa: E402
from agents.core.memory.atlas_snapshot import AtlasConfidence  # noqa: E402
from agents.core.memory.episodes import EpisodeReference  # noqa: E402
from agents.core.reflection_lesson import compare_outcome  # noqa: E402

_DIGEST = "b" * 64
_ENQUEUE_ID = "6f1a3d2e-8c4b-4f1e-9a7d-2b3c4d5e6f70"
_RECEIPT_ID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
_PAYLOAD = {"target": "window:Notepad", "step": "click", "name": "File"}


class _FakeIntent:
    def __init__(self) -> None:
        self.target_agents = ["ultron", "jarvis"]
        self.is_general = False
        self.confidence = 0.83
        self.context = {"source": "keyword", "scores": {"ultron": 4.0, "jarvis": 1.0}}


class _FakeRouter:
    async def classify(self, text, agents):
        return _FakeIntent()

    async def classify_deterministic(self, text, agents):
        return _FakeIntent()


class _KernelDecision:
    """Duck-typed kernel ``Decision`` (verdict carries ``.value`` like the StrEnum)."""

    class _Verdict:
        def __init__(self, value: str) -> None:
            self.value = value

    def __init__(self, verdict: str, tier: int | None = 2, reason: str = "ok") -> None:
        self.verdict = self._Verdict(verdict)
        self.tier = tier
        self.reason = reason


class _Action:
    kind = "desktop.step"
    agent = "jarvis"
    title = "Click File in Notepad"
    payload = _PAYLOAD
    scope = "global"
    origin = "generated"


async def _decision_record() -> DecisionRecord:
    captured: list[DecisionRecord] = []
    router = ShadowDecisionRouter(_FakeRouter(), captured.append)
    await router.classify("open notepad and click file", {"ultron": {}, "jarvis": {}})
    assert len(captured) == 1
    return captured[0]


def _signer() -> DetachedHMACSigner:
    key = b"ledger-test-key"
    return DetachedHMACSigner(lambda b: hmac.new(key, b, hashlib.sha256).hexdigest())


def _receipt(verdict: str = "grant", payload=None):
    expectation = ReceiptExpectation(
        enqueue_id=_ENQUEUE_ID,
        agent="jarvis",
        kind="desktop.step",
        title="Click File in Notepad",
        origin="generated",
        scope="global",
        payload=_PAYLOAD if payload is None else payload,
        effective_tier=2,
        policy_revision="policy-v1",
        enqueue_revision=1,
    )
    receipt = issue_receipt(
        _signer(),
        receipt_id=_RECEIPT_ID,
        expectation=expectation,
        verdict=verdict,
        tier=2,
        reason="ok",
        issued_at_ms=3_000,
        expires_at_ms=63_000,
    )
    assert receipt is not None
    return receipt


def _episode_ref(role: str, record_id: str, occurred_at: float) -> EpisodeReference:
    return EpisodeReference.build(
        role=role,  # type: ignore[arg-type]
        source_id="ledger-fixture",
        record_id=record_id,
        source_kind="synthetic_public",
        source_schema="nerva.episode.v1",
        privacy_class="personal",
        integrity_sha256=_DIGEST,
        occurred_at=occurred_at,
        deletion_root_id=f"root:{record_id}",
        confidence=AtlasConfidence("unknown"),
    )


def _observation(matched: bool = True):
    outcome = _episode_ref("outcome", "outcome-1", 9.0)
    return compare_outcome(
        episode_id="episode-1",
        expected_reference=_episode_ref("decision", "decision-1", 2.0),
        observed_references=(outcome,),
        matches_expectation={outcome.reference_id: matched},
        environment="hermetic-fixture",
        observed_at=9.0,
        created_at=9.5,
    )


def _goal(*, approved: bool = True, created_at: float = 1.0, title: str = "Tidy") -> GoalSpec:
    return GoalSpec.build(
        created_at=created_at,
        privacy_class="personal",
        goal_id="goal-notepad",
        title=title,
        scope=GoalScope(domains=("desktop",), capability_ids=("tool.rpc",)),
        budget=GoalBudget(steps=5, wall_seconds=120.0, usd=0.0),
        deadline_at=100.0,
        stop_conditions=("budget exhausted", "owner halt"),
        approved_by=LedgerRef("nerva.audit.v1", "audit-1", _DIGEST, "personal")
        if approved
        else None,
    )


def _full_chain(decision: DecisionRecord, *, verified: bool = True):
    goal = _goal()
    receipt = _receipt()
    intent = ActionIntent.from_action(
        _Action(),
        goal=goal,
        created_at=2.0,
        privacy_class="private_local",
        decision_ref=LedgerRef.from_decision_record(decision),
    )
    authorization = AuthorizationRecord.from_decision(
        _KernelDecision("grant"),
        intent=intent,
        created_at=3.0,
        decided_at=3.0,
        privacy_class="private_local",
        receipt=receipt,
    )
    execution = ExecutionRecord.build(
        created_at=6.0,
        privacy_class="private_local",
        authorization_ref=LedgerRef.to_record(authorization),
        task_id="41",
        execution_id="exec-1",
        status="done",
        started_at=4.0,
        finished_at=6.0,
    )
    reality_run = {
        "schema": "nerva.reality.run.v1",
        "harness_id": "operator-capabilities",
        "finished_at": "2026-09-06T00:00:07+00:00",
        "totals": {"passed": 7, "total": 7},
    }
    verification = VerificationRecord.build(
        created_at=7.0,
        privacy_class="private_local",
        execution_ref=LedgerRef.to_record(execution),
        method="reality_run",
        run_ref=LedgerRef.from_reality_run(reality_run),
        verdict="verified" if verified else "not_verified",
        environment="local",
        verified_at=7.0,
    )
    observation = _observation(matched=verified)
    outcome = OutcomeRecord.from_observation(
        observation, verification=verification, created_at=9.5
    )
    evidence = EvidenceRecord.build(
        created_at=10.0,
        privacy_class="private_local",
        claim="Notepad File menu opened as the owner asked",
        environment="local",
        sources=(LedgerRef.to_record(outcome), LedgerRef.to_record(verification)),
        observed_at=9.5,
    )
    records = (goal, intent, authorization, execution, verification, outcome, evidence)
    return LedgerChain.build(records), records, receipt, reality_run, observation


async def test_chain_links_real_decision_receipt_and_observation():
    decision = await _decision_record()
    chain, records, receipt, reality_run, observation = _full_chain(decision)
    goal, intent, authorization, execution, verification, outcome, evidence = records

    # Every derived record names its sources and the trace reaches the goal.
    trace = chain.trace(evidence.record_id)
    assert [r.record_kind for r in trace] == [
        "goal", "intent", "authorization", "execution", "verification", "outcome",
    ]
    assert intent.decision_ref.integrity_sha256 == decision.replay_fingerprint
    assert authorization.receipt_ref.record_id == receipt.receipt_id
    assert intent.payload_sha256 == receipt.payload_sha256 == payload_digest(_PAYLOAD)
    assert outcome.observation_ref.record_id == observation.observation_id

    # External refs are bound by fingerprint when the caller supplies them.
    external = {
        ("nerva.decision.v1", intent.decision_ref.record_id): decision.replay_fingerprint,
        ("nerva.reality.run.v1", verification.run_ref.record_id): hashlib.sha256(
            json.dumps(reality_run, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    chain.validate(external=external)
    with pytest.raises(ValueError, match="external ref .* integrity mismatch"):
        chain.validate(
            external={("nerva.decision.v1", intent.decision_ref.record_id): "0" * 64}
        )
    assert {ref.record_schema for ref in chain.unresolved} == {
        "nerva.audit.v1",
        "nerva.decision.v1",
        "nerva.mediation.receipt.v1",
        "nerva.reality.run.v1",
        "nerva.outcome-observation.v1",
    }

    # Round trip through canonical payloads preserves identity and fingerprint.
    reloaded = load_chain(chain.to_payloads())
    assert reloaded.fingerprint == chain.fingerprint
    assert reloaded.records == chain.records
    summary = summarize(chain)
    assert summary["schema"] == SCHEMA and summary["authority"] == AUTHORITY
    assert summary["executed_done"] == 1 and summary["verified"] == 1
    for record in records:
        assert record.record_id.startswith(f"ledger:{record.record_kind}:")
        assert (record.can_authorize, record.can_execute, record.can_mark_complete) == (
            False, False, False,
        )


async def test_broken_source_ref_is_rejected():
    decision = await _decision_record()
    chain, records, *_ = _full_chain(decision)
    goal, intent, authorization = records[:3]

    # A ref to a record that is not in the chain.
    with pytest.raises(ValueError, match="not in the chain"):
        LedgerChain.build(records[1:])
    # A ref whose integrity digest does not match the retained record.
    forged_ref = replace(LedgerRef.to_record(goal), integrity_sha256="c" * 64)
    forged_intent = replace(intent, record_id="", goal_ref=forged_ref)
    with pytest.raises(ValueError, match="integrity mismatch"):
        LedgerChain.build((goal, forged_intent))
    # A tampered record_id no longer matches the content.
    with pytest.raises(ValueError, match="record_id does not match"):
        replace(authorization, record_id="ledger:authorization:000000000000000000000000")
    # Chronology: a derived record cannot precede its source.
    early = replace(intent, record_id="", created_at=0.5)
    with pytest.raises(ValueError, match="precedes its goal source"):
        LedgerChain.build((goal, early))


def test_supersession_retains_prior_and_never_forks_or_overwrites():
    draft = _goal(approved=False, created_at=1.0, title="Draft")
    approved = draft.superseded_by(
        created_at=1.5,
        approved_by=LedgerRef("nerva.audit.v1", "audit-1", _DIGEST, "personal"),
    )
    chain = LedgerChain.build((draft, approved))
    assert len(chain.records) == 2 and chain.heads == (approved,)
    assert approved.supersedes_record_id == draft.record_id
    assert draft in chain.records  # retained, never overwritten

    # An approved goal is frozen: it cannot be superseded again.
    with pytest.raises(ValueError, match="approved goal is frozen"):
        chain.append(approved.superseded_by(created_at=2.0, title="Renamed"))
    # Two records superseding the same prior is a fork.
    with pytest.raises(ValueError, match="fork"):
        chain.append(draft.superseded_by(created_at=1.6, title="Other"))
    # Supersession cannot change goal_id or precede the prior.
    with pytest.raises(ValueError, match="cannot change goal_id"):
        LedgerChain.build((draft, draft.superseded_by(created_at=1.7, goal_id="other")))
    with pytest.raises(ValueError, match="cannot precede"):
        LedgerChain.build((draft, draft.superseded_by(created_at=0.5, title="Past")))
    # Supersession must name a retained record.
    with pytest.raises(ValueError, match="retained record"):
        LedgerChain.build((approved,))
    # An intent under an unapproved goal is rejected.
    intent = ActionIntent.from_action(
        _Action(), goal=draft, created_at=2.0, privacy_class="personal"
    )
    with pytest.raises(ValueError, match="requires an approved goal"):
        LedgerChain.build((draft, intent))


def test_privacy_only_escalates_along_the_chain():
    restricted_goal = replace(_goal(), record_id="", privacy_class="restricted")
    with pytest.raises(ValueError, match="cannot fall below its sources"):
        ActionIntent.from_action(
            _Action(), goal=restricted_goal, created_at=2.0, privacy_class="personal"
        )
    intent = ActionIntent.from_action(
        _Action(), goal=restricted_goal, created_at=2.0, privacy_class="restricted"
    )
    assert intent.privacy_class == "restricted"
    with pytest.raises(ValueError, match="privacy class"):
        LedgerRef("nerva.audit.v1", "audit-1", _DIGEST, "secret")
    with pytest.raises(ValueError, match="privacy class"):
        replace(_goal(), record_id="", privacy_class="internal")


def test_forged_authorization_is_rejected():
    goal = _goal()
    intent = ActionIntent.from_action(
        _Action(), goal=goal, created_at=2.0, privacy_class="personal"
    )
    common = {"created_at": 3.0, "decided_at": 3.0, "privacy_class": "personal"}

    # grant without a sealed receipt is a forgery, whichever way it is built.
    with pytest.raises(ValueError, match="forged"):
        AuthorizationRecord.build(
            intent_ref=LedgerRef.to_record(intent),
            verdict="grant", tier=2, reason_sha256=_DIGEST, **common,
        )
    with pytest.raises(ValueError, match="forged"):
        AuthorizationRecord.from_decision(_KernelDecision("grant"), intent=intent, **common)
    # A receipt sealed over a different payload does not bind this intent.
    with pytest.raises(ValueError, match="does not bind the intent payload"):
        AuthorizationRecord.from_decision(
            _KernelDecision("grant"), intent=intent,
            receipt=_receipt(payload={"other": True}), **common,
        )
    # A receipt whose verdict differs from the recorded decision is rejected.
    with pytest.raises(ValueError, match="verdict differs"):
        AuthorizationRecord.from_decision(
            _KernelDecision("grant"), intent=intent, receipt=_receipt("queue"), **common
        )
    # A queue verdict needs no receipt, but nothing may run on it.
    queued = AuthorizationRecord.from_decision(
        _KernelDecision("queue"), intent=intent, **common
    )
    assert queued.receipt_ref is None and queued.authority == "record_only"
    chain = LedgerChain.build((goal, intent, queued))
    chain.append(ExecutionRecord.build(
        created_at=4.0, privacy_class="personal",
        authorization_ref=LedgerRef.to_record(queued),
        task_id="7", execution_id="exec-q", status="queued",
    ))
    with pytest.raises(ValueError, match="requires a grant"):
        chain.append(ExecutionRecord.build(
            created_at=4.0, privacy_class="personal",
            authorization_ref=LedgerRef.to_record(queued),
            task_id="7", execution_id="exec-q", status="done",
            started_at=3.5, finished_at=4.0,
        ))
    denied = AuthorizationRecord.from_decision(
        _KernelDecision("deny", reason="kill_switch"), intent=intent, **common
    )
    with pytest.raises(ValueError, match="denied"):
        LedgerChain.build((goal, intent, denied)).append(ExecutionRecord.build(
            created_at=4.0, privacy_class="personal",
            authorization_ref=LedgerRef.to_record(denied),
            task_id="7", execution_id="exec-d", status="queued",
        ))


async def test_authority_flags_are_immutable_and_forged_payloads_are_rejected():
    decision = await _decision_record()
    chain, records, *_ = _full_chain(decision)
    authorization = records[2]

    with pytest.raises(FrozenInstanceError):
        authorization.can_execute = True  # type: ignore[misc]
    with pytest.raises(ValueError):
        replace(authorization, can_authorize=True)

    payload = authorization.canonical_payload()
    for flag in ("can_authorize", "can_execute", "can_mark_complete"):
        forged = dict(payload, **{flag: True})
        with pytest.raises(ValueError, match=f"{flag} is forged"):
            load_record(forged)
    with pytest.raises(ValueError, match="authority is forged"):
        load_record(dict(payload, authority="kernel"))
    with pytest.raises(ValueError, match="schema"):
        load_record(dict(payload, schema="nerva.ledger.v2"))
    # Editing a field in the payload breaks the content address.
    with pytest.raises(ValueError, match="record_id does not match"):
        load_record(dict(payload, verdict="deny", receipt_ref=None))


async def test_fingerprint_is_stable_and_loader_rejects_unknown_keys_and_bool_times():
    decision = await _decision_record()
    chain_a, records_a, *_ = _full_chain(decision)
    chain_b, records_b, *_ = _full_chain(decision)
    assert chain_a.fingerprint == chain_b.fingerprint
    assert [r.fingerprint for r in records_a] == [r.fingerprint for r in records_b]
    assert records_a[0].to_json() == json.dumps(
        records_a[0].canonical_payload(), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    )
    changed, *_ = _full_chain(decision, verified=False)
    assert changed.fingerprint != chain_a.fingerprint

    payload = records_a[0].canonical_payload()
    with pytest.raises(ValueError, match="keys do not match"):
        load_record(dict(payload, extra="x"))
    with pytest.raises(ValueError, match="keys do not match"):
        load_record({k: v for k, v in payload.items() if k != "budget"})
    with pytest.raises(ValueError, match="numeric timestamp"):
        load_record(dict(payload, created_at=True))
    with pytest.raises(ValueError, match="numeric timestamp"):
        load_record(dict(payload, deadline_at=False))
    with pytest.raises(ValueError, match="keys do not match"):
        load_record(dict(payload, budget=dict(payload["budget"], tokens=1)))
    with pytest.raises(ValueError, match="kind is not recognized"):
        load_record(dict(payload, record_kind="lesson"))
    with pytest.raises(ValueError, match="numeric timestamp"):
        GoalSpec.build(**{
            **{k: getattr(records_a[0], k) for k in (
                "privacy_class", "goal_id", "title", "scope", "budget",
                "deadline_at", "stop_conditions", "approved_by",
            )},
            "created_at": True,
        })


async def test_ran_is_not_verified_and_scope_deadline_are_enforced():
    decision = await _decision_record()
    chain, records, *_ = _full_chain(decision, verified=False)
    goal, intent, authorization, execution, verification, outcome, _ = records
    assert execution.status == "done" and verification.verdict == "not_verified"
    assert outcome.comparison_status == "refuted"
    summary = summarize(chain)
    assert summary["executed_done"] == 1 and summary["verified"] == 0

    # A confirmed outcome cannot rest on an unverified verification.
    with pytest.raises(ValueError, match="requires a verified verification"):
        chain.append(OutcomeRecord.from_observation(
            _observation(matched=True), verification=verification, created_at=9.6
        ))
    # Verification needs a finished execution and must follow it.
    running = replace(execution, record_id="", status="running", finished_at=None)
    with pytest.raises(ValueError, match="finished execution"):
        LedgerChain.build((goal, intent, authorization, running)).append(
            replace(verification, record_id="", execution_ref=LedgerRef.to_record(running))
        )
    with pytest.raises(ValueError, match="precedes the execution"):
        LedgerChain.build((goal, intent, authorization, execution)).append(
            replace(verification, record_id="", verified_at=5.0)
        )
    # not_exercised must state why.
    with pytest.raises(ValueError, match="limitation"):
        replace(verification, record_id="", verdict="not_exercised")
    # Scope and deadline of the approved goal bind every intent.
    with pytest.raises(ValueError, match="outside the goal scope"):
        LedgerChain.build((goal, replace(intent, record_id="", kind="call.outbound")))
    with pytest.raises(ValueError, match="past the goal deadline"):
        LedgerChain.build((goal, replace(intent, record_id="", created_at=101.0)))
    assert LedgerChain.build((goal, replace(intent, record_id="", kind="tool.rpc")))
    with pytest.raises(ValueError, match="scope cannot be empty"):
        GoalScope()
