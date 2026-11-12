"""H231 — fuzzy, description-aware command resolution, shared by the hub and the terminal.

An unknown slash command is answered with the closest commands the speaker may run (by
name and by description), and nothing is run; a guest is never shown an owner command.
The terminal chat's Tab completion falls back to the same scorer when no name matches.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agents.cli import repl as R
from agents.core.commands import (
    ADMIN,
    CommandRegistry,
    Principal,
    SlashCommand,
    build_default_registry,
)
from agents.core.fuzzy_match import THRESHOLD, rank, score
from tests.h058_access_fixture import allow_user_tier

CATALOG = [("help", "the commands you can use here"), ("sessions", "the five most recent sessions"),
           ("status", "backend, agents, autonomy mode, e-stop"), ("stop", "same as /pause"),
           ("compress", "what compaction does to this conversation now"),
           ("context", "what fills the model's window"), ("usage", "cloud provider quota left")]


@pytest.mark.parametrize("query,expected", [
    ("/sesion", ["sessions"]),             # a typo
    ("/stat", ["status"]),                 # a prefix
    ("/hlp", ["help"]),                    # a subsequence
    ("/compaction", ["compress"]),         # a description word, by its stem
    ("/window", ["context"]),              # a description word
    ("/quota", ["usage"]),
    ("/xyzzy", []),                        # nothing close: nothing offered
])
def test_rank_by_name_and_description(query, expected):
    got = rank(query, CATALOG)
    assert got[:1] == expected if expected else got == []


def test_score_bounds_and_exact_match():
    assert score("/help", "help") == 1.0
    assert score("", "help") == 0.0 and score("x", "") == 0.0
    assert score("/zzz", "help", "nothing alike") < THRESHOLD
    assert rank("/s", CATALOG, limit=2) == ["sessions", "status"]     # prefix, catalog order, limit


def _say(registry, text, principal):
    async def run():
        return await registry.dispatch(text, orch=SimpleNamespace(), principal=principal)

    return asyncio.run(run())


def test_unknown_command_suggests_without_running_anything(monkeypatch, tmp_path):
    allow_user_tier(monkeypatch, tmp_path)
    registry = build_default_registry()
    ran = []
    registry.register(SlashCommand("summarize", "summarise this conversation", lambda _ctx: ran.append(1)))
    outcome = _say(registry, "/summary", Principal(admin=True))
    assert outcome.status == "unknown" and ran == []
    assert outcome.reply.startswith("Unknown command /summary. Did you mean /summarize (summarise this conversation)")
    assert outcome.reply.endswith("Try /help.")
    assert _say(registry, "/zzzzqqq", Principal(admin=True)).reply == "Unknown command /zzzzqqq. Try /help."


def test_a_guest_is_never_shown_an_owner_command(monkeypatch, tmp_path):
    allow_user_tier(monkeypatch, tmp_path)
    registry = CommandRegistry()
    registry.register(SlashCommand("help", "the commands you can use here", lambda _ctx: "h"))
    registry.register(SlashCommand("deploybox", "deploy the box", lambda _ctx: "d", tier=ADMIN))
    guest = _say(registry, "/deploybx", Principal(admin=False))
    assert "deploybox" not in guest.reply and guest.reply == "Unknown command /deploybx. Try /help."
    owner = _say(registry, "/deploybx", Principal(admin=True))
    assert "Did you mean /deploybox (deploy the box)?" in owner.reply


def test_a_failing_suggestion_never_breaks_the_reply(monkeypatch, tmp_path):
    allow_user_tier(monkeypatch, tmp_path)
    registry = build_default_registry()
    monkeypatch.setattr(registry, "visible", lambda principal: (_ for _ in ()).throw(RuntimeError("x")))
    assert _say(registry, "/sesion", Principal(admin=True)).reply == "Unknown command /sesion. Try /help."


# ── the terminal's Tab completion ─────────────────────────────────────────────

def test_tab_falls_back_to_fuzzy_names_and_descriptions():
    commands = ["/help", "/sessions", "/usage"]
    described = [("/help", "the commands you can use here"), ("/usage", "cloud provider quota left")]
    assert R.completions("/se", line="/se", begin=0, commands=commands, described=described) == ["/sessions"]
    assert R.completions("/sesion", line="/sesion", begin=0, commands=commands, described=described) == ["/sessions"]
    assert R.completions("/quota", line="/quota", begin=0, commands=commands, described=described) == ["/usage"]
    # the client's own commands are matched by their descriptions too
    assert "/copy" in R.completions("/clipboard", line="/clipboard", begin=0, commands=commands)
    # two letters with no prefix match: nothing guessed
    assert R.completions("/qz", line="/qz", begin=0, commands=commands, described=described) == []
    # a description from the catalog never adds a name the catalog does not hold
    assert R.completions("/zzz", line="/zzz", begin=0, commands=commands,
                         described=[("/rm-rf", "zzz zzz")]) == []


def test_the_catalog_keeps_card_safe_descriptions(tmp_path, monkeypatch):
    from tests.test_h224_terminal_interaction import FakeHub, _repl

    hub = FakeHub({("GET", "/api/commands"): {"commands": [
        {"command": "/usage", "description": "quota\x1b[2J left ‮"}, {"command": "/BAD name"}]}})
    repl, *_ = _repl(tmp_path, monkeypatch, hub)
    repl.load_catalog()
    assert repl.commands == ["/usage"]
    assert repl.described == [("/usage", "quota [2J left")]


def test_a_guest_is_never_offered_a_name_help_would_not_list(monkeypatch, tmp_path):
    from agents.core import slash_access

    allow_user_tier(monkeypatch, tmp_path)
    registry = build_default_registry()
    monkeypatch.setattr(slash_access, "listed_names", lambda reg, principal, orch=None: ["help", "whoami"])
    guest = _say(registry, "/sesion", Principal(admin=False))
    assert "sessions" not in guest.reply and guest.reply == "Unknown command /sesion. Try /help."
    assert "/sessions" in _say(registry, "/sesion", Principal(admin=True)).reply
