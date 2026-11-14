"""Acquisition composition boundaries for lazy extension command restoration."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import safe_mode
from agents.core.acquisition.runtime import AcquisitionRuntime
from agents.core.commands import CommandRegistry, Principal
from agents.core.extensions.activation_hints import (
    ActivationHint,
    ActivationHintStoreError,
)
from agents.core.extensions.consent import declared_digest
from agents.core.extensions.manifest import ExtensionManifest

REVISION = "a" * 64
PACKAGE_HASH = "b" * 64


def manifest():
    return ExtensionManifest("boats", "1.0.0", ("commands",), (), ("boat_report",), (), (), (), ())


class ConsentStub:
    def __init__(self, descriptor):
        self.descriptor = descriptor
        self.calls = 0

    def check(self, candidate):
        self.calls += 1
        return SimpleNamespace(allowed=True, digest=declared_digest(candidate), grant_revision=REVISION)


class HintsStub:
    def __init__(self, descriptor):
        self.rows = [ActivationHint(descriptor, PACKAGE_HASH, declared_digest(descriptor), REVISION)]
        self.read_calls = 0
        self.remove_calls = []
        self.remove_error = None

    def read_all(self):
        self.read_calls += 1
        return tuple(self.rows)

    def remove(self, extension_id):
        self.remove_calls.append(extension_id)
        if self.remove_error is not None:
            raise self.remove_error
        before = len(self.rows)
        self.rows = [row for row in self.rows if row.manifest.id != extension_id]
        return len(self.rows) != before


class FakeExtensionRuntime:
    def __init__(self, bindings, descriptor):
        self.command_bindings = bindings
        self.descriptor = descriptor
        self._active = {}
        self._activation_epochs = {}
        self.status = {"state": "saved"}

    async def activate(self, candidate, *, expected_package_hash, expected_grant_revision, expected_epoch):
        assert expected_package_hash == PACKAGE_HASH
        assert expected_grant_revision == REVISION
        assert expected_epoch == self._activation_epochs.get(candidate.id, 0)
        self._activation_epochs[candidate.id] = expected_epoch + 1
        activation = SimpleNamespace(manifest=candidate, package_hash=PACKAGE_HASH, version=candidate.version)
        self._active[candidate.id] = activation

        async def active_invoke(_name, _ctx):
            return "active handler"

        self.command_bindings.install(candidate, active_invoke)
        return activation

    async def dispatch_command(self, name, args, *, expected_activation):
        assert self._active[expected_activation.manifest.id] is expected_activation
        return f"handled:{name}:{args}"

    async def deactivate(self, extension_id):
        self._activation_epochs[extension_id] = self._activation_epochs.get(extension_id, 0) + 1
        self._active.pop(extension_id, None)
        self.command_bindings.remove(extension_id)
        self.status = {"state": "removed"}
        return True

    def restoration_status(self, _extension_id):
        return dict(self.status)


def make_runtime(tmp_path, *, enabled=True, descriptor=None, hints=None, consent=None):
    descriptor = descriptor or manifest()
    registry = CommandRegistry()
    consent = consent or ConsentStub(descriptor)
    hints = hints or HintsStub(descriptor)
    runtime = AcquisitionRuntime(
        enabled=lambda: enabled,
        root=tmp_path / "acquisition",
        commands=registry,
        extension_consent=consent,
        activation_hints=hints,
    )
    return runtime, registry, consent, hints


def test_restore_is_metadata_only_and_repeated_call_preserves_lazy_runtime_binding(tmp_path):
    descriptor = manifest()
    runtime, registry, consent, hints = make_runtime(tmp_path, descriptor=descriptor)
    promotion_calls = []
    runtime.ensure_promotion = lambda: promotion_calls.append("promotion")

    assert runtime.restore_extension_commands() == ("boats",)
    placeholder = registry.get("boat_report")
    assert placeholder is not None and runtime.extension_runtime is None
    assert runtime.package_store is None and runtime.sandbox_profile is None
    assert promotion_calls == []
    assert not (tmp_path / "acquisition").exists()
    assert hints.read_calls == 1 and consent.calls >= 1

    active = FakeExtensionRuntime(runtime.command_bindings, descriptor)
    runtime.extension_runtime = active
    active._active["boats"] = SimpleNamespace(manifest=descriptor)
    active._activation_epochs["boats"] = 1
    active.command_bindings.install(descriptor, lambda _name, _ctx: _async_text("active"))
    live = registry.get("boat_report")
    assert live is not placeholder
    assert runtime.restore_extension_commands() == ("boats",)
    assert registry.get("boat_report") is live
    assert promotion_calls == []


async def _async_text(value):
    return value


@pytest.mark.asyncio
async def test_guest_does_not_compose_but_owner_first_command_composes_once(tmp_path, monkeypatch):
    descriptor = manifest()
    runtime, registry, _consent, _hints = make_runtime(tmp_path, descriptor=descriptor)
    promotion_calls, provider_calls = [], []
    active = FakeExtensionRuntime(runtime._ensure_extension_bindings(), descriptor)

    def ensure_promotion():
        promotion_calls.append("promotion")
        runtime.package_store = object()
        runtime.sandbox_profile = object()
        runtime.promotion_broker = object()
        return runtime.promotion_broker

    def extensions():
        provider_calls.append("extensions")
        runtime.extension_runtime = active
        return active

    runtime.ensure_promotion = ensure_promotion
    runtime.extensions = extensions
    assert runtime.restore_extension_commands() == ("boats",)

    guest = await registry.dispatch("/boat_report secret", orch=None, principal=Principal(admin=False))
    assert guest.status == "refused"
    assert promotion_calls == [] and provider_calls == []

    owner = await registry.dispatch("/boat_report today", orch=None, principal=Principal(admin=True))
    assert owner.status == "answered" and owner.reply == "handled:boat_report:today"
    assert promotion_calls == ["promotion"]
    assert provider_calls
    assert registry.get("boat_report") is not None
    assert runtime.extension_runtime is active
    # Calling startup composition again after lazy promotion must not reset handlers.
    live = registry.get("boat_report")
    assert runtime.restore_extension_commands() == ("boats",)
    assert registry.get("boat_report") is live


@pytest.mark.asyncio
async def test_uncomposed_deactivation_removes_hint_without_provider_and_reports_status(tmp_path):
    runtime, registry, _consent, hints = make_runtime(tmp_path)
    ensure_calls = []
    runtime.ensure_promotion = lambda: ensure_calls.append("promotion")

    assert await runtime.deactivate_extension("boats") is True
    assert hints.remove_calls == ["boats"] and hints.rows == []
    assert runtime.extension_runtime is None
    assert registry.commands() == []
    assert ensure_calls == []
    assert runtime.extension_restoration_status("boats") == {"state": "removed"}
    assert not (tmp_path / "acquisition").exists()


@pytest.mark.asyncio
async def test_uncomposed_hint_removal_failure_is_reported_without_claiming_removed(tmp_path):
    hints = HintsStub(manifest())
    hints.remove_error = ActivationHintStoreError("activation_hints_corrupt")
    runtime, _registry, _consent, _ = make_runtime(tmp_path, hints=hints)
    runtime.ensure_promotion = lambda: pytest.fail("must not compose during uncomposed removal")

    assert await runtime.deactivate_extension("boats") is False
    assert runtime.extension_restoration_status("boats") == {
        "state": "remove_failed", "reason": "activation_hints_corrupt",
    }
    assert runtime.extension_runtime is None


@pytest.mark.asyncio
async def test_composed_runtime_failure_cannot_leave_a_stale_saved_status(tmp_path):
    runtime, _registry, _consent, _hints = make_runtime(tmp_path)

    class FailingRuntime:
        def restoration_status(self, _extension_id):
            return {"state": "saved"}

        async def deactivate(self, _extension_id):
            raise RuntimeError("raw detail is not a persistence status")

    runtime.extension_runtime = FailingRuntime()
    assert runtime.extension_restoration_status("boats") == {"state": "saved"}
    assert await runtime.deactivate_extension("boats") is False
    assert runtime.extension_restoration_status("boats") == {
        "state": "remove_failed", "reason": "activation_hints_unavailable",
    }


def test_disabled_and_safe_mode_restore_do_not_read_or_create_or_lock(tmp_path, monkeypatch):
    disabled, _registry, _consent, disabled_hints = make_runtime(tmp_path, enabled=False)
    assert disabled.restore_extension_commands() == ()
    assert not disabled._extension_restore_attempted
    assert disabled_hints.read_calls == 0

    enabled, registry, _consent, hints = make_runtime(tmp_path)
    monkeypatch.setattr(safe_mode, "enabled", lambda: True)
    monkeypatch.setattr(safe_mode, "note", lambda _layer: None)
    assert enabled.restore_extension_commands() == ()
    assert not enabled._extension_restore_attempted
    assert hints.read_calls == 0
    assert registry.commands() == []
    assert not (tmp_path / "acquisition").exists()

    monkeypatch.setattr(safe_mode, "enabled", lambda: False)
    assert enabled.restore_extension_commands() == ("boats",)
    assert enabled._extension_restore_attempted


@pytest.mark.asyncio
async def test_retired_host_invalidates_captured_route_and_new_host_can_restore(tmp_path):
    from agents.core.extensions.command_bindings import CommandBindingError

    descriptor = manifest()
    registry = CommandRegistry()
    consent = ConsentStub(descriptor)
    hints = HintsStub(descriptor)
    old = AcquisitionRuntime(
        enabled=lambda: True,
        root=tmp_path / "acquisition",
        commands=registry,
        extension_consent=consent,
        activation_hints=hints,
    )
    assert old.restore_extension_commands() == ("boats",)
    stale = registry.get("boat_report").handler

    assert old.retire_extension_command_routes() == ("boats",)
    assert registry.get("boat_report") is None
    assert len(hints.rows) == 1  # Retirement preserves the persisted activation hint.
    with pytest.raises(CommandBindingError, match="command_not_owned"):
        await stale(SimpleNamespace(principal=Principal(admin=True)))

    new = AcquisitionRuntime(
        enabled=lambda: True,
        root=tmp_path / "acquisition",
        commands=registry,
        extension_consent=consent,
        activation_hints=hints,
    )
    assert new.restore_extension_commands() == ("boats",)
    assert registry.get("boat_report") is not None
    assert old.restore_extension_commands() == ()


def test_retirement_preserves_foreign_replacement(tmp_path):
    from agents.core.commands import ADMIN, SlashCommand

    runtime, registry, _consent, _hints = make_runtime(tmp_path)
    assert runtime.restore_extension_commands() == ("boats",)
    foreign = SlashCommand("boat_report", "foreign", lambda _ctx: "foreign", tier=ADMIN)
    # Simulate an outside host replacing the canonical slot after restore.
    registry._commands["boat_report"] = foreign

    assert runtime.retire_extension_command_routes() == ("boats",)
    assert registry.get("boat_report") is foreign


def test_extensions_remains_noncomposing_inspection_provider(tmp_path):
    runtime, _registry, _consent, _hints = make_runtime(tmp_path)
    assert runtime.extensions() is None
    assert runtime.extension_runtime is None
    assert runtime.package_store is None and runtime.sandbox_profile is None
    assert not (tmp_path / "acquisition").exists()
