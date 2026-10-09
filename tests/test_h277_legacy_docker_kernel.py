"""A human-accepted legacy Docker terminal task needs its own current kernel hop."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agents.core.environments import TargetRegistry, TerminalTarget
from agents.core.environments.execution import GovernedTargetRunner
from agents.core.kernel import Decision, Verdict
from agents.core.sandbox import Sandbox
from tests.test_h277_smart_terminal_integration import (
    propose,
    runtime,  # noqa: F401
    use_real_kernel,
)


class SyntheticSandbox:
    timeout = 30

    def __init__(self):
        self.commands = []

    def active_backend(self):
        return 'docker'

    async def execute_shell(self, command):
        self.commands.append(command)
        return SimpleNamespace(exit_code=0, stdout='ok', stderr='', duration=0.0)


def registry():
    return TargetRegistry([TerminalTarget(
        name='isolated-sandbox', backend='docker', enabled=True,
        allowed_agents=frozenset({'jarvis'}), capabilities=frozenset({'terminal.exec'}),
        approval_required=frozenset({'terminal.exec'}),
    )])


async def test_real_manual_approval_cannot_bypass_disabled_kernel(runtime, monkeypatch):
    queue, worker, orch, sandbox, seen = runtime
    answer = await propose(orch)
    await worker.apply_decision(answer['task_id'], 'accept', 'user')
    assert queue.get(answer['task_id']).human_decision['action'] == 'accept'
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '0')
    await worker.tick()
    assert sandbox.commands == []
    assert queue.get(answer['task_id']).result['status'] == 'failed'
    assert not any(action.kind == 'terminal.exec' for action in seen)


@pytest.mark.parametrize(('mode', 'tamper_receipt'), [
    ('off', False), ('enforce', False), ('enforce', True),
])
async def test_real_manually_accepted_task_keeps_kernel_hop_in_each_mediation_mode(
    runtime, tmp_path, mode, tamper_receipt,
):
    queue, worker, orch, sandbox, seen = runtime
    if mode == 'enforce':
        from agents.core.autonomy.mediation import MonotonicHeadAnchor
        from agents.core.autonomy.queue import TaskQueue

        head = [None]

        def cas(previous, replacement):
            if head[0] != previous:
                return False
            head[0] = replacement
            return True

        queue = TaskQueue(
            str(tmp_path / 'enforced.db'), mediation_mode='enforce',
            mediation_signer=queue._mediation_signer,
            mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas),
            mediation_classifier=lambda _kind: True, mediation_scope='global',
        ).initialize()
        worker.queue = queue
        orch.autonomy_queue = queue
    try:
        use_real_kernel((queue, worker, orch, sandbox, seen))
        answer = await propose(orch)
        await worker.tick()
        assert sandbox.commands == []
        await worker.apply_decision(answer['task_id'], 'accept', 'user')
        assert queue.get(answer['task_id']).human_decision['action'] == 'accept'
        if tamper_receipt:
            queue._conn.execute('UPDATE tasks SET mediation_receipt=? WHERE id=?',
                                ('{}', answer['task_id']))
            queue._conn.commit()
        await worker.tick()
        if tamper_receipt:
            assert sandbox.commands == []
        else:
            assert sandbox.commands == ['printf hello']
            assert queue.get(answer['task_id']).result['status'] == 'ok'
    finally:
        if mode == 'enforce':
            queue.close()


@pytest.mark.parametrize('verdict', [Verdict.DENY, Verdict.QUEUE])
async def test_legacy_manual_docker_needs_terminal_exec_grant(monkeypatch, verdict):
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    sandbox = SyntheticSandbox()
    seen = []

    def authorize(action, *, capability, approval_check=None):
        seen.append((action, capability, approval_check))
        return Decision(verdict, reason='fixture refusal')

    runner = GovernedTargetRunner(registry(), sandbox, authorizer=authorize,
                                  approval_check=lambda task_id: task_id == 17,
                                  request_check=lambda task_id, request: task_id == 17,
                                  legacy_kernel_check=lambda *_args, **_kwargs: Decision(Verdict.GRANT))
    result = await runner.run(target='isolated-sandbox', agent='jarvis',
                              command='printf hello', approved_task_id=17)
    assert result['ok'] is False and sandbox.commands == []
    assert len(seen) == 1
    action, capability, check = seen[0]
    assert action.kind == capability.name == 'terminal.exec'
    assert action.payload['approved_task_id'] == 17
    assert action.payload['target'] == 'isolated-sandbox'
    assert action.payload['backend'] == 'docker'
    assert action.payload['argv'] == ['sh', '-c', 'printf hello']
    assert callable(check) and check(action)


async def test_legacy_request_withdrawn_during_async_kernel_grant_never_spawns(monkeypatch):
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    sandbox = SyntheticSandbox()
    live = [True]

    async def grant(_action, **_kwargs):
        live[0] = False
        return Decision(Verdict.GRANT)

    runner = GovernedTargetRunner(registry(), sandbox, authorizer=grant,
                                  approval_check=lambda _task_id: live[0],
                                  request_check=lambda _task_id, _request: live[0],
                                  legacy_kernel_check=lambda *_args, **_kwargs: Decision(Verdict.GRANT))
    result = await runner.run(target='isolated-sandbox', agent='jarvis',
                              command='printf hello', approved_task_id=17)
    assert result['ok'] is False and sandbox.commands == []


async def test_legacy_docker_error_never_falls_back_to_host(monkeypatch, tmp_path):
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    monkeypatch.setattr(Sandbox, '_check_docker', lambda _self: True)
    sandbox = Sandbox(work_dir=str(tmp_path), allow_subprocess=True, allow_wasm=False)
    host_calls = []

    async def unavailable(*_args, **_kwargs):
        raise FileNotFoundError('synthetic missing docker client')

    async def host(command, **_kwargs):
        host_calls.append(command)
        return SimpleNamespace(exit_code=0, stdout='host', stderr='', duration=0)

    monkeypatch.setattr('agents.core.sandbox.asyncio.create_subprocess_exec', unavailable)
    monkeypatch.setattr(sandbox, '_execute_subprocess_shell', host)
    runner = GovernedTargetRunner(registry(), sandbox,
                                  authorizer=lambda *_args, **_kwargs: Decision(Verdict.GRANT),
                                  approval_check=lambda _task_id: True,
                                  request_check=lambda _task_id, _request: True,
                                  legacy_kernel_check=lambda *_args, **_kwargs: Decision(Verdict.GRANT))
    result = await runner.run(target='isolated-sandbox', agent='jarvis',
                              command='printf hello', approved_task_id=17)
    assert result['ok'] is False and host_calls == []


@pytest.mark.parametrize('mutation', [
    'receipt', 'mode_off', 'mode_hold', 'mode_before_rpc', 'fingerprint',
])
async def test_enforce_authority_change_after_worker_admission_blocks_physical_spawn(
    runtime, monkeypatch, tmp_path, mutation,
):
    from agents.core.autonomy.mediation import MonotonicHeadAnchor
    from agents.core.autonomy.queue import TaskQueue

    old_queue, worker, orch, _fake_sandbox, seen = runtime
    head = [None]

    def cas(previous, replacement):
        if head[0] != previous:
            return False
        head[0] = replacement
        return True

    queue = TaskQueue(
        str(tmp_path / 'late-receipt.db'), mediation_mode='enforce',
        mediation_signer=old_queue._mediation_signer,
        mediation_head_anchor=MonotonicHeadAnchor(lambda: head[0], cas),
        mediation_classifier=lambda _kind: True, mediation_scope='global',
    ).initialize()
    monkeypatch.setattr(Sandbox, '_check_docker', lambda _self: True)
    sandbox = Sandbox(work_dir=str(tmp_path / 'workspace'), allow_wasm=False)
    worker.queue = queue
    orch.autonomy_queue = queue
    orch.sandbox = sandbox
    spawns = []

    async def fake_spawn(*argv, **_kwargs):
        spawns.append(argv)
        return SimpleNamespace(returncode=0)

    async def fake_output(_proc, _sinks):
        return 'ok', ''

    monkeypatch.setattr('agents.core.sandbox.asyncio.create_subprocess_exec', fake_spawn)
    monkeypatch.setattr(sandbox, '_read_output_capped', fake_output)
    try:
        use_real_kernel((queue, worker, orch, sandbox, seen))
        answer = await propose(orch)
        task_id = answer['task_id']
        await worker.apply_decision(task_id, 'accept', 'user')
        assert queue.get(task_id).human_decision['action'] == 'accept'
        if mutation == 'mode_before_rpc':
            execute = orch.tool_rpc.execute

            async def downgrade_after_worker_admission(task, *, execution_context=None):
                assert queue.get(task_id).status == 'running'
                queue.mediation_mode = 'off'
                return await execute(task, execution_context=execution_context)

            monkeypatch.setattr(orch.tool_rpc, 'execute', downgrade_after_worker_admission)
        setup = sandbox._ensure_work_dir
        reached_running = []

        def tamper_after_admission():
            setup()
            task = queue.get(task_id)
            reached_running.append(task.status)
            assert task.status == 'running' and task.mediation_receipt
            if mutation == 'receipt':
                queue._conn.execute('UPDATE tasks SET mediation_receipt=? WHERE id=?',
                                    ('{}', task_id))
                queue._conn.commit()
            elif mutation == 'fingerprint':
                queue._conn.execute('UPDATE tasks SET title=? WHERE id=?',
                                    ('changed after admission', task_id))
                queue._conn.commit()
            elif mutation in {'mode_off', 'mode_hold'}:
                queue.mediation_mode = 'off' if mutation == 'mode_off' else 'hold'

        monkeypatch.setattr(sandbox, '_ensure_work_dir', tamper_after_admission)
        await worker.tick()
        assert reached_running == ([] if mutation == 'mode_before_rpc' else ['running'])
        assert spawns == []
    finally:
        queue.close()
        worker.queue = old_queue
        orch.autonomy_queue = old_queue


@pytest.mark.parametrize('change', [
    'approval', 'target', 'source', 'kernel', 'command', 'cancellation',
])
async def test_legacy_revocation_after_sandbox_setup_blocks_physical_spawn(
    monkeypatch, tmp_path, change,
):
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    monkeypatch.setattr(Sandbox, '_check_docker', lambda _self: True)
    sandbox = Sandbox(work_dir=str(tmp_path), allow_wasm=False)
    live = [True]
    spawned = []
    origin_token = []
    targets = registry()
    original_setup = sandbox._ensure_work_dir

    def revoke_during_setup():
        original_setup()
        if change == 'approval':
            live[0] = False
        elif change == 'target':
            targets._targets['isolated-sandbox'] = replace(
                targets.snapshot('isolated-sandbox'), enabled=False)
        elif change == 'source':
            from agents.core.action_origin import bind_action_origin

            origin_token.append(bind_action_origin('external'))
        elif change == 'kernel':
            monkeypatch.setenv('JARVIS_ACTION_KERNEL', '0')
        elif change == 'cancellation':
            asyncio.current_task().cancel()

    async def fake_spawn(*argv, **_kwargs):
        spawned.append(argv)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sandbox, '_ensure_work_dir', revoke_during_setup)
    if change == 'command':
        async def changed_command(_command):
            return await sandbox._run_docker(['sh', '-c', 'printf changed'])

        monkeypatch.setattr(sandbox, '_execute_docker_shell', changed_command)
    monkeypatch.setattr('agents.core.sandbox.asyncio.create_subprocess_exec', fake_spawn)
    monkeypatch.setattr(sandbox, '_read_output_capped', lambda *_args: ('ok', ''))
    runner = GovernedTargetRunner(targets, sandbox,
                                  authorizer=lambda *_args, **_kwargs: Decision(Verdict.GRANT),
                                  approval_check=lambda _task_id: live[0],
                                  request_check=lambda _task_id, _request: live[0],
                                  legacy_kernel_check=lambda *_args, **_kwargs: Decision(Verdict.GRANT))
    try:
        invocation = runner.run(target='isolated-sandbox', agent='jarvis',
                                command='printf hello', approved_task_id=17)
        if change == 'cancellation':
            pending = asyncio.create_task(invocation)
            try:
                result = await pending
            except asyncio.CancelledError:
                pass
            else:
                assert result['ok'] is False
        else:
            result = await invocation
            assert result['ok'] is False
        assert spawned == []
    finally:
        if origin_token:
            from agents.core.action_origin import reset_action_origin

            reset_action_origin(origin_token[0])
