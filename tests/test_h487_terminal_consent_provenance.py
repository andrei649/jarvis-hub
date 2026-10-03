"""Actual terminal producer exports private consent provenance, never approval."""
from __future__ import annotations

import json

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
)
from agents.core.autonomy.mediation import DetachedHMACSigner, canonical_json
from agents.core.autonomy.queue import TaskQueue
from agents.core.commands import Principal
from agents.core.kernel import Decision, Verdict
from tests.test_h277_smart_terminal_integration import propose, runtime  # noqa: F401


def _rewire(orch):
    orch._test_coordinator._wire_agent_tool_runtime(
        action_kernel=lambda action, **kwargs: Decision(Verdict.GRANT, reason='fixture', tier=2)
    )


async def _owner_propose(orch, *, session_id='chat', session_instance='instance'):
    turn = open_approval_turn(session_id=session_id, session_instance=session_instance,
                             principal=Principal(channel='web', admin=True),
                             session_is_live=lambda sid, instance: True)
    token = bind_approval_turn(turn)
    try:
        return await propose(orch)
    finally:
        close_approval_turn(turn, token)


@pytest.mark.asyncio
async def test_real_terminal_registration_is_stable_and_intake_exports_verified_scope(runtime, monkeypatch):
    queue, worker, orch, sandbox, _seen = runtime
    _rewire(orch)
    initial = orch.tool_rpc._tools['terminal_run']
    key = initial.get('_consent_registration_key')
    assert isinstance(key, str) and len(key) == 64
    _rewire(orch)
    current = orch.tool_rpc._tools['terminal_run']
    assert current['_consent_registration_key'] == key
    assert current['_grouping_epoch'] != initial['_grouping_epoch']
    observed = []
    original = worker.govern_enqueue

    def capture(*args, **kwargs):
        from agents.core.autonomy.approval_grouping import (
            current_model_producer,
            model_consent_semantics,
        )
        task_id = original(*args, **kwargs)
        observed.append(model_consent_semantics(current_model_producer(), queue.get(task_id)))
        return task_id

    monkeypatch.setattr(worker, 'govern_enqueue', capture)
    turn = open_approval_turn(session_id='chat', session_instance='instance',
                             principal=Principal(channel='web', admin=True),
                             session_is_live=lambda sid, instance: True)
    token = bind_approval_turn(turn)
    try:
        answer = await propose(orch)
    finally:
        close_approval_turn(turn, token)
    assert len(observed) == 1 and observed[0] is not None
    assert observed[0]['registration_key'] == key
    assert observed[0]['session_id'] == 'chat'
    assert observed[0]['request']['args']['command'] == 'printf hello'
    assert queue.get(answer['task_id']).status == 'blocked'
    assert queue._consent_source(answer['task_id'])['producer']['registration_key'] == key
    assert 'registration_key' not in str(answer)
    assert 'registration_key' not in str(queue.get(answer['task_id']).payload)
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_real_terminal_without_verified_owner_turn_exports_no_consent_scope(runtime, monkeypatch):
    queue, worker, orch, sandbox, _seen = runtime
    _rewire(orch)
    key = orch.tool_rpc._tools['terminal_run'].get('_consent_registration_key')
    assert isinstance(key, str) and len(key) == 64
    observed = []
    original = worker.govern_enqueue

    def capture(*args, **kwargs):
        from agents.core.autonomy.approval_grouping import (
            current_model_producer,
            model_consent_semantics,
        )
        task_id = original(*args, **kwargs)
        observed.append(model_consent_semantics(current_model_producer(), queue.get(task_id)))
        return task_id

    monkeypatch.setattr(worker, 'govern_enqueue', capture)
    answer = await propose(orch)
    assert observed == [None]
    assert queue.get(answer['task_id']).status == 'blocked' and sandbox.commands == []
    assert queue._consent_source(answer['task_id']) is None


@pytest.mark.asyncio
async def test_pending_source_survives_database_reopen_without_exposing_or_approving_it(runtime):
    queue, _worker, orch, sandbox, _seen = runtime
    _rewire(orch)
    task_id = (await _owner_propose(orch))['task_id']
    source = queue._consent_source(task_id)
    assert source is not None
    reopened = TaskQueue(queue.db_path, mediation_signer=queue._mediation_signer).initialize()
    try:
        assert reopened._consent_source(task_id) == source
        assert reopened.get(task_id).status == 'blocked'
        assert 'producer' not in reopened.get(task_id).to_dict()
    finally:
        reopened.close()
    assert sandbox.commands == []


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['payload', 'deadline', 'birth', 'origin', 'ready',
                                     'intent', 'namespace', 'signature', 'source', 'purpose'])
async def test_changed_intent_association_or_signed_source_refuses_consent_provenance(runtime, mutation):
    queue, _worker, orch, sandbox, _seen = runtime
    _rewire(orch)
    task_id = (await _owner_propose(orch))['task_id']
    assert queue._consent_source(task_id) is not None

    conn = queue._conn
    if mutation == 'payload':
        payload = queue.get(task_id).payload
        payload['args']['command'] = 'rm -rf synthetic'
        conn.execute('UPDATE tasks SET payload=? WHERE id=?', (json.dumps(payload), task_id))
    elif mutation == 'deadline':
        conn.execute('UPDATE tasks SET approval_deadline_at=? WHERE id=?',
                     ('2100-01-01T00:00:00+00:00', task_id))
    elif mutation == 'birth':
        conn.execute('UPDATE tasks SET created_at=? WHERE id=?', ('replaced', task_id))
    elif mutation == 'origin':
        conn.execute('UPDATE chat_approval_origins SET session_instance=?', ('replaced',))
    elif mutation == 'ready':
        conn.execute('UPDATE chat_approval_tasks SET ready=0 WHERE task_id=?', (task_id,))
    elif mutation == 'intent':
        conn.execute('UPDATE chat_approval_tasks SET intent_sha256=? WHERE task_id=?', ('0'*64, task_id))
    elif mutation == 'namespace':
        queue._group_namespace = 'replaced'
    elif mutation == 'signature':
        conn.execute('UPDATE task_consent_sources SET signature=? WHERE task_id=?', ('0'*64, task_id))
    else:
        row = conn.execute('SELECT * FROM task_consent_sources WHERE task_id=?', (task_id,)).fetchone()
        source = json.loads(row['source'])
        source['purpose' if mutation == 'purpose' else 'policy'] = 'replaced'
        encoded = canonical_json(source)
        signature = (queue._mediation_signer.sign(encoded) if mutation == 'purpose'
                     else row['signature'])
        conn.execute('UPDATE task_consent_sources SET source=?,signature=? WHERE task_id=?',
                     (encoded.decode(), signature, task_id))
    conn.commit()
    assert queue._consent_source(task_id) is None
    assert queue.get(task_id).status == 'blocked' and sandbox.commands == []


@pytest.mark.asyncio
async def test_session_purge_removes_private_source_bytes_only_for_selected_instance(runtime):
    queue, _worker, orch, sandbox, _seen = runtime
    _rewire(orch)
    first = (await _owner_propose(orch))['task_id']
    second = (await _owner_propose(orch, session_instance='another-instance'))['task_id']
    assert queue._consent_source(first) is not None
    assert queue.purge_chat_outcomes('chat', 'instance') == 1
    assert queue._conn.execute('SELECT source FROM task_consent_sources WHERE task_id=?',
                               (first,)).fetchone() is None
    assert queue._consent_source(second) is not None
    assert queue.get(first).status == 'blocked' and sandbox.commands == []
    assert queue.purge_chat_outcomes('chat') == 1
    assert queue._conn.execute('SELECT COUNT(*) FROM task_consent_sources').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_acknowledged_settled_retention_removes_source_but_preserves_pending_source(runtime):
    queue, worker, orch, _sandbox, _seen = runtime
    _rewire(orch)
    pending = (await _owner_propose(orch))['task_id']
    settled = (await _owner_propose(orch))['task_id']
    await worker.apply_decision(settled, 'reject', 'user')
    for task_id in (pending, settled):
        row = queue._conn.execute('SELECT * FROM chat_approval_tasks WHERE task_id=?',
                                  (task_id,)).fetchone()
        revision = queue._chat_observation_locked(row)['revision']
        queue._conn.execute('''UPDATE chat_approval_tasks
            SET acknowledged_at=?,acknowledged_revision=? WHERE task_id=?''',
            ('2000-01-01T00:00:00+00:00', revision, task_id))
    queue._conn.commit()
    assert queue.prune_chat_outcomes() == 1
    assert queue._conn.execute('SELECT source FROM task_consent_sources WHERE task_id=?',
                               (settled,)).fetchone() is None
    assert queue._consent_source(pending) is not None


@pytest.mark.asyncio
async def test_source_cannot_be_replayed_to_another_task_or_recaptured_in_a_new_turn(runtime, monkeypatch):
    queue, _worker, orch, sandbox, _seen = runtime
    _rewire(orch)
    first = (await _owner_propose(orch))['task_id']
    saved = dict(queue._conn.execute('SELECT * FROM task_consent_sources WHERE task_id=?',
                                    (first,)).fetchone())
    queue._conn.execute('DELETE FROM task_consent_sources WHERE task_id=?', (first,))
    queue._conn.commit()
    captured = []
    original = queue._capture_consent_source

    def capture(task_id, *, policy):
        captured.append(original(first, policy=policy))
        return original(task_id, policy=policy)

    monkeypatch.setattr(queue, '_capture_consent_source', capture)
    second = (await _owner_propose(orch))['task_id']
    assert captured == [False]
    assert queue._consent_source(first) is None
    assert queue._consent_source(second) is not None
    queue._conn.execute('UPDATE task_consent_sources SET source=?,signature=? WHERE task_id=?',
                        (saved['source'], saved['signature'], second))
    queue._conn.commit()
    assert queue._consent_source(second) is None
    assert all(queue.get(tid).status == 'blocked' for tid in (first, second))
    assert sandbox.commands == []


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['signer', 'storage'])
async def test_unavailable_source_does_not_lose_ordinary_approval(runtime, monkeypatch, failure):
    queue, _worker, orch, sandbox, _seen = runtime
    _rewire(orch)
    if failure == 'signer':
        queue._mediation_signer = DetachedHMACSigner(None)
    else:
        def fail(*args, **kwargs):
            raise RuntimeError('synthetic storage failure')
        monkeypatch.setattr(queue, '_capture_consent_source', fail)
    task_id = (await _owner_propose(orch))['task_id']
    assert queue.get(task_id).status == 'blocked'
    assert queue._consent_source(task_id) is None and sandbox.commands == []


@pytest.mark.asyncio
async def test_source_read_refuses_smart_deny_and_ordinary_owner_decision(runtime):
    from agents.core.autonomy.smart_approvals import SmartApprovalResult

    queue, worker, orch, sandbox, _seen = runtime
    _rewire(orch)
    first = (await _owner_propose(orch))['task_id']
    assert queue._consent_source(first) is not None
    await worker.apply_decision(first, 'accept', 'user')
    assert queue._consent_source(first) is None
    second = (await _owner_propose(orch))['task_id']
    assert queue._consent_source(second) is not None
    digest = queue.approval_snapshot_digest(queue.get(second))
    denial = SmartApprovalResult('deny', 'a'*64, 'b'*64, {'model': 'fixture'}, 1.0)
    assert queue.store_smart_terminal_judgement(second, digest, denial, check=lambda: True)[0]
    assert queue.smart_terminal_denial(second, digest) is not None
    assert queue._consent_source(second) is None and sandbox.commands == []


@pytest.mark.asyncio
async def test_source_helpers_do_not_commit_or_rollback_a_callers_transaction(runtime):
    queue, _worker, orch, _sandbox, _seen = runtime
    _rewire(orch)
    task_id = (await _owner_propose(orch))['task_id']
    queue._conn.execute('CREATE TABLE synthetic_transaction(value TEXT)')
    queue._conn.commit()
    queue._conn.execute('INSERT INTO synthetic_transaction VALUES(?)', ('pending',))
    assert queue._consent_source(task_id) is None
    assert not queue._capture_consent_source(task_id, policy={})
    assert queue._conn.in_transaction
    queue._conn.rollback()
    assert queue._conn.execute('SELECT COUNT(*) FROM synthetic_transaction').fetchone()[0] == 0
    assert queue._consent_source(task_id) is not None
