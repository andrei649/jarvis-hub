"""H079: owner slash invocations load one or up to five installed skills."""

from pathlib import Path

import pytest

from agents.core import settings_db
from agents.core.skills import bundles, slash_load
from tests.test_h026_skill_bundles import (  # noqa: F401
    _BODIES,
    _answered,
    _hub,
    _md_skill,
    _say,
    _write,
    isolated,
)


def test_resolution_normalizes_names_and_folders_and_reserves_commands():
    skill = _md_skill("athena only", path=Path("/installed/weather_notes"))
    loader = type("Loader", (), {"skills": {skill.name: skill}})()
    assert slash_load.resolve("/ATHENA_ONLY focus", loader).skill_name == "athena only"
    assert slash_load.resolve("/weather-notes focus", loader).instruction == "focus"
    assert slash_load.resolve("/weather_notes focus", loader).skill_name == "athena only"
    assert slash_load.resolve("/athena-only focus", loader, taken=lambda name: name == "athena-only") is None
    assert slash_load.resolve("/missing focus", loader) is None
    assert slash_load.resolve("/1weather-notes focus", loader) is None
    assert slash_load.resolve("/../weather_notes", loader) is None


def test_normalized_collision_refuses_without_selecting_a_skill():
    a = _md_skill("weather", path=Path("/installed/weather_notes"))
    b = _md_skill("notes", path=Path("/installed/weather-notes"))
    loader = type("Loader", (), {"skills": {s.name: s for s in (a, b)}})()
    inv = slash_load.resolve("/weather_notes tell me", loader)
    assert inv is not None and inv.ambiguous
    assert slash_load.begin_load(inv, loader, owner=True, session="s") == (
        "The skill could not be loaded; nothing was sent to the model.")
    assert bundles.current_load() is None


def test_helper_checks_owner_even_for_a_resolved_skill():
    skill = _md_skill("weather")
    loader = type("Loader", (), {"skills": {skill.name: skill}})()
    inv = slash_load.resolve("/weather", loader)
    assert inv is not None
    assert slash_load.begin_load(inv, loader, owner=False, session="s") == (
        "The skill could not be loaded; nothing was sent to the model.")
    assert bundles.current_load() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_owner_slash_loads_one_skill_through_shared_turn(tmp_path, monkeypatch, stream):
    orch, seen = _hub(tmp_path, monkeypatch, _md_skill("weather"))
    reply, notices = await _say(orch, "/weather umbrella today", stream=stream)
    assert _answered(reply) and len(seen.sent) == 1
    prompt = seen.sent[0]
    assert '[The owner invoked the "weather" skill for this turn.' in prompt
    assert "Skill: weather" in prompt and "User instruction: umbrella today" in prompt
    assert '<loaded-skill name="weather">' in prompt and _BODIES["weather"] in prompt
    assert "bundle=" not in prompt and "skill bundle" not in prompt
    assert notices == ["Skill weather: loaded weather."]
    assert seen.bumps == [("weather", "view")]
    history = await orch.memory.get_history("s")
    assert history[0]["content"] == "/weather umbrella today"
    assert _BODIES["weather"] not in str(history)
    orch.checkpoints.close()


@pytest.mark.asyncio
async def test_non_owner_and_unknown_skill_do_not_reach_model(tmp_path, monkeypatch):
    orch, seen = _hub(tmp_path, monkeypatch, _md_skill("weather"))
    denied, _ = await _say(orch, "/weather private", admin=False)
    assert not _answered(denied) and seen.sent == []
    missing, _ = await _say(orch, "/missing-skill private")
    assert not _answered(missing) and seen.sent == []
    orch.checkpoints.close()


@pytest.mark.asyncio
async def test_disabled_skill_refuses_without_model_read(tmp_path, monkeypatch):
    orch, seen = _hub(tmp_path, monkeypatch, _md_skill("weather"))
    settings_db.put_category("skills", {"disabled": ["weather"]})
    reply, _ = await _say(orch, "/weather go")
    assert reply.startswith("Skill weather: loaded no skill; skipped weather (switched off).")
    assert "Nothing was sent to the model" in reply and seen.sent == []
    orch.checkpoints.close()


@pytest.mark.asyncio
async def test_ambiguous_skill_refuses_without_disclosing_candidates(tmp_path, monkeypatch):
    a = _md_skill("weather", path=Path("/installed/weather_notes"))
    b = _md_skill("notes", path=Path("/installed/weather-notes"))
    orch, seen = _hub(tmp_path, monkeypatch, a, b)
    reply, _ = await _say(orch, "/weather_notes go")
    assert "could not be loaded" in reply and "weather" not in reply and "notes" not in reply
    assert seen.sent == []
    orch.checkpoints.close()


def test_turn_prompt_rechecks_switch_after_initial_read(tmp_path, monkeypatch):
    orch, _ = _hub(tmp_path, monkeypatch, _md_skill("weather"))
    token = bundles.bind_turn()
    try:
        inv = slash_load.resolve("/weather go", orch.skills)
        assert slash_load.begin_load(inv, orch.skills, owner=True, session="s") is None
        settings_db.put_category("skills", {"disabled": ["weather"]})
        block = bundles.turn_block(orch.skills, "athena", session="s")
        assert _BODIES["weather"] not in block
        assert "Skills skipped: weather (switched off)" in block
        assert bundles.commit_turn() == 0
    finally:
        bundles.reset_turn(token)
        orch.checkpoints.close()


@pytest.mark.asyncio
async def test_imported_skill_is_tainted_and_clean_skill_records_ledger(tmp_path, monkeypatch):
    from agents.core.security.taint import is_untrusted_source
    from agents.core.skills.tools import LEDGER

    orch, seen = _hub(tmp_path, monkeypatch, _md_skill("imported", vouched=False),
                      _md_skill("weather"))
    await _say(orch, "/imported go")
    assert '<loaded-skill name="imported" tainted="true">' in seen.sent[0]
    assert is_untrusted_source(seen.origins[0])
    assert LEDGER.loaded("s", "athena") == []
    await _say(orch, "/weather go")
    assert not is_untrusted_source(seen.origins[-1])
    assert LEDGER.loaded("s", "athena") == ["weather"]
    orch.checkpoints.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("name,text", [("h", "/h"), ("nerva", "/nerva help"),
                                       ("status", "/status")])
async def test_installed_skill_cannot_shadow_command_alias_or_fallback(tmp_path, monkeypatch,
                                                                        name, text, stream):
    skill = _md_skill("weather")
    skill.name = name
    orch, seen = _hub(tmp_path, monkeypatch, skill)
    reply, notices = await _say(orch, text, stream=stream)
    assert seen.sent == [] and notices == []
    if name == "status":
        assert reply.startswith("Nerva ")
    else:
        assert "/help" in reply
    orch.checkpoints.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_quick_command_precedes_installed_skill(tmp_path, monkeypatch, stream):
    skill = _md_skill("weather")
    skill.name = "forecast"
    orch, seen = _hub(tmp_path, monkeypatch, skill)
    settings_db.put_category("commands", {"quick_commands": {
        "forecast": {"type": "alias", "target": "/help"}}})
    reply, notices = await _say(orch, "/forecast", stream=stream)
    assert "/help" in reply and seen.sent == [] and notices == []
    orch.checkpoints.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_bundle_precedes_installed_skill_with_same_slash_slug(tmp_path, monkeypatch, stream):
    skill = _md_skill("notes")
    skill.name = "morning"
    orch, seen = _hub(tmp_path, monkeypatch, _md_skill("weather"), skill)
    _write(tmp_path, "morning.yaml", "name: Morning\nskills: [weather]\n")
    reply, notices = await _say(orch, "/morning go", stream=stream)
    assert _answered(reply) and _BODIES["weather"] in seen.sent[0]
    assert _BODIES["notes"] not in seen.sent[0]
    assert notices == ["Bundle Morning: loaded weather."]
    orch.checkpoints.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["quarantined", "unsupported"])
async def test_hard_gated_skill_refuses_before_model(tmp_path, monkeypatch, kind):
    from agents.core.skills import visibility

    skill = _md_skill("weather", pending=kind == "quarantined")
    if kind == "unsupported":
        skill.manifest["platforms"] = ["macos"]
        monkeypatch.setattr(visibility, "host_platforms", lambda platform=None: frozenset({"linux"}))
    orch, seen = _hub(tmp_path, monkeypatch, skill)
    reply, notices = await _say(orch, "/weather go")
    assert reply.startswith("Skill weather: loaded no skill; skipped weather (")
    assert ("quarantined" if kind == "quarantined" else "not supported on this host") in reply
    assert "Nothing was sent to the model" in reply and seen.sent == [] and notices == []
    orch.checkpoints.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_stack_loads_five_skills_in_order_with_only_final_instruction(tmp_path, monkeypatch, stream):
    names = ("weather", "news", "notes", "imported", "athena only")
    orch, seen = _hub(tmp_path, monkeypatch, *(_md_skill(name) for name in names))
    reply, notices = await _say(orch, "/weather /news /notes /imported /athena_only plan today", stream=stream)
    assert _answered(reply) and len(seen.sent) == 1
    prompt = seen.sent[0]
    assert "Skills requested: weather, news, notes, imported, athena only" in prompt
    assert "User instruction: plan today" in prompt
    assert "User instruction: /news" not in prompt and "bundle=" not in prompt
    assert [prompt.index(_BODIES[name]) for name in names] == sorted(prompt.index(_BODIES[name]) for name in names)
    assert notices == ["Skills weather, news, notes, imported, athena only: loaded " + ", ".join(names) + "."]
    assert seen.bumps == [(name, "view") for name in names]
    orch.checkpoints.close()


@pytest.mark.asyncio
async def test_sixth_leading_skill_refuses_instead_of_becoming_instruction(tmp_path, monkeypatch):
    names = ("weather", "news", "notes", "imported", "athena only", "pending")
    orch, seen = _hub(tmp_path, monkeypatch, *(_md_skill(name) for name in names))
    reply, notices = await _say(orch, "/weather /news /notes /imported /athena_only /pending plan")
    assert "nothing was sent to the model" in reply.lower()
    assert seen.sent == [] and seen.bumps == [] and notices == []
    orch.checkpoints.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("second", ["/h", "/status", "/forecast", "/morning", "/ghost"])
async def test_second_stack_token_cannot_bypass_command_or_bundle_precedence(tmp_path, monkeypatch, second):
    orch, seen = _hub(tmp_path, monkeypatch, _md_skill("weather"), _md_skill("news"))
    settings_db.put_category("commands", {"quick_commands": {
        "forecast": {"type": "alias", "target": "/help"}}})
    _write(tmp_path, "morning.yaml", "name: Morning\nskills: [news]\n")
    reply, notices = await _say(orch, "/weather " + second + " plan")
    assert "nothing was sent to the model" in reply.lower()
    assert seen.sent == [] and seen.bumps == [] and notices == []
    orch.checkpoints.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["disabled", "quarantined", "unsupported"])
async def test_initial_stack_hard_gate_refuses_all_members(tmp_path, monkeypatch, kind):
    from agents.core.skills import visibility

    second = _md_skill("news", pending=kind == "quarantined")
    if kind == "unsupported":
        second.manifest["platforms"] = ["macos"]
        monkeypatch.setattr(visibility, "host_platforms", lambda platform=None: frozenset({"linux"}))
    orch, seen = _hub(tmp_path, monkeypatch, _md_skill("weather"), second)
    if kind == "disabled":
        settings_db.put_category("skills", {"channel_disabled": {"telegram": ["news"]}})
    reply, notices = await _say(orch, "/weather /news plan", channel="telegram")
    assert "nothing was sent to the model" in reply.lower()
    assert seen.sent == [] and seen.bumps == [] and notices == []
    orch.checkpoints.close()


def test_stack_preserves_slash_path_as_instruction(tmp_path, monkeypatch):
    orch, _ = _hub(tmp_path, monkeypatch, _md_skill("weather"), _md_skill("news"))
    inv = slash_load.resolve("/weather /news inspect /tmp/file", orch.skills)
    assert inv.skill_names == ("weather", "news")
    assert inv.instruction == "inspect /tmp/file"
    path_inv = slash_load.resolve("/weather /tmp/file", orch.skills)
    assert path_inv.skill_names == ("weather",) and path_inv.instruction == "/tmp/file"
    orch.checkpoints.close()


def test_stack_prompt_rechecks_each_member_after_initial_read(tmp_path, monkeypatch):
    orch, _ = _hub(tmp_path, monkeypatch, _md_skill("weather"), _md_skill("news"))
    token = bundles.bind_turn()
    try:
        inv = slash_load.resolve("/weather /news plan", orch.skills)
        assert slash_load.begin_load(inv, orch.skills, owner=True, session="s") is None
        settings_db.put_category("skills", {"disabled": ["news"]})
        block = bundles.turn_block(orch.skills, "athena", session="s")
        assert _BODIES["weather"] in block and _BODIES["news"] not in block
        assert "Skills skipped: news (switched off)" in block
        assert bundles.commit_turn() == 1
    finally:
        bundles.reset_turn(token)
        orch.checkpoints.close()


@pytest.mark.asyncio
async def test_stack_preserves_taint_environment_and_clean_ledger_reads(tmp_path, monkeypatch):
    from agents.core.code_env import CodeEnvRegistry
    from agents.core.security.taint import is_untrusted_source
    from agents.core.skills.tools import LEDGER

    weather = _md_skill("weather")
    weather.manifest["required_environment_variables"] = [{"name": "WEATHER_API_KEY"}]
    imported = _md_skill("imported", vouched=False)
    orch, seen = _hub(tmp_path, monkeypatch, weather, imported)
    registry = CodeEnvRegistry()
    orch.code_environment = registry
    reply, _ = await _say(orch, "/weather /imported plan")
    assert _answered(reply) and is_untrusted_source(seen.origins[0])
    assert '<loaded-skill name="imported" tainted="true">' in seen.sent[0]
    assert registry.resolve_names(agent="athena", principal="owner", session_id="s") == {"WEATHER_API_KEY"}
    assert LEDGER.loaded("s", "athena") == ["weather"]
    orch.checkpoints.close()


@pytest.mark.asyncio
async def test_ambiguous_second_skill_refuses_whole_stack(tmp_path, monkeypatch):
    a = _md_skill("news", path=Path("/installed/weather_notes"))
    b = _md_skill("notes", path=Path("/installed/weather-notes"))
    orch, seen = _hub(tmp_path, monkeypatch, _md_skill("weather"), a, b)
    reply, notices = await _say(orch, "/weather /weather_notes plan")
    assert "nothing was sent to the model" in reply.lower()
    assert seen.sent == [] and seen.bumps == [] and notices == []
    orch.checkpoints.close()
