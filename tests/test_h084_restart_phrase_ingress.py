"""Private restart phrases route to governance without becoming model prompts."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from agents.core.commands import build_default_registry
from agents.core.orchestrator import Orchestrator


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['restart gateway', 'Please restart the Nerva gateway!', 'restart nerva?'])
async def test_private_telegram_phrase_rewrites_only_after_gateway(text):
    orch = Orchestrator.__new__(Orchestrator)
    orch.commands = build_default_registry()
    seen = []

    async def admitted(text, channel, **kwargs):
        seen.append((text, channel, kwargs))
        return 'governed command'

    orch._channel_handler_admitted = admitted
    assert await orch.channel_handler(text, 'telegram', sender='42', chat_id=42) == 'governed command'
    assert seen[0][0] == '/restart'
    assert seen[0][2]['pending_input_eligible'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('channel,metadata', [
    ('telegram', {'chat_type': 'group'}), ('telegram', {'chat_type': 'supergroup'}),
    ('telegram', {'observe_only': True}), ('telegram', {'message_thread_id': 4}),
    ('web', {}), ('slack', {}),
])
async def test_nonprivate_or_other_surface_keeps_prose(channel, metadata):
    orch = Orchestrator.__new__(Orchestrator)
    orch.commands = build_default_registry()
    seen = []

    async def admitted(text, *args, **kwargs):
        seen.append(text)

    orch._channel_handler_admitted = admitted
    await orch.channel_handler('restart gateway', channel, **metadata)
    assert seen == ['restart gateway']


@pytest.mark.asyncio
@pytest.mark.parametrize('broken', [False, True])
async def test_restart_dispatch_unavailable_never_falls_through_to_model(broken):
    orch = Orchestrator.__new__(Orchestrator)

    async def raises(*args, **kwargs):
        raise RuntimeError('registry unavailable')

    orch.commands = SimpleNamespace(dispatch=raises) if broken else None
    result = await orch._dispatch_command('/restart')
    assert result is not None and result.name == 'restart' and result.status == 'failed'
    assert await orch._dispatch_command('ordinary prose') is None


@pytest.mark.asyncio
async def test_real_private_phrase_keeps_source_and_bypasses_both_pending_paths(tmp_path, monkeypatch):
    from agents.core import hub_restart_apply, settings_db
    from agents.core.channel_inbox import ChannelInboxStore
    from tests.test_h058_slash_access import OWNER_ID, _Hub

    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    monkeypatch.setattr(settings_db, '_wal_set', False)
    hub = _Hub(tmp_path)
    channel = hub.channel
    hub.orch.channel_manager.channels = {'telegram': channel}
    gateway = channel.handler.__self__
    gateway.command_source_adapter = lambda: hub.orch.channels.get('telegram')
    gateway.inbox_store = ChannelInboxStore(tmp_path / 'inbox.db')
    channel._running = True
    channel._owner_once_generation = 'phrase-live-generation'
    channel._verified_bot_generation = channel._owner_once_generation
    channel._bot_id = 777
    seen = []

    async def fake_post(*args, **kwargs):
        return {'ok': True}

    async def capture_request(orch, *, principal, source):
        seen.append(source)
        return {'pending': 8}

    def forbidden(*args, **kwargs):
        pytest.fail('restart phrase reached pending input instead of command governance')

    pending = SimpleNamespace(bind=lambda *a, **kw: nullcontext(), intercept=forbidden,
                              command=forbidden)
    monkeypatch.setattr(hub.orch, '_pending_input_service', lambda: pending)
    monkeypatch.setattr(channel, '_post', fake_post)
    monkeypatch.setattr(hub_restart_apply, 'request_restart', capture_request)
    try:
        await channel._handle_update({'update_id': 1235, 'message': {
            'message_id': 18, 'from': {'id': OWNER_ID, 'is_bot': False},
            'chat': {'id': OWNER_ID, 'type': 'private'}, 'text': 'restart gateway'}})
        assert len(seen) == 1 and seen[0] is not None
        assert seen[0].candidate.text == 'restart gateway'
        assert seen[0].provider_id == 'telegram:777:1235'
        assert 'Restart approval card #8 queued' in hub.sent[-1][1]
    finally:
        await hub.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('original_text', ['/restart', 'Please restart the gateway!'])
async def test_real_phrase_ingress_signed_card_precedes_mocked_restart(tmp_path, monkeypatch, original_text):
    from agents.core import hub_restart_apply, settings_db
    from agents.core.channel_inbox import ChannelInboxStore
    from agents.core.kernel import authorize, revalidate
    from agents.core.kernel.binding import MediationKernelBridge
    from tests.test_h058_slash_access import OWNER_ID, _Hub
    from tests.test_h084_update_kernel import _rig

    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    monkeypatch.setattr(settings_db, '_wal_set', False)
    signed = _rig(tmp_path, monkeypatch)
    hub = _Hub(tmp_path)
    hub.orch.autonomy = signed.worker
    hub.orch.autonomy_queue = signed.queue
    channel = hub.channel
    hub.orch.channel_manager.channels = {'telegram': channel}
    gateway = channel.handler.__self__
    gateway.command_source_adapter = lambda: hub.orch.channels.get('telegram')
    gateway.inbox_store = ChannelInboxStore(tmp_path / 'inbox.db')
    hub.orch.sender_pairing = gateway.pairing

    async def no_history(*args, **kwargs):
        pytest.fail('fixed restart command read conversation history')

    monkeypatch.setattr(hub.orch, '_guard_foreign_turn', no_history)
    monkeypatch.setattr(hub.orch, '_guard_media_history', no_history)
    channel._running = True
    channel._owner_once_generation = 'signed-phrase-generation'
    channel._verified_bot_generation = channel._owner_once_generation
    channel._bot_id = 777

    def kernel(action, **kw):
        return authorize(action, policy=signed.worker.policy)

    kernel.revalidate = lambda action, capability=None, approval_check=None: revalidate(
        action, policy=signed.worker.policy, approval_check=approval_check)
    signed.worker._mediation_kernel = MediationKernelBridge(kernel)
    enqueue_errors = []
    govern = signed.worker.govern_enqueue

    def capture_govern(**kwargs):
        try:
            return govern(**kwargs)
        except Exception as exc:
            enqueue_errors.append((type(exc).__name__, str(exc)))
            raise

    monkeypatch.setattr(signed.worker, 'govern_enqueue', capture_govern)
    hub_restart_apply.hub_update.reset_for_tests()
    monkeypatch.setattr(hub_restart_apply.backup, 'boot_restore_due', lambda: False)
    monkeypatch.setattr(hub_restart_apply.backup, 'restore_in_progress', lambda: False)
    monkeypatch.setattr(hub_restart_apply.hub_update_apply, 'current', lambda: None)
    monkeypatch.setattr(hub_restart_apply.hub_restart, 'request',
                        lambda *_: pytest.fail('intake attempted a physical restart'))

    async def fake_post(*args, **kwargs):
        return {'ok': True}

    monkeypatch.setattr(channel, '_post', fake_post)
    try:
        await channel._handle_update({'update_id': 1236, 'message': {
            'message_id': 19, 'from': {'id': OWNER_ID, 'is_bot': False},
            'chat': {'id': OWNER_ID, 'type': 'private'}, 'text': original_text}})
        tasks = signed.queue.list()
        assert len(tasks) == 1, enqueue_errors
        task = tasks[0]
        assert task.kind == 'hub.restart' and task.status == 'blocked'
        assert task.mediation_receipt['verdict'] == 'queue'
        assert task.payload['source_ticket']['body']['version'] == 2
        assert task.payload['source_ticket']['body']['original_text'] == original_text
        assert task.origin == 'manual' and 'tainted' not in task.payload
        assert task.payload['requester']['provider_key'] == 'telegram:777:1236'
        assert task.attempts == 0
        await signed.worker.tick()
        assert signed.queue.get(task.id).attempts == 0
        assert 'Restart approval card #' in hub.sent[-1][1]

        from agents.core.autonomy import irreversible
        from agents.core.restart_runtime import runtime_for

        runtime = runtime_for(hub.orch)
        signed.worker._restart_runtime = runtime
        signed.executor._restart_runtime = runtime
        effects = []

        async def execute(task):
            return await irreversible.execute(task, orch=hub.orch)

        async def completed(task_id, digest):
            assert signed.queue.get(task_id).status == 'done'
            assert runtime.snapshot()['active'] == 0
            return await hub_restart_apply.after_completion(hub.orch, task_id, digest)

        def stop(_reason):
            assert signed.queue.get(task.id).status == 'done'
            assert runtime.snapshot()['active'] == 0
            effects.append('mocked stop')
            return True

        signed.executor.register('hub.restart', execute)
        signed.worker._restart_completed = completed
        monkeypatch.setattr(hub_restart_apply.hub_restart, 'request', stop)
        signed.worker.policy.mode = 'auto'
        await signed.worker.apply_decision(task.id, 'accept', decided_by='owner')
        assert effects == []
        await signed.worker.tick()
        assert effects == ['mocked stop']
        assert signed.queue.get(task.id).status == 'done'
        await signed.worker.tick()
        assert effects == ['mocked stop']
    finally:
        signed.queue.close()
        await hub.close()
        hub_restart_apply.hub_update.reset_for_tests()
