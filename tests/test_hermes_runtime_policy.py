import json
from types import SimpleNamespace

import pytest

from agents.core.hermes_runtime.policy import HermesGate, RuntimeDenied, catalog, classify
from agents.core.kernel import Decision, Verdict


def test_catalog_contains_entire_pinned_protocol():
    value = catalog()
    assert len(value['methods']) == 262
    assert len(value['server_requests']) == 16
    assert len(value['notifications']) == 78
    assert value['source_sha'] == '9c0560f8e6856bc14c11bfe6d666df06be14d2de'
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


# Reviewed for the 9c0560f8 pin (docs/hermes/RUNTIME_INTEGRATION.md, "Pin 9c0560f8").
NEW_AT_9C0560F8 = {
    'billing.keep_going_on_credits': 3, 'connectors.accounts.rename': 3, 'free_tier.challenge_result': 3,
    'free_tier.claim_nudge': 3, 'groups.attachment.download': 3, 'groups.attachment.upload': 3,
    'groups.context': 3, 'groups.continue': 3, 'groups.discard': 3, 'image.render': 3,
    'machine.facts': 0, 'onboarding.set_run': 3, 'onboarding.skip': 3, 'onboarding.start': 3,
    'onboarding.state': 3, 'plugins.catalog.lookup': 3, 'subagent.roster': 0, 'vault.preview.fill': 3,
}


def test_methods_new_at_this_pin_carry_their_reviewed_tier():
    assert {name: classify('rpc', name) for name in NEW_AT_9C0560F8} == NEW_AT_9C0560F8
    tiers = [method['risk_tier'] for method in catalog()['methods']]
    assert (tiers.count(0), tiers.count(2), tiers.count(3)) == (87, 15, 160)
    for removed in ('browser.controller.register', 'onboarding.ensure_setup_profile', 'profiles.remember_onboarding'):
        with pytest.raises(RuntimeDenied):
            classify('rpc', removed)


def test_every_pin_anchor_names_the_same_commit():
    from pathlib import Path

    from agents.core.hermes_runtime import distribution, worker

    root = Path(distribution.__file__).resolve().parents[3]
    commit = distribution.load_pin()['commit']
    policy_file = json.loads((root / 'runtime/hermes/rpc-policy.json').read_text())
    assert commit == distribution.PINNED_COMMIT == worker.SOURCE_SHA == catalog()['source_sha'] == policy_file['source_sha']
    assert f'Commit: {commit}' in (root / 'runtime/hermes/NOTICE.md').read_text()
