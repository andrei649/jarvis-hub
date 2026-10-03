"""Trusted terminal consent follows current declared target and producer identity."""

import copy
from types import SimpleNamespace

import pytest

from agents.core.autonomy.policy import AutonomyPolicy
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.environments.targets import TargetRegistry, TerminalTarget
from agents.core.tool_rpc import ToolRPCServer

try:
    from agents.core.autonomy.terminal_consent_runtime import build_terminal_consent_resolver
except ModuleNotFoundError:
    build_terminal_consent_resolver = None


async def _handler(args):
    return {'ok': True}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '1')
    monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_HOST', '1')
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    root = tmp_path / 'uncreated-root'
    monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_ROOTS', str(root))
    queue = TaskQueue(str(tmp_path / 'queue.db')).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy())
    server = ToolRPCServer()
    server.register_tool('terminal_run', _handler, gated=True, trusted_execution=True,
                         consent_revision='nerva.terminal_run.v1')
    spec = server._tools['terminal_run']
    target = TerminalTarget('synthetic', 'local', True, frozenset({'jarvis'}),
                            frozenset({'terminal.exec'}), frozenset({'terminal.exec'}))
    registry = TargetRegistry([target])
    orch = SimpleNamespace(autonomy=worker, autonomy_queue=queue, sandbox=None)
    args = {'target': 'synthetic', 'command': 'git reset --hard'}
    task_id = queue.enqueue(agent='jarvis', kind='toolrpc.terminal_run', title='synthetic',
                            payload={'tool': 'terminal_run', 'target': 'terminal_run', 'args': args})
    policy = {key: copy.deepcopy(getattr(worker.policy, key)) for key in (
        'mode', 'agent_modes', 'cap_per_action', 'daily_ceiling',
        'earned_autonomy_enabled', 'tier_outcomes',
    )}
    policy['tier_outcomes'] = {str(int(k)): v for k, v in policy['tier_outcomes'].items()}
    source = {'policy': policy, 'producer': {
        'request': {'tool': 'terminal_run', 'args': args},
        'principal': '["web","owner"]', 'surface': 'generic_model_toolrpc',
        'session_id': 'synthetic-session', 'session_instance': 'instance',
        'registration_key': spec['_consent_registration_key'],
        'registration_epoch': spec['_grouping_epoch'],
    }}
    yield SimpleNamespace(q=queue, worker=worker, server=server, spec=spec, registry=registry,
                          orch=orch, source=source, task=queue.get(task_id), root=root)
    queue.close()


def resolve(rig):
    assert callable(build_terminal_consent_resolver), 'terminal producer has no trusted consent resolver'
    return build_terminal_consent_resolver(rig.orch, rig.registry, rig.server, rig.spec)


def test_terminal_descriptor_binds_current_config_without_creating_workspace(rig, monkeypatch):
    resolver = resolve(rig)
    first = resolver(rig.task, rig.source)
    assert first is not None and first.categories
    assert first.context.registration_key == rig.spec['_consent_registration_key']
    assert first.registration_epoch == rig.spec['_grouping_epoch']
    assert not rig.root.exists()
    assert resolver(rig.task, rig.source) == first
    monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_ROOTS', str(rig.root.parent / 'different'))
    assert resolver(rig.task, rig.source).context.target_scope != first.context.target_scope
    assert not rig.root.exists()


@pytest.mark.parametrize('mutation', ['registration', 'epoch', 'producer_args', 'target',
                                     'policy', 'worker', 'feature', 'kernel'])
def test_changed_trusted_terminal_scope_refuses_old_source(rig, monkeypatch, mutation):
    resolver = resolve(rig)
    assert resolver(rig.task, rig.source) is not None
    if mutation == 'registration':
        rig.spec['description'] = 'changed declared producer'
    elif mutation == 'epoch':
        rig.spec['_grouping_epoch'] = 'different'
    elif mutation == 'producer_args':
        rig.source['producer']['request'] = {'tool': 'terminal_run', 'args': {}}
    elif mutation == 'target':
        rig.registry._targets.clear()
    elif mutation == 'policy':
        rig.worker.policy.mode = 'off'
    elif mutation == 'worker':
        rig.orch.autonomy = AutonomyWorker(rig.q)
    elif mutation == 'feature':
        monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_HOST', '0')
    elif mutation == 'kernel':
        monkeypatch.setenv('JARVIS_ACTION_KERNEL', '0')
    assert resolver(rig.task, rig.source) is None


def test_dynamic_spend_does_not_change_static_consent_policy_identity(rig):
    resolver = resolve(rig)
    first = resolver(rig.task, rig.source)
    assert first is not None
    rig.worker.policy._spent_today = 11
    rig.source['policy']['_spent_today'] = 4
    rig.source['policy']['decision'] = {'outcome': 'ask'}
    assert resolver(rig.task, rig.source) == first
