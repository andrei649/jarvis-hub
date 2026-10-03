"""Real terminal registration, owner turn, queue and consent worker integration."""

import asyncio
import hashlib
import hmac
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents.core.approval_outcomes import (
    bind_approval_turn,
    close_approval_turn,
    open_approval_turn,
)
from agents.core.autonomy.consent_head_store import make_consent_head_anchor
from agents.core.autonomy.consent_types import OwnerConsentActor
from agents.core.autonomy.executor import TaskExecutor
from agents.core.autonomy.mediation import DetachedHMACSigner, MonotonicHeadAnchor
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.terminal_consent_categories import terminal_consent_catalog
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.commands import Principal
from agents.core.kernel.binding import make_action_kernel
from agents.core.routers import _deps
from agents.core.routers import autonomy as autonomy_routes
from agents.core.routers._deps import admin_guard


@pytest.fixture(params=['off', 'enforce'])
def consent_runtime(tmp_path, monkeypatch, request):
    monkeypatch.setenv('JARVIS_TERMINAL_TARGETS', '1')
    monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_HOST', '1')
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    root = tmp_path / 'workspace'
    root.mkdir()
    monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_ROOTS', str(root))
    signer = DetachedHMACSigner(lambda body: hmac.new(b'synthetic-runtime', body, hashlib.sha256).hexdigest())
    heads = [None]
    mediation_anchor = MonotonicHeadAnchor(
        lambda: heads[0],
        lambda before, after: (heads.__setitem__(0, after) or True) if heads[0] == before else False,
    )
    queue = TaskQueue(str(tmp_path / 'queue.db'), mediation_signer=signer,
                      mediation_mode=request.param, mediation_head_anchor=mediation_anchor,
                      mediation_scope='*',
                      consent_categories=terminal_consent_catalog(),
                      consent_head_anchor=make_consent_head_anchor(tmp_path / 'consent-head.json')).initialize()
    halted = [False]
    kill_switch = SimpleNamespace(is_halted=lambda scope: halted[0])
    worker = AutonomyWorker(queue, kill_switch=kill_switch)
    orch = SimpleNamespace(agents={}, autonomy=worker, autonomy_queue=queue, sandbox=None,
                           get_setting=lambda key, default=None: default,
                           kill_switch=kill_switch)
    worker.bind_mediation(make_action_kernel(orch), signer)
    coordinator = AutonomyCoordinator(orch)
    coordinator._wire_agent_tool_runtime(action_kernel=worker.kernel_gate)
    executor = TaskExecutor(execution_guard=worker.execution_allowed)
    executor.register('toolrpc.terminal_run', coordinator._approved_desktop_tool_rpc_execute)
    worker.executor = executor.execute
    yield SimpleNamespace(q=queue, worker=worker, orch=orch, coordinator=coordinator,
                          root=root, halted=halted, mode=request.param)
    queue.close()


async def ask(runtime, command='git reset --hard', *, session='owner-chat', instance='instance'):
    turn = open_approval_turn(session_id=session, session_instance=instance,
                             principal=Principal(channel='web', admin=True),
                             session_is_live=lambda sid, inst: True)
    token = bind_approval_turn(turn)
    try:
        reply = await runtime.orch.tool_rpc.handle(
            {'tool': 'terminal_run', 'args': {'target': 'local-host', 'command': command}}, actor='jarvis',
        )
        return runtime.q.get(reply['task_id'])
    finally:
        close_approval_turn(turn, token)


@pytest.mark.asyncio
async def test_actual_terminal_intake_exposes_exact_reusable_owner_offer(consent_runtime):
    runtime = consent_runtime
    task = await ask(runtime)
    offer = runtime.q.pending_consent_offer(task.id)
    assert offer is not None, 'registered terminal producer is not connected to reusable consent'
    assert offer.member_ids == (task.id,) and offer.categories
    assert task.status == 'blocked' and task.human_decision is None
    assert runtime.q._consent_source(task.id)['version'] == 2


@pytest.mark.asyncio
async def test_real_owner_choice_and_later_request_have_distinct_attribution(consent_runtime):
    runtime = consent_runtime
    first = await ask(runtime)
    offer = runtime.q.pending_consent_offer(first.id)
    assert offer is not None
    result = await runtime.worker.apply_consent_decision(
        first.id, offer.revision, choice='always',
        actor=OwnerConsentActor('admin', 'admin', lambda: True),
    )
    assert result is not None and len(result.tasks) == 1
    first = runtime.q.get(first.id)
    assert first.human_decision['action'] == 'always' and first.decided_by == 'admin'
    later = await ask(runtime, session='new-owner-chat', instance='new-instance')
    assert later.status == 'approved'
    assert later.decided_by == 'consent' and later.human_decision is None
    assert not runtime.worker.execution_allowed(later)


class _Process:
    returncode = 0

    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(b'synthetic effect only\n')
        self.stdout.feed_eof()
        self.stderr.feed_eof()

    async def wait(self):
        return 0

    def kill(self):
        self.returncode = -9


@pytest.mark.asyncio
async def test_real_consent_worker_reaches_physical_gate_once_per_task(consent_runtime, monkeypatch):
    runtime = consent_runtime
    effects = []

    async def spawn(*args, **kwargs):
        effects.append((args, kwargs['cwd']))
        return _Process()

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    first = await ask(runtime)
    offer = runtime.q.pending_consent_offer(first.id)
    assert offer is not None
    result = await runtime.worker.apply_consent_decision(
        first.id, offer.revision, choice='session',
        actor=OwnerConsentActor('admin', 'admin', lambda: True),
    )
    assert result is not None
    assert (await runtime.worker.tick(task_id=first.id))['done'] == 1
    assert runtime.q.get(first.id).status == 'done'
    assert effects == [(('git', 'reset', '--hard'), str(runtime.root))]
    later = await ask(runtime)
    assert later.status == 'approved' and later.human_decision is None
    assert (await runtime.worker.tick(task_id=later.id))['done'] == 1
    await runtime.worker.tick()
    assert len(effects) == 2
    assert runtime.q.get(first.id).attempts == runtime.q.get(later.id).attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['session', 'always'])
async def test_new_session_only_reuses_explicit_always_choice(consent_runtime, choice):
    runtime = consent_runtime
    first = await ask(runtime)
    offer = runtime.q.pending_consent_offer(first.id)
    assert offer is not None
    assert await runtime.worker.apply_consent_decision(
        first.id, offer.revision, choice=choice,
        actor=OwnerConsentActor('admin', 'admin', lambda: True),
    ) is not None
    later = await ask(runtime, session='different', instance='different')
    assert later.status == ('approved' if choice == 'always' else 'blocked')
    assert later.human_decision is None


@pytest.mark.asyncio
@pytest.mark.parametrize('floor', ['halt', 'policy', 'target', 'revoke'])
async def test_current_floor_change_before_tick_prevents_physical_effect(consent_runtime, monkeypatch, floor):
    runtime = consent_runtime
    effects = []

    async def spawn(*args, **kwargs):
        effects.append(args)
        return _Process()

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    first = await ask(runtime)
    source = runtime.q._consent_source(first.id)
    descriptor = runtime.q._consent_resolver(first, source)
    offer = runtime.q.pending_consent_offer(first.id)
    assert offer is not None
    assert await runtime.worker.apply_consent_decision(
        first.id, offer.revision, choice='session',
        actor=OwnerConsentActor('admin', 'admin', lambda: True),
    ) is not None
    if floor == 'halt':
        runtime.halted[0] = True
    elif floor == 'policy':
        runtime.worker.policy.mode = 'off'
    elif floor == 'target':
        monkeypatch.setenv('JARVIS_TERMINAL_LOCAL_ROOTS', str(runtime.root / 'changed'))
    else:
        assert runtime.q._consent_ledger.revoke(descriptor.context)
        runtime.q._conn.commit()
    result = await runtime.worker.tick(task_id=first.id)
    assert result['done'] == result['ran'] == 0
    assert effects == [] and runtime.q.get(first.id).status == 'approved'


@pytest.mark.asyncio
async def test_production_composed_domain_guard_preserves_terminal_consent(consent_runtime, monkeypatch):
    runtime = consent_runtime
    runtime.orch.jobs = SimpleNamespace(bind_url_monitor=lambda adapter: None, store=None)
    runtime.orch.secret_broker = SimpleNamespace(redact=lambda text: text)
    executor = runtime.worker.executor.__self__
    runtime.coordinator._wire_url_monitor(executor)
    runtime.coordinator._wire_cloud_image(executor)
    assert executor.execution_guard != runtime.worker.execution_allowed
    effects = []

    async def spawn(*args, **kwargs):
        effects.append(args)
        return _Process()

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    first = await ask(runtime)
    offer = runtime.q.pending_consent_offer(first.id)
    assert offer is not None
    assert await runtime.worker.apply_consent_decision(
        first.id, offer.revision, choice='session',
        actor=OwnerConsentActor('admin', 'admin', lambda: True),
    ) is not None
    result = await runtime.worker.tick(task_id=first.id)
    assert result['done'] == 1 and len(effects) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('current_owner', [True, False])
async def test_owner_http_offer_is_public_and_current_identity_is_rechecked(consent_runtime, monkeypatch, current_owner):
    runtime = consent_runtime
    first = await ask(runtime)
    monkeypatch.setattr(autonomy_routes, 'get_orch', lambda: runtime.orch)
    # Dependency authentication happened; the actual queue callback must still
    # consult the current credential policy if that identity has been revoked.
    web = SimpleNamespace(_admin_credential_ok=lambda supplied: current_owner and supplied == 'synthetic-owner',
                          _admin_configured=lambda: True,
                          _real_client_host=lambda request: '127.0.0.1', _LOCALHOSTS={'127.0.0.1'})
    monkeypatch.setattr(_deps, '_web', lambda: web)
    app = FastAPI()
    app.include_router(autonomy_routes.router)
    app.dependency_overrides[admin_guard] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://synthetic') as client:
        response = await client.get('/autonomy/tasks?status=blocked')
        assert response.status_code == 200
        offer = response.json()['tasks'][0].get('consent_offer')
        assert offer is not None
        assert offer['count'] == 1 and offer['categories'][0]['description']
        assert offer['choices'] == ['session', 'always', 'deny']
        assert all(value not in response.text for value in ('registration_key', 'principal_key', 'source_sha256'))
        decided = await client.post(
            f'/autonomy/tasks/{first.id}/consent',
            headers={'x-admin-token': 'synthetic-owner'},
            json={'revision': offer['revision'], 'choice': 'always', 'reason': 'Synthetic owner choice'},
        )
    assert decided.status_code == (200 if current_owner else 409)
    task = runtime.q.get(first.id)
    assert task.status == ('approved' if current_owner else 'blocked')
    assert (task.human_decision is not None) is current_owner
    if current_owner:
        assert task.human_decision['action'] == 'always'
        assert task.human_decision['by'] == 'admin'


@pytest.mark.asyncio
async def test_real_pending_followers_each_dispatch_their_own_claim(consent_runtime, monkeypatch):
    runtime = consent_runtime
    effects = []

    async def spawn(*args, **kwargs):
        effects.append(args)
        return _Process()

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    first = await ask(runtime)
    second = await ask(runtime)
    offer = runtime.q.pending_consent_offer(first.id)
    assert offer is not None and offer.member_ids == (first.id, second.id)
    result = await runtime.worker.apply_consent_decision(
        first.id, offer.revision, choice='session',
        actor=OwnerConsentActor('admin', 'admin', lambda: True),
    )
    assert result is not None
    for task_id in offer.member_ids:
        assert (await runtime.worker.tick(task_id=task_id))['done'] == 1
        assert runtime.q.get(task_id).attempts == 1
    assert effects == [('git', 'reset', '--hard'), ('git', 'reset', '--hard')]
    await runtime.worker.tick()
    assert len(effects) == 2
    assert all(runtime.q.get(task_id).status == 'done' for task_id in offer.member_ids)
    if runtime.mode == 'enforce':
        bindings = runtime.q._conn.execute(
            "SELECT task_id,execution_id FROM task_mediation_events "
            "WHERE outcome='governed' ORDER BY task_id",
        ).fetchall()
        assert {row['task_id'] for row in bindings} == set(offer.member_ids)
        assert len({row['execution_id'] for row in bindings}) == 2
