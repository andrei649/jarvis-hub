"""Tests for agent routing — channel config, intent classifier, agent_override."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.config import JarvisConfig
from agents.core.router import IntentRouter
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


def test_intent_router_general():
    cfg = JarvisConfig()
    router = IntentRouter(cfg)

    async def _test():
        intent = await router.classify("what is the meaning of life?", {})
        assert intent.target_agents == ["jarvis"]
        assert intent.is_general

    import asyncio
    asyncio.run(_test())


def test_intent_router_music():
    cfg = JarvisConfig()
    router = IntentRouter(cfg)

    async def _test():
        intent = await router.classify("play some music", {})
        assert "jerome" in intent.target_agents

    import asyncio
    asyncio.run(_test())
