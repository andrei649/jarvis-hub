import pytest

from agents.core.hermes_runtime.service import HermesRuntimeService, RuntimeUnavailable


@pytest.mark.asyncio
async def test_disabled_runtime_never_starts_or_dispatches(monkeypatch):
    monkeypatch.delenv('JARVIS_HERMES_ENABLED', raising=False)
    service = HermesRuntimeService()
    assert not (await service.status())['enabled']
    with pytest.raises(RuntimeUnavailable):
        await service.start()
    with pytest.raises(RuntimeUnavailable):
        await service.rpc('session.create', {})


@pytest.mark.asyncio
async def test_unmatched_server_reply_rejected():
    service = HermesRuntimeService()
    with pytest.raises(RuntimeUnavailable):
        await service.reply({'id': 'forged', 'result': {}})
