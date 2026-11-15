"""Native discovery must redact whole metadata before provider length limits."""
from types import SimpleNamespace

import pytest

from agents.core.channels import outbound_safety
from agents.core.channels.discord_commands import project_commands
from agents.core.channels.skill_menu import project_skill_menu
from agents.core.commands import SlashCommand, slack_native_slashes, telegram_menu
from tests.test_h026_skill_bundles import _hub, _md_skill, isolated  # noqa: F401


def _command(*, name, description):
    return SlashCommand(name, description, lambda _ctx: "")


@pytest.mark.parametrize("platform", ["telegram", "discord", "slack"])
def test_native_command_description_redacts_before_truncation(platform, monkeypatch):
    secret = "private-custom-" + "x" * 290
    monkeypatch.setattr(outbound_safety, "_known_redactor", lambda text: text.replace(secret, "[REDACTED]"))
    command = _command(name="weather", description="Read " + secret)
    if platform == "telegram":
        result = telegram_menu([command])[0]["description"]
    elif platform == "slack":
        result = slack_native_slashes(SimpleNamespace(commands=lambda: [command], get=lambda _: None))[1]["description"]
    else:
        result = project_commands(SimpleNamespace(commands=lambda: [command])).entries[0].description
    assert "private-custom" not in result and "[REDACTED]" in result


@pytest.mark.parametrize("platform", ["telegram", "discord"])
def test_skill_description_is_redacted_before_whitespace_and_length(platform, tmp_path, monkeypatch):
    secret = "private  custom\n" + "x" * 290
    monkeypatch.setattr(outbound_safety, "_known_redactor", lambda text: text.replace(secret, "[REDACTED]"))
    skill = _md_skill("weather")
    skill.manifest["description"] = "Read " + secret
    orch, _ = _hub(tmp_path, monkeypatch, skill)
    try:
        result = project_skill_menu(orch.skills, platform=platform, slots=1,
                                    taken=orch._command_name_taken).entries[0]
        assert "private" not in result.description and "[REDACTED]" in result.description
    finally:
        orch.checkpoints.close()


def test_secret_command_names_are_hidden_not_renamed(monkeypatch):
    monkeypatch.setattr(outbound_safety, "_known_redactor", lambda text: text.replace("privatekey", "[REDACTED]"))
    command = _command(name="privatekey", description="A command")
    assert telegram_menu([command]) == []
    projected = project_commands(SimpleNamespace(commands=lambda: [command]))
    assert projected.entries == () and projected.hidden_count == 1


def test_secret_skill_name_is_checked_before_slugging(tmp_path, monkeypatch):
    monkeypatch.setattr(outbound_safety, "_known_redactor", lambda text: text.replace("Private Key", "[REDACTED]"))
    skill = _md_skill("weather")
    skill.name = "Private Key"
    orch, _ = _hub(tmp_path, monkeypatch, skill)
    try:
        result = project_skill_menu(orch.skills, platform="telegram", slots=1,
                                    taken=orch._command_name_taken)
        assert result.entries == () and result.hidden_count == 1
    finally:
        orch.checkpoints.close()


def test_redactor_failure_withholds_native_names(monkeypatch):
    def failed(_text):
        raise RuntimeError("redactor unavailable")
    monkeypatch.setattr(outbound_safety, "_known_redactor", failed)
    command = _command(name="weather", description="A command")
    assert telegram_menu([command]) == []
    assert project_commands(SimpleNamespace(commands=lambda: [command])).entries == ()


def test_slack_alias_metadata_also_masks_full_description(monkeypatch):
    secret = "private-custom-" + "x" * 290
    monkeypatch.setattr(outbound_safety, "_known_redactor", lambda text: text.replace(secret, "[REDACTED]"))
    command = _command(name="help", description=secret)
    registry = SimpleNamespace(commands=lambda: [command], get=lambda name: command if name == "help" else None)
    entries = slack_native_slashes(registry)
    aliases = [row for row in entries if row["command"] not in {"/help", "/nerva"}]
    assert aliases
    assert all("private-custom" not in row["description"] and "[REDACTED]" in row["description"] for row in aliases)


def test_slack_hides_secret_names_preserving_fixed_fallback(monkeypatch):
    monkeypatch.setattr(outbound_safety, "_known_redactor", lambda text: text.replace("privatekey", "[REDACTED]"))
    command = _command(name="privatekey", description="A command")
    entries = slack_native_slashes(SimpleNamespace(commands=lambda: [command], get=lambda _: None))
    assert [row["command"] for row in entries] == ["/nerva"]
