"""Owner selected metadata uses a live signed record, vault HWM and real Kernel."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.kernel import Verdict
from agents.core.llm import provider_selection
from agents.core.llm.providers.packages import ProviderPackageError
from tests.test_h361_provider_credentials import active
from tests.test_h361_provider_install_kernel import _bind_real_kernel
from tests.test_h361_provider_install_routes import HEADERS, client
from tests.test_h361_provider_install_service import owner, service


@pytest.fixture
def selected_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, 'DB_PATH', tmp_path / 'settings.db')
    monkeypatch.setattr(settings_db, '_initialized', False)
    settings_db.init_db(force=True)
    return settings_db.DB_PATH


def test_real_owner_selection_cas_consent_receipt_and_clear(service, tmp_path, selected_store):
    svc, _, _, seen, events, artifact = active(service, tmp_path)
    key = 'synthetic-selected-key'
    svc.put_credential('synthetic-addon', artifact['package_hash'], key, actor=owner())
    before = provider_selection.current_revision()
    with pytest.raises(ProviderPackageError):
        svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
                            expected_revision=before, actor=owner())
    chosen = svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
        expected_revision=before, acknowledge_unknown_price=True,
        acknowledge_data_policy=True, actor=owner())
    assert chosen == {'provider': 'synthetic-addon', 'model': 'synthetic-model',
                      'package_hash': artifact['package_hash'], 'revision': before + 1,
                      'credential_generation': 1, 'status': 'selected'}
    saved = provider_selection.read_selection()
    assert saved.revision == before + 1
    assert saved.binding.artifact_id == artifact['artifact_id']
    assert saved.binding.endpoint == 'https://synthetic.invalid/v1'
    assert saved.binding.credential_generation == 1
    assert key not in str(saved) + str(chosen) + str(events) + str(seen)
    assert any(action.kind == 'provider.selection' and decision.verdict is Verdict.GRANT
               for action, decision in seen)
    with pytest.raises(provider_selection.SelectionConflict):
        svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
            expected_revision=before, acknowledge_unknown_price=True,
            acknowledge_data_policy=True, actor=owner())
    cleared = svc.clear_selection(expected_revision=before + 1, actor=owner())
    assert cleared == {'status': 'cleared', 'revision': before + 2}
    assert provider_selection.read_selection() is None
    # The B1 CAS is a storage primitive, not owner consent. An unacknowledged
    # record stays inert even if an internal caller writes well-formed bytes.
    provider_selection.compare_and_swap(
        selected_store, replace(saved.binding, unknown_price_ack=False),
        expected_revision=cleared['revision'])
    with pytest.raises(ProviderPackageError, match='risk consent'):
        svc.selected_runtime()


@pytest.mark.parametrize('model', ['unknown-model', 'gpt-4o'])
def test_unsigned_model_cannot_borrow_builtin_price_or_policy(
        service, tmp_path, selected_store, model):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-model-test-key', actor=owner())
    before = provider_selection.current_revision()
    with pytest.raises(ProviderPackageError):
        svc.select_provider('synthetic-addon', artifact['package_hash'], model,
                            expected_revision=before, acknowledge_unknown_price=True,
                            acknowledge_data_policy=True, actor=owner())
    assert provider_selection.read_selection() is None


def test_owner_route_no_echo_and_strict_body(client, service, tmp_path, selected_store):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-api-key-not-echoed', actor=owner())
    path = '/api/admin/llm/provider-selection'
    assert client.get(path).status_code == 401
    before = client.get(path, headers=HEADERS)
    assert before.status_code == 200 and before.json() == {'status': 'unselected'}
    body = {'provider': 'synthetic-addon', 'package_hash': artifact['package_hash'],
            'model': 'synthetic-model', 'expected_revision': provider_selection.current_revision(),
            'acknowledge_unknown_price': True, 'acknowledge_data_policy': True}
    invalid = client.put(path, headers=HEADERS,
                         json={**body, 'unknown': 'synthetic-api-key-not-echoed'})
    assert invalid.status_code == 422 and 'synthetic-api-key-not-echoed' not in invalid.text
    selected = client.put(path, headers=HEADERS, json=body)
    assert selected.status_code == 200
    assert selected.json()['revision'] == body['expected_revision'] + 1
    status = client.get(path, headers=HEADERS)
    assert status.status_code == 200 and status.json() == selected.json()
    clear = client.request('DELETE', path, headers=HEADERS,
                           json={'expected_revision': selected.json()['revision']})
    assert clear.status_code == 200 and clear.json()['status'] == 'cleared'
    for response in (before, invalid, selected, status, clear):
        assert 'no-store' in response.headers.get('cache-control', '')
        assert 'synthetic-api-key-not-echoed' not in response.text


@pytest.mark.asyncio
async def test_router_refreshes_owner_choice_without_network_detection(
        service, tmp_path, selected_store, monkeypatch):
    from agents.core.llm import data_handling
    from agents.core.llm.hybrid_router import HybridRouter, LocalBackendUnavailableError

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-router-key', actor=owner())
    router = HybridRouter()

    class Builtin:
        async def aclose(self):
            pass

    baseline = Builtin()
    router._compatible_backend = baseline
    router._compatible_model = 'builtin-model'
    router._compatible_provider_id = 'openrouter'
    router._cloud_available = False
    local = Builtin()
    monkeypatch.setattr(router, '_select_backend_inner',
                        lambda agent, _prompt: (local, 'local-model', 'local') if agent == 'frigga'
                        else (baseline, 'builtin-model', 'cloud'))
    monkeypatch.setattr(router, '_enforce_approved_models', lambda *_args: None)
    chosen = svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
        expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    with pytest.raises(LocalBackendUnavailableError):
        router.preview_backend('athena', 'hello')
    await router.refresh_selected(svc)
    assert router._cloud_available is True
    backend, model, route = router.preview_backend('athena', 'hello')
    assert backend is router._selected_provider_runtime.backend
    assert model == 'synthetic-model' and route == 'cloud-compatible'
    assert router.preview_backend('frigga', 'hello')[0] is local
    monkeypatch.setattr(data_handling, '_scope_key', lambda: b'selected-scope-test-key')
    selected_policy = data_handling.posture(router)['providers'][0]
    assert selected_policy['provider'] == 'synthetic-addon'
    assert selected_policy['acknowledged'] is True
    assert selected_policy['can_acknowledge'] is False
    assert 'synthetic-router-key' not in str(selected_policy)
    svc.clear_selection(expected_revision=chosen['revision'], actor=owner())
    with pytest.raises(LocalBackendUnavailableError):
        router.preview_backend('athena', 'hello')
    await router.refresh_selected(svc)
    assert router._cloud_available is False
    assert router.preview_backend('athena', 'hello') == (
        baseline, 'builtin-model', 'cloud-compatible')
    await router.aclose()


def test_signed_guard_uses_exact_profile_and_unknown_price_ack(
        service, tmp_path, selected_store, monkeypatch):
    from agents.core import app_state
    from agents.core.llm import cost_estimator, selection_guards
    from agents.core.llm.providers import install_service

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'], 'synthetic-key', actor=owner())
    svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
        expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    runtime = svc.selected_runtime()
    monkeypatch.setattr(app_state, 'get_orch', lambda: SimpleNamespace(
        llm_router=SimpleNamespace(_selected_provider_runtime=runtime)))
    monkeypatch.setattr(install_service, 'get_install_service', lambda _orch: svc)
    monkeypatch.setitem(cost_estimator.MODELS, 'synthetic-model',
                        {'input': 100.0, 'output': 100.0})
    choice = selection_guards.Choice('job.model', 'synthetic-addon', 'synthetic-model')
    assert selection_guards.cost_guard(choice) is None
    (exact,) = selection_guards._profiles_for('synthetic-addon')
    assert exact.id == 'synthetic-addon'
    assert exact._package_hash == artifact['package_hash']


def test_owner_selection_runs_registered_guard_once_before_cas(
        service, tmp_path, selected_store, monkeypatch):
    from agents.core.llm import selection_guards as sg

    svc, _, _, seen, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-registry-key', actor=owner())
    observed = []

    def extra(choice):
        observed.append(choice)
        return sg.Finding('synthetic_review_guard', 'uncleared_guard', choice,
                          'registered review required')

    monkeypatch.setattr(sg, 'GUARDS', [*sg.GUARDS, extra])
    before = provider_selection.current_revision()
    with pytest.raises(sg.SelectionRefused) as refused:
        svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
            expected_revision=before, acknowledge_unknown_price=True,
            acknowledge_data_policy=True, actor=owner())
    assert refused.value.missing == ['uncleared_guard']
    assert len(observed) == 1
    assert observed[0] == sg.Choice('provider.selection', 'synthetic-addon', 'synthetic-model')
    assert provider_selection.current_revision() == before
    assert provider_selection.read_selection() is None
    assert not [action for action, _decision in seen if action.kind == 'provider.selection']


def test_owner_selection_guard_exception_keeps_revision_and_binding(
        service, tmp_path, selected_store, monkeypatch):
    from agents.core.llm import selection_guards as sg

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-registry-key', actor=owner())
    calls = []

    def broken(choice):
        calls.append(choice)
        raise RuntimeError('synthetic secret in guard failure')

    monkeypatch.setattr(sg, 'GUARDS', [*sg.GUARDS, broken])
    before = provider_selection.current_revision()
    with pytest.raises(ProviderPackageError, match='guard unavailable') as refused:
        svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
            expected_revision=before, acknowledge_unknown_price=True,
            acknowledge_data_policy=True, actor=owner())
    assert 'synthetic secret' not in str(refused.value)
    assert len(calls) == 1
    assert provider_selection.current_revision() == before
    assert provider_selection.read_selection() is None


def _active_with_signed_policy(service, tmp_path, *, provider_id='synthetic-addon',
                               model='synthetic-model', policy='no-training'):
    svc, profile, hooks, _ = service
    svc, _, _, _ = _bind_real_kernel(service, tmp_path)
    events = []
    svc.audit = SimpleNamespace(log=events.append)
    if provider_id != profile.id:
        source = svc.incoming('user') / 'addon'
        (source / 'provider.json').write_text(json.dumps(
            {'schema_version': 1, 'id': provider_id, 'aliases': [],
             'replacement_target': provider_id}))
        script = source / 'main.py'
        script.write_text(script.read_text().replace(profile.id, provider_id))
    profile = replace(profile, id=provider_id, auth_type='bearer',
                      fallback_models=(model,), data_policy=policy)
    artifact = svc.stage('addon', profile=profile, hooks=hooks, source='user',
                         replacement_target=provider_id if provider_id == 'openrouter' else None,
                         actor=owner())
    offer = svc.propose(artifact['artifact_id'], actor=owner())
    svc.decide(offer['proposal_id'], artifact_id=artifact['artifact_id'],
               package_hash=artifact['package_hash'], approved=True, permanent=True,
               actor=owner())
    svc.promote(offer['proposal_id'], actor=owner())
    svc.put_credential(provider_id, artifact['package_hash'], 'synthetic-policy-key', actor=owner())
    return svc, artifact, events


def test_signed_owner_choice_uses_candidate_policy_and_never_builtin_collision(
        service, tmp_path, selected_store, monkeypatch):
    from agents.core.llm import selection_guards as sg

    model = 'anthropic/claude-fable-5:free'
    svc, artifact, _ = _active_with_signed_policy(
        service, tmp_path, provider_id='openrouter', model=model)
    seen = []

    def inspect(choice):
        seen.append((sg._current_signed_choice(choice),
                     sg._profiles_for(choice.provider, choice.model)[0].data_policy))

    def no_stale_lookup():
        raise AssertionError('stale selection lookup')

    monkeypatch.setattr(sg, '_selected_service_record', no_stale_lookup)
    monkeypatch.setattr(sg, 'GUARDS', [*sg.GUARDS, inspect])
    before = provider_selection.current_revision()
    chosen = svc.select_provider('openrouter', artifact['package_hash'], model,
        expected_revision=before, acknowledge_unknown_price=True,
        acknowledge_data_policy=False, actor=owner())
    assert chosen['revision'] == before + 1
    assert seen == [(True, 'no-training')]
    assert provider_selection.read_selection().binding.data_policy_ack is False


def test_signed_training_guard_requires_audit_and_fails_closed(
        service, tmp_path, selected_store):
    svc, artifact, events = _active_with_signed_policy(
        service, tmp_path, policy='trains-on-inputs')
    before = provider_selection.current_revision()
    with pytest.raises(ProviderPackageError, match='risk acknowledgement'):
        svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
            expected_revision=before, acknowledge_unknown_price=True, actor=owner())
    assert provider_selection.current_revision() == before
    original = svc.audit.log

    def fail_guard_audit(event):
        if event.action_taken == 'model_training_consent':
            raise OSError('synthetic audit failure')
        original(event)

    svc.audit = SimpleNamespace(log=fail_guard_audit)
    with pytest.raises(ProviderPackageError, match='guard consent audit unavailable'):
        svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
            expected_revision=before, acknowledge_unknown_price=True,
            acknowledge_data_policy=True, actor=owner())
    assert provider_selection.current_revision() == before
    assert provider_selection.read_selection() is None
    svc.audit = SimpleNamespace(log=events.append)
    chosen = svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
        expected_revision=before, acknowledge_unknown_price=True,
        acknowledge_data_policy=True, actor=owner())
    assert chosen['revision'] == before + 1
    assert [event.action_taken for event in events].count('model_training_consent') == 1
    assert [event.action_taken for event in events].count(
        'provider_selection_unknown_price_acknowledged') == 2
    assert [event.action_taken for event in events].count(
        'provider_selection_data_policy_acknowledged') == 2


def test_registered_guard_denial_preserves_existing_signed_binding(
        service, tmp_path, selected_store, monkeypatch):
    from agents.core.llm import selection_guards as sg

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-registry-key', actor=owner())
    saved = svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
        expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    before = provider_selection.read_selection()

    def blocking(choice):
        return sg.Finding('extra_review', 'unprovided_flag', choice, 'extra review')

    monkeypatch.setattr(sg, 'GUARDS', [*sg.GUARDS, blocking])
    with pytest.raises(sg.SelectionRefused):
        svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
            expected_revision=saved['revision'], acknowledge_unknown_price=True,
            acknowledge_data_policy=True, actor=owner())
    assert provider_selection.read_selection() == before
    assert provider_selection.current_revision() == saved['revision']


def test_owner_route_reports_bounded_guard_requirement_without_message_echo(
        client, service, tmp_path, selected_store, monkeypatch):
    from agents.core.llm import selection_guards as sg

    svc, _, _, _, _, artifact = active(service, tmp_path)
    secret = 'synthetic-guard-secret-not-echoed'
    svc.put_credential('synthetic-addon', artifact['package_hash'], secret, actor=owner())

    def extra(choice):
        return sg.Finding('private-guard', secret, choice, secret)

    monkeypatch.setattr(sg, 'GUARDS', [*sg.GUARDS, extra])
    before = provider_selection.current_revision()
    response = client.put('/api/admin/llm/provider-selection', headers=HEADERS,
        json={'provider': 'synthetic-addon', 'package_hash': artifact['package_hash'],
              'model': 'synthetic-model', 'expected_revision': before,
              'acknowledge_unknown_price': True, 'acknowledge_data_policy': True})
    assert response.status_code == 409
    assert response.json() == {'error': 'selection_guard', 'needs': ['additional_guard']}
    assert secret not in response.text
    assert provider_selection.current_revision() == before
    assert provider_selection.read_selection() is None
