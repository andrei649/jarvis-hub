"""Cross-cutting: per-agent integration tests.

For every active agent this verifies the three things that make an agent real:
  1. loads — its SOUL.md is present and non-empty after construction
  2. routable — the intent router maps its wake word to it
  3. processes — Agent.process returns output when the LLM backend is mocked

No live LLM, no network, no external services. The LLM is replaced with a
fake router so the whole agent pipeline runs deterministically.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.config import JarvisConfig
from agents.core.agent import Agent
from agents.core.router import IntentRouter
from agents.core.plugin_gate import PermissionGate


MOCK_REPLY = "[mocked agent reply]"


class _FakeBackend:
    async def generate(self, model="", prompt="", system=""):
        return MOCK_REPLY


class _FakeRouter:
    """Stand-in for HybridRouter: no network, always returns the fake backend."""
    def select_backend(self, agent_id, prompt):
        return _FakeBackend(), {"backend": "mock"}

    def get_howard_model(self):
        return "mock-howard-model"


def _active_agent_ids():
    cfg = JarvisConfig()
    return [a.id for a in cfg.get_active_agents()]


def _build_agent(agent_id, cfg):
    """Construct an agent the same way Orchestrator.load_agents does."""
    ac = cfg.get_agent(agent_id)
    agent_dict = {
        "name": ac.name, "model": ac.model, "heartbeat": ac.has_heartbeat,
        "channel": ac.channel, "plugins": ac.plugins, "tier": ac.tier,
    }
    agent = Agent(agent_id, agent_dict, _FakeRouter(), permission_gate=PermissionGate())
    agent.guardrails = None  # no guardrails wrapping in this isolated test
    return agent


# Parametrize so each agent is an independent, named test case.
AGENT_IDS = _active_agent_ids()


def test_active_agent_roster():
    # 15 core agents + howard (activated 2026-05-30). Guard against an empty
    # or accidentally-truncated roster rather than pinning an exact count.
    assert len(AGENT_IDS) >= 15
    for core in ("jarvis", "friday", "pepper", "vision", "frigga"):
        assert core in AGENT_IDS


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_agent_loads_soul(agent_id):
    cfg = JarvisConfig()
    agent = _build_agent(agent_id, cfg)
    assert agent.soul.get("content"), f"{agent_id} has empty/missing SOUL.md"


@pytest.mark.parametrize("agent_id", AGENT_IDS)
async def test_agent_is_routable(agent_id):
    cfg = JarvisConfig()
    router = IntentRouter(cfg)
    intent = await router.classify(f"{agent_id} please give me a status report", cfg.agents)
    assert agent_id in intent.target_agents, f"{agent_id} not routable via its wake word"


@pytest.mark.parametrize("agent_id", AGENT_IDS)
async def test_agent_processes_with_mocked_llm(agent_id):
    cfg = JarvisConfig()
    agent = _build_agent(agent_id, cfg)
    out = await agent.process("hello, are you there?", {"session_id": "test"})
    assert out == MOCK_REPLY
    assert agent.last_latency >= 0.0


async def test_agent_failure_increments_counter_without_crashing():
    """A backend that raises should be recorded as a failure, not swallowed."""
    cfg = JarvisConfig()
    agent = _build_agent("jarvis", cfg)
    failing = _FakeRouter()
    failing.select_backend = lambda aid, prompt: (_RaisingBackend(), {})
    agent.llm_router = failing
    with pytest.raises(Exception):
        await agent.process("trigger failure", {"session_id": "test"})
    assert agent._failures == 1


def test_agent_guardrails_defaults_to_none():
    """Regression: Agent.process reads self.guardrails; it must exist even when
    the orchestrator never wired security (e.g. no LLM backend present)."""
    agent = Agent("jarvis", {"name": "Jarvis"}, _FakeRouter())
    assert agent.guardrails is None


class _RaisingBackend:
    async def generate(self, model="", prompt="", system=""):
        raise RuntimeError("backend down")
