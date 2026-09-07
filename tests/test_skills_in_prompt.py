"""Hermes absorption 0.2 — the model is told which skills exist.

`Agent.build_prompt` has rendered an "Available skills" block from ``context["skills"]``
since the beginning, and nothing in the repo ever set that key: skills were discovered,
signed and pinned, and invisible to the model. `SkillLoader.prompt_catalog` is the producer
and `Orchestrator._prompt_context` is the wire; these tests pin both, and the two rules
that keep the block honest — a quarantined skill is never advertised, and the block is
bounded because every row is paid for on every turn.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.core.agent import Agent
from agents.core.config import JarvisConfig
from agents.core.orchestrator import Orchestrator
from agents.core.skills.loader import Skill, SkillLoader


def _skill(name, *, commands=(), agents=(), description="", sandboxed=False) -> Skill:
    skill = Skill(
        name,
        Path("/nonexistent") / name,
        {
            "name": name,
            "description": description,
            "agents": list(agents),
            "commands": list(commands),
        },
    )
    skill.sandboxed = sandboxed
    return skill


def _loader(*skills: Skill) -> SkillLoader:
    loader = SkillLoader.__new__(SkillLoader)
    loader.skills = {skill.name: skill for skill in skills}
    return loader


WEATHER = _skill(
    "weather",
    description="Live weather data from wttr.in.",
    agents=("friday", "jarvis"),
    commands=(
        {"command": "weather", "args": "location", "description": "current conditions"},
        {"command": "forecast", "args": "location", "description": ""},
    ),
)


# ── the catalog ──────────────────────────────────────────────────────────────


def test_catalog_rows_render_the_commands_the_loader_would_honour():
    rows = _loader(WEATHER).prompt_catalog("jarvis")

    assert rows == [
        {"skill": "weather", "command": "weather <location>", "description": "current conditions"},
        # A command without its own description borrows the skill's.
        {"skill": "weather", "command": "forecast <location>", "description": "Live weather data from wttr.in."},
    ]


def test_quarantined_and_sandboxed_skills_are_never_advertised():
    """Their commands cannot run in-process; advertising them teaches a command that refuses."""
    pending = _skill("evil", commands=({"command": "evil", "description": "x"},), sandboxed=True)

    assert _loader(WEATHER, pending).prompt_catalog() == _loader(WEATHER).prompt_catalog()


def test_a_skill_is_shown_to_the_agents_it_declares_and_general_ones_to_all():
    friday_only = _skill("brief", agents=("friday",), commands=({"command": "brief", "description": "d"},))
    everyone = _skill("pm", agents=("all",), commands=({"command": "pm", "description": "d"},))
    undeclared = _skill("notes", commands=({"command": "note", "description": "d"},))
    loader = _loader(friday_only, everyone, undeclared)

    assert [row["skill"] for row in loader.prompt_catalog("jarvis")] == ["notes", "pm"]
    assert [row["skill"] for row in loader.prompt_catalog("friday")] == ["brief", "notes", "pm"]
    assert [row["skill"] for row in loader.prompt_catalog()] == ["brief", "notes", "pm"]


def test_the_catalog_is_bounded_in_rows_and_in_description_length():
    big = _skill(
        "big",
        commands=tuple({"command": f"c{i}", "description": "word " * 100} for i in range(50)),
    )

    rows = _loader(big).prompt_catalog(limit=20, description_chars=30)

    assert len(rows) == 20
    assert all(len(row["description"]) <= 30 for row in rows)
    assert "\n" not in rows[0]["description"]


def test_malformed_command_metadata_is_skipped_not_rendered():
    odd = _skill(
        "odd",
        commands=(
            "not-a-dict",
            {"command": "rm -rf", "description": "regex chars"},
            {"command": 7},
            {"command": "ok", "description": "fine"},
        ),
    )

    assert _loader(odd).prompt_catalog() == [{"skill": "odd", "command": "ok", "description": "fine"}]


# ── the wire ─────────────────────────────────────────────────────────────────


def _agent(agent_id: str) -> Agent:
    """`Agent.build_prompt` needs only an identity; the roster is built at start(), not here."""
    agent = Agent.__new__(Agent)
    agent.id = agent_id
    agent.name = agent_id.title()
    return agent


@pytest.fixture
def orch():
    orchestrator = Orchestrator(JarvisConfig())
    orchestrator.skills = _loader(WEATHER)
    orchestrator._runtime_settings["llm.skills_in_prompt"] = True
    orchestrator.agents = {"jarvis": _agent("jarvis"), "frigga": _agent("frigga")}
    return orchestrator


def test_the_prompt_finally_carries_the_skills_block(orch):
    context = {"keywords_found": [], "scores": {}, "source": "keyword_match"}

    prompt = orch._build_agent_prompt(orch.agents["jarvis"], "hello", context)

    assert "Available skills:" in prompt
    assert "  - weather <location>: current conditions" in prompt
    assert "  - forecast <location>: Live weather data from wttr.in." in prompt
    # The intent context is shared across agents and traced; it must not be mutated.
    assert "skills" not in context


def test_the_block_respects_agent_scoping(orch):
    prompt = orch._build_agent_prompt(orch.agents["frigga"], "hello", {})

    assert "Available skills:" not in prompt


def test_the_setting_turns_the_block_off(orch):
    orch._runtime_settings["llm.skills_in_prompt"] = False

    prompt = orch._build_agent_prompt(orch.agents["jarvis"], "hello", {})

    assert "Available skills:" not in prompt


def test_a_caller_supplied_catalog_is_respected(orch):
    supplied = [{"command": "custom", "description": "from the caller"}]

    prompt = orch._build_agent_prompt(orch.agents["jarvis"], "hello", {"skills": supplied})

    assert "  - custom: from the caller" in prompt
    assert "weather <location>" not in prompt


def test_a_broken_catalog_fails_closed_to_no_block(orch):
    class _Broken:
        def prompt_catalog(self, agent_id=None):
            raise RuntimeError("boom")

    orch.skills = _Broken()

    prompt = orch._build_agent_prompt(orch.agents["jarvis"], "hello", {})

    assert "Available skills:" not in prompt
    assert "User said: hello" in prompt
