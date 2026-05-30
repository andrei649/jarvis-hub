"""Tests for agent routing — channel config, intent classifier, agent_override."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.config import JarvisConfig
from agents.core.router import IntentRouter, Intent
from agents.core.orchestrator import Orchestrator


def test_all_agents_have_correct_channel():
    cfg = JarvisConfig()
    expected = {
        "jarvis": "voice", "friday": "voice", "pepper": "voice",
        "jerome": "voice", "athena": "web-dashboard", "stark": "telegram",
        "veronica": "telegram", "vision": "web-dashboard", "steve": "telegram",
        "oracle": "web-dashboard", "ultron": "log-only", "gecko": "telegram",
        "hercules": "telegram", "hephaestus": "telegram", "frigga": "local-only",
    }
    for aid, expected_channel in expected.items():
        agent = cfg.agents.get(aid)
        assert agent is not None, f"Agent {aid} not found in config"
        assert agent.channel == expected_channel, (
            f"Agent {aid} expected channel='{expected_channel}', got '{agent.channel}'"
        )


def test_intent_router_weather():
    cfg = JarvisConfig()
    router = IntentRouter(cfg)

    async def _test():
        intent = await router.classify("weather in bucuresti", {})
        assert "friday" in intent.target_agents
        assert not intent.is_general

    import asyncio
    asyncio.run(_test())


def test_first_target_agent_normal():
    cfg = JarvisConfig()
    orch = Orchestrator(cfg)
    intent = Intent(target_agents=["friday"], is_general=False, context={})
    assert orch._first_target_agent(intent) == "friday"


def test_first_target_agent_empty_list():
    cfg = JarvisConfig()
    orch = Orchestrator(cfg)
    intent = Intent(target_agents=[], is_general=False, context={})
    assert orch._first_target_agent(intent) == "jarvis"


def test_first_target_agent_no_target():
    cfg = JarvisConfig()
    orch = Orchestrator(cfg)
    intent = Intent(target_agents=None, is_general=True, context={})
    assert orch._first_target_agent(intent) == "jarvis"


def test_any_agent_can_allows_when_first_has_permission():
    cfg = JarvisConfig()
    orch = Orchestrator(cfg)
    intent = Intent(target_agents=["jarvis", "friday"], is_general=False, context={})
    assert orch._any_agent_can("weather", intent)


def test_any_agent_can_denies_when_none_have_permission():
    cfg = JarvisConfig()
    orch = Orchestrator(cfg)
    intent = Intent(target_agents=["vision"], is_general=False, context={})
    # Vision does not have spotify permission (only jerome does)
    assert not orch._any_agent_can("spotify", intent)



def test_intent_router_music():
    cfg = JarvisConfig()
    router = IntentRouter(cfg)

    async def _test():
        intent = await router.classify("play some music", {})
        assert "jerome" in intent.target_agents

    import asyncio
    asyncio.run(_test())
