"""Consented manifest argument metadata controls Telegram's native picker."""

import pytest

from agents.core.commands import (
    ADMIN,
    TELEGRAM_MENU_MAX,
    Principal,
    SlashCommand,
    build_default_registry,
    telegram_menu,
)
from agents.core.extensions.runtime import ExtensionRuntimeError
from tests.test_extension_runtime import COMMAND_EXTENSION, descriptor, rig  # noqa: F401 — fixture


def _command(name, *, required=False):
    return SlashCommand(name, "description", lambda _: "ok", requires_args=required)


def test_telegram_menu_skips_required_commands_before_cap_and_refills():
    commands = [_command(f"a{i:03d}", required=True) for i in range(60)]
    commands += [_command(f"b{i:03d}") for i in range(150)]
    projected = telegram_menu(commands)
    names = [item["command"] for item in projected]
    assert len(names) == TELEGRAM_MENU_MAX
    assert names == [f"b{i:03d}" for i in range(TELEGRAM_MENU_MAX)]


def test_existing_optional_usage_and_positional_constructor_stay_in_menu():
    positional = SlashCommand("optional", "description", lambda _: "ok", "user", "[arguments]", ())
    required = SlashCommand("required", "description", lambda _: "ok", ADMIN,
                            "<arguments>", (), True)
    assert positional.requires_args is False
    assert [item["command"] for item in telegram_menu([required, positional])] == ["optional"]
    assert "/optional [arguments] —" in positional.summary
    assert "/required <arguments> —" in required.summary


@pytest.mark.asyncio
async def test_consented_runtime_activation_marks_declared_subset_and_keeps_typed_dispatch(rig):
    registry = rig.runtime.commands = build_default_registry()
    source = COMMAND_EXTENSION.replace('["boat_report"]', '["boat_report", "boat_status"]')
    rig.packages.write(source)
    manifest = descriptor(tools=[], commands=["boat_report", "boat_status"],
                          command_requires_args=["boat_report"])
    assert registry.get("boat_report") is None
    with pytest.raises(ExtensionRuntimeError, match="consent_required"):
        await rig.runtime.activate(manifest)
    assert registry.get("boat_report") is None

    rig.consent.grant(manifest)
    activation = await rig.runtime.activate(manifest)
    assert activation.as_dict()["command_requires_args"] == ["boat_report"]
    report, status = registry.get("boat_report"), registry.get("boat_status")
    assert report is not None and status is not None
    assert report.tier == status.tier == ADMIN
    assert report.requires_args is True and report.usage == "<arguments>"
    assert status.requires_args is False and status.usage == "[arguments]"
    assert "boat_report" not in [entry["command"] for entry in telegram_menu(registry.commands())]
    assert "boat_status" in [entry["command"] for entry in telegram_menu(registry.commands())]
    guest = await registry.dispatch("/boat_report today", orch=None, principal=Principal(admin=False))
    assert guest.status == "refused"
    owner = await registry.dispatch("/boat_report today", orch=None, principal=Principal(admin=True))
    assert owner.status == "answered" and owner.reply == "Report: today"
    assert (await registry.dispatch("/boat_report", orch=None,
                                    principal=Principal(admin=True))).reply == "Report: "
    assert await rig.runtime.deactivate("boats")
    assert registry.get("boat_report") is None


@pytest.mark.asyncio
async def test_old_manifest_keeps_optional_runtime_command_in_native_menu(rig):
    registry = rig.runtime.commands = build_default_registry()
    rig.packages.write(COMMAND_EXTENSION)
    manifest = descriptor(tools=[], commands=["boat_report"])
    rig.consent.grant(manifest)
    activation = await rig.runtime.activate(manifest)
    assert activation.as_dict()["command_requires_args"] == []
    command = registry.get("boat_report")
    assert command is not None and command.requires_args is False
    assert command.usage == "[arguments]"
    assert "boat_report" in [entry["command"] for entry in telegram_menu(registry.commands())]
