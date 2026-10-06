import json

import httpx

from agents.core.hermes_runtime.bridge import AuthorizationBridge, BrokerClient


def test_bridge_auth_generation_and_replay():
    calls = []
    bridge = AuthorizationBridge(lambda frame: calls.append(frame) or {'verdict': 'grant'})
    bridge.start()
    try:
        bridge.generation = 'g1'
        frame = {'generation': 'g1', 'nonce': 'n1', 'kind': 'rpc', 'target': 'ping', 'args': {}}
        headers = {'X-Jarvis-Bridge-Token': bridge.token}
        assert httpx.post(bridge.url, json=frame, trust_env=False).status_code == 403
        assert httpx.post(bridge.url, headers=headers, json={**frame, 'generation': 'old'}, trust_env=False).status_code == 403
        assert httpx.post(bridge.url, headers=headers, json=frame, trust_env=False).json()['verdict'] == 'grant'
        assert httpx.post(bridge.url, headers=headers, json=frame, trust_env=False).status_code == 403
        assert len(calls) == 1
    finally:
        bridge.stop()


def test_broker_failure_never_runs_effect():
    broker = BrokerClient('http://127.0.0.1:1/authorize', 'token', 'generation')
    effect = []
    result = broker.run('tool', 'terminal', {'command': 'echo hello'}, lambda: effect.append(True))
    assert not effect
    assert 'error' in result
    assert 'unavailable' in json.dumps(result)
