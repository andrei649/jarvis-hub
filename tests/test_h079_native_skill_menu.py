"""Native skill pickers advertise only owner-routable, catalog-readable names."""

import pytest

from agents.core import settings_db
from agents.core.channels.skill_menu import project_skill_menu
from tests.test_h026_skill_bundles import _hub, _md_skill, _write, isolated  # noqa: F401


def test_telegram_rewrites_skill_name_only_when_wire_spelling_still_resolves(tmp_path, monkeypatch):
    orch, _ = _hub(tmp_path, monkeypatch, _md_skill("athena only"), _md_skill("weather"))
    projection = project_skill_menu(orch.skills, platform="telegram", slots=62,
                                    taken=orch._command_name_taken)
    assert [entry.name for entry in projection.entries] == ["athena_only", "weather"]
    assert [entry.skill_name for entry in projection.entries] == ["athena only", "weather"]
    assert projection.unavailable is False
    orch.checkpoints.close()


def test_native_projection_honors_platform_switches_and_hard_gates(tmp_path, monkeypatch):
    from agents.core.skills import visibility

    pending = _md_skill("pending", pending=True)
    unsupported = _md_skill("notes")
    unsupported.manifest["platforms"] = ["macos"]
    monkeypatch.setattr(visibility, "host_platforms", lambda platform=None: frozenset({"linux"}))
    orch, _ = _hub(tmp_path, monkeypatch, _md_skill("weather"), _md_skill("news"), pending, unsupported)
    settings_db.put_category("skills", {"channel_disabled": {"telegram": ["weather"]}})
    tg = project_skill_menu(orch.skills, platform="telegram", slots=62, taken=orch._command_name_taken)
    discord = project_skill_menu(orch.skills, platform="discord", slots=62, taken=orch._command_name_taken)
    assert [entry.name for entry in tg.entries] == ["news"]
    assert [entry.name for entry in discord.entries] == ["news", "weather"]
    orch.checkpoints.close()


def test_projection_keeps_registry_quick_bundle_and_wire_collisions_out(tmp_path, monkeypatch):
    command = _md_skill("weather")
    command.name = "status"
    alias = _md_skill("news")
    alias.name = "h"
    quick = _md_skill("notes")
    quick.name = "forecast"
    bundle = _md_skill("pending")
    bundle.name = "morning"
    telegram = _md_skill("athena only")
    orch, _ = _hub(tmp_path, monkeypatch, command, alias, quick, bundle, telegram)
    settings_db.put_category("commands", {"quick_commands": {
        "forecast": {"type": "alias", "target": "/help"},
        "athena_only": {"type": "alias", "target": "/help"}}})
    _write(tmp_path, "morning.yaml", "name: Morning\nskills: [pending]\n")
    tg = project_skill_menu(orch.skills, platform="telegram", slots=62, taken=orch._command_name_taken)
    assert tg.entries == ()
    assert tg.hidden_count == 5
    orch.checkpoints.close()


def test_malformed_quick_configuration_still_reserves_its_skill_name(tmp_path, monkeypatch):
    orch, _ = _hub(tmp_path, monkeypatch, _md_skill("weather"))
    settings_db.put_category("commands", {"quick_commands": {"weather": {"type": "invalid"}}})
    projected = project_skill_menu(orch.skills, platform="telegram", slots=62,
                                   taken=orch._command_name_taken)
    assert projected.entries == () and projected.hidden_count == 1
    orch.checkpoints.close()


def test_native_cap_keeps_stable_first_skill_and_counts_hidden(tmp_path, monkeypatch):
    orch, _ = _hub(tmp_path, monkeypatch, _md_skill("weather"), _md_skill("news"), _md_skill("notes"))
    projected = project_skill_menu(orch.skills, platform="discord", slots=1,
                                   taken=orch._command_name_taken)
    assert [entry.name for entry in projected.entries] == ["news"]
    assert projected.hidden_count == 2
    assert project_skill_menu(orch.skills, platform="discord", slots=-1,
                              taken=orch._command_name_taken).unavailable
    orch.checkpoints.close()


def test_owner_telegram_menu_adds_skills_but_guest_menu_does_not(tmp_path, monkeypatch):
    from agents import web

    monkeypatch.delenv("AUTONOMY_OWNER_CHAT_ID", raising=False)
    orch, seen = _hub(tmp_path, monkeypatch, _md_skill("athena only"))
    seen.values["autonomy.owner_chat_id"] = "42"
    everyone, owner = web._telegram_command_menus(orch)
    assert not any(row["command"] == "athena_only" for row in everyone)
    assert owner is not None and owner[0] == 42
    assert any(row["command"] == "athena_only" for row in owner[1])
    orch.checkpoints.close()
