"""Strict-local gating: local_only agents (e.g. Frigga/family) must never
hit the Claude cloud backend. Runs on stdlib unittest — no extra deps."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from core.agent_loader import AgentLoader
from core.orchestrator import Orchestrator


def run(coro):
    return asyncio.run(coro)


class LocalOnlyGatingTest(unittest.TestCase):
    def _orchestrator(self):
        orch = Orchestrator()
        # Claude reports available and would answer "CLOUD" if ever called.
        orch.claude.is_available = MagicMock(return_value=True)
        orch.claude.ask = AsyncMock(return_value="CLOUD")
        # No Ollama client; force the file-bridge fallback to answer "LOCAL".
        orch._client = None
        orch.bridge.ask = MagicMock(return_value="LOCAL")
        return orch

    def test_local_only_agent_never_calls_claude(self):
        orch = self._orchestrator()
        result = run(orch._call_llm("qwen2.5:14b", "hi", "frigga", local_only=True))
        self.assertEqual(result, "LOCAL")
        orch.claude.ask.assert_not_awaited()

    def test_cloud_agent_uses_claude(self):
        orch = self._orchestrator()
        result = run(orch._call_llm("deepseek-r1:32b", "hi", "jarvis", local_only=False))
        self.assertEqual(result, "CLOUD")
        orch.claude.ask.assert_awaited_once()


class FriggaConfigTest(unittest.TestCase):
    def test_frigga_is_local_only(self):
        loader = AgentLoader("agents")
        frigga = loader.get("frigga")
        self.assertIsNotNone(frigga)
        self.assertTrue(frigga.local_only, "Frigga must be strict-local (no cloud fallback)")

    def test_other_agents_default_to_cloud_eligible(self):
        loader = AgentLoader("agents")
        jarvis = loader.get("jarvis")
        self.assertIsNotNone(jarvis)
        self.assertFalse(jarvis.local_only)


if __name__ == "__main__":
    unittest.main()
