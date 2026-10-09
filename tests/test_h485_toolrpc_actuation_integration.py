"""One ToolRPC invocation uses the actual judge, signed queue, kernel and worker."""
import asyncio
import json

import pytest

from agents.core.autonomy.executor import TaskExecutor
from agents.core.commands import Principal
from agents.core.kernel import Decision, Verdict
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.orchestrator import bind_turn_principal, reset_turn_principal
from agents.core.turn_approvals import (
    bind_turn_approvals,
    current_turn_approvals,
    reset_turn_approvals,
)
from tests.test_h277_smart_terminal_integration import (
    bind_judge,  # noqa: F401
    drain,
    propose,
    runtime,
    use_real_kernel,
)
from tests.test_h487_chat_outcome_integration import chat  # noqa: F401


@pytest.fixture
def sync_runtime(runtime):
    queue, worker, orch, sandbox, seen = runtime
    coordinator = orch._test_coordinator
    def authorize(action, **kwargs):
        seen.append(action)
        return Decision(Verdict.GRANT, reason='fixture grant', tier=2)
    coordinator._wire_agent_tool_runtime(action_kernel=authorize)
    executor = TaskExecutor()
    executor.register('toolrpc.terminal_run', coordinator._approved_desktop_tool_rpc_execute)
    worker.executor = executor.execute
    return queue, worker, orch, sandbox, seen


async def started(requests):
    async def observe():
        while not requests:
            await asyncio.sleep(0)
    await asyncio.wait_for(observe(), timeout=2)


@pytest.mark.asyncio
async def test_two_native_approvals_execute_in_their_invocations_through_real_kernel(sync_runtime):
    queue, worker, orch, sandbox, _seen = sync_runtime
    use_real_kernel(sync_runtime, synchronous=True)
    _env, requests = bind_judge(worker, 'APPROVE')
    token = bind_turn_approvals()
    try:
        first = await propose(orch)
        assert first['ok'] is True
        assert first['result']['stdout'] == 'hello'
        task = queue.get(first['task_id'])
        assert task.status == 'done' and task.result['status'] == 'ok'
        assert task.decision == 'smart-approve' and task.human_decision is None
        second = await propose(orch)
        assert second['ok'] is True and second['task_id'] != first['task_id']
        assert sandbox.commands == ['printf hello', 'printf hello']
        assert len(requests) == 2 and current_turn_approvals() == []
        await worker.tick()
        assert sandbox.commands == ['printf hello', 'printf hello']
    finally:
        reset_turn_approvals(token)


@pytest.mark.asyncio
async def test_deny_returns_sanitized_feedback_without_pending_footer_or_execution(sync_runtime):
    queue, worker, orch, sandbox, _seen = sync_runtime
    env, _requests = bind_judge(worker, 'DENY')
    env['JARVIS_SMART_APPROVAL_POLICY'] = 'private operator rule never shown to model'
    token = bind_turn_approvals()
    try:
        result = await propose(orch)
        assert result['reason'] == 'guardian_denied'
        assert result['ok'] is False and 'denied' in result['notice'].lower()
        assert 'private operator' not in str(result)
        assert queue.get(result['task_id']).status == 'rejected'
        assert sandbox.commands == [] and current_turn_approvals() == []
        from agents.core.autonomy.queue import TaskQueueError

        with pytest.raises(TaskQueueError):
            await worker.apply_decision(result['task_id'], 'accept', 'user')
        await worker.tick()
        assert sandbox.commands == []
    finally:
        reset_turn_approvals(token)


@pytest.mark.asyncio
@pytest.mark.parametrize('verdict', ['ESCALATE', 'unparseable'])
async def test_uncertain_review_keeps_manual_approval(sync_runtime, verdict):
    queue, worker, orch, sandbox, _seen = sync_runtime
    bind_judge(worker, verdict)
    token = bind_turn_approvals()
    try:
        result = await propose(orch)
        assert result['reason'] == 'approval_required'
        assert current_turn_approvals() == [result['task_id']]
        assert queue.get(result['task_id']).status == 'blocked' and sandbox.commands == []
    finally:
        reset_turn_approvals(token)


@pytest.mark.asyncio
async def test_caller_cancellation_invalidates_review_before_any_late_approval(sync_runtime):
    queue, worker, orch, sandbox, _seen = sync_runtime
    release = asyncio.Event()
    _env, requests = bind_judge(worker, 'APPROVE', gate=release)
    invocation = asyncio.create_task(propose(orch))
    await started(requests)
    assert not invocation.done() and sandbox.commands == []
    invocation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await invocation
    release.set()
    await drain(worker.approval_judge)
    task, = queue.list()
    assert task.status == 'blocked' and sandbox.commands == []


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['revoke', 'owner-reject', 'halt'])
async def test_changed_authority_during_native_review_prevents_same_invocation_execution(sync_runtime, change):
    queue, worker, orch, sandbox, _seen = sync_runtime
    halted = use_real_kernel(sync_runtime, synchronous=True)
    release = asyncio.Event()
    env, requests = bind_judge(worker, 'APPROVE', gate=release)
    invocation = asyncio.create_task(propose(orch))
    await started(requests)
    task, = queue.list()
    if change == 'revoke':
        env['JARVIS_SMART_APPROVALS'] = '0'
    elif change == 'owner-reject':
        await worker.apply_decision(task.id, 'reject', 'owner')
    else:
        halted[0] = True
    release.set()
    result = await invocation
    assert result['ok'] is False and sandbox.commands == []
    persisted = queue.get(task.id)
    if persisted.status == 'done':
        assert persisted.result['status'] == 'failed' and result['reason'] == 'kernel_denied'


@pytest.mark.asyncio
async def test_approved_but_refused_transport_is_not_reported_as_success(sync_runtime):
    queue, worker, orch, sandbox, _seen = sync_runtime
    bind_judge(worker, 'APPROVE')
    sandbox.active_backend = lambda: 'local'
    result = await propose(orch)
    assert result['ok'] is False and result['reason'] == 'docker_backend_unavailable:local'
    assert queue.get(result['task_id']).result['status'] == 'failed'
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_replaced_terminal_registration_during_review_cannot_actuate(sync_runtime):
    queue, worker, orch, sandbox, _seen = sync_runtime
    release = asyncio.Event()
    _env, requests = bind_judge(worker, 'APPROVE', gate=release)
    invocation = asyncio.create_task(propose(orch))
    await started(requests)
    spec = orch.tool_rpc._tools['terminal_run']
    orch.tool_rpc.register_tool('terminal_run', spec['handler'], gated=True, trusted_execution=True)
    release.set()
    result = await invocation
    assert result['reason'] == 'registration_changed' and result['ok'] is False
    assert sandbox.commands == [] and queue.list()[0].status != 'done'


@pytest.mark.asyncio
async def test_closed_originating_chat_turn_cannot_actuate_after_native_review(sync_runtime):
    from agents.core.approval_outcomes import (
        bind_approval_turn,
        close_approval_turn,
        open_approval_turn,
    )

    queue, worker, orch, sandbox, _seen = sync_runtime
    turn = open_approval_turn(session_id='owner-session', session_instance='birth',
                              principal=Principal(channel='web', admin=True),
                              session_is_live=lambda *_: True)
    token = bind_approval_turn(turn)
    release = asyncio.Event()
    _env, requests = bind_judge(worker, 'APPROVE', gate=release)
    invocation = asyncio.create_task(propose(orch))
    try:
        await started(requests)
    finally:
        close_approval_turn(turn, token)
        release.set()
    result = await invocation
    assert result['reason'] == 'terminal_review_changed' and result['ok'] is False
    assert sandbox.commands == [] and queue.list()[0].status != 'done'


@pytest.mark.asyncio
async def test_scheduler_claimed_operation_is_observed_once_with_worker_completion_proof(sync_runtime):
    queue, worker, orch, sandbox, _seen = sync_runtime
    _env, _requests = bind_judge(worker, 'APPROVE')
    began, release = asyncio.Event(), asyncio.Event()
    original_execute = sandbox.execute_shell
    scheduler = []

    async def transport(command):
        began.set()
        await release.wait()
        return await original_execute(command)

    sandbox.execute_shell = transport
    adapter = worker.approval_judge
    original_after = adapter._after_judgement

    async def after(snapshot, annotation):
        await original_after(snapshot, annotation)
        scheduler.append(asyncio.create_task(worker.tick(task_id=snapshot['task_id'])))
        await began.wait()

    adapter._after_judgement = after
    invocation = asyncio.create_task(propose(orch))
    await asyncio.wait_for(began.wait(), timeout=2)
    assert not invocation.done() and queue.list()[0].status == 'running'
    release.set()
    result = await invocation
    await asyncio.gather(*scheduler)
    assert result['ok'] is True and sandbox.commands == ['printf hello']
    assert queue.verify_smart_terminal_result(result['task_id']) is True
    await worker.tick(task_id=result['task_id'])
    assert sandbox.commands == ['printf hello']


@pytest.mark.asyncio
async def test_synthetic_done_without_worker_execution_cannot_report_success(sync_runtime):
    from agents.core.autonomy.queue import TaskStatus

    queue, worker, orch, sandbox, _seen = sync_runtime
    bind_judge(worker, 'APPROVE')
    adapter = worker.approval_judge
    original_after = adapter._after_judgement

    async def after(snapshot, annotation):
        await original_after(snapshot, annotation)
        queue.transition(snapshot['task_id'], TaskStatus.RUNNING)
        queue.transition(snapshot['task_id'], TaskStatus.DONE,
                         result={'status': 'ok', 'result': {'ok': True, 'stdout': 'fake'}})

    adapter._after_judgement = after
    result = await propose(orch)
    assert result['ok'] is False and result['reason'] == 'terminal_execution_unverified'
    assert sandbox.commands == []


def wire_chat(chat, sync_runtime):
    from agents.core.autonomy_coordinator import AutonomyCoordinator

    queue, worker, _orch, sandbox, _seen = sync_runtime
    chat.orch.autonomy_queue, chat.orch.autonomy, chat.orch.sandbox = queue, worker, sandbox
    original_setting = chat.orch.get_setting
    chat.orch.get_setting = lambda key, default=None: (
        True if key == 'llm.tool_loop_enabled' else original_setting(key, default))
    coordinator = AutonomyCoordinator(chat.orch)
    chat.orch._test_coordinator = coordinator
    coordinator._wire_agent_tool_runtime(action_kernel=lambda action, **kw:
                                         Decision(Verdict.GRANT, reason='fixture grant', tier=2))
    executor = TaskExecutor()
    executor.register('toolrpc.terminal_run', coordinator._approved_desktop_tool_rpc_execute)
    worker.executor = executor.execute
    return chat.orch.tool_rpc


def terminal_call(n):
    args = {'target': 'isolated-sandbox', 'command': f'printf hello # attempt {n}'}
    return ToolTurn(tool_calls=(ToolCall(id=f'operation-{n}', name='terminal_run',
                                        raw_arguments=json.dumps(args), arguments=args),))


@pytest.mark.asyncio
@pytest.mark.parametrize('stream', [False, True])
async def test_three_denials_warn_model_in_same_turn_and_stop_fourth_operation(chat, sync_runtime, stream, monkeypatch):
    monkeypatch.delenv('JARVIS_SMART_DENIAL_BREAKER_THRESHOLD', raising=False)
    queue, worker, _orch, sandbox, _seen = sync_runtime
    wire_chat(chat, sync_runtime)
    _env, requests = bind_judge(worker, 'DENY')
    chat.backend.turns.extend([terminal_call(n) for n in range(4)])
    entry = chat.orch.handle_input_stream if stream else chat.orch.handle_input
    principal = bind_turn_principal(Principal(channel='web', admin=True))
    try:
        reply = await entry('run the three terminal operations', channel='web', session_id='s')
        assert len(queue.list()) == 3 and len(requests) == 3 and sandbox.commands == []
        assert 'owner' in reply.lower()
        assert chat.backend.calls[-1]['tools'] == []
        assert 'STOP attempting variations' in str(chat.backend.calls[-1]['messages'])
        assert 'consecutive_denials' in str(chat.backend.calls[-1]['messages'])
    finally:
        reset_turn_principal(principal)


@pytest.mark.asyncio
@pytest.mark.parametrize('stream', [False, True])
async def test_denial_breaker_blocks_fourth_gated_operation_in_one_provider_batch(
        chat, sync_runtime, stream, monkeypatch):
    monkeypatch.delenv('JARVIS_SMART_DENIAL_BREAKER_THRESHOLD', raising=False)
    queue, worker, _orch, sandbox, _seen = sync_runtime
    wire_chat(chat, sync_runtime)
    _env, requests = bind_judge(worker, 'DENY')
    calls = tuple(terminal_call(n).tool_calls[0] for n in range(4))
    chat.backend.turns.extend([ToolTurn(tool_calls=calls), ToolTurn(content='I will ask the owner.')])
    entry = chat.orch.handle_input_stream if stream else chat.orch.handle_input
    principal = bind_turn_principal(Principal(channel='web', admin=True))
    try:
        reply = await entry('run the terminal operations', channel='web', session_id='s')
        assert reply == 'I will ask the owner.'
        assert len(queue.list()) == 3 and len(requests) == 3 and sandbox.commands == []
        assert chat.backend.calls[-1]['tools'] == []
    finally:
        reset_turn_principal(principal)


@pytest.mark.asyncio
@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('failed_answer', [False, True])
async def test_same_turn_denial_acknowledgment_waits_for_successful_persisted_answer(
        chat, sync_runtime, stream, failed_answer):
    queue, worker, _orch, sandbox, _seen = sync_runtime
    wire_chat(chat, sync_runtime)
    bind_judge(worker, 'DENY')
    text = '[Gemini error: failed]' if failed_answer else 'The reviewer denied it. I will ask the owner.'
    chat.backend.turns.extend([terminal_call(1), ToolTurn(content=text)])
    entry = chat.orch.handle_input_stream if stream else chat.orch.handle_input
    principal = bind_turn_principal(Principal(channel='web', admin=True))
    try:
        reply = await entry('run the terminal operation', channel='web', session_id='s')
        assert reply == text
        assert 'guardian_denied' in str(chat.backend.calls[-1]['messages'])
        assert len(queue.list()) == 1 and sandbox.commands == []
        chat.backend.turns.append(ToolTurn(content='Next answer.'))
        await entry('what happened?', channel='web', session_id='s')
        assert ('Approval outcome observations' in str(chat.backend.calls[-1]['messages'])) is failed_answer
    finally:
        reset_turn_principal(principal)


@pytest.mark.asyncio
@pytest.mark.parametrize('stream', [False, True])
async def test_truncated_denial_is_retained_for_next_turn_instead_of_acknowledged(chat, sync_runtime, stream):
    queue, worker, _orch, sandbox, _seen = sync_runtime
    wire_chat(chat, sync_runtime)
    bind_judge(worker, 'DENY')
    for agent in chat.orch.agents.values():
        agent.tool_runtime._result_thresholds = lambda: {'terminal_run': 8}
        agent.tool_runtime._result_store = None
    chat.backend.turns.extend([terminal_call(1), ToolTurn(content='I will ask the owner.')])
    entry = chat.orch.handle_input_stream if stream else chat.orch.handle_input
    principal = bind_turn_principal(Principal(channel='web', admin=True))
    try:
        assert await entry('run the terminal operation', channel='web', session_id='s') == 'I will ask the owner.'
        tool_messages = [message['content'] for message in chat.backend.calls[-1]['messages']
                         if message['role'] == 'tool']
        assert 'consecutive_denials' not in str(tool_messages)
        chat.backend.turns.append(ToolTurn(content='The reviewer denied it.'))
        await entry('what happened?', channel='web', session_id='s')
        assert 'Approval outcome observations' in str(chat.backend.calls[-1]['messages'])
        assert len(queue.list()) == 1 and sandbox.commands == []
    finally:
        reset_turn_principal(principal)
