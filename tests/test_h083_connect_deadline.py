"""Validated persisted opening budgets do not disable channel lifecycle fences."""

import pytest

from tests.test_settings_db import temp_db  # noqa: F401


@pytest.mark.parametrize("value,expected", [
    (15, 15.0), (2.5, 2.5), ("8.5", 8.5), (0, 1.0), (-1, 1.0), (99, 25.0),
    (True, 15.0), (False, 15.0), (None, 15.0), ("", 15.0), ("bad", 15.0),
    (float("nan"), 15.0), (float("inf"), 15.0), (float("-inf"), 15.0),
    ({}, 15.0), ([], 15.0), (10 ** 400, 15.0),
])
def test_connect_budget_is_finite_bounded_and_never_disabled(value, expected):
    from agents.core.channels.connect_deadline import channel_connect_timeout

    assert channel_connect_timeout(value) == expected


def test_setting_is_seeded_persisted_and_visible_to_generic_admin_editor(temp_db):
    rows = {row["key"]: row for row in temp_db.get_category("system")}
    assert "channel_connect_timeout_seconds" in rows
    row = rows["channel_connect_timeout_seconds"]
    assert row["value"] == row["default"] == 15
    assert row["kind"] == "number"
    assert all(name in row["label"] for name in
               ("Telegram", "Discord", "ntfy", "IMAP", "Slack"))
    count, skipped = temp_db.put_category("system", {"channel_connect_timeout_seconds": 7})
    assert count == 1 and skipped == []
    temp_db._initialized = False
    assert temp_db.get_value("system", "channel_connect_timeout_seconds") == 7


def test_real_lifespan_passes_one_configured_budget_to_all_five_transports(monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from tests.test_h083_platform_command import FakeChannel

    captured = {}
    original_get = web.Orchestrator.get_setting

    def configured(self, key, default=None):
        if key == "system.channel_connect_timeout_seconds":
            captured["reads"] = captured.get("reads", 0) + 1
            return 7
        return original_get(self, key, default)

    def telegram(**kwargs):
        captured["telegram"] = kwargs["connect_timeout_seconds"]
        return FakeChannel("telegram")

    def email(**kwargs):
        captured["email"] = kwargs["connect_timeout_seconds"]
        return FakeChannel("email")

    def slack(**kwargs):
        captured["slack"] = kwargs["connect_timeout_seconds"]
        return FakeChannel("slack")

    def discord(**kwargs):
        captured["discord"] = kwargs["connect_timeout_seconds"]
        return FakeChannel("discord")

    class Ntfy:
        @classmethod
        def from_env(cls, environ, *, connect_timeout_seconds):
            captured["ntfy"] = connect_timeout_seconds
            return FakeChannel("ntfy")

    monkeypatch.setattr(web.Orchestrator, "get_setting", configured)
    monkeypatch.setattr(web, "TelegramChannel", telegram)
    monkeypatch.setattr(web, "NtfyChannel", Ntfy)
    monkeypatch.setattr(web, "EmailChannel", email)
    monkeypatch.setattr(web, "SlackChannel", slack)
    monkeypatch.setattr(web, "DiscordChannel", discord)
    monkeypatch.setenv("SMTP_HOST", "smtp.invalid")
    monkeypatch.setenv("IMAP_HOST", "imap.invalid")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "offline-slack-budget-test")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "offline-discord-budget-test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "offline-identity-budget-test")
    with TestClient(web.app):
        assert captured == {"reads": 1, "telegram": 7.0, "ntfy": 7.0,
                            "email": 7.0, "slack": 7.0, "discord": 7.0}
        assert {"telegram", "ntfy", "email", "slack", "discord"} <= set(web.orch.channels)
