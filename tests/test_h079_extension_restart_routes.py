"""Restart metadata remains separate from live activation/revoked authority."""
from types import SimpleNamespace

import pytest

from agents.core.acquisition.runtime import AcquisitionRuntime
from agents.core.commands import build_default_registry
from agents.core.extensions.activation_hints import ActivationHintStore
from agents.core.extensions.manifest import parse_manifest
from tests.test_extension_activation_routes import DESCRIPTOR, OWNER, client, rig  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['saved', 'save_failed'])
async def test_activation_reports_live_success_and_separate_restart_status(rig, state):
    rig.runtime.restoration_status = lambda _id: {'state': state, 'reason': 'private detail'}
    queued = []
    rig.orch.channel_manager = SimpleNamespace(queue_command_menu_refresh=lambda **kw: queued.append(kw))
    async with client(rig) as http:
        reply = await http.post('/api/plugins/extensions/activate', json={'manifest': DESCRIPTOR}, headers=OWNER)
    assert reply.status_code == 200
    assert reply.json()['ok'] is True
    assert reply.json()['restart_restore'] == {'state': state}
    assert len(queued) == 1 and queued[0]['owner_current']()
    rig.orch.channel_manager = None
    assert not queued[0]['owner_current']()


@pytest.mark.asyncio
async def test_revoke_uncomposed_acquisition_removes_placeholder_and_hint(rig):
    body = {**DESCRIPTOR, 'capabilities': ['commands'], 'tools': [], 'commands': ['boat_report']}
    manifest = parse_manifest(body)
    decision = rig.store.grant(manifest)
    hints = ActivationHintStore(rig.store._path.with_name('activation_hints.json'))
    hints.put(manifest, 'c' * 64, decision.grant_revision)
    registry = build_default_registry()
    acquisition = AcquisitionRuntime(enabled=lambda: True, commands=registry,
                                     extension_consent=rig.store, activation_hints=hints)
    assert acquisition.restore_extension_commands() == ('boats',)
    assert acquisition.extension_runtime is None
    assert registry.get('boat_report') is not None
    rig.orch.acquisition = acquisition
    async with client(rig) as http:
        reply = await http.post('/api/plugins/extensions/consent',
                                json={'manifest': body, 'revoke': True}, headers=OWNER)
    assert reply.status_code == 200 and reply.json()['ok'] is True
    assert reply.json()['restart_restore'] == {'state': 'removed'}
    assert not rig.store.check(manifest).allowed
    assert hints.read_all() == () and registry.get('boat_report') is None
    assert acquisition.extension_runtime is None and acquisition.package_store is None


@pytest.mark.asyncio
async def test_revoke_reports_hint_failure_without_undoing_consent(rig):
    manifest = parse_manifest(DESCRIPTOR)
    rig.store.grant(manifest)

    async def fail(_id):
        raise OSError('private path or secret')

    rig.orch.acquisition = SimpleNamespace(deactivate_extension=fail)
    async with client(rig) as http:
        reply = await http.post('/api/plugins/extensions/consent',
                                json={'manifest': DESCRIPTOR, 'revoke': True}, headers=OWNER)
    assert reply.status_code == 200 and reply.json()['ok'] is True
    assert reply.json()['restart_restore'] == {'state': 'remove_failed'}
    assert not rig.store.check(manifest).allowed
    assert 'private' not in reply.text


@pytest.mark.asyncio
async def test_explicit_owner_activation_may_compose_but_guest_request_cannot(rig):
    prepared = []
    rig.orch.acquisition = SimpleNamespace(
        ensure_promotion=lambda: prepared.append(True),
        extensions=lambda: rig.runtime if prepared else None,
    )
    async with client(rig) as http:
        guest = await http.post('/api/plugins/extensions/activate', json={'manifest': DESCRIPTOR})
        assert guest.status_code == 401 and prepared == []
        owner = await http.post('/api/plugins/extensions/activate', json={'manifest': DESCRIPTOR}, headers=OWNER)
    assert owner.status_code == 200 and owner.json()['ok'] is True
    assert prepared == [True]
