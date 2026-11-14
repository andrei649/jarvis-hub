"""Focused V50 activation-pin and exact-command-activation regressions."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents.core.commands import Principal, build_default_registry
from agents.core.extensions.command_bindings import CommandBindingError, ExtensionCommandBindings
from agents.core.extensions.runtime import ExtensionRuntimeError
from tests import test_extension_runtime as runtime_tests

rig = runtime_tests.rig


class _DelayedUnregisterRPC(runtime_tests._ToolRPC):
    def __init__(self):
        super().__init__()
        self.unregister_started = asyncio.Event()
        self.release_unregister = asyncio.Event()

    async def unregister_tool(self, name, *, cancel_inflight=False):
        self.unregister_started.set()
        await self.release_unregister.wait()
        await super().unregister_tool(name, cancel_inflight=cancel_inflight)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pin", "value", "reason"),
    [
        ("expected_package_hash", "d" * 64, "package_changed"),
        ("expected_grant_revision", "e" * 64, "consent_changed"),
        ("expected_epoch", 1, "activation_superseded"),
    ],
)
async def test_stale_activation_pin_refuses_before_runner(rig, pin, value, reason):
    manifest = runtime_tests.descriptor()
    rig.consent.grant(manifest)
    before = len(rig.runner.calls)

    with pytest.raises(ExtensionRuntimeError, match=reason):
        await rig.runtime.activate(manifest, **{pin: value})

    assert len(rig.runner.calls) == before
    assert rig.runtime.active() == ()


@pytest.mark.asyncio
async def test_deactivation_before_first_activation_invalidates_epoch_pin(rig):
    manifest = runtime_tests.descriptor()
    rig.consent.grant(manifest)
    package_hash = rig.packages.record.package_hash
    grant_revision = rig.consent.check(manifest).grant_revision
    assert rig.runtime._activation_epochs == {}

    assert await rig.runtime.deactivate(manifest.id) is False
    before = len(rig.runner.calls)
    with pytest.raises(ExtensionRuntimeError, match="activation_superseded"):
        await rig.runtime.activate(
            manifest,
            expected_package_hash=package_hash,
            expected_grant_revision=grant_revision,
            expected_epoch=0,
        )
    assert len(rig.runner.calls) == before
    assert rig.runtime.active() == ()


@pytest.mark.asyncio
async def test_matching_pins_allow_one_registration(rig):
    manifest = runtime_tests.descriptor()
    rig.consent.grant(manifest)
    grant_revision = rig.consent.check(manifest).grant_revision
    package_hash = rig.packages.record.package_hash

    activation = await rig.runtime.activate(
        manifest,
        expected_package_hash=package_hash,
        expected_grant_revision=grant_revision,
        expected_epoch=0,
    )

    assert rig.runtime.active() == (activation,)
    assert len(rig.runner.calls) == 1


@pytest.mark.asyncio
async def test_captured_old_command_handler_cannot_dispatch_replacement_activation(rig):
    manifest = runtime_tests.descriptor(tools=[], commands=["boat_report"])
    registry = build_default_registry()
    rig.runtime.commands = registry
    bindings = ExtensionCommandBindings(registry)
    rig.runtime.command_bindings = bindings
    rig.packages.write(runtime_tests.COMMAND_EXTENSION)
    rig.consent.grant(manifest)

    old_activation = await rig.runtime.activate(manifest)
    old_command = bindings.registrations[manifest.id][0]
    new_activation = await rig.runtime.activate(manifest)
    assert new_activation is not old_activation
    assert bindings.registrations[manifest.id][0] is not old_command
    before = len(rig.runner.calls)
    context = SimpleNamespace(args="today", principal=Principal(admin=True))

    with pytest.raises(CommandBindingError, match="command_not_owned"):
        await old_command.handler(context)
    with pytest.raises(ExtensionRuntimeError, match="command_not_activated"):
        await rig.runtime.dispatch_command("boat_report", "today", expected_activation=old_activation)

    assert len(rig.runner.calls) == before
    assert rig.runtime.active() == (new_activation,)
    assert rig.runtime._command_registrations is bindings.registrations
    assert registry.get("boat_report") is bindings.registrations[manifest.id][0]


@pytest.mark.asyncio
async def test_captured_old_rpc_handler_cannot_dispatch_replacement_activation(rig):
    manifest = runtime_tests.descriptor()
    rig.consent.grant(manifest)
    rpc = rig.runtime.rpc = runtime_tests._ToolRPC()

    old_activation = await rig.runtime.activate(manifest)
    old_handler = rpc.tools["boats.summarize"]["handler"]
    new_activation = await rig.runtime.activate(manifest)
    new_handler = rpc.tools["boats.summarize"]["handler"]
    assert new_activation is not old_activation
    assert new_handler is not old_handler
    before = len(rig.runner.calls)

    with pytest.raises(ExtensionRuntimeError, match="tool_not_activated"):
        await old_handler({"text": "stale activation"})
    assert len(rig.runner.calls) == before

    result = await new_handler({"text": "current activation"})
    assert result == {"tool": "boats.summarize", "seen": {"text": "current activation"}}
    assert len(rig.runner.calls) == before + 1


@pytest.mark.asyncio
async def test_expected_activation_cleanup_waits_for_lock_and_preserves_replacement(rig):
    manifest = runtime_tests.descriptor()
    rig.consent.grant(manifest)
    rpc = rig.runtime.rpc = _DelayedUnregisterRPC()
    old_activation = await rig.runtime.activate(manifest)

    replacement_task = asyncio.create_task(rig.runtime.activate(manifest))
    await asyncio.wait_for(rpc.unregister_started.wait(), timeout=5)
    cleanup_task = asyncio.create_task(
        rig.runtime.deactivate(manifest.id, expected_activation=old_activation)
    )
    await asyncio.sleep(0)
    assert not cleanup_task.done()

    rpc.release_unregister.set()
    replacement = await asyncio.wait_for(replacement_task, timeout=5)
    assert await asyncio.wait_for(cleanup_task, timeout=5) is False
    assert replacement is not old_activation
    assert rig.runtime.active() == (replacement,)
    assert list(rpc.tools) == ["boats.summarize"]
