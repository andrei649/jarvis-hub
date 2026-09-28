"""H487 task cards group registration, never signed execution authorization."""
import asyncio
import hashlib
import hmac
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents.core.autonomy.inbox import OwnerTaskRegistrationContext, is_decision_notification_leader
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.routers import autonomy

BODY = {'agent': 'jarvis', 'kind': 'delete_file', 'title': 'Delete one file',
        'payload': {'path': 'old'}, 'origin': 'generated'}


@pytest.fixture
def q(tmp_path):
    queue = TaskQueue(str(tmp_path / 'tasks.db')).initialize()
    yield queue
    queue.close()


async def submit(worker, body=None, *, trusted=True, attention='none'):
    request = dict(BODY if body is None else body)
    context = OwnerTaskRegistrationContext.from_request(request) if trusted else None
    return await worker.submit(**{key: request[key] for key in BODY}, attention_mode=attention,
                               grouping_context=context)


async def test_two_tasks_one_group_restart_and_private_snapshots(q):
    worker = AutonomyWorker(q)
    a, b = await submit(worker), await submit(worker)
    group, = q.pending_groups()
    assert group['member_ids'] == [a.id, b.id] and group['leader_id'] == a.id and group['count'] == 2
    assert set(group) == {'id', 'leader_id', 'count', 'member_ids', 'snapshot'}
    assert len(q.list(status='blocked')) == 2
    assert 'group' not in a.to_dict() and 'grouping' not in a.to_dict()
    other = TaskQueue(q.db_path).initialize()
    try:
        assert other.pending_groups() == [group]
        await submit(AutonomyWorker(other))
        assert q.pending_groups()[0]['count'] == 3
    finally:
        other.close()


@pytest.mark.parametrize('change', [{'origin': 'inbound'}, {'title': 'Another intent'},
                                   {'payload': {'path': 'other'}}, {'agent': 'other'},
                                   {'kind': 'send_email'}, {'payload': {'path': 'old', 'tainted': True}}])
async def test_full_semantics_origin_and_taint_isolation(q, change):
    worker = AutonomyWorker(q)
    await submit(worker)
    await submit(worker, {**BODY, **change})
    assert q.pending_groups() == []


@pytest.mark.parametrize('claims', [{'session_id': 'chat'}, {'principal': 'owner'},
                                   {'payload': {'path': 'old', 'authority': 'grant'}},
                                   {'context': {}}, {'task_id': 1},
                                   {'payload': {'path': 'old', 'mediation_receipt': {'signature': 'claimed'}}}])
async def test_authority_claims_and_direct_producers_opt_out(q, claims):
    worker = AutonomyWorker(q)
    body = {**BODY, **claims}
    await submit(worker, body)
    await submit(worker, body)
    assert q.pending_groups() == []
    await submit(worker, trusted=False)
    await submit(worker, trusted=False)
    assert q.pending_groups() == []


async def test_policy_revision_configuration_and_attention_isolate(q):
    worker = AutonomyWorker(q)
    await submit(worker)
    worker.policy.cap_per_action += 1
    await submit(worker)
    worker.policy.cap_per_action -= 1
    q._mediation_policy_revision = 'v2'
    await submit(worker)
    q._mediation_policy_revision = 'v1'
    await submit(worker, attention='digest')
    assert q.pending_groups() == []


async def test_accept_executes_one_promotes_follower_and_leaves_its_authority_independent(q):
    calls = []

    async def executor(task):
        calls.append(task.id)
        return {'ok': True}

    worker = AutonomyWorker(q, executor=executor)
    a, b, c = await submit(worker), await submit(worker), await submit(worker)
    first = q.pending_groups()[0]
    await worker.apply_decision(a.id, 'accept')
    group, = q.pending_groups()
    assert group['leader_id'] == b.id and group['member_ids'] == [b.id, c.id]
    assert group['snapshot'] != first['snapshot']
    assert (await worker.tick())['done'] == 1 and calls == [a.id]
    assert q.get(b.id).status == q.get(c.id).status == 'blocked'


@pytest.mark.parametrize('action', ['accept', 'reject', 'defer', 'edit'])
async def test_notification_follower_spends_no_budget_is_unpushed_and_promotes(q, action):
    deliveries = []
    notifications = []

    async def notify(task):
        notifications.append(task.id)
        return True

    class Broker:
        async def dispatch(self, delivery_id, category, callback):
            deliveries.append(delivery_id)
            await callback()
            return {'status': 'delivered'}

    worker = AutonomyWorker(q, notifier=notify, delivery_broker=Broker())
    a, b = await submit(worker, attention='interrupt'), await submit(worker, attention='interrupt')
    assert notifications == [a.id] and deliveries == [f'task-{a.id}']
    assert q.get(a.id).pushed and not q.get(b.id).pushed
    group, = q.pending_groups()
    assert is_decision_notification_leader(q, a) and not is_decision_notification_leader(q, b)
    q.mark_pushed(a.id)  # ordinary notification bookkeeping does not revoke the group
    assert q.pending_groups() == [group]
    await worker.apply_decision(a.id, action, payload={'path': 'edited'} if action == 'edit' else None)
    assert is_decision_notification_leader(q, b) and q.get(b.id).pushed
    assert notifications == ([a.id, a.id, b.id] if action == 'edit' else [a.id, b.id])
    assert len(deliveries) == (3 if action == 'edit' else 2)


async def test_explicit_reject_group_commits_all_reasons_then_audits_and_reconciles(q, monkeypatch):
    worker = AutonomyWorker(q)
    a, b = await submit(worker), await submit(worker)
    group, = q.pending_groups()
    observations = []
    monkeypatch.setattr(worker, '_audit', lambda event, task, detail:
                        observations.append(('audit', task.id, q.get(a.id).status, q.get(b.id).status)))
    monkeypatch.setattr(worker, '_reconcile_waiting_run', lambda task:
                        observations.append(('reconcile', task.id, q.get(a.id).status, q.get(b.id).status)))
    rejected = await worker.reject_group(group['id'], snapshot=group['snapshot'],
                                        member_ids=group['member_ids'], reason=' Wrong\nfile ')
    assert [task.id for task in rejected] == [a.id, b.id]
    assert all(task.human_decision['reason'] == 'Wrong file' for task in rejected)
    assert all(entry[2:] == ('rejected', 'rejected') for entry in observations)
    assert len(observations) == 4 and q.pending_groups() == []


@pytest.mark.parametrize('mutation', ['addition', 'accept', 'edit', 'defer', 'reject'])
async def test_stale_membership_or_edit_never_partially_rejects(q, mutation):
    worker = AutonomyWorker(q)
    a, _ = await submit(worker), await submit(worker)
    group, = q.pending_groups()
    if mutation == 'addition':
        await submit(worker)
    else:
        await worker.apply_decision(a.id, mutation, payload={'path': 'new'} if mutation == 'edit' else None)
    before = [task.to_dict() for task in q.list()]
    assert await worker.reject_group(group['id'], snapshot=group['snapshot'], member_ids=group['member_ids']) is None
    assert [task.to_dict() for task in q.list()] == before


async def test_sql_abort_rolls_back_all_group_statuses_and_reasons(q):
    worker = AutonomyWorker(q)
    _, b = await submit(worker), await submit(worker)
    group, = q.pending_groups()
    before = [task.to_dict() for task in q.list()]
    q._conn.execute(f"CREATE TRIGGER refuse_second BEFORE UPDATE ON tasks WHEN NEW.id={b.id} "
                    "AND NEW.status='rejected' BEGIN SELECT RAISE(ABORT, 'cannot reject second'); END")
    with pytest.raises(Exception, match='cannot reject second'):
        await worker.reject_group(group['id'], snapshot=group['snapshot'], member_ids=group['member_ids'], reason='No')
    assert [task.to_dict() for task in q.list()] == before and q.pending_groups() == [group]


def test_second_connection_accept_vs_group_reject_has_one_transaction_winner(q):
    other = TaskQueue(q.db_path).initialize()
    try:
        for i in range(10):
            worker = AutonomyWorker(q)
            a = asyncio.run(submit(worker, {**BODY, 'title': f'Race {i}'}))
            b = asyncio.run(submit(worker, {**BODY, 'title': f'Race {i}'}))
            group = q.pending_group(a.id)
            gate = Barrier(2)

            def accept(gate=gate, task_id=a.id):
                gate.wait()
                try:
                    return other.transition(task_id, TaskStatus.APPROVED, decided_by='owner',
                                            decision='accept', human_reason='Once')
                except Exception:
                    return None

            def reject(gate=gate, group=group):
                gate.wait()
                return q.reject_pending_group(group['id'], snapshot=group['snapshot'], member_ids=group['member_ids'])

            with ThreadPoolExecutor(max_workers=2) as executor:
                x, y = executor.submit(accept), executor.submit(reject)
                accepted, rejected = x.result(), y.result()
            if rejected is None:
                assert accepted and q.get(a.id).status == 'approved' and q.get(b.id).status == 'blocked'
            else:
                assert accepted is None and q.get(a.id).status == q.get(b.id).status == 'rejected'
    finally:
        other.close()


async def test_actual_admin_task_route_produces_groups_and_rejects_exact_members(q, monkeypatch):
    worker = AutonomyWorker(q)
    monkeypatch.setattr(autonomy, 'get_orch', lambda: SimpleNamespace(autonomy=worker, autonomy_queue=q))
    app = FastAPI()
    app.include_router(autonomy.router)
    app.dependency_overrides[autonomy.admin_guard] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert 'groups' not in (await client.get('/autonomy/tasks?status=blocked')).json()
        for _ in range(2):
            assert (await client.post('/autonomy/tasks', json=BODY)).status_code == 200
        public = (await client.get('/autonomy/tasks?status=blocked')).json()
        assert len(public['tasks']) == 2 and len(public['groups']) == 1
        group = public['groups'][0]
        invalid = await client.post(f"/autonomy/tasks/groups/{group['id']}/reject",
                                    json={**group, 'reason': 17})
        assert invalid.status_code == 422
        ok = await client.post(f"/autonomy/tasks/groups/{group['id']}/reject", json={
            'snapshot': group['snapshot'], 'member_ids': group['member_ids'], 'reason': 'Stop'})
        assert ok.status_code == 200 and len(ok.json()['tasks']) == 2
        for _ in range(2):
            await client.post('/autonomy/tasks', json={**BODY, 'session_id': 'claimed'})
        assert q.pending_groups() == []


async def test_mediated_grouping_preserves_individual_receipts_and_executes_only_once(tmp_path, monkeypatch):
    from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor
    from agents.core.kernel import Decision, Verdict
    from agents.core.kernel.binding import MediationKernelBridge

    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    signer = DetachedHMACSigner(lambda raw: hmac.new(b'h487-owner', raw, hashlib.sha256).hexdigest())
    head = [None]

    def cas(expected, replacement):
        if head[0] != expected:
            return False
        head[0] = replacement
        return True

    q = TaskQueue(str(tmp_path / 'mediated.db'), mediation_mode='enforce', mediation_signer=signer,
                  mediation_classifier=lambda kind: True, mediation_scope='global',
                  mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas)).initialize()
    calls = []

    async def execute(task):
        calls.append(task.id)
        return {'ok': True}

    verdict = [Verdict.QUEUE]
    worker = AutonomyWorker(q, executor=execute, mediation_signer=signer,
                            kernel=MediationKernelBridge(lambda action: Decision(verdict[0], tier=3)))
    try:
        a, b = await submit(worker), await submit(worker)
        assert a.mediation_receipt != b.mediation_receipt and q.pending_group(a.id)['count'] == 2
        assert q.execution_fingerprint(q.get(a.id)) == q.execution_fingerprint(a)
        verdict[0] = Verdict.GRANT
        c = await submit(worker)
        assert q.pending_group(c.id) is None
        assert q.pending_group(a.id)['member_ids'] == [a.id, b.id]
        receipts = {task.id: task.mediation_receipt for task in (a, b)}
        chain = q.mediation_events()
        assert all(q.get(task.id).mediation_receipt == receipts[task.id] for task in (a, b))
        assert q.mediation_events() == chain
        before = q.execution_fingerprint(a)
        q.mark_pushed(a.id)
        assert q.execution_fingerprint(q.get(a.id)) == before and q.pending_group(a.id)['count'] == 2
        await worker.apply_decision(a.id, 'accept')
        assert (await worker.tick())['done'] == 1 and calls == [a.id]
        assert q.get(b.id).status == 'blocked' and q.get(b.id).mediation_receipt == receipts[b.id]
    finally:
        q.close()


def test_group_card_is_view_only_and_keeps_single_task_callbacks():
    from agents.core.autonomy.inbox import build_decision_card

    task = {'id': 7, 'title': 'One file', 'agent': 'jarvis', 'kind': 'delete_file',
            'risk_tier': 3, 'payload': {'path': 'old'}}
    before = {**task, 'payload': dict(task['payload'])}
    baseline = build_decision_card(task)
    grouped = build_decision_card(task, group={'leader_id': 7, 'count': 3})
    assert '3 cereri identice' in grouped['text'] and 'doar acestei sarcini' in grouped['text']
    assert grouped['reply_markup']['inline_keyboard'][0][0]['text'] == '✅ Aprob o dată'
    assert [button['callback_data'] for button in grouped['reply_markup']['inline_keyboard'][0]] == [
        button['callback_data'] for button in baseline['reply_markup']['inline_keyboard'][0]]
    assert task == before
    assert build_decision_card(task, group={'leader_id': 8, 'count': 3}) == baseline


async def test_same_bytes_edit_and_signed_binding_substitution_revoke_membership(q):
    worker = AutonomyWorker(q)
    a, b = await submit(worker), await submit(worker)
    original, = q.pending_groups()
    await worker.apply_decision(a.id, 'edit', payload=dict(a.payload))
    assert q.pending_groups() == []
    assert q.reject_pending_group(original['id'], snapshot=original['snapshot'],
                                   member_ids=original['member_ids']) is None
    c = await submit(worker)
    group = q.pending_group(b.id)
    assert group['member_ids'] == [b.id, c.id]
    q._conn.execute('UPDATE tasks SET kernel_intake_id=? WHERE id=?', ('substituted', c.id))
    q._conn.commit()
    assert q.pending_groups() == []
    assert q.reject_pending_group(group['id'], snapshot=group['snapshot'], member_ids=group['member_ids']) is None


async def test_unknown_custom_policy_does_not_produce_grouping(q):
    from agents.core.autonomy.policy import ASK, Decision, RiskTier

    policy = SimpleNamespace(decide=lambda action: Decision(ASK, RiskTier.IRREVERSIBLE_OR_MONEY, 'custom'))
    worker = AutonomyWorker(q, policy=policy)
    await submit(worker)
    await submit(worker)
    assert q.pending_groups() == []


async def test_notification_failure_after_commit_never_undoes_owner_decision(q):
    async def notify(task):
        raise RuntimeError('delivery unavailable')

    worker = AutonomyWorker(q, notifier=notify)
    a, b = await submit(worker, attention='interrupt'), await submit(worker, attention='interrupt')
    original = q.pending_group(a.id)
    accepted = await worker.apply_decision(a.id, 'accept')
    assert accepted.status == 'approved' and q.get(b.id).status == 'blocked'
    assert q.get(b.id).pushed == 0
    assert q.reject_pending_group(original['id'], snapshot=original['snapshot'],
                                   member_ids=original['member_ids']) is None


async def test_live_binding_revision_change_revokes_existing_group(q):
    worker = AutonomyWorker(q)
    await submit(worker)
    await submit(worker)
    group, = q.pending_groups()
    q._mediation_policy_revision = 'v2'
    assert q.pending_groups() == []
    assert q.reject_pending_group(group['id'], snapshot=group['snapshot'], member_ids=group['member_ids']) is None


async def test_group_fanout_is_bounded_to_64_members(q):
    worker = AutonomyWorker(q)
    for _ in range(65):
        await submit(worker)
    group, = q.pending_groups()
    assert group['count'] == 64 and len(q.list(limit=100)) == 65


async def test_boolean_is_not_an_exact_task_identity_in_group_cas(q):
    worker = AutonomyWorker(q)
    a, b = await submit(worker), await submit(worker)
    assert a.id == 1
    group, = q.pending_groups()
    assert q.reject_pending_group(group['id'], snapshot=group['snapshot'], member_ids=[True, b.id]) is None
    assert q.get(a.id).status == q.get(b.id).status == 'blocked'


@pytest.mark.parametrize('action', ['accept', 'reject', 'defer', 'edit'])
async def test_follower_joining_singleton_before_settlement_is_actually_notified(q, action):
    from threading import Event

    notifications = []

    async def notify(task):
        notifications.append(task.id)
        return True

    class Broker:
        async def dispatch(self, delivery_id, category, callback):
            await callback()
            return {'status': 'delivered'}

    worker = AutonomyWorker(q, notifier=notify, delivery_broker=Broker())
    leader = await submit(worker, attention='interrupt')
    assert q.pending_group(leader.id) is None  # private singleton membership exists
    other = TaskQueue(q.db_path).initialize()
    follower_worker = AutonomyWorker(other, notifier=notify, delivery_broker=Broker())
    entered, release = Event(), Event()
    connection = q._conn

    class SettlementBoundary:
        def __getattr__(self, key):
            return getattr(connection, key)

        def execute(self, sql, *args):
            if sql == 'BEGIN IMMEDIATE':
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('settlement barrier timed out')
            return connection.execute(sql, *args)

    q._conn = SettlementBoundary()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            settling = executor.submit(lambda: asyncio.run(worker.apply_decision(
                leader.id, action, payload={'path': 'edited'} if action == 'edit' else None)))
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                follower = await submit(follower_worker, attention='interrupt')
                assert notifications == [leader.id] and not other.get(follower.id).pushed
                release.set()
                await asyncio.to_thread(settling.result, 5)
                assert notifications.count(follower.id) == 1
                assert other.get(follower.id).pushed and other.get(follower.id).status == 'blocked'
            finally:
                release.set()
    finally:
        q._conn = connection
        other.close()
