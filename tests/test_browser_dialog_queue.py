"""A dialog response is claimed once beside its current signed opener."""
from __future__ import annotations

import uuid

from agents.core.autonomy.mediation import ReceiptExpectation, issue_receipt
from agents.core.autonomy.queue import TaskQueue, TaskStatus
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
