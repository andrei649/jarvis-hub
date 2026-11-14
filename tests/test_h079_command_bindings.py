"""Exact command ownership and direct-handler authorization regressions."""
from __future__ import annotations

import pytest

from agents.core.commands import (
    ADMIN,
    CommandContext,
    CommandRegistry,
    Principal,
    SlashCommand,
    build_default_registry,
)
from agents.core.extensions.command_bindings import CommandBindingError, ExtensionCommandBindings
from agents.core.extensions.manifest import ExtensionManifest


def manifest(extension_id="boats", commands=("boat_report",), requires=()):
    return ExtensionManifest(extension_id, "1.0.0", ("commands",), (), tuple(commands), (), (), (),
                             tuple(requires))


def test_install_records_exact_owner_objects_and_argument_metadata():
    registry = CommandRegistry()
    bindings = ExtensionCommandBindings(registry)
    installed = bindings.install(
        manifest(commands=("boat_report", "boat_detail"), requires=("boat_report",)),
        lambda _name, _ctx: _async_result("ok"),
    )

    assert len(installed) == 2
    assert bindings.registrations["boats"] == installed
    assert bindings.current("boats")
    report = registry.get("boat_report")
    assert report is installed[0] and report.tier == ADMIN
    assert report.requires_args and report.usage == "<arguments>"
    assert registry.get("boat-report") is report
    detail = registry.get("boat_detail")
    assert detail is installed[1] and not detail.requires_args and detail.usage == "[arguments]"
    assert bindings.remove("boats") is True
    assert registry.get("boat_report") is None and registry.get("boat-report") is None
    assert not bindings.current("boats")
    assert bindings.remove("boats") is False


async def _async_result(value):
    return value


@pytest.mark.asyncio
async def test_registry_and_direct_handler_both_refuse_guest_before_invoking():
    registry = CommandRegistry()
    bindings = ExtensionCommandBindings(registry)
    calls = []

    async def invoke(name, ctx):
        calls.append((name, ctx.args))
        return "ok"

    command = bindings.install(manifest(), invoke)[0]
    guest = Principal(admin=False)
    outcome = await registry.dispatch("/boat_report private", orch=None, principal=guest)
    assert outcome is not None and outcome.status == "refused"
    assert calls == []

    direct = await command.handler(CommandContext(None, guest, "boat_report", "private"))
    assert direct == "This extension command requires the owner."
    assert calls == []


@pytest.mark.asyncio
async def test_owner_handler_checks_current_ownership_then_sanitizes_media_reply():
    registry = CommandRegistry()
    bindings = ExtensionCommandBindings(registry)
    calls = []

    async def invoke(name, ctx):
        calls.append((name, ctx.args))
        return "MEDIA: /tmp/export\nsafe\x00"

    command = bindings.install(manifest(), invoke)[0]
    ctx = CommandContext(None, Principal(admin=True), "boat_report", "today")
    assert await command.handler(ctx) == "> MEDIA: /tmp/export\nsafe"
    assert calls == [("boat_report", "today")]

    bindings.remove("boats")
    with pytest.raises(CommandBindingError, match="command_not_owned"):
        await command.handler(ctx)
    assert calls == [("boat_report", "today")]


@pytest.mark.asyncio
async def test_captured_old_handler_cannot_run_after_same_id_reinstall():
    registry = CommandRegistry()
    bindings = ExtensionCommandBindings(registry)
    old_calls, new_calls = [], []

    async def old_invoke(name, ctx):
        old_calls.append((name, ctx.args))
        return "old"

    async def new_invoke(name, ctx):
        new_calls.append((name, ctx.args))
        return "new"

    old_command = bindings.install(manifest(), old_invoke)[0]
    captured_old_handler = old_command.handler
    new_command = bindings.install(manifest(), new_invoke)[0]
    assert new_command is not old_command and bindings.current("boats")
    ctx = CommandContext(None, Principal(admin=True), "boat_report", "today")

    with pytest.raises(CommandBindingError, match="command_not_owned"):
        await captured_old_handler(ctx)
    assert old_calls == [] and new_calls == []
    assert await new_command.handler(ctx) == "new"
    assert old_calls == [] and new_calls == [("boat_report", "today")]


def test_check_blocks_core_reserved_alias_quick_and_hyphen_spelling_collisions(monkeypatch):
    from agents.core import quick_commands

    registry = build_default_registry()
    bindings = ExtensionCommandBindings(registry, reserved_commands=lambda: ("reserved_command",))
    for name in ("help", "reserved_command", "nerva", "h"):
        with pytest.raises(CommandBindingError, match="command_collision"):
            bindings.check(manifest(commands=(name,)))

    monkeypatch.setattr(quick_commands, "named", lambda name: name == "boat-report")
    with pytest.raises(CommandBindingError, match="command_collision"):
        bindings.check(manifest(commands=("boat_report",)))


def test_install_prechecks_complete_set_before_claiming_any_name():
    registry = CommandRegistry()
    foreign = registry.register(SlashCommand("boat_two", "foreign", lambda _ctx: "foreign"))
    bindings = ExtensionCommandBindings(registry)
    with pytest.raises(CommandBindingError, match="command_collision"):
        bindings.install(manifest(commands=("boat_one", "boat_two")),
                         lambda _name, _ctx: _async_result("unused"))
    assert registry.get("boat_one") is None
    assert registry.get("boat_two") is foreign
    assert bindings.registrations == {}


def test_invalid_registry_or_reserved_provider_fails_as_commands_unavailable():
    with pytest.raises(CommandBindingError, match="commands_unavailable"):
        ExtensionCommandBindings(None).check(manifest())
    with pytest.raises(CommandBindingError, match="commands_unavailable"):
        ExtensionCommandBindings(CommandRegistry(), reserved_commands=lambda: 7).check(manifest())


def test_foreign_replacement_fails_current_and_remove_never_removes_foreign():
    registry = CommandRegistry()
    bindings = ExtensionCommandBindings(registry)
    owned = bindings.install(manifest(), lambda _name, _ctx: _async_result("owned"))[0]
    foreign = SlashCommand("boat_report", "foreign", lambda _ctx: "foreign", tier=ADMIN)
    registry._commands["boat_report"] = foreign

    assert not bindings.current("boats")
    with pytest.raises(CommandBindingError, match="command_collision"):
        bindings.install(manifest(), lambda _name, _ctx: _async_result("new"))
    assert bindings.remove("boats")
    assert registry.get("boat_report") is foreign
    assert registry.get("boat-report") is None
    assert owned not in bindings.registrations.get("boats", ())


def test_partial_registration_failure_rolls_back_only_fresh_exact_objects(monkeypatch):
    registry = CommandRegistry()
    bindings = ExtensionCommandBindings(registry)
    original_register = registry.register
    attempted = []

    def register_then_fail_second(command):
        attempted.append(command)
        registered = original_register(command)
        if len(attempted) == 2:
            raise RuntimeError("untrusted registrar detail")
        return registered

    monkeypatch.setattr(registry, "register", register_then_fail_second)
    with pytest.raises(CommandBindingError, match="command_registration_failed"):
        bindings.install(manifest(commands=("boat_one", "boat_two")),
                         lambda _name, _ctx: _async_result("unused"))

    assert bindings.registrations == {}
    assert registry.get("boat_one") is None and registry.get("boat_two") is None
    assert len(attempted) == 2


def test_partial_failure_cleanup_preserves_foreign_replacement():
    registry = CommandRegistry()
    bindings = ExtensionCommandBindings(registry)
    original_register = registry.register
    attempted = []
    foreign = SlashCommand("boat_two", "foreign", lambda _ctx: "foreign", tier=ADMIN)

    def register_then_replace_and_fail(command):
        attempted.append(command)
        original_register(command)
        if len(attempted) == 2:
            registry._commands[command.name] = foreign
            raise RuntimeError("failure after foreign replacement")
        return command

    registry.register = register_then_replace_and_fail
    with pytest.raises(CommandBindingError, match="command_registration_failed"):
        bindings.install(manifest(commands=("boat_one", "boat_two")),
                         lambda _name, _ctx: _async_result("unused"))

    assert registry.get("boat_one") is None
    assert registry.get("boat_two") is foreign
    assert bindings.registrations == {}
