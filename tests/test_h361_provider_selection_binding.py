"""Owner selected metadata uses a live signed record, vault HWM and real Kernel."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.kernel import Verdict
from agents.core.llm import provider_selection
from agents.core.llm.providers.packages import ProviderPackageError
from tests.test_h361_provider_credentials import active
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
