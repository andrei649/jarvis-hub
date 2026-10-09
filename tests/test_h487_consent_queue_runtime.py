"""A trusted producer, one owner choice, and a later queue claim."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from contextlib import contextmanager
from dataclasses import replace

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
)
from agents.core.autonomy.consent_ledger import ConsentCategory, ConsentContext
from agents.core.autonomy.consent_types import ConsentDescriptor, OwnerConsentActor
from agents.core.autonomy.mediation import (
    DetachedHMACSigner,
    MonotonicHeadAnchor,
    ReceiptExpectation,
    issue_intake_evidence,
    issue_receipt,
)
from agents.core.autonomy.queue import TaskQueue, TaskQueueError, TaskStatus
from agents.core.commands import Principal
from agents.core.tool_rpc import ToolRPCServer


def _handler(args):
    return args


@contextmanager
def _turn(*, session="session", instance="instance"):
    turn = open_approval_turn(
        session_id=session, session_instance=instance,
        principal=Principal(channel="web", admin=True), session_is_live=lambda *_: True,
    )
    token = bind_approval_turn(turn)
    try:
        yield
    finally:
        close_approval_turn(turn, token)


@pytest.fixture
def world(tmp_path, request):
    key = b"private synthetic owner key"
    signer = DetachedHMACSigner(lambda body: hmac.new(key, body, hashlib.sha256).hexdigest())
    external = [None]
    anchor = MonotonicHeadAnchor(
        lambda: external[0],
        lambda before, after: (external.__setitem__(0, after) or True)
        if external[0] == before else False,
    )
    category = ConsentCategory("terminal.run")
    mode = getattr(request, 'param', 'off')
    b7_external = [None]
    b7_anchor = MonotonicHeadAnchor(
        lambda: b7_external[0],
        lambda before, after: (b7_external.__setitem__(0, after) or True)
        if b7_external[0] == before else False,
    )
    queue = TaskQueue(str(tmp_path / "tasks.db"), mediation_signer=signer,
                      mediation_mode=mode, mediation_head_anchor=b7_anchor,
                      mediation_scope='global', mediation_policy_revision='policy-1',
                      consent_categories=(category,), consent_head_anchor=anchor).initialize()
    policy = ["policy-1"]

    def resolve(task, source):
        producer = source["producer"]
        return ConsentDescriptor(
            ConsentContext(producer["principal"], "terminal", producer["session_id"],
                           producer["session_instance"], producer["registration_key"],
                           policy[0], "local:synthetic-target"),
            (category,), producer["registration_epoch"],
        )

    queue.bind_consent_resolver(resolve)
    captured = []

    def enqueue(agent, kind, title, *, payload, **_):
        from agents.core.autonomy.approval_grouping import current_model_producer
        if mode == 'enforce':
            now_ms = queue._clock_ms()
            expected = ReceiptExpectation(
                enqueue_id=str(uuid.uuid4()), agent=agent, kind=kind, title=title,
                origin='generated', scope='global', payload=payload, effective_tier=2,
                policy_revision='policy-1', enqueue_revision=1,
            )
            receipt = issue_receipt(
                signer, receipt_id=str(uuid.uuid4()), expectation=expected,
                verdict='queue', tier=2, reason='owner approval',
                issued_at_ms=now_ms, expires_at_ms=now_ms + 60_000,
            )
            task_id = queue.enqueue_mediated(agent, kind, title, payload, receipt=receipt,
                                             origin='generated')
        else:
            task_id = queue.enqueue(agent, kind, title, payload, origin="generated")
        intake = issue_intake_evidence(
            signer, intake_id=str(uuid.uuid4()), agent=agent, kind=kind, title=title,
            origin='generated', payload=payload, verdict='queue', tier=2,
            task_tier=queue.get(task_id).risk_tier,
            issued_at_ms=queue._clock_ms(), task_id=task_id,
        )
        assert intake is not None and queue.attach_kernel_intake_evidence(task_id, intake)
        queue.transition(task_id, TaskStatus.BLOCKED, decided_by="policy", decision="needs-approval")
        captured.append(queue._capture_consent_source(task_id, policy={"revision": policy[0]}))
        queue.register_pending_group(task_id, context=current_model_producer(),
                                     policy={"revision": policy[0]})
        return task_id

    server = ToolRPCServer(enqueue=enqueue)
    server.register_tool("terminal_run", _handler, gated=True, consent_revision="test.v1",
                         input_schema={"type": "object", "properties": {"command": {"type": "string"}}})
    assert server._tools['terminal_run']['_consent_registration_key'] is not None
    yield queue, server, policy, external, captured
    queue.close()


async def _ask(server, *, session="session", instance="instance"):
    with _turn(session=session, instance=instance):
        result = await server.handle({"tool": "terminal_run", "args": {"command": "printf synthetic"}})
    return result["task_id"]


@pytest.mark.parametrize('world', ['enforce'], indirect=True)
def test_canonical_terminal_producer_uses_physical_kernel_classification(world):
    queue, _server, _policy, _external, _captured = world
    assert queue._classification('toolrpc.terminal_run') is True
    assert queue._classification('toolrpc.unregistered_tool') is None
    assert queue._classification('terminal.exec') is True


@pytest.mark.asyncio
@pytest.mark.parametrize('world', ['off', 'enforce'], indirect=True)
async def test_exact_owner_choice_grants_and_future_request_claims(world):
    queue, server, _policy, _external, captured = world
    first = await _ask(server)
    assert captured == [True]
    assert queue._consent_source(first) is not None
    with queue._lock:
        row = queue._conn.execute('SELECT * FROM tasks WHERE id=?', (first,)).fetchone()
        assert queue._consent_intake_locked(row), (row['risk_tier'], row['kernel_intake_evidence'])
    offer = queue.pending_consent_offer(first)
    assert offer is not None and offer.member_ids == (first,)
    actor = OwnerConsentActor("admin", "admin", lambda: True)
    result = queue.decide_reusable_consent(first, offer.revision, choice="always", actor=actor)
    assert result is not None and [task.id for task in result.tasks] == [first]
    assert queue.get(first).status == "approved"
    assert queue.get(first).decision == 'consent-always'
    assert queue.get(first).human_decision['action'] == 'always'
    second = await _ask(server, instance="later")
    assert queue.approve_with_current_consent(second)
    assert queue.get(second).decided_by == "consent"
    assert queue.get(second).human_decision is None
    execution_id = str(uuid.uuid4())
    claim = queue.claim_consent(second, execution_id=execution_id, live_check=lambda: True)
    assert claim is not None and queue.get(second).status == "running"
    assert queue.verify_consent_execution(second, claim, live_check=lambda: True)
    assert not queue.consent_execution_dispatched(second, claim, live_check=lambda: True)
    with pytest.raises(TaskQueueError):
        queue.transition(second, TaskStatus.DONE, result={'ok': True})
    assert queue.consent_dispatch_current(second, claim, live_check=lambda: True)
    assert queue.consent_execution_dispatched(second, claim, live_check=lambda: True)
    assert not queue.consent_dispatch_current(second, claim, live_check=lambda: True)
    assert queue.transition(second, TaskStatus.DONE, result={'ok': True}).status == 'done'
    assert second not in queue._consent_claims
    if queue.mediation_mode == 'enforce':
        first_receipt = queue.get(first).mediation_receipt['receipt_id']
        second_receipt = queue.get(second).mediation_receipt['receipt_id']
        assert first_receipt != second_receipt
        governed = [event for event in queue.mediation_events() if event['outcome'] == 'governed']
        assert [(event['task_id'], event['execution_id'], event['receipt_id']) for event in governed] == [
            (second, execution_id, second_receipt),
        ]


@pytest.mark.asyncio
async def test_policy_change_blocks_future_reuse(world):
    queue, server, policy, _external, captured = world
    first = await _ask(server)
    offer = queue.pending_consent_offer(first)
    assert offer is not None
    actor = OwnerConsentActor("admin", "admin", lambda: True)
    assert queue.decide_reusable_consent(first, offer.revision, choice="session", actor=actor)
    policy[0] = "policy-2"
    later = await _ask(server)
    assert not queue.approve_with_current_consent(later)
    assert queue.get(later).status == "blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize('world', ['enforce'], indirect=True)
async def test_offer_revision_and_owner_liveness_are_atomic_for_exact_followers(world):
    queue, server, _policy, _external, _captured = world
    with _turn():
        first = (await server.handle({"tool": "terminal_run", "args": {"command": "printf synthetic"}}))["task_id"]
        second = (await server.handle({"tool": "terminal_run", "args": {"command": "printf synthetic"}}))["task_id"]
    offer = queue.pending_consent_offer(first)
    assert offer is not None and offer.member_ids == (first, second)
    asleep = OwnerConsentActor("admin", "admin", lambda: False)
    assert queue.decide_reusable_consent(first, offer.revision, choice="always", actor=asleep) is None
    wrong_channel = OwnerConsentActor("owner", "admin", lambda: True)
    assert queue.decide_reusable_consent(first, offer.revision,
                                         choice="always", actor=wrong_channel) is None
    assert [queue.get(i).status for i in offer.member_ids] == ["blocked", "blocked"]
    queue.update_payload(second, queue.get(second).payload)
    awake = OwnerConsentActor("admin", "admin", lambda: True)
    assert queue.decide_reusable_consent(first, offer.revision, choice="always", actor=awake) is None
    assert [queue.get(i).status for i in offer.member_ids] == ["blocked", "blocked"]


@pytest.mark.asyncio
@pytest.mark.parametrize('world', ['enforce'], indirect=True)
async def test_owner_choice_settles_exact_followers_with_distinct_receipts(world):
    queue, server, _policy, _external, _captured = world
    with _turn():
        first = (await server.handle({"tool": "terminal_run", "args": {"command": "printf synthetic"}}))["task_id"]
        second = (await server.handle({"tool": "terminal_run", "args": {"command": "printf synthetic"}}))["task_id"]
    offer = queue.pending_consent_offer(first)
    assert offer is not None and offer.member_ids == (first, second)
    result = queue.decide_reusable_consent(
        first, offer.revision, choice='session',
        actor=OwnerConsentActor('admin', 'admin', lambda: True),
    )
    assert result is not None and tuple(task.id for task in result.tasks) == (first, second)
    assert all(task.status == 'approved' and task.human_decision['action'] == 'session'
               for task in result.tasks)
    assert queue.get(first).mediation_receipt['receipt_id'] != queue.get(second).mediation_receipt['receipt_id']
    execution_id = str(uuid.uuid4())
    assert queue.claim_consent(second, execution_id=execution_id,
                               live_check=lambda: True) is not None
    governed = [event for event in queue.mediation_events() if event['outcome'] == 'governed']
    assert [(event['task_id'], event['execution_id']) for event in governed] == [(second, execution_id)]


@pytest.mark.asyncio
async def test_revoked_then_regranted_category_does_not_revive_staged_task(world):
    queue, server, _policy, _external, _captured = world
    first = await _ask(server)
    offer = queue.pending_consent_offer(first)
    assert offer is not None
    actor = OwnerConsentActor("admin", "admin", lambda: True)
    assert queue.decide_reusable_consent(first, offer.revision, choice="always", actor=actor)
    later = await _ask(server)
    assert queue.approve_with_current_consent(later)
    source = queue._conn.execute('SELECT source FROM task_consent_sources WHERE task_id=?',
                                 (later,)).fetchone()[0]
    import json
    context = ConsentContext(**json.loads(source)['descriptor']['context'])
    assert queue._consent_ledger.revoke(context)
    assert queue._consent_ledger.grant(context, (ConsentCategory("terminal.run"),),
                                       choice="always", decision_id="different-decision",
                                       decided_by="admin")
    assert queue.claim_consent(later, execution_id="stale", live_check=lambda: True) is None


@pytest.mark.asyncio
async def test_corrupt_proof_cannot_downgrade_to_generic_running(world):
    queue, server, _policy, _external, _captured = world
    first = await _ask(server)
    offer = queue.pending_consent_offer(first)
    assert offer is not None
    assert queue.decide_reusable_consent(
        first, offer.revision, choice="session",
        actor=OwnerConsentActor("admin", "admin", lambda: True),
    )
    queue._conn.execute('UPDATE task_consent_proofs SET signature=? WHERE task_id=?',
                        ('0' * 64, first))
    queue._conn.commit()
    assert queue.consent_task_marker(first)
    with pytest.raises(TaskQueueError):
        queue.transition(first, TaskStatus.RUNNING)
    assert queue.claim_consent(first, execution_id="forged", live_check=lambda: True) is None
    assert queue.get(first).status == "approved"


@pytest.mark.asyncio
async def test_new_owner_choice_witnesses_its_own_decision_when_session_grant_exists(world):
    import json

    queue, server, _policy, _external, _captured = world
    actor = OwnerConsentActor("admin", "admin", lambda: True)
    first = await _ask(server)
    first_offer = queue.pending_consent_offer(first)
    assert first_offer is not None
    assert queue.decide_reusable_consent(first, first_offer.revision,
                                         choice="session", actor=actor)
    first_proof = json.loads(queue._conn.execute(
        'SELECT payload FROM task_consent_proofs WHERE task_id=?', (first,)
    ).fetchone()[0])
    second = await _ask(server)
    second_offer = queue.pending_consent_offer(second)
    assert second_offer is not None
    assert queue.decide_reusable_consent(second, second_offer.revision,
                                         choice="always", actor=actor)
    second_proof = json.loads(queue._conn.execute(
        'SELECT payload FROM task_consent_proofs WHERE task_id=?', (second,)
    ).fetchone()[0])
    assert first_proof['witness']['terminal.run']['scope'] == 'session'
    assert second_proof['witness']['terminal.run']['scope'] == 'always'
    assert second_proof['witness']['terminal.run']['decision_id'] == second_proof['decision_id']
    assert queue.claim_consent(second, execution_id=str(uuid.uuid4()),
                               live_check=lambda: True) is not None


@pytest.mark.asyncio
async def test_unanchored_legacy_source_cannot_mint_reusable_grant(world):
    queue, server, _policy, _external, captured = world
    queue._consent_ledger = None  # Synthetic missing external anchor at intake.
    task_id = await _ask(server)
    assert captured == [True]
    source = queue._consent_source(task_id)
    assert source is not None and source['version'] == 1
    assert queue.pending_consent_offer(task_id) is None
    assert not queue.approve_with_current_consent(task_id)
    assert queue.get(task_id).status == 'blocked'


@pytest.mark.asyncio
async def test_external_head_or_immutable_source_change_blocks_staged_claim(world):
    queue, server, _policy, external, _captured = world
    first = await _ask(server)
    offer = queue.pending_consent_offer(first)
    assert offer is not None
    assert queue.decide_reusable_consent(
        first, offer.revision, choice='always',
        actor=OwnerConsentActor('admin', 'admin', lambda: True),
    )
    later = await _ask(server)
    assert queue.approve_with_current_consent(later)
    external[0] = replace(external[0], signature='0' * 64)
    assert queue.claim_consent(later, execution_id=str(uuid.uuid4()),
                               live_check=lambda: True) is None
    assert queue.get(later).status == 'approved'


@pytest.mark.asyncio
@pytest.mark.parametrize('head_state', ['missing', 'corrupt'])
async def test_unavailable_anchored_head_omits_reusable_offer(world, head_state):
    queue, server, _policy, external, _captured = world
    task_id = await _ask(server)
    assert queue._consent_source(task_id)['version'] == 2
    assert queue.pending_consent_offer(task_id) is not None
    external[0] = None if head_state == 'missing' else replace(external[0], signature='0' * 64)
    assert queue.pending_consent_offer(task_id) is None
    assert queue.get(task_id).status == 'blocked'


@pytest.mark.asyncio
async def test_failed_execution_releases_in_memory_consent_claim(world):
    queue, server, _policy, _external, _captured = world
    first = await _ask(server)
    offer = queue.pending_consent_offer(first)
    assert offer is not None
    assert queue.decide_reusable_consent(
        first, offer.revision, choice='session',
        actor=OwnerConsentActor('admin', 'admin', lambda: True),
    )
    claim = queue.claim_consent(first, execution_id=str(uuid.uuid4()), live_check=lambda: True)
    assert claim is not None and queue._consent_claims[first] is claim
    assert queue.transition(first, TaskStatus.FAILED, result={'error': 'synthetic'}).status == 'failed'
    assert first not in queue._consent_claims


@pytest.mark.asyncio
async def test_forged_consent_marker_cannot_use_generic_transition(world):
    queue, server, _policy, _external, _captured = world
    task_id = await _ask(server)
    with pytest.raises(TaskQueueError):
        queue.transition(task_id, TaskStatus.APPROVED,
                         decided_by='consent', decision='auto-consent-always')
    assert queue.get(task_id).status == 'blocked'


@pytest.mark.asyncio
async def test_missing_proof_with_corrupt_decider_still_cannot_fall_back(world):
    queue, server, _policy, _external, _captured = world
    first = await _ask(server)
    offer = queue.pending_consent_offer(first)
    assert offer is not None
    assert queue.decide_reusable_consent(
        first, offer.revision, choice='always',
        actor=OwnerConsentActor('admin', 'admin', lambda: True),
    )
    queue._conn.execute('DELETE FROM task_consent_proofs WHERE task_id=?', (first,))
    queue._conn.execute("UPDATE tasks SET decided_by='policy' WHERE id=?", (first,))
    queue._conn.commit()
    assert queue.consent_task_marker(first)
    with pytest.raises(TaskQueueError):
        queue.transition(first, TaskStatus.RUNNING)
    assert queue.claim_consent(first, execution_id=str(uuid.uuid4()),
                               live_check=lambda: True) is None
