"""Actual ToolRPC, native mock judge, signed task, worker and terminal gates."""
import asyncio
import hashlib
import hmac
from types import SimpleNamespace

import httpx
import pytest

from agents.core.autonomy.approval_judge import ApprovalJudge
from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.mediation import DetachedHMACSigner
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.kernel import Decision, Verdict
from agents.core.llm.base import LMStudioBackend
from agents.core.llm.egress import llm_async_client


class Sandbox:
    timeout = 30

    def __init__(self):
        self.commands = []

    def active_backend(self):
        return 'docker'

    async def execute_shell(self, command):
        self.commands.append(command)
        return SimpleNamespace(exit_code=0, stdout='hello', stderr='', duration=0.0)


async def drain(adapter):
    await asyncio.sleep(0)
    while adapter._judge_tasks:
        await asyncio.gather(*tuple(adapter._judge_tasks))
        await asyncio.sleep(0)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '1')
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    signer = DetachedHMACSigner(lambda data: hmac.new(b'fixture', data, hashlib.sha256).hexdigest())
    queue = TaskQueue(str(tmp_path / 'queue.db'), mediation_signer=signer).initialize()
    executor = TaskExecutor()
    worker = AutonomyWorker(queue, executor=executor.execute)
    sandbox = Sandbox()
    orch = SimpleNamespace(agents={}, autonomy=worker, autonomy_queue=queue, sandbox=sandbox,
                           get_setting=lambda key, default=None: default)
    seen = []

    def authorize(action, **kwargs):
        seen.append(action)
        return Decision(Verdict.GRANT, reason='fixture grant', tier=2)

    coordinator = AutonomyCoordinator(orch)
    orch._test_coordinator = coordinator
    coordinator._wire_agent_tool_runtime(action_kernel=authorize)
    executor.register('toolrpc.terminal_run', coordinator._approved_desktop_tool_rpc_execute)
    yield queue, worker, orch, sandbox, seen
    queue.close()


def bind_judge(worker, text, *, gate=None):
    requests = []
    env = {'JARVIS_ROLE_APPROVAL_JUDGE_MODEL': 'fixture-judge',
           'JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER': 'lm-studio',
           'JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL': 'http://localhost:1234',
           'JARVIS_SMART_APPROVALS': '1'}

    async def respond(request):
        requests.append(request)
        if gate is not None:
            await gate.wait()
        return httpx.Response(200, json={'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}]})

    def backend(status):
        instance = object.__new__(LMStudioBackend)
        instance.base_url = status.base_url
        instance.client = llm_async_client('lm-studio', base_url=status.base_url, trust_env=False,
                                          transport=httpx.MockTransport(respond))
        return instance

    judge = ApprovalJudge(env=env, settings=lambda category, key, default=None: default,
                          backend_factory=backend)
    worker.attach_approval_judge(judge, loop=asyncio.get_running_loop())
    return env, requests


async def propose(orch):
    return await orch.tool_rpc.handle({'tool': 'terminal_run', 'args': {
        'target': 'isolated-sandbox', 'command': 'printf hello',
    }}, actor='jarvis')


@pytest.mark.asyncio
async def test_manual_docker_approval_preserves_kernel_disabled_execution(runtime, monkeypatch):
    queue, worker, orch, sandbox, _seen = runtime
    answer = await propose(orch)
    await worker.apply_decision(answer['task_id'], 'accept', 'user')
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '0')
    await worker.tick()
    assert queue.get(answer['task_id']).status == 'done'
    assert sandbox.commands == ['printf hello']


@pytest.mark.asyncio
async def test_native_guardian_approves_one_exact_toolrpc_operation_without_human_attribution(runtime):
    queue, worker, orch, sandbox, seen = runtime
    bind_judge(worker, 'APPROVE')
    answer = await propose(orch)
    await drain(worker.approval_judge)
    task = queue.get(answer['task_id'])
    assert task.status == 'approved'
    assert task.decision == 'smart-approve' and task.decided_by == 'smart_approval'
    assert task.human_decision is None and sandbox.commands == []
    await worker.tick()
    assert queue.get(task.id).status == 'done'
    assert sandbox.commands == ['printf hello']
    assert any(action.kind == 'terminal.exec' for action in seen)
    await worker.tick()
    assert sandbox.commands == ['printf hello']


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['DENY', 'ESCALATE', 'APPROVE because harmless', ''])
async def test_nonapproval_remains_pending_with_clear_machine_outcome_and_owner_override(runtime, text):
    queue, worker, orch, sandbox, _seen = runtime
    bind_judge(worker, text)
    answer = await propose(orch)
    await drain(worker.approval_judge)
    task = queue.get(answer['task_id'])
    assert task.status == 'blocked'
    annotation = worker.approval_judge.project(task)['judge']
    assert annotation['decision'] == ('deny' if text == 'DENY' else 'escalate')
    assert annotation['advisory'] is False
    await worker.tick()
    assert sandbox.commands == []
    await worker.apply_decision(task.id, 'accept', 'user')
    await worker.tick()
    assert sandbox.commands == ['printf hello']


def use_real_kernel(runtime):
    from agents.core.kernel.binding import make_action_kernel

    queue, worker, orch, _sandbox, _seen = runtime
    halted = [False]
    orch.kill_switch = SimpleNamespace(is_halted=lambda scope: halted[0])
    real = make_action_kernel(orch)
    worker.bind_mediation(real, queue._mediation_signer)
    coordinator = orch._test_coordinator
    coordinator._wire_agent_tool_runtime(action_kernel=worker.kernel_gate)
    executor = TaskExecutor()
    executor.register('toolrpc.terminal_run', coordinator._approved_desktop_tool_rpc_execute)
    worker.executor = executor.execute
    return halted


@pytest.mark.asyncio
async def test_real_kernel_satisfies_exact_sealed_terminal_approval_in_auto_mode(runtime):
    queue, worker, orch, sandbox, _seen = runtime
    use_real_kernel(runtime)
    bind_judge(worker, 'APPROVE')
    answer = await propose(orch)
    await drain(worker.approval_judge)
    assert queue.get(answer['task_id']).decision == 'smart-approve'
    await worker.tick()
    assert sandbox.commands == ['printf hello']
    assert queue.get(answer['task_id']).result['status'] == 'ok'
    second = await propose(orch)
    await drain(worker.approval_judge)
    assert second['task_id'] != answer['task_id']
    await worker.tick()
    assert sandbox.commands == ['printf hello', 'printf hello']


@pytest.mark.asyncio
@pytest.mark.parametrize('guard', ['halt', 'ask', 'off'])
async def test_real_kernel_restrictive_mode_and_estop_win_after_guardian_approval(runtime, guard):
    queue, worker, orch, sandbox, _seen = runtime
    halted = use_real_kernel(runtime)
    bind_judge(worker, 'APPROVE')
    answer = await propose(orch)
    await drain(worker.approval_judge)
    assert queue.get(answer['task_id']).decision == 'smart-approve'
    if guard == 'halt':
        halted[0] = True
    else:
        worker.policy.mode = guard
    await worker.tick()
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_real_kernel_does_not_let_local_guardian_launder_untrusted_task_origin(runtime):
    from agents.core.action_origin import bind_action_origin, reset_action_origin

    queue, worker, orch, sandbox, _seen = runtime
    use_real_kernel(runtime)
    bind_judge(worker, 'APPROVE')
    token = bind_action_origin('external')
    try:
        answer = await propose(orch)
    finally:
        reset_action_origin(token)
    await drain(worker.approval_judge)
    assert queue.get(answer['task_id']).origin == 'external'
    await worker.tick()
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_revoked_smart_mode_after_approval_cannot_execute(runtime):
    queue, worker, orch, sandbox, _seen = runtime
    env, _requests = bind_judge(worker, 'APPROVE')
    answer = await propose(orch)
    await drain(worker.approval_judge)
    assert queue.get(answer['task_id']).status == 'approved'
    env['JARVIS_SMART_APPROVALS'] = '0'
    await worker.tick()
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_smart_execution_keeps_the_reviewed_agent_at_the_target_and_kernel(runtime):
    queue, worker, orch, sandbox, seen = runtime
    from agents.core.environments import TargetRegistry, TerminalTarget

    orch._test_coordinator._targets = TargetRegistry([TerminalTarget(
        name='isolated-sandbox', backend='docker', enabled=True, allowed_agents=frozenset({'jarvis'}),
        capabilities=frozenset({'terminal.exec'}), approval_required=frozenset({'terminal.exec'}),
    )])
    bind_judge(worker, 'APPROVE')
    answer = await orch.tool_rpc.handle({'tool': 'terminal_run', 'args': {
        'target': 'isolated-sandbox', 'command': 'printf hello',
    }}, actor='other')
    await drain(worker.approval_judge)
    assert queue.get(answer['task_id']).agent == 'other'
    await worker.tick()
    assert sandbox.commands == []  # this target permits jarvis only
    assert not any(action.kind == 'terminal.exec' and action.agent == 'jarvis' for action in seen)


@pytest.mark.asyncio
async def test_machine_approval_cannot_be_downgraded_to_unsigned_human_accept(runtime):
    queue, worker, orch, sandbox, _seen = runtime
    env, _requests = bind_judge(worker, 'APPROVE')
    answer = await propose(orch)
    await drain(worker.approval_judge)
    queue._conn.execute("UPDATE tasks SET decision='accept' WHERE id=?", (answer['task_id'],))
    queue._conn.commit()
    env['JARVIS_SMART_APPROVALS'] = '0'
    await worker.tick()
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_smart_pending_projection_and_explicit_owner_deny_at_execution(runtime, monkeypatch):
    queue, worker, orch, sandbox, _seen = runtime
    gate = asyncio.Event()
    bind_judge(worker, 'APPROVE', gate=gate)
    answer = await propose(orch)
    await asyncio.sleep(0)
    projection = worker.approval_judge.project(queue.get(answer['task_id']))
    assert projection['judge_pending'] is True and projection['judge_mode'] == 'smart'
    gate.set()
    await drain(worker.approval_judge)
    monkeypatch.setenv('JARVIS_SMART_APPROVAL_DENY', '["printf*"]')
    await worker.tick()
    assert sandbox.commands == []
