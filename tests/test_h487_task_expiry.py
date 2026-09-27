"""Persisted approval deadlines are metadata, never execution authorization."""
from datetime import UTC, datetime, timedelta

import pytest

from agents.core.autonomy import queue as module
from agents.core.autonomy.queue import TaskQueue, TaskQueueError, TaskStatus

NOW = datetime(2030, 1, 2, 12, tzinfo=UTC)


@pytest.fixture
def q(tmp_path):
    queue = TaskQueue(str(tmp_path / 'tasks.db')).initialize()
    yield queue
    queue.close()


def pending(q, *, deadline=None, status=TaskStatus.BLOCKED):
    task_id = q.enqueue('jarvis', 'test', 'One ask', payload={'x': 1},
                        approval_deadline_at=deadline)
    if status != TaskStatus.PROPOSED:
        q.transition(task_id, status)
    return task_id


@pytest.mark.parametrize('value', [1, True, datetime.now(), '', '2030-01-02',
                                   '2030-01-02T12:00:00', '2030-02-30T12:00:00Z',
                                   'NaN', 'x' * 65])
def test_strict_deadline_input(value):
    with pytest.raises(ValueError):
        module.normalize_approval_deadline(value)


def test_normalization_and_legacy_public_shape(q):
    assert module.normalize_approval_deadline(None) is None
    assert module.normalize_approval_deadline('2030-01-02T14:00:00+02:00') == '2030-01-02T12:00:00.000000+00:00'
    assert module.normalize_approval_deadline('2030-01-02T12:00:00Z') == '2030-01-02T12:00:00.000000+00:00'
    task_id = q.enqueue('jarvis', 'test', 'legacy')
    assert 'approval_deadline_at' not in q.get(task_id).to_dict()
    assert 'expired_at' not in q.get(task_id).to_dict()
    task_id = pending(q, deadline=NOW.isoformat())
    assert q.get(task_id).to_dict()['approval_deadline_at'] == '2030-01-02T12:00:00.000000+00:00'
    batch = q.expire_pending_approvals(now=NOW)
    assert [task.id for task in batch.tasks] == [task_id]
    assert batch.tasks[0].status == 'expired' and batch.tasks[0].expired_at == batch.tasks[0].approval_deadline_at
    assert batch.effects[0].task_id == task_id
    assert q.expire_pending_approvals(now=NOW).tasks == ()
    with pytest.raises(TaskQueueError):
        q.transition(task_id, TaskStatus.APPROVED)


@pytest.mark.parametrize('delta,pending_result', [(-1, True), (0, False), (1, False)])
def test_due_boundary_and_pure_predicate(q, delta, pending_result):
    task_id = pending(q, deadline=NOW.isoformat())
    clock = NOW + timedelta(microseconds=delta)
    assert module.approval_is_pending(q.get(task_id), now=clock) is pending_result
    batch = q.expire_pending_approvals(now=clock)
    assert bool(batch.tasks) is not pending_result


def test_naive_sweep_clock_refused(q):
    with pytest.raises(ValueError):
        q.expire_pending_approvals(now=NOW.replace(tzinfo=None))


@pytest.mark.parametrize('action', ['accept', 'reject', 'defer', 'edit', 'payload'])
def test_due_decision_commits_expiry_before_error_without_human_writes(q, monkeypatch, action):
    task_id = pending(q, deadline=NOW.isoformat())
    before = q.get(task_id)
    fingerprint = q.execution_fingerprint(before)
    monkeypatch.setattr(module, '_approval_now', lambda now=None: now if now is not None else NOW)
    with pytest.raises(module.TaskApprovalExpired) as caught:
        if action == 'edit':
            q.update_payload_policy(task_id, {'x': 2}, risk_tier=3, autonomy_level='ask',
                                    decided_by='web', human_reason='change', approve=False)
        elif action == 'payload':
            q.update_payload(task_id, {'x': 2})
        else:
            target = {'accept': TaskStatus.APPROVED, 'reject': TaskStatus.REJECTED,
                      'defer': TaskStatus.DEFERRED}[action]
            q.transition(task_id, target, decided_by='web', decision=action, human_reason='too late')
    task = q.get(task_id)
    assert task.status == 'expired' and task.payload == before.payload
    assert task.human_decision is None and task.decided_by is None and task.decision is None
    assert q.execution_fingerprint(task) == fingerprint
    assert caught.value.batch.tasks[0].id == task_id
    assert q.pending_approval_expiry_effects().effects == caught.value.batch.effects
    with pytest.raises(TaskQueueError):
        q.update_payload(task_id, {'late': True})


def test_early_accept_and_nonawaiting_states_never_expire(q, monkeypatch):
    ids = [pending(q, deadline=NOW.isoformat()) for _ in range(5)]
    monkeypatch.setattr(module, '_approval_now', lambda now=None: now if now is not None else NOW-timedelta(seconds=1))
    q.transition(ids[0], TaskStatus.APPROVED)
    q.transition(ids[1], TaskStatus.DEFERRED)
    q.transition(ids[2], TaskStatus.REJECTED)
    q.transition(ids[3], TaskStatus.APPROVED)
    q.transition(ids[3], TaskStatus.RUNNING)
    q.transition(ids[4], TaskStatus.APPROVED)
    q.transition(ids[4], TaskStatus.RUNNING)
    q.transition(ids[4], TaskStatus.DONE)
    assert q.expire_pending_approvals(now=NOW+timedelta(days=2)).tasks == ()
    assert [q.get(task_id).status for task_id in ids] == ['approved', 'deferred', 'rejected', 'running', 'done']
    # Deferred acceptance stays allowed; reopening the other deferred row checks the retained deadline.
    another = pending(q, deadline=NOW.isoformat())
    q.transition(another, TaskStatus.DEFERRED)
    monkeypatch.setattr(module, '_approval_now', lambda now=None: now if now is not None else NOW)
    q.transition(ids[1], TaskStatus.APPROVED)
    with pytest.raises(module.TaskApprovalExpired):
        q.transition(another, TaskStatus.BLOCKED)
    assert q.get(another).status == 'expired'


def test_ask_edit_preserves_original_deadline_and_historical_reason(q, monkeypatch):
    task_id = pending(q, deadline=NOW.isoformat())
    monkeypatch.setattr(module, '_approval_now', lambda now=None: now if now is not None else NOW-timedelta(seconds=1))
    q.update_payload_policy(task_id, {'x': 2}, risk_tier=3, autonomy_level='ask',
                            decided_by='web', human_reason='edit only', approve=False)
    edited = q.get(task_id)
    q.expire_pending_approvals(now=NOW)
    expired = q.get(task_id)
    assert expired.status == 'expired'
    assert expired.human_decision == edited.human_decision
    assert expired.approval_deadline_at == edited.approval_deadline_at
    assert q.execution_fingerprint(expired) == q.execution_fingerprint(edited)


def test_corrupt_deadline_fails_closed_and_does_not_starve_sweep(q, monkeypatch):
    bad = pending(q, deadline=NOW.isoformat())
    good = pending(q, deadline=NOW.isoformat())
    q._conn.execute("UPDATE tasks SET approval_deadline_at='not a date' WHERE id=?", (bad,))
    q._conn.commit()
    assert not module.approval_is_pending(q.get(bad), now=NOW)
    monkeypatch.setattr(module, '_approval_now', lambda now=None: now if now is not None else NOW)
    with pytest.raises(TaskQueueError, match='unreadable'):
        q.transition(bad, TaskStatus.APPROVED)
    assert q.get(bad).status == 'blocked'
    assert q.expire_pending_approvals(now=NOW, limit=1).tasks == ()
    assert q.expire_pending_approvals(now=NOW, limit=1).tasks[0].id == good
    assert q.get(bad).status == 'blocked'


def test_outbox_restart_round_robin_purged_receipts_and_ack_cas(q):
    ids = [pending(q, deadline=NOW.isoformat()) for _ in range(3)]
    q.expire_pending_approvals(now=NOW)
    first = q.pending_approval_expiry_effects(limit=1)
    assert first.effects[0].task_id == ids[0]
    other = TaskQueue(q.db_path).initialize()
    try:
        second = other.pending_approval_expiry_effects(limit=1)
        assert second.effects[0].task_id == ids[1]
        q._conn.execute('DELETE FROM tasks WHERE id=?', (ids[2],))
        q._conn.commit()
        third = other.pending_approval_expiry_effects(limit=1)
        assert third.tasks == () and third.effects[0].task_id == ids[2]
        assert other.ack_approval_expiry_effects(third) == 1
        stale = module.ApprovalExpiryBatch((), (), effects=(module.ApprovalExpiryEffect(ids[0], 'wrong'),))
        assert other.ack_approval_expiry_effects(stale) == 0
        assert other.ack_approval_expiry_effects(first) == 1
        assert other.ack_approval_expiry_effects(first) == 0
        assert other.ack_approval_expiry_effects(second) == 1
        assert other.pending_approval_expiry_effects().effects == ()
        # Whole-DB purge clears singleton state too; live queue self-seeds it.
        other._conn.execute('DELETE FROM task_approval_expiry_state')
        other._conn.commit()
        assert other.pending_approval_expiry_effects().effects == ()
    finally:
        other.close()


def test_expiry_insert_failure_rolls_back_all_metadata(q, monkeypatch):
    task_id = pending(q, deadline=NOW.isoformat())
    q._conn.execute("CREATE TRIGGER fail_expiry BEFORE INSERT ON task_approval_expiry_effects "
                    "BEGIN SELECT RAISE(ABORT, 'outbox unavailable'); END")
    q._conn.commit()
    monkeypatch.setattr(module, '_approval_now', lambda now=None: now if now is not None else NOW)
    with pytest.raises(Exception, match='outbox unavailable'):
        q.transition(task_id, TaskStatus.APPROVED)
    assert q.get(task_id).status == 'blocked' and q.get(task_id).expired_at is None
    assert q.pending_approval_expiry_effects().effects == ()


def test_due_opinion_read_and_store_refuse_before_sweep(q, monkeypatch):
    task_id = pending(q, deadline=NOW.isoformat())
    digest = q.approval_snapshot_digest(q.get(task_id))
    opinion = {'score': 0.7}
    monkeypatch.setattr(module, '_approval_now', lambda now=None: now if now is not None else NOW-timedelta(seconds=1))
    assert q.store_approval_judgement(task_id, digest, opinion) == opinion
    monkeypatch.setattr(module, '_approval_now', lambda now=None: now if now is not None else NOW)
    assert q.approval_judgement(task_id, digest) is None
    assert q.store_approval_judgement(task_id, digest, {'score': 0.8}) is None
    assert q.get(task_id).status == 'blocked'


@pytest.mark.parametrize('offset', ['+00:99', '+01:60', '-01:99', '+24:00'])
def test_invalid_offset_ranges_rejected(offset):
    with pytest.raises(ValueError):
        module.normalize_approval_deadline('2030-01-02T12:00:00' + offset)


def grouped(q, deadlines):
    from agents.core.autonomy.inbox import OwnerTaskRegistrationContext
    context = OwnerTaskRegistrationContext.from_request({'agent': 'jarvis', 'kind': 'test',
        'title': 'One ask', 'payload': {'x': 1}, 'origin': 'generated'})
    ids = []
    for deadline in deadlines:
        task_id = pending(q, deadline=deadline)
        q.register_pending_group(task_id, context=context, policy={'mode': 'ask'})
        ids.append(task_id)
    return ids, q.pending_groups()[0]


def test_due_group_member_commits_only_expiry_and_promotes_survivors(q, monkeypatch):
    ids, group = grouped(q, [NOW.isoformat(), (NOW+timedelta(days=1)).isoformat(), None])
    outsider = pending(q, deadline=NOW.isoformat())
    monkeypatch.setattr(module, '_approval_now', lambda now=None: now if now is not None else NOW)
    with pytest.raises(module.TaskApprovalExpired) as caught:
        q.reject_pending_group(group['id'], snapshot=group['snapshot'], member_ids=ids,
                               reason='reject all')
    assert [task.id for task in caught.value.batch.tasks] == ids[:1]
    assert caught.value.batch.group_ids == (group['id'],)
    assert q.get(ids[0]).status == 'expired'
    assert q.get(outsider).status == 'blocked'
    assert all(q.get(task_id).human_decision is None and q.get(task_id).status == 'blocked'
               for task_id in ids[1:])
    promoted = q.pending_groups()[0]
    assert promoted['leader_id'] == ids[1] and promoted['snapshot'] != group['snapshot']
    assert q.reject_pending_group(group['id'], snapshot=group['snapshot'], member_ids=ids) is None
    assert q.reject_pending_group(group['id'], snapshot=promoted['snapshot'], member_ids=ids[1:])


def test_due_group_singleton_remains_notification_leader(q, monkeypatch):
    ids, group = grouped(q, [NOW.isoformat(), None])
    monkeypatch.setattr(module, '_approval_now', lambda now=None: now if now is not None else NOW)
    with pytest.raises(module.TaskApprovalExpired):
        q.reject_pending_group(group['id'], snapshot=group['snapshot'], member_ids=ids)
    assert q.pending_groups() == []
    assert q.pending_group_leader(group['id']).id == ids[1]


def test_expiry_chat_revision_preserves_original_intent_and_omits_human_attribution(q):
    from agents.core.approval_outcomes import (
        bind_approval_turn,
        close_approval_turn,
        open_approval_turn,
        tool_approval_scope,
    )
    from agents.core.commands import Principal
    def turn():
        return open_approval_turn(session_id='s', session_instance='i',
            principal=Principal(channel='web', admin=True), session_is_live=lambda sid, instance: True)
    origin = turn()
    token = bind_approval_turn(origin)
    try:
        with tool_approval_scope('file_write'):
            task_id = q.enqueue('jarvis', 'test', 'Ask', approval_deadline_at=NOW.isoformat())
            q.transition(task_id, TaskStatus.BLOCKED, decided_by='policy', decision='needs-approval')
    finally:
        close_approval_turn(origin, token)
    consumer = turn()
    old = q.chat_outcome_snapshot(consumer)
    assert old[0]['intent'] == 'original'
    # Historical attribution may exist; expiry is not that person's decision.
    q._conn.execute('UPDATE tasks SET human_decision=? WHERE id=?',
                    ('{"id":"' + 'a'*32 + '","action":"edit","by":"web","at":"2030-01-01","reason":"old edit"}', task_id))
    q._conn.commit()
    intent = q._chat_intent_locked(q.get(task_id))
    batch = q.expire_pending_approvals(now=NOW)
    assert q._chat_intent_locked(batch.tasks[0]) == intent
    item, = q.chat_outcome_snapshot(consumer)
    assert item['intent'] == 'original' and item['outcome'] == 'expired_unanswered' and item['state'] == 'expired'
    assert 'decision' not in item and item['expired_at'] == batch.tasks[0].expired_at
    assert item['approval_deadline_at'] == batch.tasks[0].approval_deadline_at
    assert q.ack_chat_outcomes(consumer, old) == 0
    assert q.ack_chat_outcomes(consumer, [item]) == 1
    q._conn.execute("UPDATE chat_approval_tasks SET acknowledged_at='2000-01-01T00:00:00+00:00'")
    q._conn.commit()
    assert q.prune_chat_outcomes() == 1


@pytest.mark.parametrize('action', ['accept', 'reject', 'defer', 'edit'])
def test_waiting_second_connection_decision_uses_fresh_locked_clock(q, monkeypatch, action):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    task_id = pending(q, deadline=NOW.isoformat())
    other = TaskQueue(q.db_path).initialize()
    clock = [NOW-timedelta(seconds=1)]
    monkeypatch.setattr(module, '_approval_now', lambda now=None: now if now is not None else clock[0])
    entered = Event()
    def decide():
        entered.set()
        if action == 'edit':
            return q.update_payload_policy(task_id, {'x': 2}, risk_tier=3, autonomy_level='ask',
                                            decided_by='web', human_reason='late')
        return q.transition(task_id, {'accept': TaskStatus.APPROVED, 'reject': TaskStatus.REJECTED,
                                     'defer': TaskStatus.DEFERRED}[action],
                            decided_by='web', decision=action, human_reason='late')
    try:
        other._conn.execute('BEGIN IMMEDIATE')
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(decide)
            assert entered.wait(2)
            clock[0] = NOW
            other._conn.commit()
            with pytest.raises(module.TaskApprovalExpired):
                waiting.result(timeout=3)
        assert other.get(task_id).status == 'expired'
        assert other.get(task_id).human_decision is None
        assert len(other.pending_approval_expiry_effects().effects) == 1
    finally:
        other.close()


def test_two_connection_sweeps_expire_each_row_only_once(q):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    ids = [pending(q, deadline=NOW.isoformat()) for _ in range(5)]
    other = TaskQueue(q.db_path).initialize()
    barrier = Barrier(2)
    def sweep(queue):
        barrier.wait(timeout=3)
        return queue.expire_pending_approvals(now=NOW)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(sweep, q), pool.submit(sweep, other)
            expired = [task.id for future in (a, b) for task in future.result(timeout=3).tasks]
        assert sorted(expired) == ids
        assert len(q.pending_approval_expiry_effects().effects) == 5
    finally:
        other.close()


def test_old_database_migration_and_direct_task_defaults(tmp_path):
    import sqlite3

    from agents.core.autonomy.queue import Task
    path = str(tmp_path / 'legacy.db')
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
        risk_tier INTEGER NOT NULL DEFAULT 3, status TEXT NOT NULL DEFAULT 'proposed',
        autonomy_level TEXT NOT NULL DEFAULT 'ask', origin TEXT NOT NULL DEFAULT 'generated',
        attempts INTEGER NOT NULL DEFAULT 0, result TEXT, decided_by TEXT, decision TEXT,
        pushed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    conn.execute("INSERT INTO tasks(agent,kind,title,created_at,updated_at) VALUES('jarvis','test','legacy','old','old')")
    conn.commit()
    conn.close()
    migrated = TaskQueue(path).initialize()
    try:
        task = migrated.get(1)
        assert task.approval_deadline_at is None and task.expired_at is None
        old_fields = {key: value for key, value in task.__dict__.items()
                      if key not in {'approval_deadline_at', 'expired_at'}}
        direct = Task(**old_fields)
        assert 'approval_deadline_at' not in direct.to_dict() and 'expired_at' not in direct.to_dict()
        assert migrated.expire_pending_approvals(now=NOW).effects == ()
    finally:
        migrated.close()


def test_signed_mediated_bytes_and_replay_unchanged_by_deadline_and_expiry(tmp_path):
    import hashlib
    import hmac
    import uuid

    from agents.core.autonomy.mediation import (
        DetachedHMACSigner,
        MonotonicHeadAnchor,
        ReceiptExpectation,
        issue_receipt,
    )
    signer = DetachedHMACSigner(lambda raw: hmac.new(b'expiry-test', raw, hashlib.sha256).hexdigest())
    head = [None]
    def cas(old, new):
        if head[0] != old:
            return False
        head[0] = new
        return True
    queue = TaskQueue(str(tmp_path / 'signed.db'), mediation_mode='enforce', mediation_signer=signer,
        mediation_classifier=lambda kind: True, mediation_scope='global', mediation_policy_revision='test',
        mediation_clock_ms=lambda: 1000,
        mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas)).initialize()
    expected = ReceiptExpectation(enqueue_id=str(uuid.uuid4()), agent='jarvis', kind='filesystem.write',
        title='Write', origin='generated', scope='global', payload={'x': 1}, effective_tier=2,
        policy_revision='test', enqueue_revision=1)
    receipt = issue_receipt(signer, receipt_id=str(uuid.uuid4()), expectation=expected,
                           verdict='queue', tier=2, reason='ask', issued_at_ms=1000, expires_at_ms=100000)
    try:
        task_id = queue.enqueue_mediated('jarvis', 'filesystem.write', 'Write', {'x': 1},
                                         receipt=receipt, scope='global', approval_deadline_at=NOW.isoformat())
        queue.transition(task_id, TaskStatus.BLOCKED)
        before = queue.get(task_id)
        fingerprint = queue.execution_fingerprint(before)
        raw_before = queue._conn.execute('SELECT mediation_receipt,mediation_task_sha256 FROM tasks').fetchone()
        chain = queue.mediation_events()
        assert queue.expire_pending_approvals(now=NOW).tasks[0].id == task_id
        after = queue.get(task_id)
        assert after.mediation_receipt == before.mediation_receipt == receipt.to_dict()
        assert queue.execution_fingerprint(after) == fingerprint
        assert tuple(queue._conn.execute('SELECT mediation_receipt,mediation_task_sha256 FROM tasks').fetchone()) == tuple(raw_before)
        assert queue.mediation_events() == chain
        for new_deadline in (None, (NOW+timedelta(days=1)).isoformat()):
            with pytest.raises(TaskQueueError, match='replay'):
                queue.enqueue_mediated('jarvis', 'filesystem.write', 'Write', {'x': 1},
                    receipt=receipt, scope='global', approval_deadline_at=new_deadline)
        assert queue.get(task_id).approval_deadline_at == before.approval_deadline_at
        assert queue.get(task_id).status == 'expired'
    finally:
        queue.close()


def test_due_sweep_is_bounded_and_uses_aware_instants(q):
    ids = [pending(q, deadline='2030-01-02T14:00:00+02:00') for _ in range(4)]
    first = q.expire_pending_approvals(now=NOW, limit=2)
    second = q.expire_pending_approvals(now=NOW.astimezone(UTC), limit=2)
    assert [task.id for task in first.tasks] == ids[:2]
    assert [task.id for task in second.tasks] == ids[2:]
    assert q.expire_pending_approvals(now=NOW).effects == ()
    assert q.expire_pending_approvals(now=NOW, limit=0).effects == ()


def test_group_expiry_persistence_failure_rolls_back_membership_and_survivors(q, monkeypatch):
    ids, group = grouped(q, [NOW.isoformat(), None])
    q._conn.execute("CREATE TRIGGER fail_expiry BEFORE INSERT ON task_approval_expiry_effects "
                    "BEGIN SELECT RAISE(ABORT, 'outbox unavailable'); END")
    q._conn.commit()
    monkeypatch.setattr(module, '_approval_now', lambda now=None: now if now is not None else NOW)
    with pytest.raises(Exception, match='outbox unavailable'):
        q.reject_pending_group(group['id'], snapshot=group['snapshot'], member_ids=ids, reason='late')
    assert q.pending_groups() == [group]
    assert all(q.get(task_id).status == 'blocked' and q.get(task_id).human_decision is None for task_id in ids)
    assert q.pending_approval_expiry_effects().effects == ()
