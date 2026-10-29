"""A dialog response is claimed once beside its current signed opener."""
from __future__ import annotations

import asyncio
import contextvars
import threading
import uuid

import pytest

from agents.core.autonomy.mediation import ReceiptExpectation, issue_receipt
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker, _ExecutionPermit
from tests.test_task_mediation_evidence import NOW_MS, _head_anchor, _signer


def _queue(tmp_path):
    path = tmp_path / 'dialog.db'
    return TaskQueue(
        db_path=str(path), mediation_mode='enforce', mediation_signer=_signer(),
        mediation_head_anchor=_head_anchor(path),
        mediation_classifier=lambda kind: kind in {'toolrpc.browser_run', 'toolrpc.browser_dialog'},
        mediation_scope='global', mediation_policy_revision='policy-17',
        mediation_clock_ms=lambda: NOW_MS,
    ).initialize()


def _enqueue(queue, kind, payload, *, owner='owner-a'):
    title = 'Opening browser' if kind == 'toolrpc.browser_run' else 'Respond to browser dialog'
    expectation = ReceiptExpectation(
        enqueue_id=str(uuid.uuid4()), agent='ultron', kind=kind, title=title,
        origin='generated', scope='global', payload=payload, effective_tier=3,
        policy_revision='policy-17', enqueue_revision=1,
    )
    receipt = issue_receipt(
        _signer(), receipt_id=str(uuid.uuid4()), expectation=expectation,
        verdict='queue', tier=3, reason='owner approval required',
        issued_at_ms=NOW_MS, expires_at_ms=NOW_MS + 60_000,
    )
    assert receipt is not None
    task_id = queue.enqueue_mediated('ultron', kind, title, payload, receipt=receipt,
                                     autonomy_level='ask', origin='generated')
    queue.transition(task_id, TaskStatus.APPROVED, decided_by=owner,
                     decision='accept', human_reason=None)
    return task_id


def test_dialog_claim_requires_current_signed_opener_and_sets_one_use_attempt(tmp_path):
    queue = _queue(tmp_path)
    opener_id = _enqueue(queue, 'toolrpc.browser_run',
                         {'tool': 'browser_run', 'args': {'mode': 'start'}, 'target': 'browser_run'})
    opener = queue.claim_mediated(opener_id, execution_id=str(uuid.uuid4()))
    assert opener is not None
    fingerprint = queue.execution_fingerprint(opener)
    response_id = _enqueue(queue, 'toolrpc.browser_dialog',
                           {'tool': 'browser_dialog', 'args': {
                               'opener_task_id': opener_id, 'choice': 'dismiss',
                               'opener_fingerprint': fingerprint,
                               'dialog_id': 'a' * 32}, 'target': 'browser_dialog'})
    assert queue.claim_mediated(response_id, execution_id=str(uuid.uuid4())) is None
    assert queue.claim_browser_dialog(response_id, opener_task_id=opener_id,
                                      opener_fingerprint='wrong', execution_id=str(uuid.uuid4())) is None
    assert queue.get(response_id).attempts == 0
    response = queue.claim_browser_dialog(response_id, opener_task_id=opener_id,
                                          opener_fingerprint=fingerprint,
                                          execution_id=str(uuid.uuid4()))
    assert response is not None
    assert response.status == 'running'
    assert response.attempts == 1
    assert queue.claim_browser_dialog(response_id, opener_task_id=opener_id,
                                      opener_fingerprint=fingerprint,
                                      execution_id=str(uuid.uuid4())) is None


def test_dialog_claim_blocks_wrong_owner_and_revoked_opener(tmp_path):
    queue = _queue(tmp_path)
    opener_id = _enqueue(queue, 'toolrpc.browser_run',
                         {'tool': 'browser_run', 'args': {'mode': 'start'}, 'target': 'browser_run'})
    opener = queue.claim_mediated(opener_id, execution_id=str(uuid.uuid4()))
    assert opener is not None
    fingerprint = queue.execution_fingerprint(opener)
    args = {'opener_task_id': opener_id, 'opener_fingerprint': fingerprint,
            'choice': 'dismiss', 'dialog_id': 'b' * 32}
    wrong_owner = _enqueue(queue, 'toolrpc.browser_dialog',
                           {'tool': 'browser_dialog', 'args': args, 'target': 'browser_dialog'},
                           owner='owner-b')
    assert queue.claim_browser_dialog(wrong_owner, opener_task_id=opener_id,
                                      opener_fingerprint=fingerprint,
                                      execution_id=str(uuid.uuid4())) is None
    response = _enqueue(queue, 'toolrpc.browser_dialog',
                        {'tool': 'browser_dialog', 'args': args, 'target': 'browser_dialog'})
    queue.transition(opener_id, TaskStatus.FAILED, result={'reason': 'revoked'})
    assert queue.claim_browser_dialog(response, opener_task_id=opener_id,
                                      opener_fingerprint=fingerprint,
                                      execution_id=str(uuid.uuid4())) is None


@pytest.mark.asyncio
async def test_generic_worker_explicitly_holds_dialog_response_for_private_child(tmp_path):
    queue = _queue(tmp_path)
    response = _enqueue(queue, 'toolrpc.browser_dialog',
                        {'tool': 'browser_dialog', 'args': {
                            'opener_task_id': 11, 'opener_fingerprint': 'not-current',
                            'choice': 'dismiss', 'dialog_id': 'c' * 32},
                         'target': 'browser_dialog'})
    called = 0

    async def executor(_task):
        nonlocal called
        called += 1
        return {'status': 'ok'}

    worker = AutonomyWorker(queue, executor=executor)
    result = await worker._run_runnable([queue.get(response)])
    assert result['held'] == 1
    assert called == 0
    assert queue.get(response).status == 'approved'


@pytest.mark.asyncio
async def test_private_same_worker_bridge_claims_in_empty_context_only_while_opener_lives(tmp_path):
    queue = _queue(tmp_path)
    opener_id = _enqueue(queue, 'toolrpc.browser_run',
                         {'tool': 'browser_run', 'args': {'mode': 'start'}, 'target': 'browser_run'})
    opener = queue.claim_mediated(opener_id, execution_id=str(uuid.uuid4()))
    assert opener is not None
    fingerprint = queue.execution_fingerprint(opener)
    worker = AutonomyWorker(queue)
    permit = _ExecutionPermit(opener)
    assert permit.consume(opener, validate=lambda _task, _fp: True)
    token = worker._execution_context.set(permit)
    try:
        bridge = worker.begin_browser_dialog_bridge(opener)
    finally:
        worker._execution_context.reset(token)
    response_id = _enqueue(queue, 'toolrpc.browser_dialog',
                           {'tool': 'browser_dialog', 'args': {
                               'opener_task_id': opener_id, 'opener_fingerprint': fingerprint,
                               'choice': 'dismiss', 'dialog_id': 'd' * 32},
                            'target': 'browser_dialog'})

    async def claim():
        assert worker._execution_context.get() is None
        return await worker.claim_browser_dialog_bridge(bridge, response_id)

    claimed = await asyncio.create_task(claim(), context=contextvars.Context())
    assert claimed is not None and claimed.status == 'running' and claimed.attempts == 1
    bridge.close()
    next_id = _enqueue(queue, 'toolrpc.browser_dialog',
                       {'tool': 'browser_dialog', 'args': {
                           'opener_task_id': opener_id, 'opener_fingerprint': fingerprint,
                           'choice': 'dismiss', 'dialog_id': 'e' * 32},
                        'target': 'browser_dialog'})
    assert await asyncio.create_task(
        worker.claim_browser_dialog_bridge(bridge, next_id),
        context=contextvars.Context(),
    ) is None


@pytest.mark.asyncio
async def test_cancelled_claim_retains_the_durable_running_row_for_unknown_settlement(
        tmp_path, monkeypatch):
    queue = _queue(tmp_path)
    opener_id = _enqueue(queue, 'toolrpc.browser_run',
                         {'tool': 'browser_run', 'args': {'mode': 'start'},
                          'target': 'browser_run'})
    opener = queue.claim_mediated(opener_id, execution_id=str(uuid.uuid4()))
    worker = AutonomyWorker(queue)
    permit = _ExecutionPermit(opener)
    assert permit.consume(opener, validate=lambda _task, _fp: True)
    token = worker._execution_context.set(permit)
    try:
        bridge = worker.begin_browser_dialog_bridge(opener)
    finally:
        worker._execution_context.reset(token)
    response_id = _enqueue(queue, 'toolrpc.browser_dialog',
                           {'tool': 'browser_dialog', 'args': {
                               'opener_task_id': opener_id,
                               'opener_fingerprint': queue.execution_fingerprint(opener),
                               'choice': 'dismiss', 'dialog_id': 'f' * 32},
                            'target': 'browser_dialog'})
    started, release = threading.Event(), threading.Event()
    real_claim = queue.claim_browser_dialog

    def delayed_claim(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return real_claim(*args, **kwargs)

    monkeypatch.setattr(queue, 'claim_browser_dialog', delayed_claim)
    child = asyncio.create_task(worker.claim_browser_dialog_bridge(bridge, response_id),
                                context=contextvars.Context())
    assert await asyncio.to_thread(started.wait, 2)
    child.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(child, 5)
    assert bridge.claimed_task is not None
    assert bridge.claimed_task.id == response_id
    assert queue.get(response_id).status == 'running'
    assert queue.get(response_id).attempts == 1
    bridge.close()
