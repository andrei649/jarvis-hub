"""H088 — one channel policy, asked by both the boot and the HUD's pre-write check.

The owner cannot save, from the Channels panel, a channel configuration the next start
refuses: the panel and the boot guard call the same predicate
(``boot_guards.front_door_problem``) over the environment the next start would read. The
channel port rule is shared the same way (``channel_config.port_value``: the panel's field
validation and the start's ``SMTP_PORT`` / ``IMAP_PORT`` read).
"""
from __future__ import annotations

import itertools

import pytest

from agents.core import boot_guards
from agents.core import channel_config as cc
from agents.core.env_alias import ConfigurationRefused

TOKEN = "123456:" + "A" * 35

ENVS = [
    {},
    {"TELEGRAM_BOT_TOKEN": TOKEN},
    {"TELEGRAM_BOT_TOKEN": TOKEN, "JARVIS_CHANNEL_PAIRING": "0"},
    {"TELEGRAM_BOT_TOKEN": TOKEN, "JARVIS_CHANNEL_PAIRING": "0", "TELEGRAM_ALLOWED_USER_IDS": "42"},
    {"TELEGRAM_BOT_TOKEN": TOKEN, "JARVIS_CHANNEL_PAIRING": "0", "JARVIS_CHANNEL_OPEN": "1"},
    {"JARVIS_CHANNEL_PAIRING": "0"},
    {"JARVIS_CHANNEL_PAIRING": "0", "DISCORD_BOT_TOKEN": "d" * 30},
    {"NERVA_CHANNEL_PAIRING": "off", "SLACK_BOT_TOKEN": "xoxb-1", "SLACK_APP_TOKEN": "xapp-1"},
    {"JARVIS_CHANNEL_PAIRING": "0", "IMAP_HOST": "imap.x", "SMTP_HOST": "smtp.x"},
]

CHANGES = [
    {"TELEGRAM_BOT_TOKEN": TOKEN},
    {"TELEGRAM_BOT_TOKEN": None},
    {"TELEGRAM_ALLOWED_USER_IDS": None},
    {"TELEGRAM_ALLOWED_USER_IDS": "42"},
    {"DISCORD_BOT_TOKEN": "d" * 30},
    {"IMAP_HOST": "imap.x", "SMTP_HOST": "smtp.x"},
    {"SMTP_HOST": None},
]


def _boot_refuses(env: dict) -> bool:
    try:
        boot_guards.assert_guarded_channels(env)
    except ConfigurationRefused as refused:
        assert refused.exit_status == 78
        return True
    return False


@pytest.mark.parametrize("env", ENVS)
def test_the_predicate_is_the_boot_guard(env):
    assert (boot_guards.front_door_problem(env) is not None) == _boot_refuses(env)


@pytest.mark.parametrize("env, change", list(itertools.product(ENVS, CHANGES)))
def test_the_panel_refuses_exactly_what_the_next_start_would(env, change):
    after = dict(env)
    for name, value in change.items():
        after.pop(name, None)
        if value is not None:
            after[name] = value
    boot_after, boot_before = _boot_refuses(after), _boot_refuses(env)
    try:
        cc.front_door_check(change, environ=env)
        refused = False
    except cc.FrontDoorRefused as exc:
        refused = True
        assert "would answer any sender" in str(exc)
        assert TOKEN not in str(exc) and "42" not in str(exc)
    if refused:
        assert boot_after, "the panel refused a write the next start would accept"
    if boot_after and not boot_before:
        assert refused, "the panel saved a write the next start refuses"


def test_set_secret_refuses_before_anything_is_stored(monkeypatch):
    from agents.core import integration_keys

    stored = []
    monkeypatch.setattr(integration_keys, "set_key", lambda *a, **k: stored.append(a))
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "0")
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USER_IDS", "JARVIS_CHANNEL_OPEN", "NERVA_CHANNEL_OPEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(cc.FrontDoorRefused):
        cc.set_secret("telegram", "TELEGRAM_BOT_TOKEN", TOKEN)
    assert stored == []


def test_set_plain_refuses_removing_the_allowlist_that_guards_the_bot(monkeypatch):
    from agents.core import settings_db

    writes = []
    monkeypatch.setattr(settings_db, "put_category", lambda *a, **k: writes.append(a))
    monkeypatch.setattr(cc, "plain_env_owned", lambda name: False)
    monkeypatch.setattr(cc, "_check_managed", lambda name: None)
    monkeypatch.setenv("JARVIS_CHANNEL_PAIRING", "0")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "42")
    for name in ("JARVIS_CHANNEL_OPEN", "NERVA_CHANNEL_OPEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(cc.FrontDoorRefused):
        cc.set_plain("telegram", {"TELEGRAM_ALLOWED_USER_IDS": None})
    assert writes == []


@pytest.mark.parametrize("raw", ["", "0", "1", "25", "587", "65535", "65536", "99999", "-1", "+25", " 993 ",
                                 "1e3", "١٢٣", "0587", "000000465", "abc", "25.0"])
def test_one_port_rule_for_the_panel_and_the_start(raw, monkeypatch):
    field = cc.channel("email").field("SMTP_PORT")
    try:
        accepted = int(cc.normalise(field, raw))
    except cc.InvalidValue:
        accepted = None
    assert accepted == cc.port_value(raw)
    monkeypatch.setenv("SMTP_PORT", raw)
    assert cc.env_port("SMTP_PORT", 587) == (587 if accepted is None else accepted)
