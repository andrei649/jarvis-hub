"""The first decision cutoff survives later decisions and delayed consumers."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from agents.core.autonomy import queue as qm
from agents.core.autonomy.inbox import OwnerTaskRegistrationContext
from agents.core.autonomy.queue import TaskQueue, TaskStatus


@pytest.fixture
def clock_queue(tmp_path, monkeypatch):
    now = [datetime(2026, 9, 27, 12, tzinfo=UTC)]
    monkeypatch.setattr(qm, '_approval_now', lambda value=None: value or now[0])
    queue = TaskQueue(str(tmp_path / 'tasks.db')).initialize()
    yield queue, now
    queue.close()


def pending(queue):
    task_id = queue.enqueue('jarvis', 'delete_file', 'Delete', payload={'path': 'old'})
    return queue.transition(task_id, TaskStatus.BLOCKED)


@pytest.mark.parametrize('first', ['defer', 'edit'])
def test_first_decision_survives_replacement_and_reopen(clock_queue, first):
    queue, now = clock_queue
    task = pending(queue)
    if first == 'defer':
        decided = queue.transition(task.id, TaskStatus.DEFERRED, decided_by='owner',
                                   decision='defer', human_reason=None)
    else:
        decided, _ = queue.update_payload_policy_with_group(
            task.id, {'path': 'new'}, risk_tier=2, autonomy_level='ask',
            decided_by='owner', human_reason=None)
    stamp = decided.human_decision['at']
    now[0] += timedelta(seconds=100)
    accepted = queue.transition(task.id, TaskStatus.APPROVED, decided_by='owner',
                                decision='accept', human_reason=None)
    assert accepted.human_decision['first_at'] == stamp
    assert accepted.human_decision['at'] != stamp
    other = TaskQueue(queue.db_path).initialize()
    try:
        assert other.get(task.id).human_decision['first_at'] == stamp
    finally:
        other.close()


def test_group_rejection_preserves_each_members_first_decision(clock_queue):
    queue, now = clock_queue
    first, second = pending(queue), pending(queue)
    deferred = queue.transition(first.id, TaskStatus.DEFERRED, decided_by='owner',
                                decision='defer', human_reason=None)
    stamp = deferred.human_decision['at']
    queue.transition(first.id, TaskStatus.BLOCKED)
    context = OwnerTaskRegistrationContext.from_request({
        'agent': 'jarvis', 'kind': 'delete_file', 'title': 'Delete', 'payload': {'path': 'old'},
    })
    assert context is not None
    for task in (first, second):
        queue.register_pending_group(task.id, context=context, policy={})
    group = queue.pending_group(first.id)
    assert group is not None
    now[0] += timedelta(seconds=100)
    rejected = queue.reject_pending_group(group['id'], snapshot=group['snapshot'],
        member_ids=group['member_ids'], decided_by='owner')
    assert rejected[0].human_decision['first_at'] == stamp
    assert rejected[1].human_decision['first_at'] == rejected[1].human_decision['at']


@pytest.mark.parametrize('previous', [
    '{', json.dumps({'at': '2026-09-27T11:59:00+00:00'}),
    json.dumps({'first_at': None}), json.dumps({'first_at': 'invalid'}),
    json.dumps({'first_at': '2027-01-01T00:00:00+00:00'}),
])
def test_unproven_previous_history_cannot_be_relabelled_as_first_decision(clock_queue, previous):
    queue, _ = clock_queue
    task = pending(queue)
    queue._conn.execute('UPDATE tasks SET human_decision=? WHERE id=?', (previous, task.id))
    queue._conn.commit()
    accepted = queue.transition(task.id, TaskStatus.APPROVED, decided_by='owner',
                                decision='accept', human_reason=None)
    assert accepted.human_decision['first_at'] is None
    assert accepted.status == 'approved'
