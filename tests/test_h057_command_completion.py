"""H057: the bounded /nerva command fallback."""

from __future__ import annotations

import pytest

from agents.core.commands import (
    ADMIN,
    CommandRegistry,
    Principal,
    SlashCommand,
    build_default_registry,
)


def test_quick_commands_cannot_take_the_fallback_name():
    from agents.core.quick_commands import configuration_problem

    assert "built-in command fallback" in configuration_problem({
        "NERVA": {"type": "alias", "target": "/help"},
    })


@pytest.mark.asyncio
async def test_fallback_dispatches_canonical_target_with_its_access_gate():
    registry = CommandRegistry()
    registry.register(SlashCommand("help", "help", lambda ctx: "helped"))
    registry.register(SlashCommand("secret", "secret", lambda ctx: "done", tier=ADMIN))
    guest = Principal(channel="telegram", sender="T1:U1")
    owner = Principal(channel="telegram", sender="T1:U1", admin=True)
    answer = await registry.dispatch("/nerva help", orch=None, principal=guest)
    assert answer.name == "help" and answer.reply == "helped"
    denied = await registry.dispatch("/nerva secret", orch=None, principal=guest)
    assert denied.name == "secret" and denied.status == "refused"
    allowed = await registry.dispatch("/nerva secret", orch=None, principal=owner)
    assert allowed.name == "secret" and allowed.reply == "done"
    nested = await registry.dispatch("/nerva nerva secret", orch=None, principal=owner)
    assert nested.status == "refused"
    assert CommandRegistry.parse("/nerva stop now") == ("stop", "now")
    assert CommandRegistry.parse("/nerva h") == ("help", "")


@pytest.mark.parametrize("sub", ["new", "reset", "undo", "btw", "checkpoints", "rollback"])
@pytest.mark.asyncio
async def test_fallback_does_not_move_special_commands_after_append(sub):
    registry = build_default_registry()
    outcome = await registry.dispatch(f"/nerva {sub}", orch=None,
                                      principal=Principal(channel="telegram", admin=True))
    assert outcome.status == "refused"
