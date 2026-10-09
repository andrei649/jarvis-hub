"""A smart Docker approval still needs a fresh guard and kernel GRANT."""
from types import SimpleNamespace

import pytest

from agents.core.environments import TargetRegistry, TerminalTarget
from agents.core.environments.execution import GovernedTargetRunner
from agents.core.kernel import Decision, Verdict


class Sandbox:
    timeout = 30

    def __init__(self):
        self.commands = []

    def active_backend(self):
        return 'docker'

    async def execute_shell(self, command):
        self.commands.append(command)
        return SimpleNamespace(exit_code=0, stdout='', stderr='', duration=0)


def registry():
    return TargetRegistry([TerminalTarget(name='sandbox', backend='docker', enabled=True,
                           allowed_agents=frozenset({'jarvis'}), capabilities=frozenset({'terminal.exec'}),
                           approval_required=frozenset({'terminal.exec'}))])


@pytest.mark.asyncio
@pytest.mark.parametrize('verdict', [Verdict.DENY, Verdict.QUEUE])
async def test_smart_docker_requires_kernel_grant(monkeypatch, verdict):
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    sandbox = Sandbox()
    runner = GovernedTargetRunner(registry(), sandbox, approval_check=lambda _id: True,
                                  smart_approval_check=lambda _id: True,
                                  request_check=lambda _id, args: True,
                                  authorizer=lambda *args, **kwargs: Decision(verdict, reason='fixture', tier=2))
    result = await runner.run(target='sandbox', agent='jarvis', command='printf hello', approved_task_id=1)
    assert result['ok'] is False
    assert sandbox.commands == []


@pytest.mark.asyncio
async def test_async_kernel_grant_cannot_outlive_approval_revocation(monkeypatch):
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    active = [True]
    sandbox = Sandbox()

    async def grant(*args, **kwargs):
        active[0] = False
        return Decision(Verdict.GRANT, reason='fixture', tier=2)

    runner = GovernedTargetRunner(registry(), sandbox, approval_check=lambda _id: True,
                                  smart_approval_check=lambda _id: True,
                                  request_check=lambda _id, args: active[0], authorizer=grant)
    result = await runner.run(target='sandbox', agent='jarvis', command='printf hello', approved_task_id=1)
    assert result['ok'] is False and sandbox.commands == []


@pytest.mark.asyncio
async def test_smart_docker_does_not_claim_ignored_runtime_options(monkeypatch):
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    sandbox = Sandbox()
    runner = GovernedTargetRunner(registry(), sandbox, approval_check=lambda _id: True,
                                  smart_approval_check=lambda _id: True,
                                  request_check=lambda _id, args: True,
                                  authorizer=lambda *args, **kwargs: Decision(Verdict.GRANT, reason='fixture', tier=2))
    result = await runner.run(target='sandbox', agent='jarvis', command='printf hello', approved_task_id=1,
                              cwd='/other', timeout=10)
    assert result['ok'] is False and sandbox.commands == []


@pytest.mark.asyncio
async def test_docker_backend_switch_during_kernel_grant_cannot_fall_back_to_host(monkeypatch):
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    sandbox = Sandbox()
    active = ['docker']
    sandbox.active_backend = lambda: active[0]

    async def grant(*args, **kwargs):
        active[0] = 'subprocess'
        return Decision(Verdict.GRANT, reason='fixture', tier=2)

    runner = GovernedTargetRunner(registry(), sandbox, approval_check=lambda _id: True,
                                  smart_approval_check=lambda _id: True,
                                  request_check=lambda _id, args: True, authorizer=grant)
    result = await runner.run(target='sandbox', agent='jarvis', command='printf hello', approved_task_id=1)
    assert not result['ok'] and sandbox.commands == []


@pytest.mark.asyncio
async def test_broken_machine_classifier_never_selects_legacy_docker_path(monkeypatch):
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    sandbox = Sandbox()

    def unavailable(_id):
        raise RuntimeError('classification unavailable')

    runner = GovernedTargetRunner(registry(), sandbox, approval_check=lambda _id: True,
                                  smart_approval_check=unavailable, request_check=lambda _id, args: True,
                                  authorizer=lambda *args, **kwargs: Decision(Verdict.DENY, reason='fixture', tier=2))
    result = await runner.run(target='sandbox', agent='jarvis', command='printf hello', approved_task_id=1)
    assert not result['ok'] and sandbox.commands == []


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['local', 'ssh'])
async def test_host_transport_rechecks_request_after_async_kernel_grant(monkeypatch, tmp_path, backend):
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_HOST', '1')
    monkeypatch.setenv('JARVIS_TERMINAL_SSH_HOST', '1')
    current = [True]
    calls = []

    async def run(*args, **kwargs):
        calls.append(args)
        return {'ok': True}

    async def grant(*args, **kwargs):
        current[0] = False
        return Decision(Verdict.GRANT, reason='fixture', tier=2)

    transport = SimpleNamespace(roots=[str(tmp_path)], max_timeout=60, run=run,
                                bound_timeout=lambda timeout: 30,
                                resolve_cwd=lambda *args: str(tmp_path),
                                host_for=lambda target: SimpleNamespace(target=target, roots=[str(tmp_path)]))
    targets = TargetRegistry([TerminalTarget(name='host', backend=backend, enabled=True,
                              allowed_agents=frozenset({'jarvis'}), capabilities=frozenset({'terminal.exec'}),
                              approval_required=frozenset({'terminal.exec'}))])
    runner = GovernedTargetRunner(targets, Sandbox(), local_transport=transport, ssh_transport=transport,
                                  approval_check=lambda _id: True, request_check=lambda _id, args: current[0],
                                  authorizer=grant)
    result = await runner.run(target='host', agent='jarvis', command='printf hello', approved_task_id=1)
    assert not result['ok'] and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['timeout', 'kernel'])
async def test_smart_docker_preserves_kernel_and_timeout_until_spawn(monkeypatch, change):
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    sandbox = Sandbox()

    async def grant(*args, **kwargs):
        if change == 'timeout':
            sandbox.timeout = 600
        else:
            monkeypatch.setenv('JARVIS_ACTION_KERNEL', '0')
        return Decision(Verdict.GRANT, reason='fixture', tier=2)

    runner = GovernedTargetRunner(registry(), sandbox, approval_check=lambda _id: True,
                                  smart_approval_check=lambda _id: True,
                                  request_check=lambda _id, args: True, authorizer=grant)
    result = await runner.run(target='sandbox', agent='jarvis', command='printf hello', approved_task_id=1)
    assert not result['ok'] and sandbox.commands == []
