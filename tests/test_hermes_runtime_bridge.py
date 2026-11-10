import json

import httpx

from agents.core.hermes_runtime.bridge import AuthorizationBridge, BrokerClient, bounded_outcome


def test_native_outcome_is_bounded_json_and_scrubs_private_authority():
    assert bounded_outcome({"state": "result", "value": {
        "stdout": "credential in output", "api_key": "private",
        "nested": ["bridge-token"]}}, token="bridge-token") == {
        "state": "result", "value": {"stdout": "credential in output",
            "api_key": "[redacted]", "nested": ["[redacted]"]}}
    assert bounded_outcome({"state": "result", "value": {"text": "x" * 8192}}) == {"state": "unknown"}
    assert bounded_outcome({"state": "result", "value": float("nan")}) == {"state": "unknown"}
    assert bounded_outcome({"state": "error", "value": object()}) == {"state": "unknown"}


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


def test_worker_connector_guard_forwards_upstream_context(monkeypatch):
    """Upstream calls dispatch_connector_call(name, args, call_id, turn_id, task_id)."""
    import sys
    import types

    from agents.core.hermes_runtime import worker

    calls = []

    def original(name, arguments, tool_call_id, turn_id=None, task_id=None):
        calls.append((name, arguments, tool_call_id, turn_id, task_id))
        return 'ok'

    dispatch = types.SimpleNamespace(dispatch_connector_call=original)
    exports = types.ModuleType('tools.connectors')
    exports.dispatch = dispatch
    exports.dispatch_connector_call = original
    registry = types.SimpleNamespace(ToolRegistry=type('ToolRegistry', (), {'dispatch': lambda self, *a, **k: None}))
    server = types.SimpleNamespace(_methods={}, register_method=lambda name, handler: None)
    modules = {'tools': types.ModuleType('tools'), 'tools.connectors': exports,
               'tools.connectors.dispatch': dispatch, 'tools.registry': registry,
               'tui_gateway': types.SimpleNamespace(server=server), 'tui_gateway.server': server}
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    class Broker:
        def run(self, kind, name, args, call):
            assert kind == 'tool'
            return call()

    worker.install_guards(Broker())
    assert exports.dispatch_connector_call('gmail.send', {'to': 'x'}, 'call-1', 'turn-1', 'task-1') == 'ok'
    assert calls == [('gmail.send', {'to': 'x'}, 'call-1', 'turn-1', 'task-1')]
