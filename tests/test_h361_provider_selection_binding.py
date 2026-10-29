"""Owner selected metadata uses a live signed record, vault HWM and real Kernel."""
import asyncio
import hashlib
import hmac
import json
import multiprocessing as mp
import os
import sqlite3
import stat
import threading
from dataclasses import asdict, replace
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
    assert not (svc.root / 'selection-consent.key').exists()
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


def test_true_flag_raw_cas_without_owner_proof_cannot_construct_runtime(
        service, tmp_path, selected_store):
    from agents.core.llm.providers.credentials import credential_binding

    svc, _, _, seen, events, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-unproved-key', actor=owner())
    store = svc._store()
    record = store.require_runnable('synthetic-addon',
                                    expected_hash=artifact['package_hash'], home=svc.home)
    scope = credential_binding(record, svc.home)
    before_actions = len([action for action, _ in seen if action.kind == 'provider.selection'])
    before_events = len([event for event in events if event.action_taken.startswith('provider_selection_')])
    binding = provider_selection.SelectionBinding(
        'local-owner-v1', svc.home, record.provider_id, 'synthetic-model',
        record.source, record.artifact_id, record.package_hash, scope.endpoint,
        scope.auth_type, svc._credentials().status(scope)['generation'],
        unknown_price_ack=True, data_policy_ack=True)
    saved = provider_selection.compare_and_swap(
        selected_store, binding, expected_revision=provider_selection.current_revision())
    assert saved.binding.unknown_price_ack and saved.binding.data_policy_ack
    assert len([action for action, _ in seen if action.kind == 'provider.selection']) == before_actions
    assert len([event for event in events if event.action_taken.startswith('provider_selection_')]) == before_events
    with pytest.raises(ProviderPackageError, match='consent proof'):
        svc.selected_runtime()
    assert svc.selection_status(actor=owner())['status'] == 'stale'


def test_direct_mint_without_owner_decision_cannot_make_true_flag_cas_authoritative(
        service, tmp_path, selected_store):
    from agents.core.llm.providers.credentials import credential_binding
    from agents.core.llm.providers.selection_consent import mint

    svc, _, _, seen, events, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-direct-mint-key', actor=owner())
    record = svc._store().require_runnable('synthetic-addon',
        expected_hash=artifact['package_hash'], home=svc.home)
    scope = credential_binding(record, svc.home)
    binding = provider_selection.SelectionBinding(
        'local-owner-v1', svc.home, record.provider_id, 'synthetic-model',
        record.source, record.artifact_id, record.package_hash, scope.endpoint,
        scope.auth_type, svc._credentials().status(scope)['generation'],
        unknown_price_ack=True, data_policy_ack=True)
    revision = provider_selection.current_revision()
    policy = record.profile.data_policy_for(binding.model)[0]
    with pytest.raises(ProviderPackageError, match='mint capability'):
        mint(svc.root, binding, revision + 1, record.profile, policy)
    assert not (svc.root / 'selection-consent.key').exists()
    assert provider_selection.read_selection() is None
    assert provider_selection.current_revision() == revision
    assert not [action for action, _ in seen if action.kind == 'provider.selection']
    assert not [event for event in events if event.action_taken.startswith('provider_selection_')]


def test_owner_mint_capability_is_one_use_and_revision_bound(
        service, tmp_path, selected_store, monkeypatch):
    from agents.core.llm.providers import selection_consent

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-capability-key', actor=owner())
    minted = []
    real_mint = selection_consent.mint

    def capture_mint(root, binding, revision, profile, policy, *, capability=None):
        minted.append((root, binding, revision, profile, policy, capability))
        return real_mint(root, binding, revision, profile, policy,
                         capability=capability)

    monkeypatch.setattr(selection_consent, 'mint', capture_mint)
    selected = svc.select_provider('synthetic-addon', artifact['package_hash'],
        'synthetic-model', expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    assert len(minted) == 1
    root, binding, revision, profile, policy, capability = minted[0]
    with pytest.raises(ProviderPackageError, match='mint capability'):
        real_mint(root, binding, revision, profile, policy, capability=capability)
    assert provider_selection.current_revision() == selected['revision']
    assert svc.selected_runtime().selection.revision == selected['revision']


@pytest.mark.parametrize('change', ['revision', 'binding', 'policy'])
def test_wrong_scope_consumes_capability_without_key_or_selection(
        service, tmp_path, selected_store, monkeypatch, change):
    from agents.core.llm.providers import selection_consent

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-capability-key', actor=owner())
    before = provider_selection.current_revision()
    real_mint = selection_consent.mint

    def wrong_scope(root, binding, revision, profile, policy, *, capability=None):
        wrong_binding = replace(binding, home='other-owner-home') if change == 'binding' else binding
        wrong_revision = revision + 1 if change == 'revision' else revision
        wrong_policy = 'trains-on-inputs' if change == 'policy' else policy
        with pytest.raises(ProviderPackageError):
            real_mint(root, wrong_binding, wrong_revision, profile, wrong_policy,
                      capability=capability)
        return real_mint(root, binding, revision, profile, policy,
                         capability=capability)

    monkeypatch.setattr(selection_consent, 'mint', wrong_scope)
    with pytest.raises(ProviderPackageError, match='mint capability'):
        svc.select_provider('synthetic-addon', artifact['package_hash'],
            'synthetic-model', expected_revision=before,
            acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    assert provider_selection.current_revision() == before
    assert provider_selection.read_selection() is None
    assert not (svc.root / 'selection-consent.key').exists()


def test_owner_expiry_after_audit_refuses_capability_mint(
        service, tmp_path, selected_store, monkeypatch):
    from agents.core.llm.providers import selection_consent

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-capability-key', actor=owner())
    before = provider_selection.current_revision()
    live = [True]
    actor = owner(lambda: live[0])
    real_mint = selection_consent.mint

    def expired_mint(*args, **kwargs):
        live[0] = False
        return real_mint(*args, **kwargs)

    monkeypatch.setattr(selection_consent, 'mint', expired_mint)
    with pytest.raises(ProviderPackageError, match='mint capability'):
        svc.select_provider('synthetic-addon', artifact['package_hash'],
            'synthetic-model', expected_revision=before,
            acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=actor)
    assert provider_selection.current_revision() == before
    assert provider_selection.read_selection() is None


def test_capability_cannot_issue_during_guard_audit_callback(
        service, tmp_path, selected_store, monkeypatch):
    from agents.core.kernel import Decision
    from agents.core.llm import selection_guards as sg
    from agents.core.llm.providers import install_service, selection_consent

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-capability-key', actor=owner())
    record = svc._store().require_runnable('synthetic-addon',
        expected_hash=artifact['package_hash'], home=svc.home)
    real_record = sg.record
    checked = []

    def before_audit_returns(findings, surface, audit_log):
        service_ref, action, actor, _thread = install_service._SELECTION_RECEIPT.get()
        payload = action.payload
        binding = provider_selection.SelectionBinding(
            payload['authority'], payload['home'], payload['provider_id'],
            payload['model'], payload['source'], payload['artifact_id'],
            payload['package_hash'], payload['endpoint'], payload['auth_type'],
            payload['credential_generation'], unknown_price_ack=True,
            data_policy_ack=payload['data_ack'])
        with pytest.raises(ProviderPackageError, match='mint capability'):
            selection_consent._issue(
                service_ref, actor, action, Decision(Verdict.GRANT, tier=3),
                binding, payload['selected_revision'], record.profile,
                record.profile.data_policy_for(binding.model)[0])
        checked.append(True)
        return real_record(findings, surface, audit_log)

    monkeypatch.setattr(sg, 'record', before_audit_returns)
    chosen = svc.select_provider('synthetic-addon', artifact['package_hash'],
        'synthetic-model', expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    assert checked == [True]
    assert svc.selected_runtime().selection.revision == chosen['revision']


def test_guard_audit_failure_never_issues_mint_capability(
        service, tmp_path, selected_store, monkeypatch):
    from agents.core.llm import selection_guards as sg

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-capability-key', actor=owner())
    before = provider_selection.current_revision()

    def failed_guard_audit(*_args):
        raise OSError('synthetic selection guard audit failure')

    monkeypatch.setattr(sg, 'record', failed_guard_audit)
    with pytest.raises(ProviderPackageError, match='selection guard consent audit unavailable'):
        svc.select_provider('synthetic-addon', artifact['package_hash'],
            'synthetic-model', expected_revision=before,
            acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    assert provider_selection.current_revision() == before
    assert provider_selection.read_selection() is None
    assert not (svc.root / 'selection-consent.key').exists()


@pytest.mark.parametrize('operation', ['clear', 'reselect'])
def test_legacy_true_flag_row_stays_inert_but_owner_can_recover(
        service, tmp_path, selected_store, operation):
    from agents.core.llm.providers.credentials import credential_binding

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-legacy-key', actor=owner())
    record = svc._store().require_runnable('synthetic-addon',
        expected_hash=artifact['package_hash'], home=svc.home)
    scope = credential_binding(record, svc.home)
    binding = provider_selection.SelectionBinding(
        'local-owner-v1', svc.home, record.provider_id, 'synthetic-model',
        record.source, record.artifact_id, record.package_hash, scope.endpoint,
        scope.auth_type, svc._credentials().status(scope)['generation'],
        unknown_price_ack=True, data_policy_ack=True)
    old = provider_selection.compare_and_swap(
        selected_store, binding, expected_revision=provider_selection.current_revision())
    fields = asdict(binding)
    fields.pop('consent_proof')
    payload = json.dumps(fields, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    with sqlite3.connect(selected_store) as conn:
        conn.execute('UPDATE signed_provider_selection SET record_json=?,record_hash=? '
                     'WHERE singleton=1',
                     (payload, provider_selection._digest(old.revision, payload)))
    assert provider_selection.read_selection().binding.consent_proof == ''
    assert svc.selection_status(actor=owner())['status'] == 'stale'
    if operation == 'clear':
        result = svc.clear_selection(expected_revision=old.revision, actor=owner())
        assert result['revision'] == old.revision + 1
        assert provider_selection.read_selection() is None
    else:
        result = svc.select_provider('synthetic-addon', artifact['package_hash'],
            'synthetic-model', expected_revision=old.revision,
            acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
        assert result['revision'] == old.revision + 1
        assert svc.selected_runtime().selection.binding.consent_proof


def test_owner_consent_proof_survives_restart_and_replay_fails(
        service, tmp_path, selected_store):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-proven-key', actor=owner())
    chosen = svc.select_provider('synthetic-addon', artifact['package_hash'],
        'synthetic-model', expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    saved = provider_selection.read_selection()
    assert len(saved.binding.consent_proof) == 64
    resumed = type(svc)(root=svc.root, signing=svc.signing, profile=svc.profile,
                        kernel=svc.kernel, enabled=svc.enabled, home=svc.home,
                        runner=svc.runner, audit=svc.audit)
    assert resumed.selected_runtime().selection == saved
    replayed = provider_selection.compare_and_swap(
        selected_store, saved.binding, expected_revision=chosen['revision'])
    assert replayed.revision == chosen['revision'] + 1
    with pytest.raises(ProviderPackageError, match='consent proof'):
        resumed.selected_runtime()


def test_clear_and_owner_reselect_mints_new_revision_proof(
        service, tmp_path, selected_store):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-proven-key', actor=owner())
    first = svc.select_provider('synthetic-addon', artifact['package_hash'],
        'synthetic-model', expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    old_binding = provider_selection.read_selection().binding
    cleared = svc.clear_selection(expected_revision=first['revision'], actor=owner())
    assert provider_selection.read_selection() is None
    replay = provider_selection.compare_and_swap(
        selected_store, old_binding, expected_revision=cleared['revision'])
    with pytest.raises(ProviderPackageError, match='consent proof'):
        svc.selected_runtime()
    second = svc.select_provider('synthetic-addon', artifact['package_hash'],
        'synthetic-model', expected_revision=replay.revision,
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    assert second['revision'] == replay.revision + 1
    assert provider_selection.read_selection().binding.consent_proof != old_binding.consent_proof
    assert svc.selected_runtime().selection.revision == second['revision']


@pytest.mark.parametrize(('field', 'value'), [
    ('home', 'other-owner-home'),
    ('provider_id', 'other-addon'),
    ('source', 'legacy'),
    ('artifact_id', 'f' * 32),
    ('package_hash', '0' * 64),
    ('endpoint', 'https://other.invalid/v1'),
    ('auth_type', 'api-key'),
    ('model', 'other-model'),
    ('credential_generation', 2),
    ('unknown_price_ack', False),
    ('data_policy_ack', False),
])
def test_owner_proof_binds_each_signed_scope_field(
        service, tmp_path, selected_store, field, value):
    from agents.core.llm.providers.selection_consent import verify

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-proven-key', actor=owner())
    svc.select_provider('synthetic-addon', artifact['package_hash'],
        'synthetic-model', expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    saved = provider_selection.read_selection()
    record = svc._store().require_runnable('synthetic-addon',
        expected_hash=artifact['package_hash'], home=svc.home)
    policy = record.profile.data_policy_for('synthetic-model')[0]
    assert verify(svc.root, saved, record.profile, policy)
    changed = provider_selection.SelectionRecord(
        saved.revision, replace(saved.binding, **{field: value}))
    assert not verify(svc.root, changed, record.profile, policy)
    assert not verify(svc.root, saved, replace(record.profile, data_policy='trains-on-inputs'),
                      'trains-on-inputs')


def test_signed_revocation_refuses_even_with_durable_consent_proof(
        service, tmp_path, selected_store):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-proven-key', actor=owner())
    svc.select_provider('synthetic-addon', artifact['package_hash'],
        'synthetic-model', expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    runtime = svc.selected_runtime()
    svc.revoke('synthetic-addon', actor=owner())
    with pytest.raises(ProviderPackageError):
        runtime.check()


def test_tampered_or_unavailable_owner_consent_proof_refuses(
        service, tmp_path, selected_store):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-proven-key', actor=owner())
    svc.select_provider('synthetic-addon', artifact['package_hash'],
        'synthetic-model', expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    saved = provider_selection.read_selection()
    key_path = svc.root / 'selection-consent.key'
    assert key_path.is_file()
    key_path.rename(svc.root / 'selection-consent.key.saved')
    with pytest.raises(ProviderPackageError, match='consent proof'):
        svc.selected_runtime()
    (svc.root / 'selection-consent.key.saved').rename(key_path)
    assert svc.selected_runtime().selection == saved
    provider_selection.compare_and_swap(
        selected_store, replace(saved.binding, consent_proof='0' * 64),
        expected_revision=saved.revision)
    with pytest.raises(ProviderPackageError, match='consent proof'):
        svc.selected_runtime()


def test_malformed_or_unsafe_consent_key_fails_closed(
        service, tmp_path, selected_store):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-proven-key', actor=owner())
    svc.select_provider('synthetic-addon', artifact['package_hash'],
        'synthetic-model', expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    key_path = svc.root / 'selection-consent.key'
    key_path.chmod(0o644)
    with pytest.raises(ProviderPackageError, match='consent proof'):
        svc.selected_runtime()
    key_path.chmod(0o600)
    saved = key_path.with_suffix('.saved')
    key_path.rename(saved)
    key_path.symlink_to(saved)
    with pytest.raises(ProviderPackageError, match='consent proof'):
        svc.selected_runtime()
    key_path.unlink()
    saved.rename(key_path)
    assert svc.selected_runtime().selection == provider_selection.read_selection()
    key_path.write_bytes(b'x' * 32)
    with pytest.raises(ProviderPackageError, match='consent proof'):
        svc.selected_runtime()


def test_selection_cas_failure_cannot_publish_owner_consent(
        service, tmp_path, selected_store, monkeypatch):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-proven-key', actor=owner())
    before = provider_selection.current_revision()

    def fail_cas(*_args, **_kwargs):
        raise OSError('synthetic SQLite commit failure')

    monkeypatch.setattr(provider_selection, 'compare_and_swap', fail_cas)
    with pytest.raises(OSError, match='synthetic SQLite'):
        svc.select_provider('synthetic-addon', artifact['package_hash'],
            'synthetic-model', expected_revision=before,
            acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    assert provider_selection.current_revision() == before
    assert provider_selection.read_selection() is None


def test_required_owner_ack_audit_failure_precedes_proof_mint(
        service, tmp_path, selected_store):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-proven-key', actor=owner())
    before = provider_selection.current_revision()
    previous_log = svc.audit.log

    def fail_owner_ack(event):
        if event.action_taken == 'provider_selection_unknown_price_acknowledged':
            raise OSError('synthetic owner audit failure')
        previous_log(event)

    svc.audit = SimpleNamespace(log=fail_owner_ack)
    with pytest.raises(ProviderPackageError, match='selection consent audit unavailable'):
        svc.select_provider('synthetic-addon', artifact['package_hash'],
            'synthetic-model', expected_revision=before,
            acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    assert provider_selection.current_revision() == before
    assert provider_selection.read_selection() is None
    assert not (svc.root / 'selection-consent.key').exists()


def test_private_consent_key_is_durable_before_selection_cas(
        service, tmp_path, selected_store, monkeypatch):
    from agents.core.llm.providers import selection_consent

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-proven-key', actor=owner())
    synced = []
    real_fsync = os.fsync
    real_cas = provider_selection.compare_and_swap

    def observed_fsync(fd):
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (
                svc.root.stat().st_dev, svc.root.stat().st_ino):
            synced.append('root')
        elif stat.S_ISREG(info.st_mode) and info.st_size == 32:
            synced.append('key')
        return real_fsync(fd)

    def checked_cas(*args, **kwargs):
        assert 'key' in synced and 'root' in synced
        key_path = svc.root / 'selection-consent.key'
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
        return real_cas(*args, **kwargs)

    monkeypatch.setattr(selection_consent.os, 'fsync', observed_fsync)
    monkeypatch.setattr(provider_selection, 'compare_and_swap', checked_cas)
    svc.select_provider('synthetic-addon', artifact['package_hash'],
        'synthetic-model', expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    assert svc.selected_runtime().selection == provider_selection.read_selection()


def test_concurrent_selection_writer_cannot_mint_or_commit_proof(
        service, tmp_path, selected_store):
    from agents.core.llm.providers import selection_gates

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-proven-key', actor=owner())
    before = provider_selection.current_revision()
    entered, release = threading.Event(), threading.Event()

    def hold_writer():
        with selection_gates.exclusive(selected_store, signed=True):
            entered.set()
            assert release.wait(3)

    holder = threading.Thread(target=hold_writer)
    holder.start()
    try:
        assert entered.wait(3)
        with pytest.raises(selection_gates.SelectionBusy):
            svc.select_provider('synthetic-addon', artifact['package_hash'],
                'synthetic-model', expected_revision=before,
                acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    finally:
        release.set()
        holder.join(3)
    assert not holder.is_alive()
    assert provider_selection.current_revision() == before
    assert provider_selection.read_selection() is None
    assert not (svc.root / 'selection-consent.key').exists()


@pytest.mark.asyncio
async def test_cancelled_owner_worker_drains_proof_and_cas_before_unwinding(
        service, tmp_path, selected_store, monkeypatch):
    from agents.core.routers.models_llm import _provider_install_worker

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-proven-key', actor=owner())
    before = provider_selection.current_revision()
    entered, release = threading.Event(), threading.Event()
    real_cas = provider_selection.compare_and_swap

    def paused_cas(*args, **kwargs):
        entered.set()
        if not release.wait(3):
            raise AssertionError('CAS test barrier timed out')
        return real_cas(*args, **kwargs)

    monkeypatch.setattr(provider_selection, 'compare_and_swap', paused_cas)
    worker = asyncio.create_task(_provider_install_worker(
        lambda: svc.select_provider('synthetic-addon', artifact['package_hash'],
            'synthetic-model', expected_revision=before,
            acknowledge_unknown_price=True, acknowledge_data_policy=True,
            actor=owner())))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        worker.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await worker
    finally:
        release.set()
        if not worker.done():
            await asyncio.gather(worker, return_exceptions=True)
    saved = provider_selection.read_selection()
    assert saved.revision == before + 1
    assert svc.selected_runtime().selection == saved


def test_selected_h513_actual_use_rechecks_proof_and_credential_generation(
        service, tmp_path, selected_store, monkeypatch):
    from agents.core.commands import Principal
    from agents.core.llm import data_handling

    monkeypatch.setattr(data_handling, '_scope_key', lambda: b'synthetic-h513-scope-key')
    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-proven-key', actor=owner())
    svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
        expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    runtime = svc.selected_runtime()
    backend = SimpleNamespace(profile=runtime.profile, _selected_provider_runtime=runtime)
    router = SimpleNamespace(_compatible_backend=backend)
    runtime.backend, runtime.router = backend, router
    allowed = data_handling.authorize(
        router, backend, 'synthetic-model', principal=Principal(), actual_use=True)
    assert allowed['acknowledged'] is True
    key_path = svc.root / 'selection-consent.key'
    key_path.rename(svc.root / 'selection-consent.key.saved')
    with pytest.raises(data_handling.DataHandlingRefused, match='consent scope'):
        data_handling.authorize(router, backend, 'synthetic-model',
                                principal=Principal(), actual_use=True)
    (svc.root / 'selection-consent.key.saved').rename(key_path)
    assert data_handling.authorize(router, backend, 'synthetic-model',
                                   principal=Principal(), actual_use=False)['acknowledged']
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-rotated-key', actor=owner())
    with pytest.raises(data_handling.DataHandlingRefused, match='consent scope'):
        data_handling.authorize(router, backend, 'synthetic-model',
                                principal=Principal(), actual_use=True)


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


def _install_pre_choice_epoch_selection(svc, *, proof=None):
    """Recreate the exact pre-H367 JSON and private HMAC without a new owner action."""
    from agents.core.llm.providers import selection_consent

    selected = provider_selection.read_selection()
    binding = selected.binding
    record = svc._store().require_runnable(binding.provider_id,
        expected_hash=binding.package_hash, home=svc.home)
    policy = record.profile.data_policy_for(binding.model)[0]
    fields = asdict(binding)
    fields.pop('choice_epoch')
    fields.pop('consent_proof')
    message = selection_consent._DOMAIN + json.dumps({
        'revision': selected.revision, 'binding': fields, 'policy': policy,
        'declaration_policy': record.profile.data_policy,
        'declaration_models': record.profile.data_policy_models,
    }, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    old_proof = hmac.new(selection_consent._key(svc.root, create=False),
                         message, hashlib.sha256).hexdigest() if proof is None else proof
    fields['consent_proof'] = old_proof
    payload = json.dumps(fields, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    conn = settings_db.get_conn()
    try:
        with conn:
            conn.execute('UPDATE signed_provider_selection SET record_json=?,record_hash=? '
                         'WHERE singleton=1',
                         (payload, provider_selection._digest(selected.revision, payload)))
            conn.execute('UPDATE provider_choice_epoch SET epoch=0 WHERE singleton=1')
    finally:
        conn.close()
    return selected.revision, payload


def test_genuine_old_signed_proof_migrates_without_new_owner_consent(
        service, tmp_path, selected_store):
    from agents.core.llm.custom_endpoints import read_choice

    svc, _, _, seen, events, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-upgrade-key', actor=owner())
    svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
        expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    before_actions = sum(action.kind == 'provider.selection' for action, _ in seen)
    before_events = sum(event.action_taken.startswith('provider_selection_') for event in events)
    revision, legacy_json = _install_pre_choice_epoch_selection(svc)
    assert 'choice_epoch' not in legacy_json
    assert provider_selection.read_selection().binding.choice_epoch == 0
    runtime = svc.selected_runtime()
    saved = provider_selection.read_selection()
    assert runtime.selection == saved
    assert saved.revision == revision
    assert saved.binding.choice_epoch == read_choice().epoch > 0
    assert svc.selection_status(actor=owner())['status'] == 'selected'
    assert sum(action.kind == 'provider.selection' for action, _ in seen) == before_actions
    assert sum(event.action_taken.startswith('provider_selection_') for event in events) == before_events
    assert svc.selected_runtime().selection == saved
    settings_db.put_category('llm', {'compatible_model': 'other-model'})
    assert provider_selection.read_selection() is None
    assert read_choice().epoch > saved.binding.choice_epoch


@pytest.mark.parametrize('mode', ['forged', 'proofless', 'rotated', 'superseded_epoch',
                                   'custom_active', 'busy'])
def test_old_signed_migration_refuses_unproven_or_concurrently_held_scope(
        service, tmp_path, selected_store, mode):
    from agents.core.llm.providers import selection_gates

    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-upgrade-key', actor=owner())
    svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
        expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    revision, legacy_json = _install_pre_choice_epoch_selection(
        svc, proof='0' * 64 if mode == 'forged' else '' if mode == 'proofless' else None)
    if mode == 'rotated':
        svc.put_credential('synthetic-addon', artifact['package_hash'],
                           'synthetic-rotated-key', actor=owner())
    elif mode == 'superseded_epoch':
        conn = settings_db.get_conn()
        try:
            with conn:
                conn.execute('UPDATE provider_choice_epoch SET epoch=1 WHERE singleton=1')
        finally:
            conn.close()
    elif mode == 'custom_active':
        conn = settings_db.get_conn()
        try:
            with conn:
                conn.execute("UPDATE custom_endpoint_choice SET active_key='unproven' WHERE singleton=1")
        finally:
            conn.close()
    if mode == 'busy':
        with selection_gates.shared(settings_db.DB_PATH), pytest.raises(selection_gates.SelectionBusy):
            svc.selected_runtime()
    else:
        with pytest.raises(ProviderPackageError):
            svc.selected_runtime()
    assert provider_selection.read_selection().revision == revision
    conn = settings_db.get_conn()
    try:
        assert conn.execute('SELECT record_json FROM signed_provider_selection').fetchone()[0] == legacy_json
    finally:
        conn.close()


def _hold_legacy_choice_read_lease(path, pipe):
    from pathlib import Path

    from agents.core import settings_db as isolated_settings
    from agents.core.llm.providers import selection_gates as isolated_gates

    isolated_settings.DB_PATH = Path(path)
    with isolated_gates.shared(isolated_settings.DB_PATH):
        pipe.send('held')
        pipe.recv()
    pipe.close()


def test_old_signed_upgrade_waits_for_cross_process_reader_then_migrates(
        service, tmp_path, selected_store):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-upgrade-key', actor=owner())
    svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
        expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    revision, legacy_json = _install_pre_choice_epoch_selection(svc)
    from agents.core.llm.providers.selection_gates import SelectionBusy

    context = mp.get_context('spawn')
    parent, child = context.Pipe()
    process = context.Process(target=_hold_legacy_choice_read_lease,
                              args=(str(settings_db.DB_PATH), child))
    try:
        process.start()
        child.close()
        assert parent.poll(5) and parent.recv() == 'held'
        with pytest.raises(SelectionBusy):
            svc.selected_runtime()
        conn = settings_db.get_conn()
        try:
            assert conn.execute('SELECT record_json FROM signed_provider_selection').fetchone()[0] == legacy_json
        finally:
            conn.close()
        parent.send('release')
        process.join(5)
        assert process.exitcode == 0
        assert svc.selected_runtime().selection.revision == revision
        assert provider_selection.read_selection().binding.choice_epoch == 1
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()
        child.close()


def test_unknown_old_selection_fields_never_become_consent(
        service, tmp_path, selected_store):
    svc, _, _, _, _, artifact = active(service, tmp_path)
    svc.put_credential('synthetic-addon', artifact['package_hash'],
                       'synthetic-upgrade-key', actor=owner())
    svc.select_provider('synthetic-addon', artifact['package_hash'], 'synthetic-model',
        expected_revision=provider_selection.current_revision(),
        acknowledge_unknown_price=True, acknowledge_data_policy=True, actor=owner())
    revision, payload = _install_pre_choice_epoch_selection(svc)
    fields = json.loads(payload)
    fields['unknown_version'] = 2
    changed = json.dumps(fields, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    conn = settings_db.get_conn()
    try:
        with conn:
            conn.execute('UPDATE signed_provider_selection SET record_json=?,record_hash=? '
                         'WHERE singleton=1',
                         (changed, provider_selection._digest(revision, changed)))
    finally:
        conn.close()
    with pytest.raises(provider_selection.SelectionInvalid):
        svc.selected_runtime()
    conn = settings_db.get_conn()
    try:
        assert conn.execute('SELECT record_json FROM signed_provider_selection').fetchone()[0] == changed
        assert conn.execute('SELECT epoch FROM provider_choice_epoch').fetchone()[0] == 0
    finally:
        conn.close()
