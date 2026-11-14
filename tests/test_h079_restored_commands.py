from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from agents.core.commands import CommandContext, Principal, build_default_registry
from agents.core.extensions.activation_hints import ActivationHint
from agents.core.extensions.command_bindings import CommandBindingError, ExtensionCommandBindings
from agents.core.extensions.consent import declared_digest
from agents.core.extensions.manifest import ExtensionManifest
from agents.core.extensions.restored_commands import RestoredCommandError, RestoredExtensionCommands

REVISION = "a" * 64
PACKAGE_HASH = "b" * 64


def manifest(extension_id="boats", commands=("boat_report",)):
    return ExtensionManifest(
        extension_id, "1.0.0", ("commands",) if commands else (), (), tuple(commands), (), (), (), ()
    )


def hint(value, *, package_hash=PACKAGE_HASH, revision=REVISION):
    return ActivationHint(value, package_hash, declared_digest(value), revision)


class HintSource:
    def __init__(self, rows):
        self.rows = tuple(rows)
        self.reads = 0

    def read_all(self):
        self.reads += 1
        return self.rows


class Consent:
    def __init__(self):
        self.rows = {}
        self.checks = []

    def grant(self, value, revision=REVISION):
        self.rows[value.id] = (declared_digest(value), revision)

    def revoke(self, extension_id):
        self.rows.pop(extension_id, None)

    def check(self, value):
        self.checks.append(value.id)
        row = self.rows.get(value.id)
        digest = declared_digest(value)
        allowed = row == (digest, row[1]) if row else False
        revision = row[1] if row else None
        return SimpleNamespace(allowed=allowed, digest=digest, declared_digest=digest,
                               grant_revision=revision)


@dataclass(frozen=True)
class FakeActivation:
    manifest: ExtensionManifest
    package_hash: str
    grant_revision: str
    epoch: int


class FakeRuntime:
    def __init__(self):
        self._activation_epochs = {}
        self._active = {}
        self.activate_calls = []
        self.dispatch_calls = []
        self.fail_advances = []
        self.registration_started = None
        self.registration_release = None
        self.publish_before_wait = False
        self.dispatch_started = None
        self.dispatch_release = None
        self.deactivate_calls = []
        self.deactivate_started = None
        self.deactivate_release = None

    async def activate(self, value, *, expected_package_hash, expected_grant_revision, expected_epoch):
        extension_id = value.id
        self.activate_calls.append((value, expected_package_hash, expected_grant_revision, expected_epoch))
        if self._activation_epochs.get(extension_id, 0) != expected_epoch or extension_id in self._active:
            raise RuntimeError("external activation fence")
        failing_attempt = bool(self.fail_advances)
        advance = self.fail_advances.pop(0) if failing_attempt else 1
        actual_epoch = expected_epoch + advance
        self._activation_epochs[extension_id] = actual_epoch
        activation = FakeActivation(value, expected_package_hash, expected_grant_revision, actual_epoch)
        if self.publish_before_wait:
            self._active[extension_id] = activation
            if self.registration_started is not None:
                self.registration_started.set()
                await self.registration_release.wait()
            return activation
        if self.registration_started is not None:
            self.registration_started.set()
            await self.registration_release.wait()
        if failing_attempt:
            raise RuntimeError("registration failure")
        self._active[extension_id] = activation
        return activation

    async def dispatch_command(self, name, args, *, expected_activation):
        self.dispatch_calls.append((name, args, expected_activation))
        if self._active.get(expected_activation.manifest.id) is not expected_activation:
            raise RuntimeError("activation replaced")
        if self.dispatch_started is not None:
            self.dispatch_started.set()
            await self.dispatch_release.wait()
        return f"Report: {args}"

    async def deactivate(self, extension_id, *, expected_activation=None):
        self.deactivate_calls.append((extension_id, expected_activation))
        if self.deactivate_started is not None:
            self.deactivate_started.set()
            await self.deactivate_release.wait()
        if self._active.get(extension_id) is not expected_activation:
            return False
        self._active.pop(extension_id, None)
        self._activation_epochs[extension_id] = self._activation_epochs.get(extension_id, 0) + 1
        return True


class Rig:
    def __init__(self, rows, *, consent=None, runtime=None, enabled=True):
        self.registry = build_default_registry()
        self.bindings = ExtensionCommandBindings(self.registry)
        self.consent = consent or Consent()
        self.hints = HintSource(rows)
        self.runtime = runtime or FakeRuntime()
        self.provider_calls = 0
        self.enabled_value = enabled

        def provider():
            self.provider_calls += 1
            return self.runtime

        self.controller = RestoredExtensionCommands(
            self.bindings, self.consent, self.hints, provider, lambda: self.enabled_value
        )


def owner_ctx(command="boat_report", args="today"):
    return CommandContext(None, Principal(admin=True), command, args)


def guest_ctx(command="boat_report", args="secret"):
    return CommandContext(None, Principal(admin=False), command, args)


def test_restore_registers_only_data_routes_and_first_owner_invocation_activates():
    value = manifest()
    consent = Consent()
    consent.grant(value)
    rig = Rig([hint(value)], consent=consent)
    assert rig.controller.restore() == (value.id,)
    assert rig.provider_calls == 0
    assert rig.runtime.activate_calls == []
    placeholder = rig.registry.get("boat_report")
    assert placeholder is not None

    assert asyncio.run(placeholder.handler(guest_ctx())) == "This extension command requires the owner."
    assert rig.provider_calls == 0 and rig.runtime.activate_calls == []
    assert asyncio.run(placeholder.handler(owner_ctx())) == "Report: today"
    assert len(rig.runtime.activate_calls) == 1
    assert rig.runtime.activate_calls[0][1:] == (PACKAGE_HASH, REVISION, 0)
    assert len(rig.runtime.dispatch_calls) == 1

    assert asyncio.run(placeholder.handler(owner_ctx(args="tomorrow"))) == "Report: tomorrow"
    assert len(rig.runtime.activate_calls) == 1
    assert len(rig.runtime.dispatch_calls) == 2


def test_restore_skips_disabled_invalid_consent_empty_and_legacy_rows_without_provider():
    allowed = manifest("allowed")
    invalid = manifest("invalid")
    empty = manifest("empty", commands=())
    consent = Consent()
    consent.grant(allowed)
    consent.grant(empty)
    rig = Rig([hint(allowed), hint(invalid), hint(empty)], consent=consent, enabled=False)
    assert rig.controller.restore() == ()
    assert rig.provider_calls == 0 and rig.runtime.activate_calls == []

    rig.enabled_value = True
    # Missing grant_revision cannot become eligible from old consent alone.
    legacy = SimpleNamespace(manifest=allowed, package_hash=PACKAGE_HASH,
                             declared_digest=declared_digest(allowed))
    rig.hints.rows = (legacy, hint(invalid), hint(empty))
    assert rig.controller.restore() == ()
    assert rig.provider_calls == 0 and rig.runtime.activate_calls == []


def test_cross_row_command_and_underscore_hyphen_collisions_skip_all_rows():
    first, second = manifest("first", ("shared_name",)), manifest("second", ("shared_name",))
    consent = Consent()
    consent.grant(first)
    consent.grant(second)
    rig = Rig([hint(first), hint(second)], consent=consent)
    assert rig.controller.restore() == ()
    assert rig.registry.get("shared_name") is None

    # This deliberately malformed typed hint simulates a legacy/foreign persisted
    # source; the collision prefilter must still reject both before helper checks.
    left = manifest("left", ("boat_report",))
    right = manifest("right", ("boat-report",))
    consent.grant(left)
    consent.grant(right)
    rig = Rig([hint(left), hint(right)], consent=consent)
    assert rig.controller.restore() == ()
    assert rig.registry.get("boat_report") is None


@pytest.mark.asyncio
async def test_preexisting_activation_or_epoch_refuses_placeholder_without_overwrite():
    value = manifest()
    consent = Consent()
    consent.grant(value)
    runtime = FakeRuntime()
    runtime._activation_epochs[value.id] = 3
    runtime._active[value.id] = object()
    rig = Rig([hint(value)], consent=consent, runtime=runtime)
    assert rig.controller.restore() == (value.id,)
    placeholder = rig.registry.get("boat_report")
    with pytest.raises(RestoredCommandError):
        await placeholder.handler(owner_ctx())
    assert runtime.activate_calls == [] and runtime.dispatch_calls == []
    assert rig.registry.get("boat_report") is None


@pytest.mark.asyncio
async def test_exactly_one_own_failed_registration_epoch_allows_retry():
    value = manifest()
    consent = Consent()
    consent.grant(value)
    runtime = FakeRuntime()
    runtime.fail_advances = [1]
    rig = Rig([hint(value)], consent=consent, runtime=runtime)
    assert rig.controller.restore() == (value.id,)
    placeholder = rig.registry.get("boat_report")
    with pytest.raises(RestoredCommandError, match="restored_command_activation_failed"):
        await placeholder.handler(owner_ctx())
    assert rig.controller._rows[value.id].expected_epoch == 1
    assert runtime.dispatch_calls == []
    assert await placeholder.handler(owner_ctx()) == "Report: today"
    assert [call[3] for call in runtime.activate_calls] == [0, 1]


@pytest.mark.asyncio
async def test_unexpected_epoch_advance_invalidates_and_removes_placeholder():
    value = manifest()
    consent = Consent()
    consent.grant(value)
    runtime = FakeRuntime()
    runtime.fail_advances = [2]
    rig = Rig([hint(value)], consent=consent, runtime=runtime)
    assert rig.controller.restore() == (value.id,)
    placeholder = rig.registry.get("boat_report")
    with pytest.raises(RestoredCommandError, match="restored_command_superseded"):
        await placeholder.handler(owner_ctx())
    assert value.id not in rig.controller._rows
    assert rig.registry.get("boat_report") is None
    assert runtime.dispatch_calls == []


@pytest.mark.asyncio
async def test_forget_during_registration_fences_epoch_and_late_activation():
    value = manifest()
    consent = Consent()
    consent.grant(value)
    runtime = FakeRuntime()
    runtime.registration_started = asyncio.Event()
    runtime.registration_release = asyncio.Event()
    rig = Rig([hint(value)], consent=consent, runtime=runtime)
    assert rig.controller.restore() == (value.id,)
    placeholder = rig.registry.get("boat_report")
    task = asyncio.create_task(placeholder.handler(owner_ctx()))
    await asyncio.wait_for(runtime.registration_started.wait(), 2)
    assert rig.controller.forget(value.id)
    assert runtime._activation_epochs[value.id] == 2
    runtime.registration_release.set()
    with pytest.raises(RestoredCommandError):
        await task
    assert runtime._active.get(value.id) is None
    assert runtime.dispatch_calls == []
    assert rig.registry.get("boat_report") is None


@pytest.mark.asyncio
async def test_late_cleanup_retires_only_exact_activation_not_external_replacement():
    value = manifest()
    consent = Consent()
    consent.grant(value)
    runtime = FakeRuntime()
    runtime.registration_started = asyncio.Event()
    runtime.registration_release = asyncio.Event()
    runtime.publish_before_wait = True
    rig = Rig([hint(value)], consent=consent, runtime=runtime)
    assert rig.controller.restore() == (value.id,)
    placeholder = rig.registry.get("boat_report")
    task = asyncio.create_task(placeholder.handler(owner_ctx()))
    await asyncio.wait_for(runtime.registration_started.wait(), 2)
    external = object()
    runtime._active[value.id] = external
    rig.controller.forget(value.id)
    runtime.registration_release.set()
    with pytest.raises(RestoredCommandError):
        await task
    assert runtime._active[value.id] is external
    assert runtime.deactivate_calls == []
    assert runtime.dispatch_calls == []


@pytest.mark.asyncio
async def test_consent_change_during_dispatch_suppresses_late_result():
    value = manifest()
    consent = Consent()
    consent.grant(value)
    runtime = FakeRuntime()
    runtime.dispatch_started = asyncio.Event()
    runtime.dispatch_release = asyncio.Event()
    rig = Rig([hint(value)], consent=consent, runtime=runtime)
    assert rig.controller.restore() == (value.id,)
    placeholder = rig.registry.get("boat_report")
    task = asyncio.create_task(placeholder.handler(owner_ctx()))
    await asyncio.wait_for(runtime.dispatch_started.wait(), 2)
    consent.grant(value, "c" * 64)
    runtime.dispatch_release.set()
    with pytest.raises(RestoredCommandError):
        await task
    assert len(runtime.dispatch_calls) == 1


@pytest.mark.asyncio
async def test_provider_replacement_and_runtime_epoch_change_fence_queued_callbacks():
    value = manifest()
    consent = Consent()
    consent.grant(value)
    runtime = FakeRuntime()
    rig = Rig([hint(value)], consent=consent, runtime=runtime)
    assert rig.controller.restore() == (value.id,)
    placeholder = rig.registry.get("boat_report")
    assert await placeholder.handler(owner_ctx()) == "Report: today"
    activation = runtime._active[value.id]

    replacement = FakeRuntime()
    rig.runtime = replacement
    with pytest.raises((RestoredCommandError, CommandBindingError)):
        await placeholder.handler(owner_ctx())
    assert replacement.activate_calls == [] and replacement.dispatch_calls == []
    assert runtime._active[value.id] is activation

    # Restore provider, then an external epoch mutation invalidates the captured route.
    rig.runtime = runtime
    runtime._activation_epochs[value.id] += 1
    with pytest.raises((RestoredCommandError, CommandBindingError)):
        await placeholder.handler(owner_ctx())
    assert runtime.dispatch_calls == [("boat_report", "today", activation)]


def test_restore_does_not_read_hint_for_legacy_consent_without_forward_hint():
    value = manifest()
    consent = Consent()
    consent.grant(value)
    rig = Rig([], consent=consent)
    assert rig.controller.restore() == ()
    assert rig.registry.get("boat_report") is None
    assert rig.provider_calls == 0


@pytest.mark.asyncio
async def test_forget_during_late_cleanup_cannot_retire_replacement_activation():
    value = manifest()
    consent = Consent()
    consent.grant(value)
    runtime = FakeRuntime()
    runtime.registration_started = asyncio.Event()
    runtime.registration_release = asyncio.Event()
    runtime.publish_before_wait = True
    runtime.deactivate_started = asyncio.Event()
    runtime.deactivate_release = asyncio.Event()
    rig = Rig([hint(value)], consent=consent, runtime=runtime)
    assert rig.controller.restore() == (value.id,)
    placeholder = rig.registry.get("boat_report")
    task = asyncio.create_task(placeholder.handler(owner_ctx()))
    await asyncio.wait_for(runtime.registration_started.wait(), 2)
    rig.controller.forget(value.id)
    runtime.registration_release.set()
    await asyncio.wait_for(runtime.deactivate_started.wait(), 2)
    external = object()
    runtime._active[value.id] = external
    runtime.deactivate_release.set()
    with pytest.raises(RestoredCommandError):
        await task
    assert runtime._active[value.id] is external
    assert len(runtime.deactivate_calls) == 1
    assert runtime.deactivate_calls[0][0] == value.id
    assert runtime.deactivate_calls[0][1] is not external


@pytest.mark.asyncio
async def test_forget_preserves_external_activation_commands_and_epoch():
    value = manifest()
    consent = Consent()
    consent.grant(value)
    runtime = FakeRuntime()
    rig = Rig([hint(value)], consent=consent, runtime=runtime)
    assert rig.controller.restore() == (value.id,)
    placeholder = rig.registry.get("boat_report")

    external_activation = FakeActivation(value, PACKAGE_HASH, REVISION, 1)
    runtime._activation_epochs[value.id] = 1
    runtime._active[value.id] = external_activation

    async def external_invoke(_name, _ctx):
        return "external"

    external_binding = rig.bindings.install(value, external_invoke)[0]
    with pytest.raises(CommandBindingError):
        await placeholder.handler(owner_ctx())
    assert rig.controller.forget(value.id)
    assert runtime._active[value.id] is external_activation
    assert runtime._activation_epochs[value.id] == 1
    assert rig.bindings.registrations[value.id] == (external_binding,)
    assert rig.registry.get("boat_report") is external_binding
    assert rig.runtime.activate_calls == [] and rig.runtime.dispatch_calls == []


@pytest.mark.asyncio
async def test_forget_after_lazy_activation_preserves_external_replacement():
    value = manifest()
    consent = Consent()
    consent.grant(value)
    runtime = FakeRuntime()
    rig = Rig([hint(value)], consent=consent, runtime=runtime)
    assert rig.controller.restore() == (value.id,)
    placeholder = rig.registry.get("boat_report")
    assert await placeholder.handler(owner_ctx()) == "Report: today"
    own_epoch = runtime._activation_epochs[value.id]

    external_activation = FakeActivation(value, PACKAGE_HASH, REVISION, own_epoch + 1)
    runtime._activation_epochs[value.id] = own_epoch + 1
    runtime._active[value.id] = external_activation

    async def external_invoke(_name, _ctx):
        return "external"

    external_binding = rig.bindings.install(value, external_invoke)[0]
    with pytest.raises(CommandBindingError):
        await placeholder.handler(owner_ctx())
    assert rig.controller.forget(value.id)
    assert runtime._active[value.id] is external_activation
    assert runtime._activation_epochs[value.id] == own_epoch + 1
    assert rig.bindings.registrations[value.id] == (external_binding,)
    assert rig.registry.get("boat_report") is external_binding
