"""Native discovery must redact whole metadata before provider length limits."""
from types import SimpleNamespace

import pytest

from agents.core.channels import outbound_safety
from agents.core.channels.skill_menu import project_skill_menu
from agents.core.commands import SlashCommand, telegram_menu
from tests.test_h026_skill_bundles import _hub, _md_skill, isolated  # noqa: F401


def _command(*, name, description):
    return SlashCommand(name, description, lambda _ctx: "")


def test_native_command_description_redacts_before_truncation(monkeypatch):
    secret = "private-custom-" + "x" * 290
    monkeypatch.setattr(outbound_safety, "_known_redactor", lambda text: text.replace(secret, "[REDACTED]"))
    command = _command(name="weather", description="Read " + secret)
    result = telegram_menu([command])[0]["description"]
    assert "private-custom" not in result and "[REDACTED]" in result


def test_skill_description_is_redacted_before_whitespace_and_length(tmp_path, monkeypatch):
    secret = "private  custom\n" + "x" * 290
    monkeypatch.setattr(outbound_safety, "_known_redactor", lambda text: text.replace(secret, "[REDACTED]"))
    skill = _md_skill("weather")
    skill.manifest["description"] = "Read " + secret
    orch, _ = _hub(tmp_path, monkeypatch, skill)
    try:
        result = project_skill_menu(orch.skills, platform="telegram", slots=1,
                                    taken=orch._command_name_taken).entries[0]
        assert "private" not in result.description and "[REDACTED]" in result.description
    finally:
        orch.checkpoints.close()


def test_secret_command_names_are_hidden_not_renamed(monkeypatch):
    monkeypatch.setattr(outbound_safety, "_known_redactor", lambda text: text.replace("privatekey", "[REDACTED]"))
    command = _command(name="privatekey", description="A command")
    assert telegram_menu([command]) == []


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
