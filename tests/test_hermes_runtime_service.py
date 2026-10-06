import pytest

from agents.core.hermes_runtime.bridge import AuthorizationBridge, BrokerClient
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


def test_startup_bridge_denies_effects_until_approval_manager_exists():
    class GrantingGate:
        def __init__(self):
            self.calls = []

        def authorize(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return {"verdict": "grant", "tier": 0}

    gate = GrantingGate()
    service = HermesRuntimeService(gate=gate)
    bridge = AuthorizationBridge(service._bridge_authorize)
    service._bridge = bridge
    bridge.start()
    bridge.generation = "starting-generation"
    effects = []
    try:
        broker = BrokerClient(bridge.url, bridge.token, bridge.generation)
        answer = broker.run("tool", "read_file", {"path": "harmless"},
                            lambda: effects.append("ran"))
        assert answer["jarvis_verdict"] == "deny"
        assert effects == []
        assert gate.calls == []
    finally:
        bridge.stop()
