"""Same-invocation terminal review; execution remains owned by the worker."""
from __future__ import annotations

import asyncio
import copy
import logging
import time

from ..approval_outcomes import (
    DENIAL_BREAKER_NOTICE,
    DENIAL_NOTICE,
    current_approval_turn,
    record_invocation_outcome,
)
from .smart_approvals import smart_policy, terminal_args
from .task_approval_judge import TaskApprovalJudge

logger = logging.getLogger(__name__)


async def review_terminal_task(worker, *, actor: str, args: dict, task_id: int,
                               registration_is_live) -> dict | None:
    """Join an existing exact review and read durable state, never infer authority."""
    adapter = getattr(worker, 'approval_judge', None)
    if type(adapter) is not TaskApprovalJudge:
        return None
    judge = adapter._judge
    if judge is None or not smart_policy(judge._env).enabled:
        return None
    queue = worker.queue
    original = queue.get(task_id)
    if (original is None or original.agent != actor or original.kind != 'toolrpc.terminal_run'
            or original.payload.get('args') != args):
        return None
    settled_denial = adapter.current_terminal_denial(task_id)
    snapshot = settled_denial[0] if settled_denial is not None else adapter._snapshot(original)
    status = judge.status()
    if (snapshot is None or terminal_args(snapshot) is None or not status.configured
            or not judge.wants(snapshot, status)):
        return None
    digest = snapshot['snapshot_sha256']
    turn = current_approval_turn()
    # Review/approval change authority fields; the originating operation must not change.
    fields = ('created_at', 'agent', 'kind', 'title', 'payload', 'risk_tier',
              'autonomy_level', 'origin', 'kernel_intake_id')
    identity = tuple(copy.deepcopy(getattr(original, field)) for field in fields)

    def live(task):
        return (registration_is_live() is True and worker.approval_judge is adapter
                and adapter._judge is judge and current_approval_turn() is turn
                and (turn is None or turn.live()) and task is not None
                and tuple(getattr(task, field) for field in fields) == identity)

    def answer(reason, **extra):
        return {'ok': False, 'reason': reason, 'tool': 'terminal_run', 'task_id': task_id, **extra}

    if not live(original):
        return answer('terminal_review_changed')
    await adapter.wait_for_review(task_id, digest, timeout=status.timeout)
    task = queue.get(task_id)
    if not live(task):
        return answer('terminal_review_changed')
    denial = adapter.current_terminal_denial(task_id)
    if denial is not None and denial[0]['snapshot_sha256'] == digest:
        _denied_snapshot, _result, current = denial
        reply = answer('guardian_denied', notice=DENIAL_NOTICE)
        if turn is not None:
            observation = queue.chat_invocation_outcome(turn, task_id)
            if observation is not None and 'guardian' in observation:
                record_invocation_outcome(turn, observation)
                reply['guardian'] = observation['guardian']
                if observation['guardian']['breaker'] is True:
                    reply['notice'] = DENIAL_BREAKER_NOTICE
        prompts = getattr(worker, '_owner_once_prompts', None)
        if prompts is None or not prompts.can_reply():
            queue.reject_smart_terminal_denial(
                task_id, digest, check=lambda: registration_is_live() is True
                and worker.approval_judge is adapter and current(),
            )
            return reply

        def reply_live():
            # Runs under queue CAS and in Telegram's callback task. It must
            # neither read the queue nor depend on that task's ContextVars.
            return (registration_is_live() is True and worker.approval_judge is adapter
                    and adapter._judge is judge and turn is not None and turn.live()
                    and getattr(worker, '_owner_once_prompts', None) is prompts
                    and current())

        claim = await prompts.request(task_id, digest, check=reply_live)
        if claim is None:
            queue.reject_smart_terminal_denial(task_id, digest, check=reply_live)
            return reply
        completed = False
        try:
            if not live(queue.get(task_id)):
                return answer('terminal_review_changed')
            await worker._run_owner_once(
                claim, live_check=lambda: reply_live() and prompts.claim_current(claim),
            )
            task = queue.get(task_id)
            if not live(task):
                return answer('terminal_review_changed')
            if task.status == 'done':
                execution = task.result
                if (type(execution) is dict and execution.get('status') == 'ok'
                        and type(execution.get('result')) is dict
                        and execution['result'].get('ok') is True
                        and queue.verify_owner_once_terminal_result(task_id)):
                    completed = True
                    return {'ok': True, 'tool': 'terminal_run', 'task_id': task_id,
                            'result': execution['result'],
                            **({'guardian': reply['guardian']} if 'guardian' in reply else {})}
                return answer('terminal_execution_unverified')
            return answer('terminal_execution_held' if task.status == 'approved'
                          else 'terminal_execution_failed')
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning('owner-once terminal execution unavailable', exc_info=True)
            return answer('terminal_execution_unavailable')
        finally:
            prompts.release_claim(claim, completed=completed)
    if task.status == 'blocked':
        return None
    if task.decision != 'smart-approve' or task.decided_by != 'smart_approval':
        return answer('terminal_review_changed')
    if task.status == 'approved':
        if not adapter.verify_smart_approval(task_id):
            return answer('smart_approval_unavailable')
        try:
            # Exact selection uses the same claim/receipt/kernel/handler pipeline as the scheduler.
            await worker.tick(limit=1, task_id=task_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning('named terminal execution unavailable', exc_info=True)
            return answer('terminal_execution_unavailable')
        task = queue.get(task_id)
    # A scheduler may already own the claim. Observe its bounded durable completion;
    # never claim a RUNNING task or retry an APPROVED task in this invocation.
    deadline = time.monotonic() + args.get('timeout', 30)
    while live(task) and task.status == 'running' and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
        task = queue.get(task_id)
    if not live(task):
        return answer('terminal_review_changed')
    if task.status == 'done':
        execution = task.result
        if (isinstance(execution, dict) and execution.get('status') == 'ok'
                and isinstance(execution.get('result'), dict)
                and execution['result'].get('ok') is True):
            if not queue.verify_smart_terminal_result(task_id):
                return answer('terminal_execution_unverified')
            return {'ok': True, 'tool': 'terminal_run', 'task_id': task_id,
                    'result': execution['result']}
        reason = execution.get('reason') if isinstance(execution, dict) else None
        return answer(reason if isinstance(reason, str) and len(reason) <= 256
                      else 'terminal_execution_failed')
    return answer({'approved': 'terminal_execution_held', 'running': 'terminal_execution_pending',
                   'failed': 'terminal_execution_failed'}.get(task.status, 'terminal_review_changed'))
