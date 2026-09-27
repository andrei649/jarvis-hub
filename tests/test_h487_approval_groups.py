"""H487 owner registration grouping keeps every approval single-use."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents.core.autonomy.action_approvals import ActionApprovalQueue
from agents.core.autonomy.approval_grouping import OwnerRegistrationContext
from agents.core.routers import actions

ACTION = {'agent': 'owner-helper', 'tool': 'send_email', 'args': {'to': 'a@example.test'},
          'summary': 'Send this email', 'risk_tier': 2}
OWNER = OwnerRegistrationContext()


def request(q, body=None):
    return q.request(dict(ACTION if body is None else body), grouping_context=OWNER)


def test_two_rows_one_group_and_no_private_metadata_in_public_items(tmp_path):
    q = ActionApprovalQueue(tmp_path / 'actions.json')
    a, b = request(q), request(q)
    assert a['id'] != b['id'] and len(q.list('pending')) == 2
    group, = q.pending_groups()
    assert group['leader_id'] == a['id'] and group['count'] == 2
    assert group['member_ids'] == [a['id'], b['id']]
    assert set(group) == {'id', 'leader_id', 'count', 'member_ids', 'snapshot'}
    public = json.dumps([a, b, q.list(), group])
    assert '_grouping' not in public and 'fingerprint' not in public and 'namespace' not in public
    assert request(ActionApprovalQueue())['id'] not in group['member_ids']


def test_restart_retains_namespace_membership_and_snapshot(tmp_path):
    path = tmp_path / 'actions.json'
    q = ActionApprovalQueue(path)
    request(q)
    request(q)
    before = q.pending_groups()
    reopened = ActionApprovalQueue(path)
    assert reopened.pending_groups() == before
    request(reopened)
    assert reopened.pending_groups()[0]['count'] == 3
    assert reopened.pending_groups()[0]['snapshot'] != before[0]['snapshot']


@pytest.mark.parametrize('change', [
    {'agent': 'other'}, {'tool': 'delete_file'}, {'args': {'to': 'other@example.test'}},
    {'summary': 'Different intent'}, {'risk_tier': 3}, {'metadata': {'intent': 'other'}},
    {'tainted': True},
])
def test_complete_request_semantics_and_taint_do_not_merge(change):
    q = ActionApprovalQueue()
    request(q)
    request(q, {**ACTION, **change})
    assert q.pending_groups() == []


@pytest.mark.parametrize('claim', [
    {'principal': 'owner'}, {'session_id': 'existing-chat'}, {'policy_revision': 'p1'},
    {'approval_binding': 'once'}, {'task_id': 1}, {'context': {'principal': 'owner'}},
    {'metadata': {'authority': 'grant'}},
])
def test_claimed_authority_and_task_binding_opt_out(claim):
    q = ActionApprovalQueue()
    request(q, {**ACTION, **claim})
    request(q, {**ACTION, **claim})
    assert q.pending_groups() == []


@pytest.mark.parametrize('change', [{'args': []}, {'tool': 12}, {'risk_tier': True},
                                    {'args': {'value': float('nan')}}])
def test_malformed_or_noncanonical_requests_cannot_group(change):
    q = ActionApprovalQueue()
    for _ in range(2):
        request(q, {**ACTION, **change})
    assert q.pending_groups() == []


def test_direct_calls_never_group_and_namespace_is_queue_specific():
    q, other = ActionApprovalQueue(), ActionApprovalQueue()
    q.request(ACTION)
    q.request(ACTION)
    assert q.pending_groups() == []
    a, b = request(q), request(q)
    request(other)
    request(other)
    assert q.pending_groups()[0]['id'] != other.pending_groups()[0]['id']
    assert q.pending_groups()[0]['member_ids'] == [a['id'], b['id']]


async def test_once_approval_wakes_only_own_waiter_and_promotes_follower():
    q = ActionApprovalQueue()
    a, b, c = request(q), request(q), request(q)
    old = q.pending_groups()[0]
    wait_a = asyncio.create_task(q.await_decision(a['id']))
    wait_b = asyncio.create_task(q.await_decision(b['id']))
    await asyncio.sleep(0)
    q.decide(a['id'], True, by='owner')
    assert await asyncio.wait_for(wait_a, .2) == 'approved'
    assert not wait_b.done() and q.get(b['id'])['status'] == 'pending'
    current, = q.pending_groups()
    assert current['leader_id'] == b['id'] and current['member_ids'] == [b['id'], c['id']]
    assert current['snapshot'] != old['snapshot']
    q.decide(b['id'], False)
    assert await asyncio.wait_for(wait_b, .2) == 'rejected'
    assert q.get(c['id'])['status'] == 'pending'


async def test_explicit_group_rejection_is_atomic_audited_and_wakes_every_waiter():
    q = ActionApprovalQueue()
    audits = []
    q.attach_audit(SimpleNamespace(record=lambda **row: audits.append(row)))
    a, b = request(q), request(q)
    group, = q.pending_groups()
    waiters = [asyncio.create_task(q.await_decision(item['id'])) for item in [a, b]]
    result = q.reject_group(group['id'], snapshot=group['snapshot'],
                            member_ids=group['member_ids'], by='owner', reason=' Try\nstaging ')
    assert [item['status'] for item in result] == ['rejected', 'rejected']
    assert [item['human_reason'] for item in result] == ['Try staging', 'Try staging']
    assert await asyncio.gather(*waiters) == ['rejected', 'rejected']
    assert q.pending_groups() == [] and q.stats()['rejected'] == 2
    assert len(audits) == 2 and all(row['metadata']['human_reason'] == 'Try staging' for row in audits)
    assert q.decide(a['id'], True)['status'] == 'rejected'


@pytest.mark.parametrize('mutation', ['addition', 'approval', 'rejection', 'expiry'])
async def test_membership_cas_loser_changes_nothing(mutation):
    q = ActionApprovalQueue()
    a, _ = request(q), request(q)
    group, = q.pending_groups()
    if mutation == 'addition':
        request(q)
    elif mutation == 'expiry':
        await q.await_decision(a['id'], timeout=0)
    else:
        q.decide(a['id'], mutation == 'approval')
    before = q.list()
    assert q.reject_group(group['id'], snapshot=group['snapshot'],
                           member_ids=group['member_ids'], reason='Stale') is None
    assert q.list() == before


def test_wrong_members_or_invalid_reason_never_mutate():
    q = ActionApprovalQueue()
    request(q)
    request(q)
    group, = q.pending_groups()
    before = q.list()
    assert q.reject_group(group['id'], snapshot=group['snapshot'], member_ids=group['member_ids'][:1]) is None
    with pytest.raises(ValueError):
        q.reject_group(group['id'], snapshot=group['snapshot'], member_ids=group['member_ids'], reason=17)
    assert q.list() == before


@pytest.fixture
def surface(monkeypatch, tmp_path):
    from agents import web
    from agents.core import idempotency
    from agents.core.idempotency import IdempotencyStore

    q = ActionApprovalQueue(tmp_path / 'actions.json')
    app = FastAPI()
    app.include_router(actions.router)
    app.dependency_overrides[actions.user_guard] = lambda: None
    app.dependency_overrides[actions.admin_guard] = lambda: None
    monkeypatch.setattr(web, '_admin_credential_ok', lambda token: token == 'verified-secret')
    monkeypatch.setattr(web, '_admin_configured', lambda: True)
    monkeypatch.setattr(actions, 'get_orch', lambda: SimpleNamespace(action_approvals=q))
    monkeypatch.setattr(actions, 'require_component', lambda *args: (None, q, None))
    store = IdempotencyStore(tmp_path / 'idem.db')
    idempotency.set_store(store)
    yield app, q
    idempotency.set_store(None)


async def test_owner_http_producer_and_optional_projection_with_legacy_complete_actions(surface):
    app, q = surface
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert 'groups' not in (await client.get('/api/actions/pending')).json()
        owner = {'X-Admin-Token': 'verified-secret'}
        for _ in range(2):
            assert (await client.post('/api/actions/request', json=ACTION, headers=owner)).status_code == 200
        public = (await client.get('/api/actions/pending')).json()
        assert len(public['actions']) == 2 and len(public['groups']) == 1
        assert public['groups'][0]['count'] == 2
        assert 'verified-secret' not in json.dumps(public)
        assert (await client.get('/api/actions')).json()['groups'] == public['groups']
        for _ in range(2):
            await client.post('/api/actions/request', json={**ACTION, 'args': {'to': 'user'}},
                              headers={'X-User-Token': 'valid-user'})
        assert len(q.pending_groups()) == 1 and len(q.list()) == 4
        group = public['groups'][0]
        stale = await client.post(f"/api/actions/groups/{group['id']}/reject",
                                  json={'snapshot': 'bad', 'member_ids': group['member_ids']})
        assert stale.status_code == 409
        rejected = await client.post(f"/api/actions/groups/{group['id']}/reject", json={
            'snapshot': group['snapshot'], 'member_ids': group['member_ids'], 'reason': 'Use staging'})
        assert rejected.status_code == 200 and len(rejected.json()['actions']) == 2


async def test_h659_replay_first_never_adds_group_member(surface):
    app, q = surface
    owner = {'X-Admin-Token': 'verified-secret', 'Idempotency-Key': 'first'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        first = await client.post('/api/actions/request', json=ACTION, headers=owner)
        replay = await client.post('/api/actions/request', json=ACTION, headers=owner)
        assert replay.headers['Idempotent-Replayed'] == 'true'
        assert first.json()['action']['id'] == replay.json()['action']['id']
        assert len(q.list()) == 1 and q.pending_groups() == []
        await client.post('/api/actions/request', json=ACTION, headers={**owner, 'Idempotency-Key': 'second'})
        group, = q.pending_groups()
        await client.post('/api/actions/request', json=ACTION, headers=owner)
        assert q.pending_groups() == [group] and len(q.list()) == 2


def test_live_origin_taint_isolation_even_with_judge_disabled():
    from agents.core.action_origin import bind_action_origin, reset_action_origin

    q = ActionApprovalQueue()
    assert q._judge is None
    request(q)
    token = bind_action_origin('inbound')
    try:
        request(q)
        request(q)
    finally:
        reset_action_origin(token)
    group, = q.pending_groups()
    assert group['count'] == 2 and len(q.list()) == 3


def test_grouped_args_are_immutable_to_request_and_public_consumers():
    q = ActionApprovalQueue()
    body = {**ACTION, 'args': {'to': 'original'}}
    first = request(q, body)
    body['args']['to'] = 'caller changed'
    first['args']['to'] = 'public changed'
    q.get(first['id'])['args']['to'] = 'reader changed'
    request(q, {**ACTION, 'args': {'to': 'original'}})
    assert q.get(first['id'])['args'] == {'to': 'original'}
    assert len(q.pending_groups()) == 1


def test_untracked_member_edit_invalidates_exact_group_snapshot():
    q = ActionApprovalQueue()
    a, _ = request(q), request(q)
    group, = q.pending_groups()
    q._items[a['id']]['args']['to'] = 'substituted target'
    before = q.list()
    assert q.pending_groups() == []
    assert q.reject_group(group['id'], snapshot=group['snapshot'], member_ids=group['member_ids']) is None
    assert q.list() == before


def test_group_reject_save_failure_rolls_back_every_member(monkeypatch):
    q = ActionApprovalQueue()
    a, b = request(q), request(q)
    group, = q.pending_groups()
    before = q.list()

    def fail_save():
        raise OSError('disk unavailable')

    monkeypatch.setattr(q, '_save', fail_save)
    with pytest.raises(OSError, match='disk unavailable'):
        q.reject_group(group['id'], snapshot=group['snapshot'], member_ids=group['member_ids'], reason='No')
    assert q.list() == before and q.pending_groups() == [group]
    assert not q._events[a['id']].is_set() and not q._events[b['id']].is_set()


def test_reject_group_and_once_decision_have_one_atomic_winner():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    for _ in range(20):
        q = ActionApprovalQueue()
        a, b = request(q), request(q)
        group, = q.pending_groups()
        gate = Barrier(2)

        def decide(gate=gate, q=q, action_id=a['id']):
            gate.wait()
            return q.decide(action_id, True)

        def reject(gate=gate, q=q, group=group):
            gate.wait()
            return q.reject_group(group['id'], snapshot=group['snapshot'], member_ids=group['member_ids'])

        with ThreadPoolExecutor(max_workers=2) as executor:
            one, all_members = executor.submit(decide), executor.submit(reject)
            approved, rejected = one.result(), all_members.result()
        if rejected is not None:
            assert approved['status'] == 'rejected'
            assert q.get(a['id'])['status'] == q.get(b['id'])['status'] == 'rejected'
        else:
            assert approved['status'] == 'approved' and q.get(b['id'])['status'] == 'pending'


def test_advisory_annotations_do_not_revoke_group_but_rejection_clears_pending():
    q = ActionApprovalQueue()
    a, b = request(q), request(q)
    group, = q.pending_groups()
    q._judge_pending.update([a['id'], b['id']])
    q.annotate(a['id'], {'score': 0.25, 'rationale': 'Advisory only'})
    assert q.pending_groups() == [group]
    rejected = q.reject_group(group['id'], snapshot=group['snapshot'], member_ids=group['member_ids'])
    assert len(rejected) == 2 and not q._judge_pending
    assert q.annotate(b['id'], {'score': 0.1}) is None


@pytest.mark.parametrize('operation', ['request', 'approve', 'expire'])
async def test_failed_persistence_preserves_current_group_and_waiter_state(tmp_path, monkeypatch, operation):
    path = tmp_path / 'actions.json'
    q = ActionApprovalQueue(path)
    a, b = request(q), request(q)
    group, = q.pending_groups()
    before, persisted = q.list(), path.read_bytes()
    q._judge_pending.update([a['id'], b['id']])

    def fail_save():
        raise OSError('disk unavailable')

    monkeypatch.setattr(q, '_save', fail_save)
    with pytest.raises(OSError, match='disk unavailable'):
        if operation == 'request':
            request(q)
        elif operation == 'approve':
            q.decide(a['id'], True, reason='Go ahead')
        else:
            await q.await_decision(a['id'], timeout=0)
    assert [{k: v for k, v in item.items() if k != 'judge_pending'} for item in q.list()] == before
    assert q.pending_groups() == [group] and path.read_bytes() == persisted
    assert set(q._events) == {a['id'], b['id']}
    assert not any(event.is_set() for event in q._events.values())
    assert q._judge_pending == {a['id'], b['id']}
