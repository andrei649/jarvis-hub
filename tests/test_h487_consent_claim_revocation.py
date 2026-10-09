"""A consent claim loses authority if a live floor changes before process launch."""

import asyncio
import json

import pytest

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
)
from agents.core.autonomy.consent_types import OwnerConsentActor
from agents.core.commands import Principal
from agents.core.environments.local_transport import LocalHostTransport
from agents.core.environments.ssh_transport import SshTransport
from agents.core.sandbox import Sandbox
from tests.test_h487_consent_runtime_integration import _Process, ask, consent_runtime


async def _ask_target(runtime, target):
    turn = open_approval_turn(
        session_id='owner-chat', session_instance='instance',
        principal=Principal(channel='web', admin=True),
        session_is_live=lambda sid, inst: True,
    )
    token = bind_approval_turn(turn)
    try:
        reply = await runtime.orch.tool_rpc.handle(
            {'tool': 'terminal_run',
             'args': {'target': target, 'command': 'git reset --hard'}}, actor='jarvis',
        )
        return runtime.q.get(reply['task_id'])
    finally:
        close_approval_turn(turn, token)


async def _approve(runtime, first):
    source = runtime.q._consent_source(first.id)
    descriptor = runtime.q._consent_resolver(first, source)
    offer = runtime.q.pending_consent_offer(first.id)
    assert descriptor is not None and offer is not None
    assert await runtime.worker.apply_consent_decision(
        first.id, offer.revision, choice='session',
        actor=OwnerConsentActor('admin', 'admin', lambda: True),
    ) is not None
    return descriptor


@pytest.mark.asyncio
@pytest.mark.parametrize('floor', ['halt', 'policy', 'target', 'revoke'])
async def test_real_local_claim_refuses_changed_floor_at_spawn(
    consent_runtime, monkeypatch, floor,
):
    runtime = consent_runtime
    effects = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def spawn(*args, **kwargs):
        effects.append(args)
        return _Process()

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    original_run = LocalHostTransport.run

    async def paused_run(self, *args, **kwargs):
        entered.set()
        await release.wait()
        return await original_run(self, *args, **kwargs)

    monkeypatch.setattr(LocalHostTransport, 'run', paused_run)
    first = await ask(runtime)
    descriptor = await _approve(runtime, first)

    tick = asyncio.create_task(runtime.worker.tick(task_id=first.id))
    await asyncio.wait_for(entered.wait(), 2)
    assert runtime.q.get(first.id).status == 'running'
    proof = runtime.q._conn.execute(
        'SELECT state FROM task_consent_proofs WHERE task_id=?', (first.id,),
    ).fetchone()
    assert proof['state'] == 'claimed'
    if floor == 'halt':
        runtime.halted[0] = True
    elif floor == 'policy':
        runtime.worker.policy.mode = 'off'
    elif floor == 'target':
        monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_ROOTS', str(runtime.root / 'changed'))
    else:
        assert runtime.q._consent_ledger.revoke(descriptor.context)
        runtime.q._conn.commit()
    release.set()
    result = await asyncio.wait_for(tick, 2)
    assert result['failed'] == 1 and result['done'] == 0
    assert runtime.q.get(first.id).status == 'failed'
    assert effects == []


@pytest.mark.asyncio
async def test_cancelled_claim_does_not_leave_a_late_local_dispatch(
    consent_runtime, monkeypatch,
):
    runtime = consent_runtime
    effects = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def spawn(*args, **kwargs):
        effects.append(args)
        return _Process()

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    original_run = LocalHostTransport.run

    async def paused_run(self, *args, **kwargs):
        entered.set()
        await release.wait()
        return await original_run(self, *args, **kwargs)

    monkeypatch.setattr(LocalHostTransport, 'run', paused_run)
    first = await ask(runtime)
    await _approve(runtime, first)
    tick = asyncio.create_task(runtime.worker.tick(task_id=first.id))
    await asyncio.wait_for(entered.wait(), 2)
    assert runtime.q.get(first.id).status == 'running'
    tick.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tick
    release.set()
    await asyncio.sleep(0)
    assert runtime.q.get(first.id).status == 'failed'
    assert (await runtime.worker.tick(task_id=first.id))['done'] == 0
    assert effects == []


class TestRealSshClaim:
    @pytest.fixture(autouse=True)
    def configured_ssh_before_registration(self, monkeypatch, tmp_path):
        known = tmp_path / 'known_hosts'
        known.write_text('synthetic pin', encoding='utf-8')
        inventory = {'pi-house': {'user': 'synthetic', 'hostname': 'example.test',
                                  'roots': ['/srv']}}
        monkeypatch.setenv('JARVIS_TERMINAL_SSH_HOST', '1')
        monkeypatch.setenv('JARVIS_TERMINAL_SSH_HOSTS', json.dumps(inventory))
        monkeypatch.setenv('JARVIS_TERMINAL_SSH_KNOWN_HOSTS', str(known))

    @pytest.mark.asyncio
    @pytest.mark.parametrize('floor', ['halt', 'policy', 'target', 'revoke'])
    async def test_changed_floor_after_claim_blocks_ssh_spawn(
        self, consent_runtime, monkeypatch, floor,
    ):
        runtime = consent_runtime
        effects = []
        entered, release = asyncio.Event(), asyncio.Event()

        async def spawn(*args, **kwargs):
            effects.append(args)
            return _Process()

        monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
        original_run = SshTransport.run

        async def paused_run(self, *args, **kwargs):
            entered.set()
            await release.wait()
            return await original_run(self, *args, **kwargs)

        monkeypatch.setattr(SshTransport, 'run', paused_run)
        first = await _ask_target(runtime, 'pi-house')
        descriptor = await _approve(runtime, first)
        tick = asyncio.create_task(runtime.worker.tick(task_id=first.id))
        await asyncio.wait_for(entered.wait(), 2)
        assert runtime.q.get(first.id).status == 'running'
        proof = runtime.q._conn.execute(
            'SELECT state FROM task_consent_proofs WHERE task_id=?', (first.id,),
        ).fetchone()
        assert proof['state'] == 'claimed'
        if floor == 'halt':
            runtime.halted[0] = True
        elif floor == 'policy':
            runtime.worker.policy.mode = 'off'
        elif floor == 'target':
            monkeypatch.setenv('JARVIS_TERMINAL_SSH_HOSTS', json.dumps({
                'pi-house': {'user': 'synthetic', 'hostname': 'changed.test', 'roots': ['/srv']},
            }))
        else:
            assert runtime.q._consent_ledger.revoke(descriptor.context)
            runtime.q._conn.commit()
        release.set()
        result = await asyncio.wait_for(tick, 2)
        assert result['failed'] == 1 and result['done'] == 0
        assert runtime.q.get(first.id).status == 'failed'
        assert effects == []

    @pytest.mark.asyncio
    async def test_current_claim_spawns_one_mocked_ssh_client(self, consent_runtime, monkeypatch):
        runtime = consent_runtime
        effects = []

        async def spawn(*args, **kwargs):
            effects.append(args)
            return _Process()

        monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
        first = await _ask_target(runtime, 'pi-house')
        await _approve(runtime, first)
        result = await runtime.worker.tick(task_id=first.id)
        assert result['done'] == 1 and result['failed'] == 0
        assert runtime.q.get(first.id).status == 'done'
        assert len(effects) == 1 and effects[0][0] == 'ssh'


@pytest.mark.asyncio
@pytest.mark.parametrize('floor', ['halt', 'policy', 'target', 'revoke'])
async def test_real_docker_claim_refuses_changed_floor_at_spawn(
    consent_runtime, monkeypatch, floor,
):
    runtime = consent_runtime
    sandbox = Sandbox.__new__(Sandbox)
    sandbox._has_docker = True
    sandbox.allow_subprocess = False
    sandbox.timeout = 30
    sandbox.max_memory_mb = 256
    sandbox.max_output_bytes = 50_000
    sandbox.docker_image = 'synthetic:local'
    sandbox.work_dir = runtime.root
    sandbox.work_dir_managed = False
    runtime.orch.sandbox = sandbox
    effects = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def spawn(*args, **kwargs):
        effects.append(args)
        return _Process()

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    original_run = Sandbox._run_docker

    async def paused_run(self, *args, **kwargs):
        entered.set()
        await release.wait()
        return await original_run(self, *args, **kwargs)

    monkeypatch.setattr(Sandbox, '_run_docker', paused_run)
    first = await _ask_target(runtime, 'isolated-sandbox')
    descriptor = await _approve(runtime, first)
    tick = asyncio.create_task(runtime.worker.tick(task_id=first.id))
    await asyncio.wait_for(entered.wait(), 2)
    assert runtime.q.get(first.id).status == 'running'
    proof = runtime.q._conn.execute(
        'SELECT state FROM task_consent_proofs WHERE task_id=?', (first.id,),
    ).fetchone()
    assert proof['state'] == 'claimed'
    if floor == 'halt':
        runtime.halted[0] = True
    elif floor == 'policy':
        runtime.worker.policy.mode = 'off'
    elif floor == 'target':
        sandbox.docker_image = 'changed:local'
    else:
        assert runtime.q._consent_ledger.revoke(descriptor.context)
        runtime.q._conn.commit()
    release.set()
    result = await asyncio.wait_for(tick, 2)
    assert result['failed'] == 1 and result['done'] == 0
    assert runtime.q.get(first.id).status == 'failed'
    assert effects == []


@pytest.mark.asyncio
async def test_current_claim_spawns_one_mocked_docker_client(consent_runtime, monkeypatch):
    runtime = consent_runtime
    sandbox = Sandbox.__new__(Sandbox)
    sandbox._has_docker = True
    sandbox.allow_subprocess = False
    sandbox.timeout = 30
    sandbox.max_memory_mb = 256
    sandbox.max_output_bytes = 50_000
    sandbox.docker_image = 'synthetic:local'
    sandbox.work_dir = runtime.root
    sandbox.work_dir_managed = False
    runtime.orch.sandbox = sandbox
    effects = []

    async def spawn(*args, **kwargs):
        effects.append(args)
        return _Process()

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    first = await _ask_target(runtime, 'isolated-sandbox')
    await _approve(runtime, first)
    result = await runtime.worker.tick(task_id=first.id)
    assert result['done'] == 1 and result['failed'] == 0
    assert runtime.q.get(first.id).status == 'done'
    assert len(effects) == 1 and effects[0][:2] == ('docker', 'run')
