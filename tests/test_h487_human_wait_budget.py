"""Bounded company approval wait uses durable queue facts, never queued claims."""
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from agents.core.autonomy.pending_requests import PendingRequests
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.work_runs import WorkRunLedger


@pytest.fixture
def world(tmp_path, monkeypatch):
    clock = [1_800_000_000.0]
    monkeypatch.setattr('agents.core.autonomy.queue._now',
                        lambda: datetime.fromtimestamp(clock[0], UTC).isoformat())
    monkeypatch.setattr('agents.core.autonomy.queue._approval_now',
                        lambda supplied=None: supplied or datetime.fromtimestamp(clock[0], UTC))
    q = TaskQueue(str(tmp_path / 'tasks.db')).initialize()
    ledger = WorkRunLedger(tmp_path / 'runs.db', clock=lambda: clock[0])
    run = ledger.open_run(SimpleNamespace(goal_id='g', title='Goal', approved_by='owner'),
                          budget={'max_steps': 50, 'max_seconds': 30, 'max_interrupts': 5})
    yield clock, q, ledger, run
    ledger.close()
    q.close()


def ask(q, ledger, run, *, status=TaskStatus.BLOCKED, deadline=None):
    tid = q.enqueue('jarvis', 'test', 'Ask', {}, approval_deadline_at=deadline)
    q.transition(tid, status)
    return tid, ledger.record_step(run.id, kind='ask', summary='Ask', outcome='queued', task_id=tid)


def test_real_blocked_ask_excludes_wait_and_raw_time_stays_raw(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    ask(q, ledger, run)
    clock[0] += 100
    state = ledger.budget_state(run.id)
    assert state['wall_seconds_used'] == 100
    assert state['human_wait_seconds'] == 100
    assert state['seconds_used'] == 0 and state['exceeded'] is None
    assert ledger.get(run.id).seconds_used(clock[0]) == 100


def test_union_cap_does_not_reset_for_second_source(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    ask(q, ledger, run)
    clock[0] += 100
    ask(q, ledger, run)
    clock[0] += 270
    state = ledger.budget_state(run.id)
    assert state['human_wait_seconds'] == 360
    assert state['seconds_used'] == 10
    clock[0] += 20
    assert ledger.budget_state(run.id)['exceeded'] == 'seconds'


def test_long_initial_deadline_freezes_union_ceiling_across_follower_and_restart(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    ask(q, ledger, run, deadline=datetime.fromtimestamp(clock[0] + 600, UTC).isoformat())
    clock[0] += 500
    ask(q, ledger, run, deadline=datetime.fromtimestamp(clock[0] + 700, UTC).isoformat())
    reopened = WorkRunLedger(ledger.path, clock=lambda: clock[0])
    try:
        reopened.bind_approval_task_reader(q.get)
        clock[0] += 200
        state = reopened.budget_state(run.id)
        assert state['wall_seconds_used'] == 700
        assert state['human_wait_seconds'] == 660
        assert state['seconds_used'] == 40 and state['exceeded'] == 'seconds'
    finally:
        reopened.close()


def test_long_wait_stops_at_first_human_decision(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    tid, _ = ask(q, ledger, run,
                 deadline=datetime.fromtimestamp(clock[0] + 900, UTC).isoformat())
    clock[0] += 400
    q.transition(tid, TaskStatus.APPROVED, decided_by='owner', decision='accept', human_reason=None)
    clock[0] += 400
    state = ledger.budget_state(run.id)
    assert state['human_wait_seconds'] == 400
    assert state['seconds_used'] == 400 and state['exceeded'] == 'seconds'


def test_legacy_epoch_without_ceiling_keeps_360_limit_after_reopen(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    ask(q, ledger, run, deadline=datetime.fromtimestamp(clock[0] + 900, UTC).isoformat())
    meta = ledger._wait_decode(ledger._conn.execute(
        'SELECT metadata FROM approval_wait_epochs').fetchone()[0])
    meta.pop('ceiling')
    meta.pop('initial_sources')
    ledger._conn.execute('UPDATE approval_wait_epochs SET metadata=?', (ledger._wait_encode(meta),))
    ledger._conn.commit()
    reopened = WorkRunLedger(ledger.path, clock=lambda: clock[0])
    try:
        reopened.bind_approval_task_reader(q.get)
        clock[0] += 500
        state = reopened.budget_state(run.id)
        assert state['human_wait_seconds'] == 360
        assert state['seconds_used'] == 140 and state['exceeded'] == 'seconds'
    finally:
        reopened.close()


@pytest.mark.parametrize('ceiling', [None, True, '960', -1, 60, float('nan'), float('inf')])
def test_malformed_ceiling_grants_no_credit(world, ceiling):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    ask(q, ledger, run, deadline=datetime.fromtimestamp(clock[0] + 900, UTC).isoformat())
    meta = ledger._wait_decode(ledger._conn.execute(
        'SELECT metadata FROM approval_wait_epochs').fetchone()[0])
    meta['ceiling'] = ceiling
    ledger._conn.execute('UPDATE approval_wait_epochs SET metadata=?', (ledger._wait_encode(meta),))
    ledger._conn.commit()
    clock[0] += 100
    state = ledger.budget_state(run.id)
    assert state['human_wait_seconds'] == 0
    assert state['exceeded'] == 'seconds'


def test_inflated_checksummed_ceiling_without_initial_source_proof_grants_no_credit(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    ask(q, ledger, run, deadline=datetime.fromtimestamp(clock[0] + 600, UTC).isoformat())
    clock[0] += 500
    ask(q, ledger, run)
    meta = ledger._wait_decode(ledger._conn.execute(
        'SELECT metadata FROM approval_wait_epochs').fetchone()[0])
    meta['ceiling'] = 999999
    ledger._conn.execute('UPDATE approval_wait_epochs SET metadata=?', (ledger._wait_encode(meta),))
    ledger._conn.commit()
    clock[0] += 200
    assert ledger.budget_state(run.id)['human_wait_seconds'] == 0


def test_nonfinite_checksummed_observation_grants_no_credit(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    ask(q, ledger, run)
    meta = ledger._wait_decode(ledger._conn.execute(
        'SELECT metadata FROM approval_wait_epochs').fetchone()[0])
    meta['observed'] = float('nan')
    ledger._conn.execute('UPDATE approval_wait_epochs SET metadata=?', (ledger._wait_encode(meta),))
    ledger._conn.commit()
    clock[0] += 100
    assert ledger.budget_state(run.id)['human_wait_seconds'] == 0


def test_read_only_reporting_uses_same_long_wait_bound_without_mutating_epoch(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    ask(q, ledger, run, deadline=datetime.fromtimestamp(clock[0] + 900, UTC).isoformat())
    clock[0] += 500
    assert ledger.budget_state(run.id)['human_wait_seconds'] == 500
    before = ledger._conn.execute('SELECT metadata FROM approval_wait_epochs').fetchone()[0]
    readonly = ledger.budget_state(run.id, settle=False)
    assert readonly['human_wait_seconds'] == 500
    assert readonly['seconds_used'] == 0
    assert ledger._conn.execute('SELECT metadata FROM approval_wait_epochs').fetchone()[0] == before


def test_reasonless_decision_cutoff_survives_delayed_reconcile(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    tid, _ = ask(q, ledger, run)
    clock[0] += 10
    q.transition(tid, TaskStatus.APPROVED, decided_by='owner', decision='accept', human_reason=None)
    assert q.get(tid).human_decision['at']
    clock[0] += 15
    result = PendingRequests(ledger, read_task=q.get).reconcile(run.id)
    assert result.resumed
    state = ledger.budget_state(run.id)
    assert state['human_wait_seconds'] == 10 and state['seconds_used'] == 15


@pytest.mark.parametrize('bound,status', [(False, TaskStatus.BLOCKED), (True, TaskStatus.APPROVED)])
def test_unproven_or_auto_approved_task_retains_wall_budget(world, bound, status):
    clock, q, ledger, run = world
    if bound:
        ledger.bind_approval_task_reader(q.get)
    ask(q, ledger, run, status=status)
    clock[0] += 40
    state = ledger.budget_state(run.id)
    assert state['human_wait_seconds'] == 0 and state['exceeded'] == 'seconds'


def test_restart_keeps_original_ceiling_and_closed_credit(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    tid, _ = ask(q, ledger, run)
    clock[0] += 100
    assert ledger.budget_state(run.id)['seconds_used'] == 0
    reopened = WorkRunLedger(ledger.path, clock=lambda: clock[0])
    try:
        reopened.bind_approval_task_reader(q.get)
        clock[0] += 200
        assert reopened.budget_state(run.id)['human_wait_seconds'] == 300
        q.transition(tid, TaskStatus.REJECTED, decided_by='owner', decision='reject', human_reason=None)
        clock[0] += 20
        assert PendingRequests(reopened, read_task=q.get).reconcile(run.id).resumed
        assert reopened.budget_state(run.id)['human_wait_seconds'] == 300
        assert reopened.get(run.id).fingerprint == run.fingerprint
    finally:
        reopened.close()


@pytest.mark.parametrize('invalidate', ['edit', 'defer', 'missing', 'reader', 'reuse', 'deadline'])
def test_invalidated_source_never_reopens_epoch(world, invalidate):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    tid, _ = ask(q, ledger, run)
    clock[0] += 10
    assert ledger.budget_state(run.id)['human_wait_seconds'] == 10
    if invalidate == 'edit':
        q.update_payload(tid, {'changed': True})
    elif invalidate == 'defer':
        q.transition(tid, TaskStatus.DEFERRED, decided_by='owner', decision='defer', human_reason=None)
    elif invalidate == 'missing':
        ledger.bind_approval_task_reader(lambda _: None)
    elif invalidate == 'reader':
        def broken(_):
            raise OSError('unavailable')
        ledger.bind_approval_task_reader(broken)
    elif invalidate == 'reuse':
        task = q.get(tid)
        task.created_at = '2020-01-01T00:00:00+00:00'
        ledger.bind_approval_task_reader(lambda _: task)
    else:
        task = q.get(tid)
        task.approval_deadline_at = datetime.fromtimestamp(clock[0] + 5, UTC).isoformat()
        ledger.bind_approval_task_reader(lambda _: task)
    clock[0] += 10
    assert ledger.budget_state(run.id)['human_wait_seconds'] == 10
    ledger.bind_approval_task_reader(q.get)
    if invalidate == 'defer':
        q.transition(tid, TaskStatus.BLOCKED)
    clock[0] += 10
    assert ledger.budget_state(run.id)['human_wait_seconds'] == 10


def test_explicit_deadline_shortens_credit_without_creating_expiry(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    deadline = datetime.fromtimestamp(clock[0] + 10, UTC).isoformat()
    tid, _ = ask(q, ledger, run, deadline=deadline)
    clock[0] += 20
    state = ledger.budget_state(run.id)
    assert state['human_wait_seconds'] == 10 and state['seconds_used'] == 10
    assert q.get(tid).status == 'blocked'


@pytest.mark.parametrize('metadata', ['null', '{}', '{"start":NaN}', '{"sources": []}', 'bad'])
def test_corrupt_metadata_never_grants_or_reopens(world, metadata):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    ask(q, ledger, run)
    ledger._conn.execute('UPDATE approval_wait_epochs SET metadata=?', (metadata,))
    ledger._conn.commit()
    clock[0] += 40
    assert ledger.budget_state(run.id)['exceeded'] == 'seconds'
    assert ledger.budget_state(run.id)['human_wait_seconds'] == 0


def test_backward_clock_closes_window_and_preserves_spent_wall_observation(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    ask(q, ledger, run)
    clock[0] += 400
    assert ledger.budget_state(run.id)['exceeded'] == 'seconds'
    clock[0] -= 390
    assert ledger.budget_state(run.id)['exceeded'] == 'seconds'
    clock[0] += 400
    assert ledger.budget_state(run.id)['human_wait_seconds'] <= 360


@pytest.mark.parametrize('hold', ['stop', 'barrier', 'interrupts', 'deadline', 'steps'])
def test_ordinary_answers_cannot_resume_other_hold_or_spent_budget(world, hold):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    if hold == 'barrier':
        ledger.set_barrier(run.id, {'id': 'b', 'kind': 'deadline', 'cap_at': clock[0] + 60,
                                   'until': clock[0] + 50})
    tid, _ = ask(q, ledger, run)
    if hold == 'stop':
        ledger.request_stop(run.id)
    elif hold == 'interrupts':
        ledger._conn.execute("UPDATE runs SET stop_reason='budget:interrupts' WHERE id=?", (run.id,))
    elif hold == 'deadline':
        ledger._conn.execute('UPDATE runs SET deadline_at=? WHERE id=?', (clock[0] + 5, run.id))
    elif hold == 'steps':
        ledger._conn.execute('UPDATE runs SET steps_used=50 WHERE id=?', (run.id,))
    ledger._conn.commit()
    clock[0] += 10
    q.transition(tid, TaskStatus.APPROVED, decided_by='owner', decision='accept', human_reason=None)
    result = PendingRequests(ledger, read_task=q.get).reconcile(run.id)
    assert not result.resumed and ledger.get(run.id).status != 'working'


def test_step_admission_uses_adjusted_budget_after_answer(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    tid, _ = ask(q, ledger, run)
    clock[0] += 100
    q.transition(tid, TaskStatus.APPROVED, decided_by='owner', decision='accept', human_reason=None)
    assert PendingRequests(ledger, read_task=q.get).reconcile(run.id).resumed
    step = ledger.record_step(run.id, kind='local', summary='Continue', outcome='ok')
    assert step.outcome == 'ok'
    ledger.set_barrier(run.id, {'id': 'b', 'kind': 'deadline', 'cap_at': clock[0] + 30,
                               'until': clock[0] + 20})
    assert ledger.get(run.id).barrier


def test_expiry_settlement_and_adjusted_resume_are_atomic(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    tid, step = ask(q, ledger, run, deadline=datetime.fromtimestamp(clock[0] + 15, UTC).isoformat())
    clock[0] += 40
    q.expire_pending_approvals()
    task = q.get(tid)
    result = ledger.settle_expired_ask(run.id, step.seq, task_id=tid, expired_at=task.expired_at)
    assert result.resumed and ledger.budget_state(run.id)['seconds_used'] == 25
    assert not ledger.settle_expired_ask(run.id, step.seq, task_id=tid, expired_at=task.expired_at).resumed


def test_reader_latency_cannot_credit_time_after_stale_pending_snapshot(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    tid, _ = ask(q, ledger, run)
    clock[0] += 10
    def slow_read(task_id):
        pending = q.get(task_id)
        clock[0] += 5
        q.transition(tid, TaskStatus.APPROVED, decided_by='owner', decision='accept', human_reason=None)
        clock[0] += 20
        return pending
    ledger.bind_approval_task_reader(slow_read)
    state = ledger.budget_state(run.id)
    assert state['human_wait_seconds'] == 10
    assert state['seconds_used'] == 25


def test_defer_then_accept_before_read_stops_at_first_durable_decision(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    tid, _ = ask(q, ledger, run)
    clock[0] += 10
    q.transition(tid, TaskStatus.DEFERRED, decided_by='owner', decision='defer', human_reason=None)
    clock[0] += 15
    q.transition(tid, TaskStatus.APPROVED, decided_by='owner', decision='accept', human_reason=None)
    assert ledger.budget_state(run.id)['human_wait_seconds'] == 10


def test_edit_then_accept_cannot_credit_time_for_changed_intent(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    tid, _ = ask(q, ledger, run)
    clock[0] += 10
    q.update_payload(tid, {'new': 'intent'})
    clock[0] += 15
    q.transition(tid, TaskStatus.APPROVED, decided_by='owner', decision='accept', human_reason=None)
    assert ledger.budget_state(run.id)['human_wait_seconds'] == 0


def test_failed_step_write_rolls_back_accrual_and_source_registration(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    ask(q, ledger, run)
    previous = ledger._conn.execute('SELECT metadata FROM approval_wait_epochs').fetchone()[0]
    clock[0] += 10
    ledger._conn.execute("CREATE TRIGGER fail_step BEFORE INSERT ON steps BEGIN SELECT RAISE(ABORT,'blocked'); END")
    ledger._conn.commit()
    with pytest.raises(Exception, match='blocked'):
        ask(q, ledger, run)
    assert ledger._conn.execute('SELECT metadata FROM approval_wait_epochs').fetchone()[0] == previous
    assert len(ledger.steps(run.id)) == 1


def test_old_answer_cannot_resume_new_epoch_across_ledger_connections(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    _, old = ask(q, ledger, run)
    ledger.resolve_step(run.id, old.seq, outcome='refused')
    other = WorkRunLedger(ledger.path, clock=lambda: clock[0])
    try:
        other.resume(run.id)
        _, fresh = ask(q, other, run)
        from agents.core.autonomy.work_runs import WorkRunError
        with pytest.raises(WorkRunError, match='approval_resume_held'):
            ledger.resume_after_asks(run.id, answered_seqs=[old.seq])
        assert ledger.outstanding_asks(run.id)[0].seq == fresh.seq
    finally:
        other.close()


def test_conditional_resume_requires_real_settled_source_not_invented_seq(world):
    _, q, ledger, run = world
    _, step = ask(q, ledger, run)
    ledger.resolve_step(run.id, step.seq, outcome='refused')
    from agents.core.autonomy.work_runs import WorkRunError
    with pytest.raises(WorkRunError, match='approval_resume_held'):
        ledger.resume_after_asks(run.id, answered_seqs=[step.seq + 1000])
    assert ledger.get(run.id).status == 'blocked'


def test_metadata_checksum_rejects_plausible_timing_corruption(world):
    import json
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    ask(q, ledger, run)
    meta = json.loads(ledger._conn.execute('SELECT metadata FROM approval_wait_epochs').fetchone()[0])
    meta['sources'][0]['end'] = clock[0] + 300
    meta['closed'] = True
    ledger._conn.execute('UPDATE approval_wait_epochs SET metadata=?', (json.dumps(meta),))
    ledger._conn.commit()
    clock[0] += 40
    assert ledger.budget_state(run.id)['human_wait_seconds'] == 0
    assert ledger.budget_state(run.id)['exceeded'] == 'seconds'


def test_budget_refresh_failure_rolls_back_every_epoch_and_closes_transaction(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    tid, _ = ask(q, ledger, run)
    clock[0] += 10
    q.transition(tid, TaskStatus.APPROVED, decided_by='owner', decision='accept', human_reason=None)
    assert PendingRequests(ledger, read_task=q.get).reconcile(run.id).resumed
    _, second = ask(q, ledger, run)
    before = list(ledger._conn.execute('SELECT marker,metadata FROM approval_wait_epochs ORDER BY marker'))
    ledger._conn.execute(f"""CREATE TRIGGER fail_refresh BEFORE UPDATE ON approval_wait_epochs
        WHEN OLD.marker={second.seq} BEGIN SELECT RAISE(ABORT,'refresh blocked'); END""")
    ledger._conn.commit()
    clock[0] += 10
    with pytest.raises(Exception, match='refresh blocked'):
        ledger.budget_state(run.id)
    assert not ledger._conn.in_transaction
    after = list(ledger._conn.execute('SELECT marker,metadata FROM approval_wait_epochs ORDER BY marker'))
    assert [tuple(row) for row in after] == [tuple(row) for row in before]


@pytest.mark.parametrize('method', ['budget_state', 'record_step', 'set_barrier'])
def test_mutating_budget_boundaries_hold_sqlite_write_transaction(world, monkeypatch, method):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    tid, _ = ask(q, ledger, run)
    clock[0] += 10
    q.transition(tid, TaskStatus.APPROVED, decided_by='owner', decision='accept', human_reason=None)
    assert PendingRequests(ledger, read_task=q.get).reconcile(run.id).resumed
    original = ledger._wait_credit_locked
    def check_transaction(*args):
        assert ledger._conn.in_transaction, 'budget snapshot has no write transaction'
        return original(*args)
    monkeypatch.setattr(ledger, '_wait_credit_locked', check_transaction)
    if method == 'budget_state':
        ledger.budget_state(run.id)
    elif method == 'record_step':
        ledger.record_step(run.id, kind='test', summary='Continue', outcome='ok')
    else:
        ledger.set_barrier(run.id, {'id': 'b', 'kind': 'deadline', 'cap_at': clock[0] + 20})


def test_refused_barrier_rolls_back_budget_metadata(world):
    clock, q, ledger, run = world
    ledger.bind_approval_task_reader(q.get)
    tid, _ = ask(q, ledger, run)
    clock[0] += 10
    q.transition(tid, TaskStatus.APPROVED, decided_by='owner', decision='accept', human_reason=None)
    assert PendingRequests(ledger, read_task=q.get).reconcile(run.id).resumed
    before = ledger._conn.execute('SELECT metadata FROM approval_wait_epochs').fetchone()[0]
    clock[0] += 5
    from agents.core.autonomy.work_runs import WorkRunError
    with pytest.raises(WorkRunError, match='no_time_left'):
        ledger.set_barrier(run.id, {'id': 'b', 'kind': 'deadline', 'cap_at': clock[0]})
    assert not ledger._conn.in_transaction
    assert ledger._conn.execute('SELECT metadata FROM approval_wait_epochs').fetchone()[0] == before
