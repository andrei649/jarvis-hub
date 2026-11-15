"""Group help lists commands addressed to the currently verified Telegram bot."""

from types import SimpleNamespace

import pytest

from agents.core import quick_commands, slash_access
from agents.core.commands import (
    CommandRegistry,
    Principal,
    SlashCommand,
    build_default_registry,
)


def _adapter(**changes):
    fields = {
        "_running": True,
        "_bot_id": 123,
        "_bot_username": "nerva_bot",
        "_owner_once_generation": "generation-1",
        "_verified_bot_generation": "generation-1",
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


async def _help(adapter, *, channel="telegram", scope="group", admin=True, registry=None):
    registry = registry or build_default_registry()
    manager = SimpleNamespace(channels={"telegram": adapter})
    orch = SimpleNamespace(commands=registry, channel_manager=manager)
    principal = Principal(channel=channel, sender="42", chat="-100", scope=scope, admin=admin)
    return (await registry.dispatch("/help", orch=orch, principal=principal)).reply


@pytest.mark.asyncio
async def test_group_help_qualifies_only_registered_names_and_quick_headers(monkeypatch):
    monkeypatch.setattr(slash_access, "_policy", lambda: {})
    reads = []

    def configured():
        reads.append(True)
        return {"custom": {"type": "alias"}, "pause": {"type": "alias"}}

    monkeypatch.setattr(quick_commands, "configured", configured)
    registry = build_default_registry()
    registry.register(SlashCommand(
        "guide", "see https://example.test/status and /pause", lambda _: "ok",
        usage="[topic]",
    ))
    reply = await _help(_adapter(), registry=registry)
    assert "/help@nerva_bot —" in reply
    assert "/guide@nerva_bot [topic] — see https://example.test/status and /pause" in reply
    assert "/custom@nerva_bot — quick alias  (owner)" in reply
    assert "/pause@nerva_bot [reason|off] —" in reply
    assert "/pause@nerva_bot — quick" not in reply
    assert reads == [True]


@pytest.mark.asyncio
async def test_group_guest_help_keeps_access_floor_and_bare_owner_examples(monkeypatch):
    monkeypatch.setattr(slash_access, "_policy", lambda: {})
    reply = await _help(_adapter(), admin=False)
    heads = {line.split()[0] for line in reply.splitlines() if line.startswith("/")}
    assert heads == {"/help@nerva_bot", "/whoami@nerva_bot"}
    assert "such as /pause, /resume, /stop, /remind and /refine" in reply


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"_running": False},
    {"_bot_id": 0},
    {"_bot_id": True},
    {"_verified_bot_generation": None},
    {"_verified_bot_generation": "older-generation"},
    {"_owner_once_generation": ""},
    {"_bot_username": "@nerva_bot"},
    {"_bot_username": "bot"},
    {"_bot_username": "a" * 33},
    {"_bot_username": "nérva_bot"},
    {"_bot_username": "nerva_bot\n/pause"},
])
async def test_unverified_or_invalid_identity_keeps_bare_names(monkeypatch, changes):
    monkeypatch.setattr(slash_access, "_policy", lambda: {})
    reply = await _help(_adapter(**changes), admin=False)
    assert "/help —" in reply
    assert "@nerva_bot" not in reply


@pytest.mark.asyncio
@pytest.mark.parametrize("channel,scope", [
    ("telegram", "dm"), ("web", "group"), ("web", "dm"),
])
async def test_help_outside_telegram_groups_stays_bare(monkeypatch, channel, scope):
    monkeypatch.setattr(slash_access, "_policy", lambda: {})
    reply = await _help(_adapter(), channel=channel, scope=scope, admin=False)
    assert "/help —" in reply
    assert "@nerva_bot" not in reply


@pytest.mark.asyncio
async def test_missing_adapter_keeps_bare_names(monkeypatch):
    monkeypatch.setattr(slash_access, "_policy", lambda: {})
    registry = build_default_registry()
    principal = Principal(channel="telegram", scope="group")
    orch = SimpleNamespace(commands=registry, channel_manager=SimpleNamespace(channels={}))
    reply = (await registry.dispatch("/help", orch=orch, principal=principal)).reply
    assert "/help —" in reply
