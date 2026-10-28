"""Owner controller uses actual signed stores; no live plugin installation."""
import asyncio
import json
import os
from dataclasses import replace

import pytest

from agents.core.acquisition.managed_signing import ManagedSigningKeyStore
from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile
from agents.core.autonomy.consent_types import OwnerConsentActor
from agents.core.kernel import Decision, Verdict
from agents.core.llm.providers import ProviderProfile
from agents.core.llm.providers.packages import ProviderPackageError
from tests.test_h361_provider_hook_runtime import IMAGE, SimulatedSealedRunner


@pytest.fixture
def service(tmp_path, monkeypatch):
    from agents.core.llm.providers.install_service import ProviderInstallService
    monkeypatch.setenv('JARVIS_ACTION_KERNEL', '1')
    signing = ManagedSigningKeyStore(tmp_path / 'signing')
    signing.provision(key_id='synthetic-install', version=1, key=b'i' * 32)
    actions = []
    def kernel(action, *, approval_check):
        actions.append(action)
        assert approval_check(action) is True
        return Decision(Verdict.GRANT, tier=3)
    svc = ProviderInstallService(root=tmp_path / 'providers', signing=signing,
        profile=AcquisitionSandboxProfile(image=IMAGE, uid=os.getuid(), gid=os.getgid()),
        kernel=lambda: kernel, enabled=lambda: True, home='owner-home',
        runner=SimulatedSealedRunner())
    source = svc.incoming('user') / 'addon'
    source.mkdir(parents=True)
    (source / 'provider.json').write_text(json.dumps(
        {'schema_version': 1, 'id': 'synthetic-addon', 'aliases': []}))
    hooks = ('prepare_messages', 'build_extra_body', 'build_api_kwargs_extras')
    (source / 'main.py').write_text('def register_provider():\n    return '+repr(
        {'id': 'synthetic-addon', 'hooks': list(hooks)})+'\n'
        'def prepare_messages(messages):\n    return messages\n'
        'def build_extra_body(**kwargs):\n    return {}\n'
        'def build_api_kwargs_extras(**kwargs):\n    return {}, {}\n')
    native = ProviderProfile('synthetic-addon', 'Synthetic', 'openai-compatible',
        is_user_defined=True, capabilities=frozenset({'chat', 'cloud'}),
        default_base_url='https://synthetic.invalid/v1')
    return svc, native, hooks, actions


def owner(live=lambda: True):
    return OwnerConsentActor('owner', 'admin', live, principal_key='synthetic-owner')


def staged(service):
    svc, profile, hooks, _ = service
    return svc.stage('addon', profile=profile, hooks=hooks, source='user', actor=owner())


def test_actor_label_is_not_owner_authority_and_path_escape_is_refused(service):
    svc, profile, hooks, _ = service
    with pytest.raises(ProviderPackageError):
        svc.stage('addon', profile=profile, hooks=hooks, source='user', actor='owner')
    with pytest.raises(ProviderPackageError):
        svc.stage('../addon', profile=profile, hooks=hooks, source='user', actor=owner())


def test_pending_and_wrong_hash_cannot_activate(service):
    svc, _, _, actions = service
    preview = staged(service)
    offer = svc.propose(preview['artifact_id'], actor=owner())
    with pytest.raises(ProviderPackageError):
        svc.promote(offer['proposal_id'], actor=owner())
    with pytest.raises(ProviderPackageError):
        svc.decide(offer['proposal_id'], artifact_id=preview['artifact_id'],
            package_hash='0' * 64, approved=True, permanent=True, actor=owner())
    assert actions == []
    assert svc.registry().list()[-1].id != 'synthetic-addon'


def test_authenticated_exact_decision_promotes_without_changing_selection_and_revokes(service):
    svc, _, _, actions = service
    preview = staged(service)
    assert 'members' not in preview and 'profile' not in preview
    offer = svc.propose(preview['artifact_id'], actor=owner())
    svc.decide(offer['proposal_id'], artifact_id=preview['artifact_id'],
        package_hash=preview['package_hash'], approved=True, permanent=True, actor=owner())
    assert actions == []
    svc.promote(offer['proposal_id'], actor=owner())
    assert [a.payload['phase'] for a in actions] == ['promote']
    admitted = svc.registry().get('synthetic-addon')
    assert admitted._package_hash == preview['package_hash']
    svc.revoke('synthetic-addon', actor=owner())
    with pytest.raises(KeyError):
        svc.registry().get('synthetic-addon')


def test_owner_revoked_at_decision_seam_cannot_approve(service):
    svc, _, _, _ = service
    preview = staged(service)
    offer = svc.propose(preview['artifact_id'], actor=owner())
    checks = iter([True, False])
    with pytest.raises(ProviderPackageError):
        svc.decide(offer['proposal_id'], artifact_id=preview['artifact_id'],
            package_hash=preview['package_hash'], approved=True, permanent=True,
            actor=owner(lambda: next(checks, False)))
    with pytest.raises(ProviderPackageError):
        svc.promote(offer['proposal_id'], actor=owner())


def test_disabled_service_stays_lazy_and_refuses(service):
    svc, profile, hooks, _ = service
    svc.enabled = lambda: False
    with pytest.raises(ProviderPackageError):
        svc.stage('addon', profile=profile, hooks=hooks, source='user', actor=owner())
    assert not (svc.root / 'packages').exists()


def test_incoming_root_symlink_is_refused(service, tmp_path):
    svc, _, _, _ = service
    (svc.root / 'incoming').rename(svc.root / 'incoming-original')
    (svc.root / 'incoming').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ProviderPackageError):
        svc.incoming('user')
    assert not (svc.root / 'packages').exists()


@pytest.mark.parametrize('approved', [True, False])
def test_decision_cannot_borrow_another_artifact_scope(service, approved):
    svc, _, _, _ = service
    first = staged(service)
    second = staged(service)
    offer = svc.propose(first['artifact_id'], actor=owner())
    with pytest.raises(ProviderPackageError):
        svc.decide(offer['proposal_id'], artifact_id=second['artifact_id'],
            package_hash=second['package_hash'], approved=approved, permanent=True, actor=owner())
    svc.decide(offer['proposal_id'], artifact_id=first['artifact_id'],
        package_hash=first['package_hash'], approved=approved, permanent=True, actor=owner())


@pytest.mark.parametrize('field,value', [
    ('auth_env', 'PRIVATE_HOST_SECRET'), ('base_url_env', 'PRIVATE_HOST_ENDPOINT'),
    ('env_vars', ('PRIVATE_HOST_SECRET',)),
])
def test_stage_refuses_package_selected_environment_authority(service, field, value):
    svc, profile, hooks, _ = service
    with pytest.raises(ProviderPackageError):
        svc.stage('addon', profile=replace(profile, **{field: value}), hooks=hooks,
                  source='user', actor=owner())
    assert not (svc.root / 'packages').exists()


def test_active_inventory_rejects_changed_scope_index(service):
    svc, _, _, _ = service
    preview = staged(service)
    offer = svc.propose(preview['artifact_id'], actor=owner())
    svc.decide(offer['proposal_id'], artifact_id=preview['artifact_id'],
        package_hash=preview['package_hash'], approved=True, permanent=True, actor=owner())
    svc.promote(offer['proposal_id'], actor=owner())
    store = svc._store()
    with store._locked():
        state = store._load()
        state['active'] = {'wrong-scope': preview['artifact_id']}
        store._commit(state)
    with pytest.raises(ProviderPackageError):
        store.list_active(home=svc.home)


def test_owner_preview_exposes_signed_trust_fields_without_header_values(service):
    svc, profile, hooks, _ = service
    profile = replace(profile, default_base_url='https://synthetic.invalid/v2',
        data_policy='no-training', data_policy_note='Synthetic declaration only',
        default_headers={'x-synthetic-marker': 'private-marker-value'},
        fallback_models=('synthetic-model',))
    preview = svc.stage('addon', profile=profile, hooks=hooks, source='user', actor=owner())
    summary = preview['profile_summary']
    assert summary['endpoint'] == {'scheme': 'https', 'host': 'synthetic.invalid',
                                   'port': None}
    assert summary['data_policy']['policy'] == 'no-training'
    assert summary['fallback_models'] == ['synthetic-model']
    assert summary['capabilities'] == ['chat', 'cloud']
    assert 'default_header_names' not in summary
    assert 'private-marker-value' not in json.dumps(preview)
    assert '/v2' not in json.dumps(preview)
    assert 'main.py' not in json.dumps(preview)
    assert 'provider.json' not in json.dumps(preview)
    assert 'home' not in preview and str(svc.root) not in json.dumps(preview)
    assert preview['member_count'] == 2
    assert preview['sandbox']['image'] == IMAGE


@pytest.mark.asyncio
async def test_async_revoke_cancels_inflight_dispatch_before_return(service):
    svc, _, _, _ = service
    preview = staged(service)
    offer = svc.propose(preview['artifact_id'], actor=owner())
    svc.decide(offer['proposal_id'], artifact_id=preview['artifact_id'],
               package_hash=preview['package_hash'], approved=True,
               permanent=True, actor=owner())
    svc.promote(offer['proposal_id'], actor=owner())
    entered = asyncio.Event()
    release = asyncio.Event()
    sent = []

    async def physical_attempt():
        async with svc._store().dispatch_lease('synthetic-addon',
                                               expected_hash=preview['package_hash'],
                                               home=svc.home):
            entered.set()
            await release.wait()
            sent.append(True)

    task = asyncio.create_task(physical_attempt())
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert await asyncio.wait_for(svc.revoke_async('synthetic-addon', actor=owner()),
                                      timeout=5) == {'provider_id': 'synthetic-addon',
                                                     'status': 'revoked'}
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sent == []
    finally:
        release.set()
        if not task.done():
            task.cancel()
