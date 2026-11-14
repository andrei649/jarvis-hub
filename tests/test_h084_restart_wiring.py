"""The production factories share one hub admission gate."""
import pytest

from agents.core.restart_runtime import runtime_for


@pytest.mark.asyncio
async def test_coordinator_shares_executor_and_subagent_runtime(tmp_path, monkeypatch):
    from tests.test_h400_delegation import _Hub

    hub = _Hub(tmp_path, monkeypatch)
    runtime = runtime_for(hub.orch)
    assert hub.orch.task_executor._restart_runtime is runtime
    assert hub.manager._admission_runtime is runtime
    token = runtime.close_admission()
    try:
        result = await hub.manager.spawn('new work')
        assert result['reason'] == 'restart_draining'
        assert not hub.child_seen
    finally:
        runtime.reopen(token)


@pytest.mark.asyncio
async def test_real_telegram_orchestrator_registry_preserves_original_source(tmp_path, monkeypatch):
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
    inbox = ChannelInboxStore(tmp_path / 'inbox.db')
    gateway.inbox_store = inbox
    channel._running = True
    channel._owner_once_generation = 'test-live-generation'
    channel._verified_bot_generation = channel._owner_once_generation
    channel._bot_id = 777
    seen = []

    async def fake_post(*args, **kwargs):
        return {'ok': True}

    monkeypatch.setattr(channel, '_post', fake_post)
    async def capture_request(orch, *, principal, source):
        seen.append(source)
        return {"pending": 7}

    monkeypatch.setattr(hub_restart_apply, 'request_restart', capture_request)
    try:
        await channel._handle_update({'update_id': 1234, 'message': {
            'message_id': 17, 'from': {'id': OWNER_ID, 'is_bot': False},
            'chat': {'id': OWNER_ID, 'type': 'private'}, 'text': '/restart'}})
        assert len(seen) == 1 and seen[0] is not None
        source = seen[0]
        assert source.provider_id == 'telegram:777:1234'
        assert source.sender_id == source.chat_id == OWNER_ID
        assert source.inbox_id
        assert 'Restart approval card #7 queued' in hub.sent[-1][1]
    finally:
        await hub.close()
