import json
from types import SimpleNamespace

import pytest

from agents.core.hermes_runtime.policy import HermesGate, RuntimeDenied, catalog, classify
from agents.core.kernel import Decision, Verdict


def test_catalog_contains_entire_pinned_protocol():
    value = catalog()
    assert len(value['methods']) == 251
    assert len(value['server_requests']) == 13
    assert len(value['notifications']) == 75
    assert value['source_sha'] == '0808ed8ec0420ef2c8e1363d919ef1d83fc4e5e7'
    assert classify('rpc', 'session.list') == 0
    assert classify('rpc', 'shell.exec') == 3
    with pytest.raises(RuntimeDenied):
        classify('rpc', 'future.effect')


@pytest.mark.parametrize('verdict', [Verdict.DENY, Verdict.QUEUE])
def test_gate_does_not_execute_non_grant(verdict, monkeypatch):
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    calls = []
    gate = HermesGate(kernel=lambda a, c: calls.append(a) or Decision(verdict, reason='blocked'))
    with pytest.raises(RuntimeDenied) as caught:
        gate.authorize('rpc', 'session.delete', {'risk_tier': 0, 'kind': 'read'}, 'g1')
    assert caught.value.verdict == verdict.value
    assert calls[0].payload['risk_tier'] >= 2
    assert calls[0].kind == 'hermes.runtime'


def test_live_gate_requires_kernel_and_capability(monkeypatch):
    monkeypatch.delenv('JARVIS_ACTION_KERNEL', raising=False)
    gate = HermesGate(orchestrator=lambda: SimpleNamespace())
    with pytest.raises(RuntimeDenied):
        gate.authorize('rpc', 'session.list', {}, 'g1')


def test_added_catalog_method_without_classification_fails_closed(tmp_path, monkeypatch):
    from agents.core.hermes_runtime import policy

    value = json.loads(policy.CATALOG_FILE.read_text())
    value['methods'].append({'name': 'future.effect'})
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps(value))
    monkeypatch.setattr(policy, 'CATALOG_FILE', path)
    with pytest.raises(RuntimeDenied, match='incomplete'):
        catalog()
