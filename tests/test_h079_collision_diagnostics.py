"""H079 skill command projections report only aggregate command-name collisions."""

import logging
from types import SimpleNamespace

from agents.core import command_discovery, command_shortcuts, settings_db
from agents.core.channels.skill_menu import project_skill_menu
from agents.core.commands import Principal, build_default_registry
from agents.core.skills import bundles
from tests.test_h026_skill_bundles import _hub, _md_skill, isolated  # noqa: F401

_DIAGNOSTIC = "Skill command collision refusals: %d"


def diagnostics(caplog):
    return [record for record in caplog.records if record.msg == _DIAGNOSTIC]


def test_commands_logs_one_count_for_canonical_alias_and_telegram_wire(tmp_path, monkeypatch, caplog):
    canonical = _md_skill("pending")
    canonical.name = "status"
    alias = _md_skill("notes")
    alias.name = "h"
    wire = _md_skill("athena only")
    orch, _ = _hub(tmp_path, monkeypatch, canonical, alias, wire, _md_skill("weather"))
    settings_db.put_category("commands", {"quick_commands": {
        "athena_only": {"type": "alias", "target": "/help"}}})
    ctx = SimpleNamespace(args="", orch=orch,
                          principal=Principal(channel="telegram", admin=True, scope="dm"))
    try:
        with caplog.at_level(logging.WARNING):
            text = command_discovery.reply(ctx)
        assert text.startswith("Commands — page 1/")
        assert [record.args for record in diagnostics(caplog)] == [(3,)]
        assert all(name not in caplog.text for name in ("athena only", "athena_only", "status", "PRIVATE"))
        caplog.clear()
        orch.skills.skills = {"weather": orch.skills.skills["weather"]}
        command_discovery.reply(ctx)
        assert diagnostics(caplog) == []
    finally:
        orch.checkpoints.close()


def test_web_shortcuts_log_only_taken_skill_names(monkeypatch, caplog):
    class Loader:
        def __init__(self, *names):
            self.skills = {name: SimpleNamespace(name=name, path=None,
                                                 description="PRIVATE BODY") for name in names}

        def catalog_gate(self, skill):
            return ""

    monkeypatch.setattr(command_shortcuts, "_quick_inventory", lambda: {
        "privatealias": {"type": "alias", "target": "/help"}})
    monkeypatch.setattr(bundles, "snapshot", lambda: ([], []))
    loader = Loader("status", "h", "privatealias", "notes")
    with caplog.at_level(logging.WARNING):
        result = command_shortcuts.project(build_default_registry(), loader, slots=32)
    assert ("skill", "notes") in {(row["kind"], row["name"]) for row in result.rows}
    assert [record.args for record in diagnostics(caplog)] == [(3,)]
    assert all(secret not in caplog.text for secret in ("privatealias", "PRIVATE BODY", "/help"))
    caplog.clear()
    command_shortcuts.project(build_default_registry(), Loader("notes"), slots=32)
    assert diagnostics(caplog) == []


def test_native_menu_logs_only_taken_candidates_and_preserves_hidden_count(
        tmp_path, monkeypatch, caplog):
    canonical = _md_skill("pending")
    canonical.name = "status"
    alias = _md_skill("notes")
    alias.name = "h"
    wire = _md_skill("athena only")
    orch, _ = _hub(tmp_path, monkeypatch, canonical, alias, wire, _md_skill("weather"))
    settings_db.put_category("commands", {"quick_commands": {
        "athena_only": {"type": "alias", "target": "/help"}}})
    try:
        with caplog.at_level(logging.WARNING):
            result = project_skill_menu(orch.skills, platform="telegram", slots=62,
                                        taken=orch._command_name_taken)
        assert [entry.name for entry in result.entries] == ["weather"]
        assert result.hidden_count == 3
        assert [record.args for record in diagnostics(caplog)] == [(3,)]
        assert all(name not in caplog.text for name in ("athena only", "athena_only", "status"))
        caplog.clear()
        orch.skills.skills = {"weather": orch.skills.skills["weather"]}
        project_skill_menu(orch.skills, platform="telegram", slots=62,
                           taken=orch._command_name_taken, reserved={"weather"})
        assert diagnostics(caplog) == []  # Reserved/capacity omissions are not command collisions.
    finally:
        orch.checkpoints.close()


def test_guest_commands_never_read_skill_inventory_or_log_collisions(monkeypatch, caplog):
    class Poison:
        @property
        def skills(self):
            raise AssertionError("guest skill inventory read")

    def forbidden():
        raise AssertionError("guest bundle inventory read")

    monkeypatch.setattr(bundles, "list_bundles", forbidden)
    ctx = SimpleNamespace(args="", orch=SimpleNamespace(commands=build_default_registry(),
                                                         skills=Poison()),
                          principal=Principal(channel="web", admin=False, scope="dm"))
    with caplog.at_level(logging.WARNING):
        result = command_discovery.reply(ctx)
    assert "Commands — page" in result
    assert diagnostics(caplog) == []
