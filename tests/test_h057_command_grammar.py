"""H057 — the chat slash-command grammar.

What the owner can do: type ``/model gpt —global`` from a phone (the keyboard's em dash is
read as ``--``), use a short alias (``/h``, ``/me``, ``/estop``), type ``!status`` in a
Slack thread or a Matrix room, and pick a command from Telegram's "/" menu. What nobody can
do: reach through an alias or a ``!`` what the canonical command's access gate refuses,
turn ordinary ``!`` text into a command, or shadow a built-in with an alias.
"""
from __future__ import annotations

import pytest

from agents.core.commands import (
    ADMIN,
    ALIASES,
    TELEGRAM_MENU_MAX,
    CommandRegistry,
    SlashCommand,
    build_default_registry,
    rewrite_bang,
    telegram_menu,
)


@pytest.fixture(scope="module")
def registry():
    return build_default_registry()


@pytest.mark.parametrize("text, expected", [
    ("/voice —always", ("voice", "--always")),
    ("/voice –always", ("voice", "--always")),
    ("/recap 3 —x —y", ("recap", "3 --x --y")),
    ("/btw what — exactly", ("btw", "what — exactly")),     # a dash in prose stays
    ("/btw a—b", ("btw", "a—b")),                          # inside a word stays
    ("/h", ("help", "")),
    ("/ME", ("whoami", "")),
    ("/estop@nerva_bot fire", ("pause", "fire")),
    ("/etc/hosts", None),                                  # a pasted path is not a command
])
def test_parse(text, expected):
    assert CommandRegistry.parse(text) == expected


def test_every_alias_points_at_a_registered_command_and_shadows_none(registry):
    names = {c.name for c in registry.commands()}
    for alias, target in ALIASES.items():
        assert target in names and alias not in names
    for session_change in ("new", "reset", "undo"):
        assert session_change not in ALIASES.values()


def test_an_alias_cannot_be_registered_as_a_command():
    reg = CommandRegistry()
    with pytest.raises(ValueError):
        reg.register(SlashCommand("h", "x", lambda *a, **k: None))


@pytest.mark.asyncio
async def test_an_alias_is_judged_as_its_canonical_command(registry):
    from agents.core.commands import Principal

    guest = Principal(channel="telegram", sender="9", admin=False)
    outcome = await registry.dispatch("/estop now", orch=None, principal=guest)
    assert outcome is not None and outcome.name == "pause" and outcome.status != "answered"


@pytest.mark.parametrize("channel, text, expected", [
    ("slack", "!status", "/status"),
    ("slack", "  !estop  now", "/estop  now"),
    ("matrix", "!h", "/h"),
    ("slack", "!nonsense here", "!nonsense here"),        # unknown: a message, not a command
    ("slack", "!!status", "!!status"),
    ("slack", "wow! status", "wow! status"),
    ("telegram", "!status", "!status"),                   # only where / does not reach the bot
    ("discord", "!status", "!status"),
])
def test_bang_prefix(registry, channel, text, expected):
    assert rewrite_bang(text, registry, channel) == expected


def test_bang_without_a_registry_is_inert():
    assert rewrite_bang("!status", None, "slack") == "!status"


def test_telegram_menu_projection(registry):
    menu = telegram_menu(registry.commands())
    assert 0 < len(menu) <= TELEGRAM_MENU_MAX
    for item in menu:
        assert set(item) == {"command", "description"}
        assert 1 <= len(item["command"]) <= 32 and item["command"] == item["command"].lower()
        assert 1 <= len(item["description"]) <= 256
    assert [m["command"] for m in menu] == sorted(m["command"] for m in menu)
    many = [SlashCommand(f"c{i:03d}", "d" * 400, lambda *a, **k: None) for i in range(150)]
    many.append(SlashCommand("Bad-Name", "x", lambda *a, **k: None))
    projected = telegram_menu(many)
    assert len(projected) == TELEGRAM_MENU_MAX and all(len(m["description"]) == 256 for m in projected)
    assert all(m["command"] != "Bad-Name" for m in projected)


def test_the_guest_menu_holds_no_owner_command(registry):
    from agents.web import _telegram_command_menus

    class _Orch:
        commands = registry

        def get_setting(self, key, default=None):
            return "4242" if key == "autonomy.owner_chat_id" else default

    everyone, owner = _telegram_command_menus(_Orch())
    admin = {c.name for c in registry.commands() if c.tier == ADMIN}
    assert admin and not admin & {m["command"] for m in everyone}
    assert owner[0] == 4242 and admin <= {m["command"] for m in owner[1]}


class _Resp:
    is_success = True
    status_code = 200

    def json(self):
        return {"ok": True}


class _Client:
    is_closed = False

    def __init__(self):
        self.posts = []

    async def post(self, url, json=None, **kwargs):
        self.posts.append((url.rsplit("/", 1)[-1], json))
        return _Resp()


@pytest.mark.asyncio
async def test_telegram_publishes_both_scopes_and_survives_a_failure():
    from agents.core.channels.telegram import TelegramChannel

    channel = TelegramChannel("tok")
    channel.client = _Client()
    channel.command_menu = lambda: ([{"command": "help", "description": "h"}],
                                    (77, [{"command": "pause", "description": "p"}]))
    assert await channel.publish_command_menu() is True
    assert channel.client.posts == [
        ("setMyCommands", {"commands": [{"command": "help", "description": "h"}]}),
        ("setMyCommands", {"commands": [{"command": "pause", "description": "p"}],
                           "scope": {"type": "chat", "chat_id": 77}}),
    ]

    def broken():
        raise RuntimeError("registry gone")

    channel.command_menu = broken
    assert await channel.publish_command_menu() is False
    channel.command_menu = None
    assert await channel.publish_command_menu() is False


# ── security review (2026-11-12) ─────────────────────────────────────────────────

@pytest.mark.parametrize("alias", sorted(ALIASES))
def test_m5_a_quick_command_cannot_take_a_built_in_alias(alias):
    from agents.core.quick_commands import configuration_problem

    problem = configuration_problem({alias.upper(): {"type": "alias", "target": "/status"}})
    assert problem is not None and "built-in alias" in problem
    assert configuration_problem({"mystatus": {"type": "alias", "target": "/status"}}) is None


def _menus(registry, owner_chat, allowed=None):
    from agents.web import _telegram_command_menus

    class _Orch:
        commands = registry

        def get_setting(self, key, default=None):
            if key == "autonomy.owner_chat_id":
                return owner_chat
            if allowed is not None and key.startswith("commands.user_allowed"):
                return allowed
            return default

    return _telegram_command_menus(_Orch())


def test_the_owner_menu_goes_only_to_a_private_chat(registry, monkeypatch):
    monkeypatch.delenv("AUTONOMY_OWNER_CHAT_ID", raising=False)
    assert _menus(registry, "-1001234")[1] is None        # a group: everyone in it would see it
    assert _menus(registry, "4242")[1][0] == 4242


def test_the_default_menu_is_what_a_guest_may_run(registry, monkeypatch):
    from agents.core.commands import Principal

    monkeypatch.delenv("AUTONOMY_OWNER_CHAT_ID", raising=False)
    everyone, _owner = _menus(registry, "")
    shown = {m["command"] for m in everyone}
    for scope in ("dm", "group"):
        visible = {c.name for c in registry.visible(Principal(channel="telegram", admin=False, scope=scope))}
        assert shown <= visible


@pytest.mark.asyncio
async def test_an_observed_group_message_is_stored_as_written():
    from agents.core.orchestrator import Orchestrator

    seen = []

    class _Stop(Exception):
        pass

    orch = Orchestrator.__new__(Orchestrator)
    orch.commands = build_default_registry()
    orch._channel_principal = lambda *a, **k: (_ for _ in ()).throw(_Stop())

    def principal(channel, sender, chat, kind):
        seen.append("principal")
        raise _Stop

    orch._channel_principal = principal
    orch._principal_chat_type = lambda channel, kwargs: "group"
    import agents.core.commands as commands_module

    calls = []
    original = commands_module.rewrite_bang
    commands_module.rewrite_bang = lambda text, reg, channel: calls.append(text) or original(text, reg, channel)
    try:
        for observe in (True, False):
            with pytest.raises(_Stop):
                await orch.channel_handler("!status", channel="slack", observe_only=observe, sender="U1")
    finally:
        commands_module.rewrite_bang = original
    assert calls == ["!status"]          # rewritten only for the answered message
