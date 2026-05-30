"""Tests for Agent.run_heartbeat — checklist execution, skill routing, error handling."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.agent import Agent
from core.skills.loader import Skill, SkillLoader


def make_agent(agent_id="test_agent", heartbeat=True):
    config = {"name": agent_id, "heartbeat": "1h" if heartbeat else "no"}
    return Agent(agent_id, config)

def make_orchestrator_with_skills(skills_map=None):
    orch = MagicMock()
    loader = MagicMock(spec=SkillLoader)
    if skills_map:
        def get_skill(name):
            return skills_map.get(name)
        loader.get_skill.side_effect = get_skill
    else:
        loader.get_skill.return_value = None
    orch.skills = loader
    return orch

def make_mock_skill(name, execute_result="ok"):
    skill = MagicMock(spec=Skill)
    skill.name = name
    skill.execute = AsyncMock(return_value=execute_result)
    return skill


class TestRunHeartbeat:
    async def test_empty_checklist_returns_none(self):
        agent = make_agent("noop")
        agent._heartbeat_config = {"checklist": []}
        result = await agent.run_heartbeat()
        assert result is None

    async def test_no_heartbeat_config_returns_none(self):
        agent = make_agent("noop")
        result = await agent.run_heartbeat()
        assert result is None

    async def test_executes_checklist_items(self):
        agent = make_agent("test")
        orch = make_orchestrator_with_skills({
            "brief": make_mock_skill("brief", "weather + news done"),
            "calendar": make_mock_skill("calendar", "3 events today"),
        })
        agent._heartbeat_config = {
            "checklist": [
                "Fetch weather for Bucharest",
                "Fetch today calendar agenda",
            ]
        }
        result = await agent.run_heartbeat(orchestrator=orch)
        assert "weather" in result
        assert "calendar" in result
        assert "[OK]" in result
        assert "[FAIL]" not in result

    async def test_missing_skills_dont_crash(self):
        agent = make_agent("test")
        orch = make_orchestrator_with_skills({})
        agent._heartbeat_config = {
            "checklist": ["Perform system status check"]
        }
        result = await agent.run_heartbeat(orchestrator=orch)
        assert "system_status not found" in result or "SYSTEM_STATUS" in result.upper() or result is not None

    async def test_skill_errors_dont_crash(self):
        agent = make_agent("test")
        failing_skill = make_mock_skill("brief")
        failing_skill.execute = AsyncMock(side_effect=RuntimeError("network down"))
        orch = make_orchestrator_with_skills({"brief": failing_skill})
        agent._heartbeat_config = {
            "checklist": ["Synthesize morning brief"]
        }
        result = await agent.run_heartbeat(orchestrator=orch)
        assert "Synthesize morning brief" in result
        assert "error" in result.lower()
        assert "network down" in result


class TestExecuteHeartbeatItem:
    def _make_agent_with_orch(self, skills_map=None):
        agent = make_agent("test")
        orch = make_orchestrator_with_skills(skills_map)
        return agent, orch

    async def test_brief_routing(self):
        agent, orch = self._make_agent_with_orch({
            "brief": make_mock_skill("brief", "brief result")
        })
        result = await agent._execute_heartbeat_item("Synthesize morning brief", orch)
        assert result == "brief result"

    async def test_weather_routing(self):
        agent, orch = self._make_agent_with_orch({
            "weather": make_mock_skill("weather", "sunny")
        })
        result = await agent._execute_heartbeat_item("Fetch weather for Bucharest", orch)
        assert result == "sunny"

    async def test_news_routing(self):
        agent, orch = self._make_agent_with_orch({
            "brief": make_mock_skill("brief", "news items")
        })
        result = await agent._execute_heartbeat_item("Fetch top 5 news headlines", orch)
        assert result == "news items"

    async def test_calendar_routing(self):
        agent, orch = self._make_agent_with_orch({
            "calendar": make_mock_skill("calendar", "2 events")
        })
        result = await agent._execute_heartbeat_item("Fetch today calendar agenda", orch)
        assert result == "2 events"

    async def test_health_routing(self):
        agent, orch = self._make_agent_with_orch({
            "health": make_mock_skill("health", "sleep: 7.5h")
        })
        result = await agent._execute_heartbeat_item("Check health metrics", orch)
        assert result == "sleep: 7.5h"

    async def test_email_routing(self):
        agent, orch = self._make_agent_with_orch({
            "email_triage": make_mock_skill("email_triage", "5 unread")
        })
        result = await agent._execute_heartbeat_item("Perform email triage", orch)
        assert result == "5 unread"

    async def test_inbox_routing(self):
        agent, orch = self._make_agent_with_orch({
            "email_triage": make_mock_skill("email_triage", "3 flagged")
        })
        result = await agent._execute_heartbeat_item("Check inbox for urgent", orch)
        assert result == "3 flagged"

    async def test_system_status_routing_graceful(self):
        agent, orch = self._make_agent_with_orch({})
        result = await agent._execute_heartbeat_item("Perform system status check", orch)
        assert "system_status" in result.lower()

    async def test_security_routing_graceful(self):
        agent, orch = self._make_agent_with_orch({})
        result = await agent._execute_heartbeat_item("Run security scan", orch)
        assert "security_scan" in result.lower()

    async def test_unknown_item_defaults(self):
        agent, orch = self._make_agent_with_orch({})
        result = await agent._execute_heartbeat_item("Do something random", orch)
        assert "checklist item executed" in result
        assert "Do something random" in result

    async def test_no_orchestrator(self):
        agent = make_agent("test")
        result = await agent._execute_heartbeat_item("Fetch weather", None)
        assert "weather" in result.lower()
        assert "not available" in result.lower()

    async def test_skill_exception_graceful(self):
        agent = make_agent("test")
        skill = make_mock_skill("brief")
        skill.execute = AsyncMock(side_effect=RuntimeError("boom"))
        orch = make_orchestrator_with_skills({"brief": skill})
        result = await agent._execute_heartbeat_item("Synthesize morning brief", orch)
        assert "error" in result.lower()
        assert "boom" in result


class TestRunSkill:
    def _make_agent_and_orch(self, skills_map=None):
        agent = make_agent("test")
        orch = make_orchestrator_with_skills(skills_map)
        return agent, orch

    async def test_calls_skill_execute(self):
        agent, orch = self._make_agent_and_orch({
            "brief": make_mock_skill("brief", "done")
        })
        result = await agent._run_skill(orch, "brief", "")
        assert result == "done"
        orch.skills.get_skill.assert_called_once_with("brief")

    async def test_missing_skill_returns_message(self):
        agent, orch = self._make_agent_and_orch({})
        result = await agent._run_skill(orch, "nonexistent", "")
        assert result == "skill nonexistent not found"

    async def test_no_orchestrator(self):
        agent = make_agent("test")
        result = await agent._run_skill(None, "brief", "")
        assert "not available" in result

    async def test_skill_execute_raises(self):
        agent = make_agent("test")
        skill = make_mock_skill("brief")
        skill.execute = AsyncMock(side_effect=ValueError("bad"))
        orch = make_orchestrator_with_skills({"brief": skill})
        result = await agent._run_skill(orch, "brief", "")
        assert "error" in result.lower()


class TestBackwardsCompat:
    async def test_run_heartbeat_without_orchestrator_or_config(self):
        agent = make_agent("legacy", heartbeat=True)
        result = await agent.run_heartbeat()
        assert result is None

    async def test_agent_without_heartbeat_skips(self):
        agent = make_agent("silent", heartbeat=False)
        result = await agent.run_heartbeat()
        assert result is None
