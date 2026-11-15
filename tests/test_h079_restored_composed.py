"""Restoration metadata reaches real runtime through an offline invocation runner."""
import asyncio

import pytest

from agents.core.commands import CommandContext, Principal, build_default_registry
from agents.core.extensions.activation_hints import ActivationHintStore
from agents.core.extensions.command_bindings import ExtensionCommandBindings
from agents.core.extensions.restored_commands import RestoredCommandError, RestoredExtensionCommands
from tests import test_extension_runtime as rt
from tests.test_h079_extension_regrant_fences import _PausedRunner

rig = rt.rig

SOURCE = '''
def register():
    return {"tools": [], "commands": ["boat_report"], "events": []}
def command(name, args):
    return "Report: " + args
'''


def setup_restore(rig):
    registry = build_default_registry()
    bindings = ExtensionCommandBindings(registry)
    runtime = rig.runtime
    runtime.commands = registry
    runtime.command_bindings = bindings
    runtime._command_registrations = bindings.registrations
    record = rig.packages.write(SOURCE)
    manifest = rt.descriptor(tools=[], commands=["boat_report"])
    revision = rig.consent.grant(manifest).grant_revision
    hints = ActivationHintStore(rig.root / 'hints.json')
    hints.put(manifest, record.package_hash, revision)
    providers = []

    def provider():
        providers.append(True)
        return runtime

    restored = RestoredExtensionCommands(bindings, rig.consent, hints, provider, lambda: True)
    return registry, restored, manifest, providers


@pytest.mark.asyncio
async def test_startup_metadata_and_first_owner_command_real_runtime(rig):
    registry, restored, manifest, providers = setup_restore(rig)
    assert restored.restore() == (manifest.id,)
    assert rig.runner.calls == [] and providers == [] and rig.runtime.active() == ()
    placeholder = registry.get('boat_report')
    guest = CommandContext(None, Principal(admin=False), 'boat_report', 'private')
    await placeholder.handler(guest)
    assert providers == [] and rig.runner.calls == []
    owner = CommandContext(None, Principal(admin=True), 'boat_report', 'today')
    assert await placeholder.handler(owner) == 'Report: today'
    assert len(rig.runner.calls) == 2
    assert registry.get('boat_report') is not placeholder
    assert await registry.get('boat_report').handler(owner) == 'Report: today'
    assert len(rig.runner.calls) == 3


@pytest.mark.asyncio
async def test_changed_package_is_refused_before_any_runner_execution(rig):
    registry, restored, _manifest, _providers = setup_restore(rig)
    restored.restore()
    rig.packages.record.package_hash = 'd' * 64
    owner = CommandContext(None, Principal(admin=True), 'boat_report', 'today')
    with pytest.raises(RestoredCommandError):
        await registry.get('boat_report').handler(owner)
    assert rig.runner.calls == [] and rig.runtime.active() == ()


@pytest.mark.asyncio
async def test_forget_while_registration_waits_never_leaves_callable_surface(rig):
    registry, restored, manifest, _providers = setup_restore(rig)
    restored.restore()
    runner = _PausedRunner()
    rig.runtime.runner = runner
    owner = CommandContext(None, Principal(admin=True), 'boat_report', 'today')
    task = asyncio.create_task(registry.get('boat_report').handler(owner))
    await asyncio.wait_for(runner.started.wait(), 5)
    restored.forget(manifest.id)
    runner.release.set()
    with pytest.raises(RestoredCommandError):
        await task
    assert registry.get('boat_report') is None
    assert rig.runtime.active() == ()


@pytest.mark.asyncio
async def test_two_inflight_placeholder_calls_register_once(rig):
    registry, restored, _manifest, _providers = setup_restore(rig)
    restored.restore()
    handler = registry.get('boat_report').handler
    runner = _PausedRunner()
    rig.runtime.runner = runner
    owner = CommandContext(None, Principal(admin=True), 'boat_report', 'today')
    first = asyncio.create_task(handler(owner))
    await asyncio.wait_for(runner.started.wait(), 5)
    second = asyncio.create_task(handler(owner))
    await asyncio.sleep(0)
    runner.release.set()
    assert await asyncio.gather(first, second) == ['Report: today', 'Report: today']
    assert len(runner.calls) == 3  # one registration, two command invocations


@pytest.mark.asyncio
async def test_explicit_deactivate_before_first_command_prevents_resurrection(rig):
    registry, restored, manifest, _providers = setup_restore(rig)
    restored.restore()
    handler = registry.get('boat_report').handler
    assert await rig.runtime.deactivate(manifest.id) is False
    with pytest.raises(RestoredCommandError):
        await handler(CommandContext(None, Principal(admin=True), 'boat_report', 'today'))
    assert rig.runner.calls == [] and rig.runtime.active() == ()
