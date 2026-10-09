"""An exact smart DENY cannot escape into a late generic approval."""

import httpx
import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
)
from agents.core.autonomy.queue import TaskQueueError
from agents.core.autonomy.terminal_review import review_terminal_task
from agents.core.commands import Principal
from tests.test_h277_smart_terminal_integration import (
    bind_judge,
    propose,
    runtime,  # noqa: F401 — dependency of the real synchronous runtime fixture
)
from tests.test_h485_smart_observer_dispatch import (
    isolated_settings,  # noqa: F401 — signed queue fixture dependency
    queue,  # noqa: F401 — notification runtime fixture
)
from tests.test_h485_smart_review_notifications import _finish, _payload, _worker
from tests.test_h485_toolrpc_actuation_integration import sync_runtime  # noqa: F401


@pytest.mark.parametrize("admin_only", [False, True])
async def test_deny_without_live_reply_channel_is_final_not_a_late_manual_execution(sync_runtime, admin_only):
    q, worker, orch, sandbox, _seen = sync_runtime
    bind_judge(worker, "DENY")
    turn = (open_approval_turn(session_id="s", session_instance="i",
                               principal=Principal(channel="web", admin=True),
                               session_is_live=lambda *_args: True) if admin_only else None)
    token = bind_approval_turn(turn)
    try:
        answer = await propose(orch)
        assert answer["reason"] == "guardian_denied" and answer["ok"] is False
        task = q.get(answer["task_id"])
        assert task.status == "rejected", "a definitive refusal must not leave an answerable generic card"
        assert task.human_decision is None, "a machine refusal is not an owner decision"
        with pytest.raises(TaskQueueError):
            await worker.apply_decision(task.id, "accept", "user")
        await worker.tick()
        assert sandbox.commands == []
    finally:
        close_approval_turn(turn, token)


@pytest.mark.parametrize("verdict,expected", [("DENY", []), ("ESCALATE", ["Review command"])])
async def test_generic_notification_only_survives_escalation(queue, tmp_path, verdict, expected):
    async def respond(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": verdict}}]})

    worker, delivered = _worker(queue, tmp_path, respond)
    task_id = worker.govern_enqueue("jarvis", "toolrpc.terminal_run", "Review command",
                                   payload=_payload(), risk_tier=3)
    await _finish(worker)
    assert [task.title for task in delivered] == expected
    if verdict == "DENY":
        assert not queue.get(task_id).pushed
        assert queue.get(task_id).status == "rejected"


async def test_notification_closure_before_invocation_observation_preserves_denial(queue, tmp_path,
                                                                                 monkeypatch):
    async def respond(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "DENY"}}]})

    worker, delivered = _worker(queue, tmp_path, respond)
    adapter = worker.approval_judge
    original_wait = adapter.wait_for_review

    async def wait_then_settle(task_id, digest, *, timeout):
        completed = await original_wait(task_id, digest, timeout=timeout)
        denial = adapter.current_terminal_denial(task_id)
        if denial is not None:
            queue.reject_smart_terminal_denial(task_id, digest, check=denial[2])
        return completed

    monkeypatch.setattr(adapter, 'wait_for_review', wait_then_settle)
    task_id = worker.govern_enqueue('jarvis', 'toolrpc.terminal_run', 'Review command',
                                   payload=_payload(), risk_tier=3)
    answer = await review_terminal_task(worker, actor='jarvis', args=_payload()['args'],
                                       task_id=task_id, registration_is_live=lambda: True)
    await _finish(worker)
    assert queue.get(task_id).status == 'rejected'
    assert delivered == []
    assert answer['reason'] == 'guardian_denied'


async def test_invocation_observer_entering_after_closed_denial_reports_refusal(queue, tmp_path):
    async def respond(_request):
        return httpx.Response(200, json={'choices': [{'message': {'content': 'DENY'}}]})

    worker, delivered = _worker(queue, tmp_path, respond)
    task_id = worker.govern_enqueue('jarvis', 'toolrpc.terminal_run', 'Review command',
                                   payload=_payload(), risk_tier=3)
    await _finish(worker)
    assert queue.get(task_id).status == 'rejected'
    answer = await review_terminal_task(worker, actor='jarvis', args=_payload()['args'],
                                       task_id=task_id, registration_is_live=lambda: True)
    assert answer is not None and answer['reason'] == 'guardian_denied'
    assert delivered == []


@pytest.mark.parametrize('no_notifier,attention_mode', [
    (True, 'interrupt'), (False, 'none'), (False, 'digest'),
])
async def test_unattended_denial_settles_without_notification_path(queue, tmp_path,
                                                                 no_notifier, attention_mode):
    async def respond(_request):
        return httpx.Response(200, json={'choices': [{'message': {'content': 'DENY'}}]})

    worker, delivered = _worker(queue, tmp_path, respond)
    if no_notifier:
        worker.notifier = None
    task_id = worker.govern_enqueue('jarvis', 'toolrpc.terminal_run', 'Review command',
                                   payload=_payload(), risk_tier=3, attention_mode=attention_mode)
    await _finish(worker)
    assert queue.get(task_id).status == 'rejected'
    assert queue.get(task_id).human_decision is None
    assert delivered == []
