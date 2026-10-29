"""A dialog response is claimed once beside its current signed opener."""
from __future__ import annotations

import asyncio
import contextvars
import threading
import uuid
from types import SimpleNamespace

import pytest

from agents.core.autonomy.mediation import ReceiptExpectation, issue_receipt
from agents.core.autonomy.queue import TaskQueue, TaskStatus
from agents.core.autonomy.worker import AutonomyWorker, _ExecutionPermit
from agents.core.browser_kernel import (
    approved_dialog_scope,
    authorize_dialog_response,
    physical_browser_dialog_allowed,
)
from agents.core.browser_playwright import PlaywrightBrowserDriver
from agents.core.browser_runtime import BrowserRuntime
from agents.core.kernel import Decision, Verdict
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


@pytest.mark.asyncio
@pytest.mark.parametrize('revoke', ['response', 'opener'])
async def test_physical_dialog_receipt_rechecks_both_signed_rows_after_kernel_await(
        tmp_path, revoke):
    queue = _queue(tmp_path)
    opener_id = _enqueue(queue, 'toolrpc.browser_run',
                         {'tool': 'browser_run', 'args': {'mode': 'start'},
                          'target': 'browser_run'})
    opener = queue.claim_mediated(opener_id, execution_id=str(uuid.uuid4()))
    opener_fp = queue.execution_fingerprint(opener)
    response_id = _enqueue(queue, 'toolrpc.browser_dialog',
                           {'tool': 'browser_dialog', 'args': {
                               'opener_task_id': opener_id,
                               'opener_fingerprint': opener_fp,
                               'dialog_id': 'f' * 32, 'choice': 'dismiss'},
                            'target': 'browser_dialog'})
    response = queue.claim_browser_dialog(response_id, opener_task_id=opener_id,
                                          opener_fingerprint=opener_fp,
                                          execution_id=str(uuid.uuid4()))
    runtime = object.__new__(BrowserRuntime)
    runtime.queue = queue
    runtime._dialog_memory_current = lambda _session, _episode: True
    episode = type('Episode', (), {
        'opener_task_id': opener_id, 'opener_fingerprint': opener_fp,
        'claimed_task': response, 'owner': 'owner-a', 'agent': 'ultron'})()
    def signed_current():
        return runtime._dialog_durable_current(object(), episode)
    assert signed_current()
    entered, release = asyncio.Event(), asyncio.Event()

    async def kernel(action, *, approval_check):
        assert approval_check(action)
        entered.set()
        await release.wait()
        return Decision(Verdict.GRANT, 'test_grant', tier=3)

    class NativeDialog:
        def __init__(self):
            self.calls = 0

        async def dismiss(self):
            self.calls += 1

    dialog = NativeDialog()
    driver = PlaywrightBrowserDriver(host_enabled=True)
    observed = SimpleNamespace(dialog=dialog, kind='alert')
    driver._dialog_observer = SimpleNamespace(pending=lambda: observed)

    async def attempt():
        with approved_dialog_scope(response, opener, dialog, session_id='s' * 32,
                                   generation=0, plan_sha256='p' * 64,
                                   step_index=0, current=signed_current):
            granted = await authorize_dialog_response(kernel)
            physical = physical_browser_dialog_allowed(dialog, 'dismiss')
            sent = await driver.respond_dialog(observed, 'dismiss')
            return granted, physical, sent

    task = asyncio.create_task(attempt())
    await asyncio.wait_for(entered.wait(), 2)
    target = response_id if revoke == 'response' else opener_id
    queue.transition(target, TaskStatus.FAILED, result={'reason': 'revoked'})
    release.set()
    assert await asyncio.wait_for(task, 2) == (False, False, False)
    assert dialog.calls == 0
    assert queue.claim_browser_dialog(response_id, opener_task_id=opener_id,
                                      opener_fingerprint=opener_fp,
                                      execution_id=str(uuid.uuid4())) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('responded', [False, True])
async def test_failed_opening_settlement_preserves_confirmed_native_response_fact(
        tmp_path, responded):
    queue = _queue(tmp_path)
    opener_id = _enqueue(queue, 'toolrpc.browser_run',
                         {'tool': 'browser_run', 'args': {'mode': 'start'},
                          'target': 'browser_run'})
    opener = queue.claim_mediated(opener_id, execution_id=str(uuid.uuid4()))
    opener_fp = queue.execution_fingerprint(opener)
    response_id = _enqueue(queue, 'toolrpc.browser_dialog',
                           {'tool': 'browser_dialog', 'args': {
                               'opener_task_id': opener_id,
                               'opener_fingerprint': opener_fp,
                               'dialog_id': 'a' * 32, 'choice': 'dismiss'},
                            'target': 'browser_dialog'})
    response = queue.claim_browser_dialog(
        response_id, opener_task_id=opener_id, opener_fingerprint=opener_fp,
        execution_id=str(uuid.uuid4()))
    runtime = object.__new__(BrowserRuntime)
    runtime.queue = queue
    runtime._dialog_settlements = set()
    runtime._dialog_settlement_failed = False
    episode = SimpleNamespace(claimed_task=response, responded=responded)
    await runtime._settle_dialog(episode, success=False)
    row = queue.get(response_id)
    assert row.status == TaskStatus.FAILED and row.attempts == 1
    if responded:
        assert row.result == {
            'reason': 'dialog_opening_incomplete', 'native_response': 'confirmed',
            'choice': 'dismiss', 'opening': 'not_completed',
            'opener_possibly_applied': True}
    else:
        assert row.result == {'reason': 'dialog_outcome_unknown', 'possibly_applied': True}
