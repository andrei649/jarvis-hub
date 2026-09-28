"""Human decision explanations remain separate from executable/signed data."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from agents.core.autonomy.queue import TaskQueue, TaskQueueError, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker


@pytest.mark.parametrize('raw,expected', [
    (None, None), ('', None), ('   ', None), ('review this', 'review this'),
    ('  chosen by owner  ', 'chosen by owner'), ('x' * 280, 'x' * 280),
    ('a\nb\u202ec\x00d', 'a b c d'), ('\x00\u200b', None),
])
def test_reason_normalization(raw, expected):
    from agents.core.autonomy.decision_reasons import normalize_reason

    assert normalize_reason(raw) == expected


@pytest.mark.parametrize('raw', [42, True, {}, [], 'x' * 281, '\x00' * 281])
def test_reason_rejects_non_strings_and_overlong_input(raw):
    from agents.core.autonomy.decision_reasons import normalize_reason

    with pytest.raises(ValueError):
        normalize_reason(raw)


@pytest.fixture
def q(tmp_path):
    queue = TaskQueue(str(tmp_path / 'tasks.db')).initialize()
    yield queue
    queue.close()


async def blocked_task(worker, title='Delete'):
    return await worker.submit('jarvis', 'delete_file', title, {'path': 'old'}, attention_mode='none')


@pytest.mark.asyncio
@pytest.mark.parametrize('action,status', [('accept', 'approved'), ('reject', 'rejected'), ('defer', 'deferred')])
async def test_successful_decision_records_normalized_reason_and_audit(q, action, status):
    audits = []
    worker = AutonomyWorker(q, audit=SimpleNamespace(log=lambda event, data: audits.append((event, data))))
    task = await blocked_task(worker)
    result = await worker.apply_decision(task.id, action, decided_by='owner', reason=' review\nthis\u202e ')
    assert result.status == status
    assert result.human_decision['action'] == action
    assert result.human_decision['reason'] == 'review this'
    assert result.human_decision['by'] == 'owner' and result.human_decision['at']
    assert result.to_dict()['human_decision'] == result.human_decision
    assert audits[-1][1]['human_decision']['reason'] == 'review this'
    assert result.payload == task.payload and result.result is None


@pytest.mark.asyncio
async def test_executor_result_cannot_forge_or_overwrite_reason(q):
    async def executor(task):
        return {'ok': True, 'reason': 'executor says yes',
                'human_decision': {'action': 'reject', 'reason': 'forged', 'by': 'attacker'}}

    worker = AutonomyWorker(q, executor=executor)
    task = await blocked_task(worker)
    approved = await worker.apply_decision(task.id, 'accept', decided_by='owner', reason='Only this file')
    original = approved.human_decision
    assert (await worker.tick())['done'] == 1
    finished = q.get(task.id)
    assert finished.result['human_decision']['reason'] == 'forged'
    assert finished.human_decision == original
    assert finished.to_dict()['human_decision']['reason'] == 'Only this file'


@pytest.mark.asyncio
async def test_reason_survives_execution_failure_and_database_reopen(q):
    async def broken(task):
        raise RuntimeError('executor failed')

    worker = AutonomyWorker(q, executor=broken)
    task = await blocked_task(worker)
    approved = await worker.apply_decision(task.id, 'accept', reason='Owner accepts the attempt')
    for _ in range(3):
        await worker.tick()
    assert q.get(task.id).status == 'failed'
    other = TaskQueue(q.db_path).initialize()
    try:
        assert other.get(task.id).human_decision == approved.human_decision
        assert other.get(task.id).result == {'error': 'executor failed'}
    finally:
        other.close()


@pytest.mark.asyncio
async def test_omitted_later_reason_clears_previous_attribution_and_preserves_legacy_shape(q):
    worker = AutonomyWorker(q)
    task = await blocked_task(worker)
    assert 'human_decision' not in task.to_dict()
    await worker.apply_decision(task.id, 'defer', reason='Tomorrow')
    accepted = await worker.apply_decision(task.id, 'accept')
    assert accepted.human_decision['reason'] is None
    assert accepted.human_decision['action'] == 'accept'
    assert 'human_decision' not in accepted.to_dict()


@pytest.mark.asyncio
@pytest.mark.parametrize('action,reason', [('invalid', 'Bad'), ('accept', 17), ('accept', 'x' * 281)])
async def test_failed_decision_never_writes_reason(q, action, reason):
    worker = AutonomyWorker(q)
    task = await blocked_task(worker)
    before = task.to_dict()
    with pytest.raises((TaskQueueError, ValueError)):
        await worker.apply_decision(task.id, action, reason=reason)
    assert q.get(task.id).to_dict() == before


@pytest.mark.asyncio
async def test_edit_still_blocked_records_reason_but_mediated_refusal_does_not(q, monkeypatch):
    worker = AutonomyWorker(q)
    task = await blocked_task(worker)
    edited = await worker.apply_decision(task.id, 'edit', payload={'path': 'new'},
                                         decided_by='owner', reason='Use this destination')
    assert edited.status == 'blocked' and edited.payload == {'path': 'new'}
    assert edited.human_decision['action'] == 'edit'
    assert edited.human_decision['reason'] == 'Use this destination'
    before = edited.to_dict()
    q.mediation_mode = 'enforce'
    monkeypatch.setattr(q, 'classify_mediation', lambda kind: True)
    with pytest.raises(TaskQueueError, match='new enqueue revision'):
        await worker.apply_decision(task.id, 'edit', payload={'path': 'denied'}, reason='Must not persist')
    assert q.get(task.id).to_dict() == before


def test_concurrent_decision_loser_cannot_replace_winner_reason(q):
    other = TaskQueue(q.db_path).initialize()
    workers = [AutonomyWorker(q), AutonomyWorker(other)]
    try:
        for i in range(12):
            task = asyncio.run(blocked_task(workers[0], str(i)))
            gate = Barrier(2)

            def decide(index, gate=gate, task_id=task.id):
                gate.wait()
                action, reason = [('accept', 'accepted by owner'), ('reject', 'rejected by owner')][index]
                try:
                    result = asyncio.run(workers[index].apply_decision(task_id, action, reason=reason))
                    return result.human_decision
                except TaskQueueError:
                    return None

            with ThreadPoolExecutor(max_workers=2) as executor:
                answers = list(executor.map(decide, [0, 1]))
            winner = [answer for answer in answers if answer is not None]
            assert len(winner) == 1
            assert q.get(task.id).human_decision == winner[0]
            assert q.get(task.id).decision == winner[0]['action']
    finally:
        other.close()


@pytest.mark.asyncio
async def test_edit_losing_to_accept_cannot_change_payload_or_reason(q, monkeypatch):
    worker = AutonomyWorker(q)
    task = await blocked_task(worker)
    original_policy = worker._policy_decision
    other = TaskQueue(q.db_path).initialize()

    def accept_before_edit_commits(*args):
        other.transition(task.id, TaskStatus.APPROVED, decided_by='owner',
                         decision='accept', human_reason='Approved original')
        return original_policy(*args)

    monkeypatch.setattr(worker, '_policy_decision', accept_before_edit_commits)
    try:
        with pytest.raises(TaskQueueError, match='cannot accept an edit'):
            await worker.apply_decision(task.id, 'edit', payload={'path': 'loser'}, reason='Lost edit')
        current = q.get(task.id)
        assert current.payload == task.payload
        assert current.human_decision['action'] == 'accept'
        assert current.human_decision['reason'] == 'Approved original'
    finally:
        other.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["reject", "edit"])
async def test_sql_write_failure_rolls_back_decision_and_reason(q, action):
    worker = AutonomyWorker(q)
    task = await blocked_task(worker)
    before = task.to_dict()
    q._conn.execute("CREATE TRIGGER refuse_human BEFORE UPDATE ON tasks "
                    "WHEN NEW.human_decision IS NOT NULL BEGIN SELECT RAISE(ABORT, 'cannot store reason'); END")
    with pytest.raises(Exception, match='cannot store reason'):
        await worker.apply_decision(task.id, action, payload={'path': 'new'}, reason='Do not do this')
    assert q.get(task.id).to_dict() == before


@pytest.mark.asyncio
async def test_pending_requests_keep_human_reason_separate_from_machine_outcome(q, tmp_path):
    from agents.core.autonomy.pending_requests import PendingRequests, classify
    from agents.core.autonomy.work_runs import WorkRunLedger

    worker = AutonomyWorker(q)
    task = await blocked_task(worker)
    ledger = WorkRunLedger(tmp_path / 'runs.db')
    try:
        goal = SimpleNamespace(goal_id='reason-goal', title='Ship',
                               approved_by=SimpleNamespace(key='owner:accept:1'), deadline_at=0.0)
        run = ledger.open_run(goal)
        ledger.record_step(run.id, kind='writeback', summary='Delete', outcome='queued', task_id=task.id)
        decided = await worker.apply_decision(task.id, 'reject', decided_by='owner', reason='Wrong file')
        assert classify(decided) == ('rejected', 'the task was rejected')
        reply = PendingRequests(ledger, read_task=q.get).reconcile(run.id)
        assert reply.outcomes[0].human_reason == 'Wrong file'
        assert reply.outcomes[0].detail == 'the task was rejected'
        saved = ledger.steps(run.id)[0].detail
        assert saved['reason'] == 'the task was rejected' and saved['human_reason'] == 'Wrong file'
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_forged_result_reason_is_not_reconciled_as_human(q, tmp_path):
    from agents.core.autonomy.pending_requests import PendingRequests
    from agents.core.autonomy.work_runs import WorkRunLedger

    worker = AutonomyWorker(q)
    task = await blocked_task(worker)
    await worker.apply_decision(task.id, 'accept', decided_by='owner')
    q.transition(task.id, TaskStatus.RUNNING)
    q.transition(task.id, TaskStatus.DONE, result={'human_reason': 'forged by executor'})
    ledger = WorkRunLedger(tmp_path / 'forged-runs.db')
    try:
        goal = SimpleNamespace(goal_id='forged-goal', title='Ship',
                               approved_by=SimpleNamespace(key='owner:accept:1'), deadline_at=0.0)
        run = ledger.open_run(goal)
        ledger.record_step(run.id, kind='writeback', summary='Delete', outcome='queued', task_id=task.id)
        reply = PendingRequests(ledger, read_task=q.get).reconcile(run.id)
        assert reply.outcomes[0].human_reason is None
        assert 'human_reason' not in reply.outcomes[0].as_dict()
        assert 'human_reason' not in ledger.steps(run.id)[0].detail
    finally:
        ledger.close()


@pytest.mark.asyncio
async def test_reason_is_outside_signed_receipt_and_execution_fingerprint(q, monkeypatch, tmp_path):
    import hashlib
    import hmac
    from dataclasses import replace

    from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor
    from agents.core.kernel import Decision, Verdict
    from agents.core.kernel.binding import MediationKernelBridge

    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    signer = DetachedHMACSigner(lambda raw: hmac.new(b'h487-owner-key', raw, hashlib.sha256).hexdigest())
    head = [None]

    def cas(expected, replacement):
        if head[0] != expected:
            return False
        head[0] = replacement
        return True

    mediated = TaskQueue(str(tmp_path / 'mediated.db'), mediation_mode='enforce',
                         mediation_signer=signer, mediation_classifier=lambda kind: True,
                         mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas),
                         mediation_scope='global').initialize()
    worker = AutonomyWorker(mediated, mediation_signer=signer,
                            kernel=MediationKernelBridge(lambda action: Decision(Verdict.QUEUE, tier=3)))
    try:
        task = await worker.submit('jarvis', 'filesystem.write', 'Write', {'path': 'report.md'}, attention_mode='none')
        receipt = task.mediation_receipt
        chain = mediated.mediation_events()
        approved = await worker.apply_decision(task.id, 'accept', reason='Only this report')
        assert approved.mediation_receipt == receipt and mediated.mediation_events() == chain
        assert mediated.execution_fingerprint(approved) == mediated.execution_fingerprint(
            replace(approved, human_decision=None))
        assert mediated.verified_mediation_stats()['valid'] is True
        assert (await worker.tick())['done'] == 1
        assert mediated.get(task.id).human_decision['reason'] == 'Only this report'
    finally:
        mediated.close()


@pytest.mark.asyncio
async def test_api_reason_is_optional_strict_and_bounded(q, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import autonomy
    from agents.core.routers._deps import admin_guard

    worker = AutonomyWorker(q)
    monkeypatch.setattr(autonomy, 'get_orch', lambda: SimpleNamespace(autonomy=worker, autonomy_queue=q))
    monkeypatch.setitem(web.app.dependency_overrides, admin_guard, lambda: None)
    client = TestClient(web.app)
    for reason in (17, True, {}, 'x' * 281):
        task = await blocked_task(worker)
        response = client.post(f'/autonomy/tasks/{task.id}/decision', json={'action': 'reject', 'reason': reason})
        assert response.status_code == 422
        assert q.get(task.id).status == 'blocked'
    for reason in (None, '', 'x' * 280):
        task = await blocked_task(worker)
        response = client.post(f'/autonomy/tasks/{task.id}/decision', json={'action': 'reject', 'reason': reason})
        assert response.status_code == 200
        if reason:
            assert response.json()['task']['human_decision']['reason'] == reason
        else:
            assert 'human_decision' not in response.json()['task']
    task = await blocked_task(worker)
    assert client.post(f'/autonomy/tasks/{task.id}/decision', json={'action': 'reject'}).status_code == 200


@pytest.mark.asyncio
async def test_telegram_reason_attachment_is_exact_metadata_only_cas(q):
    worker = AutonomyWorker(q)
    task = await blocked_task(worker)
    rejected = await worker.apply_decision(task.id, 'reject', decided_by='telegram')
    expected = dict(rejected.human_decision)
    before = rejected.to_dict()
    assert 'human_decision' not in before and expected['reason'] is None
    assert q.attach_human_reason(task.id, 'No', expected_decision={**expected, 'id': 'other'}) is None
    attached = q.attach_human_reason(task.id, ' Wrong\nfile ', expected_decision=expected)
    assert attached.human_decision == {**expected, 'reason': 'Wrong file'}
    after = attached.to_dict()
    assert {key: value for key, value in after.items() if key != 'human_decision'} == before
    assert q.attach_human_reason(task.id, 'Replacement', expected_decision=expected) is None
    assert q.get(task.id).human_decision['reason'] == 'Wrong file'


@pytest.mark.asyncio
@pytest.mark.parametrize('action,by', [('accept', 'telegram'), ('reject', 'admin'), ('defer', 'telegram')])
async def test_telegram_attachment_rejects_wrong_decision_or_origin(q, action, by):
    worker = AutonomyWorker(q)
    task = await blocked_task(worker)
    decided = await worker.apply_decision(task.id, action, decided_by=by)
    assert q.attach_human_reason(task.id, 'Must not attach', expected_decision=decided.human_decision) is None
    assert q.get(task.id).to_dict() == decided.to_dict()
