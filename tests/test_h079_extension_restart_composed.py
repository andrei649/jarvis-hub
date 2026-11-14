"""Persisted command routes survive a fresh acquisition host without startup execution."""
from types import SimpleNamespace

import pytest

from agents.core.acquisition.runtime import AcquisitionRuntime
from agents.core.commands import Principal, build_default_registry
from agents.core.extensions.activation_hints import ActivationHintStore
from tests import test_extension_runtime as rt

rig = rt.rig


@pytest.mark.asyncio
async def test_fresh_host_restores_saved_route_then_owner_executes_real_invocation(rig, monkeypatch):
    hints = ActivationHintStore(rig.root / 'activation_hints.json')
    manifest = rt.descriptor(tools=[], commands=['boat_report'])
    rig.packages.write(rt.COMMAND_EXTENSION)
    rig.consent.grant(manifest)
    monkeypatch.setattr('agents.core.acquisition.sandbox_profile.DockerSandboxRunner',
                        lambda **_kw: rig.runner)

    def host():
        return AcquisitionRuntime(enabled=lambda: True, root=rig.root / 'acquisition',
                                  commands=build_default_registry(),
                                  extension_consent=rig.consent, activation_hints=hints)

    first = host()
    first.package_store, first.sandbox_profile = rig.packages, rig.runtime.profile
    activation = await first.extensions().activate(manifest)
    assert hints.read_all()[0].package_hash == activation.package_hash
    assert first.extension_restoration_status('boats')['state'] == 'saved'
    calls = len(rig.runner.calls)

    second = host()
    composed = []

    def promotion():
        composed.append(True)
        second.package_store, second.sandbox_profile = rig.packages, rig.runtime.profile
        return SimpleNamespace()

    second.ensure_promotion = promotion
    assert second.restore_extension_commands() == ('boats',)
    assert second.extension_runtime is None and second.package_store is None
    assert len(rig.runner.calls) == calls and composed == []
    guest = await second.commands.dispatch('/boat_report today', orch=None, principal=Principal())
    assert guest.status == 'refused' and composed == []
    owner = await second.commands.dispatch('/boat_report today', orch=None, principal=Principal(admin=True))
    assert owner.status == 'answered'
    assert composed == [True] and len(rig.runner.calls) == calls + 2
    active = second.extension_runtime.active()
    command = second.commands.get('boat_report')
    second.restore_extension_commands()
    assert second.extension_runtime.active() == active
    assert second.commands.get('boat_report') is command


@pytest.mark.asyncio
async def test_failed_hint_delete_remains_revoked_across_regrant_and_fresh_host(rig, monkeypatch):
    hints = ActivationHintStore(rig.root / 'activation_hints.json')
    manifest = rt.descriptor(tools=[], commands=['boat_report'])
    revision = rig.consent.grant(manifest).grant_revision
    hints.put(manifest, rig.packages.record.package_hash, revision)
    host = AcquisitionRuntime(enabled=lambda: True, commands=build_default_registry(),
                              extension_consent=rig.consent, activation_hints=hints)
    assert host.restore_extension_commands() == ('boats',)
    rig.consent.revoke('boats')

    def refused(_id):
        raise OSError('unavailable disk')

    monkeypatch.setattr(hints, 'remove', refused)
    await host.deactivate_extension('boats')
    assert host.extension_restoration_status('boats')['state'] == 'remove_failed'
    assert host.commands.get('boat_report') is None and host.extension_runtime is None
    rig.consent.grant(manifest)
    fresh = AcquisitionRuntime(enabled=lambda: True, commands=build_default_registry(),
                               extension_consent=rig.consent, activation_hints=hints)
    assert fresh.restore_extension_commands() == ()
    assert fresh.extension_runtime is None and rig.runner.calls == []


def test_actual_coordinator_wiring_restores_routes_without_composing_extensions(tmp_path, monkeypatch):
    from agents.core.autonomy_coordinator import AutonomyCoordinator
    from agents.core.extensions.consent import ExtensionConsentStore

    monkeypatch.setenv('JARVIS_HOME', str(tmp_path))
    consent = ExtensionConsentStore()
    hints = ActivationHintStore()
    manifest = rt.descriptor(tools=[], commands=['boat_report'])
    hints.put(manifest, 'c' * 64, consent.grant(manifest).grant_revision)
    before = {p.name: p.read_bytes() for p in (tmp_path / 'extensions').iterdir() if p.is_file()}

    def no_promotion(_self):
        pytest.fail('startup composed acquisition promotion')

    monkeypatch.setattr(AcquisitionRuntime, 'ensure_promotion', no_promotion)
    orch = SimpleNamespace(agents={}, commands=build_default_registry(),
                           get_setting=lambda key, default=None: True if key == 'acquisition.enabled' else default)
    AutonomyCoordinator(orch)._wire_agent_tool_runtime()
    assert orch.commands.get('boat_report') is not None
    assert orch.acquisition.extension_runtime is None
    assert orch.acquisition.package_store is None
    assert orch.acquisition.sandbox_profile is None
    assert orch.acquisition.promotion_broker is None
    after = {p.name: p.read_bytes() for p in (tmp_path / 'extensions').iterdir() if p.is_file()}
    assert after == before


@pytest.mark.asyncio
async def test_coordinator_rewire_fences_old_host_and_replaces_only_owned_routes(tmp_path, monkeypatch):
    from agents.core.autonomy_coordinator import AutonomyCoordinator
    from agents.core.commands import CommandContext
    from agents.core.extensions.command_bindings import CommandBindingError
    from agents.core.extensions.consent import ExtensionConsentStore

    monkeypatch.setenv('JARVIS_HOME', str(tmp_path))
    manifest = rt.descriptor(tools=[], commands=['boat_report'])
    consent, hints = ExtensionConsentStore(), ActivationHintStore()
    hints.put(manifest, 'c' * 64, consent.grant(manifest).grant_revision)
    orch = SimpleNamespace(agents={}, commands=build_default_registry(),
                           get_setting=lambda key, default=None: True if key == 'acquisition.enabled' else default)
    coordinator = AutonomyCoordinator(orch)
    coordinator._wire_agent_tool_runtime()
    previous = orch.acquisition
    old_command = orch.commands.get('boat_report')
    assert previous.is_enabled()
    coordinator._wire_agent_tool_runtime()
    assert orch.acquisition is not previous and not previous.is_enabled()
    assert orch.commands.get('boat_report') is not old_command
    assert orch.commands.get('boat_report') is not None and len(hints.read_all()) == 1
    with pytest.raises(CommandBindingError):
        await old_command.handler(CommandContext(orch, Principal(admin=True), 'boat_report', 'today'))
    assert previous.extension_runtime is None and orch.acquisition.extension_runtime is None
